package com.example.roaddetector.upload

import org.json.JSONObject

/** 判定に付ける位置(GPS)。wallMs は位置を取った壁時計(epoch ms) */
data class Fix(val lat: Double, val lon: Double, val accuracyM: Float?, val wallMs: Long)

/**
 * サーバーへ送る判定結果 1 窓分。サーバーの POST /sessions/:id/detections の 1 件と同じ形(apps/server/src/schemas.ts)。
 * - windowStartMs: センサーのタイムスタンプ[ms](端末の起動から)。生データ input.csv の timestamp 列と同じ基準
 * - windowWallMs: 窓の始まりの壁時計(epoch ms)
 * - cls: flat / step / rough(モデルの dansa・dekobo は、送る前に置き換える)
 */
class DetectionRecord(
    val windowStartMs: Long,
    val windowWallMs: Long,
    val windowS: Double,
    val cls: String,
    val scores: Map<String, Double>,
    val fix: Fix?,
) {
    /** 数値のどれかが NaN・無限大なら null(JSON にできず、サーバーも受け付けない)。位置だけが壊れているときは、位置を外して送る */
    fun toJsonOrNull(): String? {
        if (scores.values.any { !it.isFinite() } || !windowS.isFinite()) return null
        val usable = fix?.takeIf { it.lat.isFinite() && it.lon.isFinite() }
        val clean = if (usable != null && usable.accuracyM != null && !usable.accuracyM.isFinite()) usable.copy(accuracyM = null) else usable
        return DetectionRecord(windowStartMs, windowWallMs, windowS, cls, scores, clean).toJson()
    }

    fun toJson(): String {
        val o = JSONObject()
            .put("window_start_ms", windowStartMs).put("window_wall_ms", windowWallMs)
            .put("window_s", windowS).put("class", cls)
            .put("scores", JSONObject().also { s -> scores.forEach { (k, v) -> s.put(k, v) } })
        if (fix != null) {
            o.put("lat", fix.lat).put("lon", fix.lon).put("located_at_ms", fix.wallMs)
            if (fix.accuracyM != null) o.put("accuracy_m", fix.accuracyM.toDouble())
        }
        return o.toString()
    }
}
