package roadml.server

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

/**
 * 入力の検証。TypeScript 版(Zod)と同じ規則にする(アプリの送る形は変えない)。
 * - 知らないキーは無視する。任意の項目に null を入れるのはエラー(Zod の optional と同じ)
 * - 整数は「小数部の無い数」で、±2^53 − 1 の範囲(JavaScript の安全な整数)
 * - 間違いは、項目の場所(path)と理由をすべて返す
 */
val CLASSES = listOf("flat", "step", "rough")

/** 1 回のバッチの上限。数秒ごとに送るので 2 窓/秒 × 数十秒でも余裕がある。再送でためた分も入るように大きめにする */
const val MAX_BATCH = 2000

data class Issue(val path: String, val message: String)

data class SessionBody(
    val id: String, val deviceId: String, val startedAt: String, val appVersion: String, val modelVersion: String,
    val wheelchair: String?, val weightKg: Double?,
)

data class Detection(
    val windowStartMs: Long, val windowWallMs: Long?, val windowS: Double, val cls: String,
    /** SVM の決定関数の値(確率ではない)。flat・step・rough の 3 つだけを、届いた数の表記のまま持つ */
    val scores: JsonObject,
    val lat: Double?, val lon: Double?, val accuracyM: Double?, val locatedAtMs: Long?,
)

data class RawComplete(val sizeBytes: Long, val sha256: String)

sealed interface Parsed<out T> {
    data class Ok<T>(val value: T) : Parsed<T>
    data class Invalid(val issues: List<Issue>) : Parsed<Nothing>
}

private val UUID_RE = Regex("^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$")
private val SHA256_RE = Regex("^[0-9a-f]{64}$")
private const val MAX_SAFE_INTEGER = 9007199254740991.0

fun isUuid(s: String) = UUID_RE.matches(s)

/** 1 つのオブジェクトを読みながら、間違いを issues にためる */
private class Reader(val obj: JsonObject, val prefix: String, val issues: MutableList<Issue>) {
    fun path(name: String) = when {
        prefix.isEmpty() -> name
        name.isEmpty() -> prefix
        else -> "$prefix.$name"
    }
    fun fail(name: String, message: String) { issues += Issue(path(name), message) }

    /** 無ければ null(required なら間違い)。ある場合は null も含めて検証に回す */
    fun present(name: String, required: Boolean): JsonElement? {
        val e = obj[name]
        if (e == null && required) fail(name, "必須")
        return e
    }

    fun string(name: String, required: Boolean = true, min: Int = 0, max: Int = Int.MAX_VALUE, check: ((String) -> String?)? = null): String? {
        val e = present(name, required) ?: return null
        if (e !is JsonPrimitive || e is JsonNull || !e.isString) { fail(name, "文字列"); return null }
        val s = e.content
        if (s.length < min) { fail(name, "$min 文字以上"); return null }
        if (s.length > max) { fail(name, "$max 文字以下"); return null }
        check?.invoke(s)?.let { fail(name, it); return null }
        return s
    }

    fun number(name: String, required: Boolean = true, check: (Double) -> String? = { null }): Double? {
        val e = present(name, required) ?: return null
        val v = (e as? JsonPrimitive)?.takeIf { it !is JsonNull && !it.isString }?.content?.toDoubleOrNull()
        if (v == null || !v.isFinite()) { fail(name, "数"); return null }
        check(v)?.let { fail(name, it); return null }
        return v
    }

    fun int(name: String, required: Boolean = true, check: (Long) -> String? = { null }): Long? {
        val v = number(name, required) ?: return null
        if (v != Math.floor(v) || Math.abs(v) > MAX_SAFE_INTEGER) { fail(name, "整数"); return null }
        val n = v.toLong()
        check(n)?.let { fail(name, it); return null }
        return n
    }

    fun obj(name: String): Reader? {
        val e = present(name, true) ?: return null
        if (e !is JsonObject) { fail(name, "オブジェクト"); return null }
        return Reader(e, path(name), issues)
    }
}

private fun <T> parseObject(json: JsonElement, read: (Reader) -> T?): Parsed<T> {
    val issues = mutableListOf<Issue>()
    if (json !is JsonObject) return Parsed.Invalid(listOf(Issue("", "オブジェクト")))
    val v = read(Reader(json, "", issues))
    return if (issues.isEmpty() && v != null) Parsed.Ok(v) else Parsed.Invalid(issues)
}

private val nonNegative: (Long) -> String? = { if (it < 0) "0 以上" else null }

fun parseSession(json: JsonElement): Parsed<SessionBody> = parseObject(json) { r ->
    val id = r.string("id", check = { if (isUuid(it)) null else "uuid" })
    val deviceId = r.string("device_id", min = 1, max = 128)
    val startedAt = r.string("started_at", check = {
        try { OffsetDateTime.parse(it); null } catch (e: DateTimeParseException) { "時差つきの ISO 8601 の日時" }
    })
    val appVersion = r.string("app_version", min = 1, max = 64)
    val modelVersion = r.string("model_version", min = 1, max = 64)
    val wheelchair = r.string("wheelchair", required = false, max = 128)
    val weightKg = r.number("weight_kg", required = false) { if (it <= 0 || it > 500) "0 より大きく 500 以下" else null }
    if (id == null || deviceId == null || startedAt == null || appVersion == null || modelVersion == null) null
    else SessionBody(id, deviceId, startedAt, appVersion, modelVersion, wheelchair, weightKg)
}

private fun readDetection(r: Reader): Detection? {
    val before = r.issues.size
    val start = r.int("window_start_ms", check = nonNegative)
    val wall = r.int("window_wall_ms", required = false, check = nonNegative)
    val windowS = r.number("window_s") { if (it <= 0 || it > 60) "0 より大きく 60 以下" else null }
    val cls = r.string("class", check = { if (it in CLASSES) null else "flat・step・rough のどれか" })
    val scores = r.obj("scores")?.let { s ->
        val vals = CLASSES.associateWith { s.number(it) }
        if (vals.values.any { it == null }) null else JsonObject(CLASSES.associateWith { s.obj[it]!! })
    }
    val lat = r.number("lat", required = false) { if (it < -90 || it > 90) "-90 以上 90 以下" else null }
    val lon = r.number("lon", required = false) { if (it < -180 || it > 180) "-180 以上 180 以下" else null }
    val acc = r.number("accuracy_m", required = false) { if (it < 0) "0 以上" else null }
    val located = r.int("located_at_ms", required = false, check = nonNegative)
    // Zod の refine と同じく、ほかの項目が正しいときだけ確かめる
    if (r.issues.size == before && (r.obj["lat"] == null) != (r.obj["lon"] == null)) r.fail("", "lat と lon は両方つけるか、両方つけない")
    if (r.issues.size != before) return null
    return Detection(start!!, wall, windowS!!, cls!!, scores!!, lat, lon, acc, located)
}

fun parseDetections(json: JsonElement): Parsed<List<Detection>> = parseObject(json) { r ->
    val e = r.present("detections", true) ?: return@parseObject null
    if (e !is JsonArray) { r.fail("detections", "配列"); return@parseObject null }
    if (e.size < 1) { r.fail("detections", "1 件以上"); return@parseObject null }
    if (e.size > MAX_BATCH) { r.fail("detections", "$MAX_BATCH 件以下"); return@parseObject null }
    e.mapIndexed { i, item ->
        val p = "detections.$i"
        if (item !is JsonObject) { r.issues += Issue(p, "オブジェクト"); null } else readDetection(Reader(item, p, r.issues))
    }.takeIf { list -> list.all { it != null } }?.map { it!! }
}

fun parseRawComplete(json: JsonElement): Parsed<RawComplete> = parseObject(json) { r ->
    val size = r.int("size_bytes") { if (it <= 0) "正の整数" else null }
    val sha = r.string("sha256", check = { if (SHA256_RE.matches(it)) null else "sha256 は小文字の 16 進 64 桁" })
    if (size == null || sha == null) null else RawComplete(size, sha)
}
