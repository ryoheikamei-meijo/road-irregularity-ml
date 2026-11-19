package roadml.server

import com.amazonaws.services.lambda.runtime.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.http4k.serverless.ApiGatewayV2FnLoader
import org.http4k.serverless.AppLoader
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.BeforeAll
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestInstance
import java.lang.reflect.Proxy
import java.util.Base64
import kotlin.test.assertEquals

/**
 * Lambda の入口。API Gateway(HTTP API、形式 2.0)が Lambda に渡すのと同じ形のイベントを、
 * Lambda の実行環境と同じ変換(http4k の ApiGatewayV2FnLoader)に入れて確かめる。SnapStart そのものは AWS でしか確かめられない。
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class LambdaHandlerTest {
    private lateinit var t: TestEnv

    @BeforeAll fun setUp() { t = TestEnv() }
    @AfterAll fun tearDown() { t.close() }

    /** Lambda の Context。入口は中身を使わないので、形だけ作る */
    private val context = Proxy.newProxyInstance(Context::class.java.classLoader, arrayOf(Context::class.java)) { _, m, _ ->
        when (m.returnType) {
            Int::class.javaPrimitiveType -> if (m.name == "getRemainingTimeInMillis") 30_000 else 512
            String::class.java -> "test"
            else -> null
        }
    } as Context

    private fun event(method: String, path: String, body: String?, headers: Map<String, String>) = obj(
        "version" to "2.0", "routeKey" to "\$default", "rawPath" to path, "rawQueryString" to "",
        "headers" to headers, "isBase64Encoded" to false, "body" to body,
        "requestContext" to mapOf(
            "accountId" to "123456789012", "apiId" to "api", "domainName" to "example.com", "requestId" to "req-1",
            "routeKey" to "\$default", "stage" to "\$default", "time" to "18/Nov/2026:05:00:00 +0000", "timeEpoch" to 1795000000000L,
            "http" to mapOf("method" to method, "path" to path, "protocol" to "HTTP/1.1", "sourceIp" to "127.0.0.1", "userAgent" to "test"),
        ),
    )

    private fun invoke(loader: AppLoader, env: Map<String, String>, event: JsonObject): JsonObject {
        val fn = ApiGatewayV2FnLoader(loader)(env)
        val out = fn(event.toString().byteInputStream(), context).readBytes().decodeToString()
        return Json.parseToJsonElement(out).jsonObject
    }

    private val testApp = AppLoader { createApp(t.deps) }
    private val withKey = mapOf("x-api-key" to TEST_ENV.getValue("API_KEY"), "content-type" to "application/json")
    private fun status(r: JsonObject) = r["statusCode"]!!.jsonPrimitive.int
    /** http4k は本文を base64 で返す(isBase64Encoded: true)。API Gateway が元に戻してクライアントへ返す */
    private fun body(r: JsonObject): JsonObject {
        val raw = r["body"]!!.jsonPrimitive.content
        val text = if (r["isBase64Encoded"]?.jsonPrimitive?.boolean == true) Base64.getDecoder().decode(raw).decodeToString() else raw
        return Json.parseToJsonElement(text).jsonObject
    }

    @Test fun `イベントから走行の登録と判定結果の保存までが通る`() {
        val s = newSession()
        val created = invoke(testApp, TEST_ENV, event("POST", "/sessions", s.toString(), withKey))
        assertEquals(201, status(created))
        assertEquals(s.id, body(created)["id"]!!.jsonPrimitive.content)

        val saved = invoke(testApp, TEST_ENV, event("POST", "/sessions/${s.id}/detections", batch(detection(1000), detection(1500)).toString(), withKey))
        assertEquals(200, status(saved))
        assertEquals(obj("received" to 2, "inserted" to 2, "duplicates" to 0), body(saved))
        assertEquals(2, t.db.query("SELECT count(*) FROM detections WHERE session_id = ?::uuid", s.id) { it.getInt(1) }.single())
    }

    @Test fun `鍵が無ければ 401、health は通る`() {
        assertEquals(401, status(invoke(testApp, TEST_ENV, event("POST", "/sessions", newSession().toString(), mapOf("content-type" to "application/json")))))
        assertEquals(200, status(invoke(testApp, TEST_ENV, event("GET", "/health", null, emptyMap()))))
    }

    @Test fun `初期化では DB につながない（つながらない DB でも入口は作れ、リクエストで初めて失敗する）`() {
        // SnapStart では、初期化が終わった時点がスナップショットになる。初期化で DB につなぐと、古い接続がスナップショットに残る
        val env = TEST_ENV + ("DATABASE_URL" to "postgres://roadml:roadml-dev@127.0.0.1:1/roadml")
        val fn = ApiGatewayV2FnLoader(appLoader)(env) // 本番と同じ appLoader。ここで例外にならない
        val out = fn(event("GET", "/health", null, emptyMap()).toString().byteInputStream(), context).readBytes().decodeToString()
        assertEquals(500, status(Json.parseToJsonElement(out).jsonObject))
    }
}
