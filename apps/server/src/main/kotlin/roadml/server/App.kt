package roadml.server

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.addJsonObject
import org.http4k.core.Filter
import org.http4k.core.HttpHandler
import org.http4k.core.Method.GET
import org.http4k.core.Method.POST
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.core.Status
import org.http4k.core.then
import org.http4k.routing.bind
import org.http4k.routing.path
import org.http4k.routing.routes
import java.security.MessageDigest

class Deps(val config: Config, val db: Database, val storage: Storage)

fun rawKey(sessionId: String) = "sessions/$sessionId/input.csv"

fun json(status: Status, body: JsonElement): Response =
    Response(status).header("content-type", "application/json").body(body.toString())

private fun error(status: Status, code: String, extra: Map<String, Long> = emptyMap()) = json(status, buildJsonObject {
    put("error", code)
    extra.forEach { (k, v) -> put(k, v) }
})

private fun safeEqual(a: String, b: String) = MessageDigest.isEqual(a.toByteArray(), b.toByteArray())

/** 本文を JSON として読み、検証する。だめなら 400 の応答を返す */
private fun <T> Request.parse(parser: (JsonElement) -> Parsed<T>): Pair<T?, Response?> {
    val element = try {
        Json.parseToJsonElement(bodyString())
    } catch (e: SerializationException) {
        return null to error(Status.BAD_REQUEST, "invalid_json")
    } catch (e: IllegalArgumentException) {
        return null to error(Status.BAD_REQUEST, "invalid_json")
    }
    return when (val p = parser(element)) {
        is Parsed.Ok -> p.value to null
        is Parsed.Invalid -> null to json(Status.BAD_REQUEST, buildJsonObject {
            put("error", "validation")
            putJsonArray("issues") { p.issues.forEach { i -> addJsonObject { put("path", i.path); put("message", i.message) } } }
        })
    }
}

/**
 * API の本体。PC のサーバー(Main.kt)と Lambda の入口(LambdaHandler.kt)の両方から使う。
 * 振る舞いは TypeScript 版(apps/server-ts)と同じ。
 */
fun createApp(deps: Deps): HttpHandler {
    val (config, db, storage) = Triple(deps.config, deps.db, deps.storage)

    fun sessionExists(id: String) = db.query("SELECT 1 FROM sessions WHERE id = ?::uuid", id) { 1 }.isNotEmpty()

    /** パスの id を確かめ、走行が登録済みなら処理する */
    fun withSession(req: Request, handle: (String) -> Response): Response {
        val id = req.path("id") ?: ""
        if (!isUuid(id)) return error(Status.BAD_REQUEST, "invalid_session_id")
        return handle(id)
    }

    val catchAll = Filter { next ->
        { req ->
            try {
                next(req)
            } catch (e: Exception) {
                System.err.println("unhandled: $e")
                e.printStackTrace()
                error(Status.INTERNAL_SERVER_ERROR, "internal")
            }
        }
    }

    // 共有キー。研究室内だけの前提で、強い認証ではない(アプリに埋め込むため)
    val apiKey = Filter { next ->
        { req ->
            val key = req.header("x-api-key")
            if (req.uri.path == "/health" || (key != null && safeEqual(key, config.apiKey))) next(req)
            else error(Status.UNAUTHORIZED, "unauthorized")
        }
    }

    val router = routes(
        "/health" bind GET to {
            db.query("SELECT 1") { 1 }
            json(Status.OK, buildJsonObject { put("ok", true) })
        },

        /** 走行の登録。同じ id で再送しても同じ結果(冪等) */
        "/sessions" bind POST to { req ->
            val (s, bad) = req.parse(::parseSession)
            if (s == null) bad!!
            else {
                val inserted = db.update(
                    """INSERT INTO sessions (id, device_id, started_at, app_version, model_version, wheelchair, weight_kg)
                       VALUES (?::uuid, ?, ?::timestamptz, ?, ?, ?, ?::real) ON CONFLICT (id) DO NOTHING""",
                    s.id, s.deviceId, s.startedAt, s.appVersion, s.modelVersion, s.wheelchair, s.weightKg,
                )
                if (inserted == 1) json(Status.CREATED, buildJsonObject { put("id", s.id); put("created", true) })
                else {
                    val existing = db.query("SELECT device_id FROM sessions WHERE id = ?::uuid", s.id) { it.getString(1) }.firstOrNull()
                    if (existing != s.deviceId) error(Status.CONFLICT, "session_id_conflict")
                    else json(Status.OK, buildJsonObject { put("id", s.id); put("created", false) })
                }
            }
        },

        /** 判定結果のバッチ。(session_id, window_start_ms) で重複を弾くので、再送しても二重にならない */
        "/sessions/{id}/detections" bind POST to { req ->
            withSession(req) { id ->
                val (list, bad) = req.parse(::parseDetections)
                when {
                    list == null -> bad!!
                    !sessionExists(id) -> error(Status.NOT_FOUND, "session_not_found")
                    else -> {
                        val rows = buildJsonArray {
                            list.forEach { d ->
                                addJsonObject {
                                    put("window_start_ms", d.windowStartMs); put("window_wall_ms", d.windowWallMs)
                                    put("window_s", d.windowS); put("class", d.cls); put("scores", d.scores)
                                    put("lat", d.lat); put("lon", d.lon); put("accuracy_m", d.accuracyM); put("located_at_ms", d.locatedAtMs)
                                }
                            }
                        }
                        val inserted = db.update(
                            """INSERT INTO detections (session_id, window_start_ms, window_wall_ms, window_s, class, scores, lat, lon, accuracy_m, located_at_ms)
                               SELECT ?::uuid, r.window_start_ms, r.window_wall_ms, r.window_s, r.class, r.scores, r.lat, r.lon, r.accuracy_m, r.located_at_ms
                               FROM jsonb_to_recordset(?::jsonb) AS r(window_start_ms bigint, window_wall_ms bigint, window_s real, class text, scores jsonb,
                                                                      lat double precision, lon double precision, accuracy_m real, located_at_ms bigint)
                               ON CONFLICT (session_id, window_start_ms) DO NOTHING""",
                            id, rows.toString(),
                        )
                        json(Status.OK, buildJsonObject {
                            put("received", list.size); put("inserted", inserted); put("duplicates", list.size - inserted)
                        })
                    }
                }
            }
        },

        /** 生データを S3 へ直接 PUT するための署名付き URL。ファイルは API を通さない(Lambda は 6 MB を超えて受けられない) */
        "/sessions/{id}/raw-upload-url" bind POST to { req ->
            withSession(req) { id ->
                if (!sessionExists(id)) error(Status.NOT_FOUND, "session_not_found")
                else {
                    val key = rawKey(id)
                    json(Status.OK, buildJsonObject {
                        put("method", "PUT"); put("url", storage.presignPut(key)); put("key", key); put("expires_in_s", config.uploadUrlTtlS)
                    })
                }
            }
        },

        /** アップロードの完了通知。置かれたファイルの大きさが申告と合うことを確かめてから記録する */
        "/sessions/{id}/raw-complete" bind POST to { req ->
            withSession(req) { id ->
                val (b, bad) = req.parse(::parseRawComplete)
                when {
                    b == null -> bad!!
                    !sessionExists(id) -> error(Status.NOT_FOUND, "session_not_found")
                    else -> {
                        val key = rawKey(id)
                        val size = storage.headSize(key)
                        when {
                            size == null -> error(Status.CONFLICT, "object_not_found")
                            size != b.sizeBytes -> error(Status.CONFLICT, "size_mismatch", mapOf("stored" to size, "declared" to b.sizeBytes))
                            else -> {
                                db.update(
                                    """INSERT INTO raw_files (session_id, object_key, size_bytes, sha256) VALUES (?::uuid, ?, ?, ?)
                                       ON CONFLICT (session_id) DO UPDATE SET object_key = EXCLUDED.object_key, size_bytes = EXCLUDED.size_bytes,
                                         sha256 = EXCLUDED.sha256, uploaded_at = now()""",
                                    id, key, size, b.sha256,
                                )
                                json(Status.OK, buildJsonObject { put("key", key); put("size_bytes", size) })
                            }
                        }
                    }
                }
            }
        },
    )

    return catchAll.then(apiKey).then(router)
}
