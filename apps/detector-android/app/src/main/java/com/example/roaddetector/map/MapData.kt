package com.example.roaddetector.map

import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile

/** 地図に載せる 1 窓。cls は flat・step・rough(サーバーへ送る形と同じ) */
data class MapPoint(val lat: Double, val lon: Double, val cls: String, val wallMs: Long)

/**
 * 端末に残る判定結果(detections.jsonl)を、地図に描く形(GeoJSON)にする。地図の土台(OSM か Google か)には依存しない。
 * - 点: step・rough と判定した窓だけ(class の色で描く)
 * - 線: 通った道。位置の付いた窓を時刻の順につなぐ。間が TRACK_GAP_MS より空いたら(GPS が途切れた、など)線を切る
 * (docs/knowledge/2026-11-19/20261119_android_map_plan.md)
 */
object MapData {
    /** 窓は 0.5 秒ごと。これより間が空いたら、別の線にする */
    const val TRACK_GAP_MS = 5_000L
    val MARKED = setOf("step", "rough")

    /** 1 行を読む。位置が無い・壊れている(走行中に OS ごと落ちた NUL の行など)ときは null */
    fun parseLine(line: String): MapPoint? {
        val o = try { JSONObject(line) } catch (e: Exception) { return null }
        if (!o.has("lat") || !o.has("lon")) return null
        val lat = o.optDouble("lat", Double.NaN)
        val lon = o.optDouble("lon", Double.NaN)
        if (!lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0) return null
        val cls = o.optString("class", "")
        if (cls.isEmpty()) return null
        return MapPoint(lat, lon, cls, o.optLong("window_wall_ms", 0L))
    }

    fun readFile(file: File): List<MapPoint> =
        if (!file.isFile) emptyList() else file.readLines().mapNotNull { if (it.isBlank()) null else parseLine(it) }

    /** 1 つの走行の点を、線に分ける(時刻が戻ったときも切る) */
    fun tracks(points: List<MapPoint>): List<List<MapPoint>> {
        val out = ArrayList<List<MapPoint>>()
        var cur = ArrayList<MapPoint>()
        for (p in points) {
            val last = cur.lastOrNull()
            if (last != null && (p.wallMs - last.wallMs > TRACK_GAP_MS || p.wallMs < last.wallMs)) {
                out += cur; cur = ArrayList()
            }
            cur += p
        }
        if (cur.isNotEmpty()) out += cur
        return out
    }

    /** 走行ごとの点から、線の FeatureCollection。2 点に満たない線は描かない */
    fun linesGeoJson(sessions: Collection<List<MapPoint>>): String {
        val features = sessions.flatMap { tracks(it) }.filter { it.size >= 2 }.map { t ->
            """{"type":"Feature","properties":{},"geometry":{"type":"LineString","coordinates":[${t.joinToString(",") { coord(it) }}]}}"""
        }
        return collection(features)
    }

    /** step・rough の点の FeatureCollection(properties.class で色を分ける) */
    fun marksGeoJson(points: Sequence<MapPoint>): String {
        val features = points.filter { it.cls in MARKED }.map {
            """{"type":"Feature","properties":{"class":"${it.cls}"},"geometry":{"type":"Point","coordinates":${coord(it)}}}"""
        }.toList()
        return collection(features)
    }

    fun pointGeoJson(lat: Double?, lon: Double?): String =
        if (lat == null || lon == null) collection(emptyList())
        else collection(listOf("""{"type":"Feature","properties":{},"geometry":{"type":"Point","coordinates":[$lon,$lat]}}"""))

    /** 南西と北東(minLat, minLon, maxLat, maxLon)。点が無ければ null */
    fun bounds(points: Sequence<MapPoint>): DoubleArray? {
        var b: DoubleArray? = null
        for (p in points) {
            val c = b ?: doubleArrayOf(p.lat, p.lon, p.lat, p.lon).also { b = it }
            c[0] = minOf(c[0], p.lat); c[1] = minOf(c[1], p.lon); c[2] = maxOf(c[2], p.lat); c[3] = maxOf(c[3], p.lon)
        }
        return b
    }

    private fun coord(p: MapPoint) = "[${p.lon},${p.lat}]"
    private fun collection(features: List<String>) = """{"type":"FeatureCollection","features":[${features.joinToString(",")}]}"""
}

/**
 * 走行中に書き足される detections.jsonl を、前回の続きから読む(地図を走行中に更新するため)。
 * 書きかけの行(末尾に改行が無い)は、次に読むまで待つ。
 */
class JsonlTail(private val file: File) {
    private var offset = 0L

    fun readNew(): List<MapPoint> {
        if (!file.isFile) return emptyList()
        val len = file.length()
        if (len < offset) offset = 0L  // 作り直された
        if (len == offset) return emptyList()
        val buf = ByteArray((len - offset).toInt())
        RandomAccessFile(file, "r").use { it.seek(offset); it.readFully(buf) }
        val end = buf.lastIndexOf('\n'.code.toByte())
        if (end < 0) return emptyList()
        offset += end + 1
        return String(buf, 0, end + 1, Charsets.UTF_8).lineSequence()
            .mapNotNull { if (it.isBlank()) null else MapData.parseLine(it) }.toList()
    }
}
