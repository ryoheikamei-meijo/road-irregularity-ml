package roadml.server

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

/**
 * 入力の検証が TypeScript 版(Zod)と同じ規則になっていること(DB は使わない)。
 * 2026-11-18 に、両方のサーバーへ同じ 54 通りの入力を送り、ステータスと返事がすべて一致したことを確かめた。その主なもの。
 */
class SchemasTest {
    private fun paths(p: Parsed<*>): List<String> = when (p) {
        is Parsed.Ok -> emptyList()
        is Parsed.Invalid -> p.issues.map { it.path }.sorted()
    }
    private fun detections(vararg items: JsonElement) = parseDetections(obj("detections" to items.toList()))
    private fun det(over: Map<String, Any?> = emptyMap()) = detection(1000, over)

    @Test fun `日時は時差つきだけ。Z と小数の秒は通る`() {
        assertEquals(emptyList(), paths(parseSession(newSession(mapOf("started_at" to "2026-11-18T05:00:00Z")))))
        assertEquals(emptyList(), paths(parseSession(newSession(mapOf("started_at" to "2026-11-18T05:00:00.123+09:00")))))
        assertEquals(listOf("started_at"), paths(parseSession(newSession(mapOf("started_at" to "2026-11-18T05:00:00")))))
        assertEquals(listOf("started_at"), paths(parseSession(newSession(mapOf("started_at" to "2026-11-18")))))
    }

    @Test fun `uuid は版と変種まで見る。大文字は通る`() {
        assertEquals(listOf("id"), paths(parseSession(newSession(mapOf("id" to "00000000-0000-0000-0000-000000000001")))))
        assertEquals(emptyList(), paths(parseSession(newSession(mapOf("id" to java.util.UUID.randomUUID().toString().uppercase())))))
    }

    @Test fun `任意の項目に null は入れられない。文字列の数も通らない`() {
        assertEquals(listOf("weight_kg"), paths(parseSession(newSession(mapOf("weight_kg" to null)))))
        assertEquals(listOf("weight_kg"), paths(parseSession(newSession(mapOf("weight_kg" to "60")))))
        assertEquals(listOf("weight_kg"), paths(parseSession(newSession(mapOf("weight_kg" to 0)))))
        assertEquals(emptyList(), paths(parseSession(newSession(mapOf("weight_kg" to 500, "extra" to 1)))))
        assertEquals(listOf("detections.0.window_wall_ms"), paths(detections(det(mapOf("window_wall_ms" to null)))))
    }

    @Test fun `整数は小数部の無い数。1000_0 は通り、1000_5 と 2 の 60 乗は通らない`() {
        assertIs<Parsed.Ok<*>>(parseDetections(Json.parseToJsonElement("""{"detections":[${det().toString().replace("\"window_start_ms\":1000", "\"window_start_ms\":1000.0")}]}""")))
        assertEquals(listOf("detections.0.window_start_ms"), paths(detections(det(mapOf("window_start_ms" to 1000.5)))))
        assertEquals(listOf("detections.0.window_start_ms"), paths(detections(det(mapOf("window_start_ms" to (1L shl 60))))))
    }

    @Test fun `lat と lon の片方だけは、ほかが正しいときだけ窓そのものの間違いになる`() {
        assertEquals(listOf("detections.0"), paths(detections(det().without("lon"))))
        assertEquals(listOf("detections.0.class"), paths(detections(det(mapOf("class" to "x")).without("lon"))))
    }

    @Test fun `間違いはすべて返す。scores は 3 つ以外を無視する`() {
        assertEquals(
            listOf("detections.0.window_s", "detections.1.lat"),
            paths(detections(det(mapOf("window_s" to 0)), detection(1500, mapOf("lat" to 100)))),
        )
        assertEquals(listOf("detections.0.scores.rough"), paths(detections(det(mapOf("scores" to mapOf("flat" to 1, "step" to 2))))))
        val ok = parseDetections(obj("detections" to listOf(det(mapOf("scores" to mapOf("flat" to 1, "step" to 2, "rough" to 3, "x" to 4))))))
        assertEquals(setOf("flat", "step", "rough"), (ok as Parsed.Ok).value.single().scores.keys)
    }

    @Test fun `本文がオブジェクトでなければ path は空`() {
        assertEquals(listOf(""), paths(parseSession(Json.parseToJsonElement("[1]"))))
        assertEquals(listOf(""), paths(parseSession(Json.parseToJsonElement("null"))))
        assertEquals(listOf("detections"), paths(parseDetections(obj("detections" to emptyList<Any>()))))
    }

    @Test fun `DATABASE_URL を JDBC の形に分ける`() {
        val c = Config.parseDatabaseUrl("postgres://roadml:p%40ss@127.0.0.1:5433/roadml?sslmode=require", 3)
        assertEquals(DbConfig("jdbc:postgresql://127.0.0.1:5433/roadml?sslmode=require", "roadml", "p@ss", 3), c)
    }
}
