package roadml.server

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.http4k.core.HttpHandler
import org.http4k.core.Method
import org.http4k.core.Request
import org.http4k.core.Response
import java.io.File
import java.util.UUID

/** compose.yaml で立てた PostgreSQL・S3 互換ストレージに実際につなぐ(.env.example と同じ値) */
val TEST_ENV = mapOf(
    "API_KEY" to "test-shared-key",
    "DATABASE_URL" to "postgres://roadml:roadml-dev@127.0.0.1:5433/roadml",
    "S3_ENDPOINT" to "http://127.0.0.1:8333",
    "S3_PUBLIC_ENDPOINT" to "http://127.0.0.1:8333",
    "S3_BUCKET" to "roadml-raw-test",
    "S3_ACCESS_KEY" to "roadml-dev",
    "S3_SECRET_KEY" to "roadml-dev-secret",
)

/** テストごとに専用のスキーマを作り、終わったら消す(開発用のデータと混ざらない) */
class TestEnv : AutoCloseable {
    val config = Config.load(TEST_ENV)
    private val schema = "test_" + UUID.randomUUID().toString().replace("-", "").take(12)
    private val admin = Database(config.db.copy(poolSize = 1))
    val db: Database
    val storage = S3Storage(config)
    val deps: Deps
    val app: HttpHandler

    init {
        admin.update("CREATE SCHEMA $schema")
        db = Database(config.db.copy(schema = schema, poolSize = 2))
        migrate(db, File("migrations"))
        storage.ensureBucket()
        storage.waitWritable()
        deps = Deps(config, db, storage)
        app = createApp(deps)
    }

    val headers = mapOf("x-api-key" to config.apiKey, "content-type" to "application/json")

    fun post(path: String, body: String, h: Map<String, String> = headers): Response =
        app(h.entries.fold(Request(Method.POST, path)) { r, (k, v) -> r.header(k, v) }.body(body))

    fun post(path: String, body: JsonElement, h: Map<String, String> = headers) = post(path, body.toString(), h)

    override fun close() {
        db.close()
        admin.update("DROP SCHEMA $schema CASCADE")
        admin.close()
    }
}

fun Response.json(): JsonObject = Json.parseToJsonElement(bodyString()).jsonObject

/** Kotlin の値から JSON を作る(テストの入力用) */
fun j(v: Any?): JsonElement = when (v) {
    null -> JsonNull
    is JsonElement -> v
    is String -> JsonPrimitive(v)
    is Number -> JsonPrimitive(v)
    is Boolean -> JsonPrimitive(v)
    is Map<*, *> -> JsonObject(v.entries.associate { (k, x) -> k as String to j(x) })
    is List<*> -> kotlinx.serialization.json.JsonArray(v.map { j(it) })
    else -> error("JSON にできない: $v")
}

fun obj(vararg pairs: Pair<String, Any?>): JsonObject = j(mapOf(*pairs)) as JsonObject

operator fun JsonObject.plus(other: Map<String, Any?>): JsonObject = JsonObject(this.toMap() + other.mapValues { j(it.value) })

fun JsonObject.without(vararg keys: String): JsonObject = JsonObject(this.filterKeys { it !in keys })

fun newSession(over: Map<String, Any?> = emptyMap()): JsonObject = obj(
    "id" to UUID.randomUUID().toString(), "device_id" to "emulator-5554", "started_at" to "2026-11-18T05:00:00+09:00",
    "app_version" to "0.1.0", "model_version" to "v4_20261118",
) + over

fun detection(startMs: Long, over: Map<String, Any?> = emptyMap()): JsonObject = obj(
    "window_start_ms" to startMs, "window_s" to 2.0, "class" to "flat", "scores" to mapOf("flat" to 1.2, "step" to -0.4, "rough" to -0.9),
    "lat" to 35.1815, "lon" to 136.9066, "accuracy_m" to 8.5, "located_at_ms" to startMs + 2000,
) + over

fun batch(vararg d: JsonObject) = obj("detections" to d.toList())

val JsonObject.id: String get() = (this["id"] as JsonPrimitive).content
