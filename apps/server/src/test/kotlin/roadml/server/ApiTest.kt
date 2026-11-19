package roadml.server

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.http4k.core.Method
import org.http4k.core.Request
import org.http4k.core.Status
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.BeforeAll
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestInstance
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.security.MessageDigest
import kotlin.random.Random
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** TypeScript 版(apps/server-ts/test/api.test.ts)の 15 件と同じ項目。本物の PostgreSQL と S3 互換のストレージにつなぐ */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ApiTest {
    private lateinit var t: TestEnv

    @BeforeAll fun setUp() { t = TestEnv() }
    @AfterAll fun tearDown() { t.close() }

    private fun count(sql: String, vararg p: Any?) = t.db.query(sql, *p) { it.getInt(1) }.single()
    private fun registered() = newSession().also { assertEquals(Status.CREATED, t.post("/sessions", it).status) }
    private val noKey = mapOf("content-type" to "application/json")

    @Nested @TestInstance(TestInstance.Lifecycle.PER_CLASS)
    inner class 認証 {
        @Test fun `health は鍵が無くても通る`() {
            assertEquals(Status.OK, t.app(Request(Method.GET, "/health")).status)
        }

        @Test fun `鍵が無い・違うときは 401`() {
            val body = newSession()
            assertEquals(Status.UNAUTHORIZED, t.post("/sessions", body, noKey).status)
            assertEquals(Status.UNAUTHORIZED, t.post("/sessions", body, noKey + ("x-api-key" to "wrong-key-xx")).status)
        }
    }

    @Nested @TestInstance(TestInstance.Lifecycle.PER_CLASS)
    inner class 走行の登録 {
        @Test fun `作成は 201、同じ id の再送は 200（冪等）`() {
            val s = newSession()
            val a = t.post("/sessions", s)
            assertEquals(Status.CREATED, a.status)
            assertEquals(JsonPrimitive(true), a.json()["created"])
            val b = t.post("/sessions", s)
            assertEquals(Status.OK, b.status)
            assertEquals(JsonPrimitive(false), b.json()["created"])
            assertEquals(1, count("SELECT count(*) FROM sessions WHERE id = ?::uuid", s.id))
        }

        @Test fun `同じ id で別の端末なら 409`() {
            val s = registered()
            assertEquals(Status.CONFLICT, t.post("/sessions", s + mapOf("device_id" to "other")).status)
        }

        @Test fun `不正な入力は 400 で、理由が返る`() {
            val r = t.post("/sessions", newSession(mapOf("id" to "not-a-uuid", "started_at" to "yesterday")))
            assertEquals(Status.BAD_REQUEST, r.status)
            val paths = r.json()["issues"]!!.jsonArray.map { it.jsonObject["path"]!!.jsonPrimitive.content }.sorted()
            assertEquals(listOf("id", "started_at"), paths)
            assertEquals(Status.BAD_REQUEST, t.post("/sessions", "{broken").status)
        }
    }

    @Nested @TestInstance(TestInstance.Lifecycle.PER_CLASS)
    inner class 判定結果のバッチ {
        private fun result(received: Int, inserted: Int, duplicates: Int) =
            obj("received" to received, "inserted" to inserted, "duplicates" to duplicates)

        @Test fun `保存でき、同じバッチを再送しても二重にならない`() {
            val s = registered()
            val b = batch(detection(1000), detection(1500, mapOf("class" to "step")), detection(2000, mapOf("class" to "rough")))
            assertEquals(result(3, 3, 0), t.post("/sessions/${s.id}/detections", b).json())
            assertEquals(result(3, 0, 3), t.post("/sessions/${s.id}/detections", b).json())
            val rows = t.db.query("SELECT class, scores::text FROM detections WHERE session_id = ?::uuid ORDER BY window_start_ms", s.id) {
                it.getString(1) to Json.parseToJsonElement(it.getString(2))
            }
            assertEquals(listOf("flat", "step", "rough"), rows.map { it.first })
            assertEquals(j(mapOf("flat" to 1.2, "step" to -0.4, "rough" to -0.9)), rows[0].second)
        }

        @Test fun `壁時計(window_wall_ms)は、あれば保存され、無ければ NULL`() {
            val s = registered()
            t.post("/sessions/${s.id}/detections", batch(detection(1000, mapOf("window_wall_ms" to 1793510619944L)), detection(1500)))
            val rows = t.db.query("SELECT window_start_ms, window_wall_ms FROM detections WHERE session_id = ?::uuid ORDER BY 1", s.id) {
                it.getLong(1) to it.getObject(2)
            }
            assertEquals(listOf(1000L to 1793510619944L, 1500L to null), rows)
        }

        @Test fun `新しい窓と再送の窓が混ざっても、新しい分だけ入る`() {
            val s = registered()
            t.post("/sessions/${s.id}/detections", batch(detection(1000), detection(1500)))
            val r = t.post("/sessions/${s.id}/detections", batch(detection(1500), detection(2000), detection(2500)))
            assertEquals(result(3, 2, 1), r.json())
        }

        @Test fun `1 つのバッチの中に同じ窓があっても、1 件だけ入る`() {
            val s = registered()
            assertEquals(result(2, 1, 1), t.post("/sessions/${s.id}/detections", batch(detection(1000), detection(1000))).json())
        }

        @Test fun `位置が取れなかった窓は NULL で保存される`() {
            val s = registered()
            val d = detection(1000).without("lat", "lon", "accuracy_m", "located_at_ms")
            assertEquals(Status.OK, t.post("/sessions/${s.id}/detections", batch(d)).status)
            val row = t.db.query("SELECT lat, lon, accuracy_m FROM detections WHERE session_id = ?::uuid", s.id) {
                listOf(it.getObject(1), it.getObject(2), it.getObject(3))
            }.single()
            assertEquals(listOf(null, null, null), row)
        }

        @Test fun `lat だけ、範囲外、不明なクラス、空のバッチは 400`() {
            val s = registered()
            fun bad(d: List<Any>) = t.post("/sessions/${s.id}/detections", obj("detections" to d)).status
            assertEquals(Status.BAD_REQUEST, bad(listOf(detection(1000).without("lon"))))
            assertEquals(Status.BAD_REQUEST, bad(listOf(detection(1000, mapOf("lat" to 91)))))
            assertEquals(Status.BAD_REQUEST, bad(listOf(detection(1000, mapOf("class" to "bump")))))
            assertEquals(Status.BAD_REQUEST, bad(emptyList()))
        }

        @Test fun `登録の無い走行は 404、uuid でなければ 400`() {
            assertEquals(Status.NOT_FOUND, t.post("/sessions/${newSession().id}/detections", batch(detection(1))).status)
            assertEquals(Status.BAD_REQUEST, t.post("/sessions/abc/detections", batch(detection(1))).status)
        }
    }

    @Nested @TestInstance(TestInstance.Lifecycle.PER_CLASS)
    inner class 生データ {
        private val http = HttpClient.newHttpClient()
        private fun sha256(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }
        private fun put(url: String, body: ByteArray) =
            http.send(HttpRequest.newBuilder(URI(url)).PUT(HttpRequest.BodyPublishers.ofByteArray(body)).build(), HttpResponse.BodyHandlers.discarding()).statusCode()

        @Test fun `URL を受け取り、ストレージへ直接 PUT し、完了を通知すると記録される。取り出すと同じ内容`() {
            val s = registered()
            val r = t.post("/sessions/${s.id}/raw-upload-url", "{}")
            assertEquals(Status.OK, r.status)
            val url = r.json()["url"]!!.jsonPrimitive.content
            val key = r.json()["key"]!!.jsonPrimitive.content
            assertEquals("sessions/${s.id}/input.csv", key)
            val body = Random.nextBytes(20 * 1024 * 1024) // Lambda の 6 MB を超える大きさ
            val hash = sha256(body)
            assertEquals(200, put(url, body))
            val done = t.post("/sessions/${s.id}/raw-complete", obj("size_bytes" to body.size, "sha256" to hash))
            assertEquals(obj("key" to key, "size_bytes" to body.size), done.json())
            val rec = t.db.query("SELECT size_bytes, sha256 FROM raw_files WHERE session_id = ?::uuid", s.id) { it.getLong(1) to it.getString(2) }.single()
            assertEquals(body.size.toLong() to hash, rec)
            val got = http.send(HttpRequest.newBuilder(URI(t.storage.presignGet(key))).build(), HttpResponse.BodyHandlers.ofByteArray()).body()
            assertEquals(hash, sha256(got))
            t.storage.remove(key)
        }

        @Test fun `置かれていない・大きさが違うときの完了通知は 409`() {
            val s = registered()
            val hash = "a".repeat(64)
            assertEquals(Status.CONFLICT, t.post("/sessions/${s.id}/raw-complete", obj("size_bytes" to 10, "sha256" to hash)).status)
            val u = t.post("/sessions/${s.id}/raw-upload-url", "{}").json()
            put(u["url"]!!.jsonPrimitive.content, "0123456789".toByteArray())
            val r = t.post("/sessions/${s.id}/raw-complete", obj("size_bytes" to 11, "sha256" to hash))
            assertEquals(Status.CONFLICT, r.status)
            assertEquals(obj("error" to "size_mismatch", "stored" to 10, "declared" to 11), r.json())
            t.storage.remove(u["key"]!!.jsonPrimitive.content)
        }

        @Test fun `sha256 の形が違うと 400、登録の無い走行は 404`() {
            val s = registered()
            assertEquals(Status.BAD_REQUEST, t.post("/sessions/${s.id}/raw-complete", obj("size_bytes" to 1, "sha256" to "XYZ")).status)
            assertEquals(Status.NOT_FOUND, t.post("/sessions/${newSession().id}/raw-upload-url", "{}").status)
        }
    }
}
