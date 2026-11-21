package com.example.roaddetector.map

import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile

/** 地図に載せる 1 窓。cls は flat・step・rough(サーバーへ送る形と同じ)。score は、その窓の cls の決定関数の値 */
data class MapPoint(val lat: Double, val lon: Double, val cls: String, val wallMs: Long, val score: Double = 0.0)

/** 同じ判定が続いた窓を 1 つにまとめたもの(段差 1 か所、凸凹 1 区間)。points は時刻の順 */
data class MapEvent(val cls: String, val points: List<MapPoint>) {
    /** 印を立てる窓: 決定関数の値が最大の窓 */
    val representative: MapPoint get() = points.maxBy { it.score }
}

/**
 * 端末に残る判定結果(detections.jsonl)を、地図に描く形(GeoJSON)にする。地図の土台(OSM か Google か)には依存しない。
 * - 段差: 続いた窓を 1 か所にまとめ、ピン 1 つ(点)
 * - 凸凹: 続いた窓を 1 区間にまとめ、帯(線)
 * - 線: 通った道。位置の付いた窓を時刻の順につなぐ。間が TRACK_GAP_MS より空いたら(GPS が途切れた、など)線を切る
 * (docs/knowledge/2026-11-19/20261119_android_map_plan.md)
 *
 * まとめ方は docs/knowledge/2026-11-19/20261119_window_merge_design.md の暫定の案(gap 0・min_n 3):
 * 同じクラスの窓が続いたものだけを 1 つにし(間にほかのクラスが挟まったら切る)、MIN_WINDOWS 個に満たないものは描かない。
 * 16 走行の分析で、段差の印は 1,470 → 162、凸凹は 730 → 67 に減り、正解の通過の再現率は 1.000 のまま、
 * flat の走行での誤検知は 2.66 → 0.70 /分になった。段差は一瞬のイベントなので点、凸凹は続く路面の状態なので区間で描く。
 */
object MapData {
    /** 窓は 0.5 秒ごと。これより間が空いたら、別の線にする */
    const val TRACK_GAP_MS = 5_000L
    /** 隣り合う窓とみなす間隔の上限(窓は 0.5 秒ごと)。これより空いたら(位置の無い窓・壊れた行が挟まった)、まとまりを切る */
    const val EVENT_STEP_MS = 750L
    /** これより少ない窓のまとまりは描かない(min_n) */
    const val MIN_WINDOWS = 3
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
        val score = o.optJSONObject("scores")?.optDouble(cls, 0.0)?.takeIf { it.isFinite() } ?: 0.0
        return MapPoint(lat, lon, cls, o.optLong("window_wall_ms", 0L), score)
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

    /** 1 つの走行の窓(時刻の順)から、段差・凸凹のまとまり。続いていない(間にほかのクラス、または時間の空き)ところで切る */
    fun events(points: List<MapPoint>): List<MapEvent> {
        val out = ArrayList<MapEvent>()
        var cur = ArrayList<MapPoint>()
        fun flush() {
            if (cur.size >= MIN_WINDOWS) out += MapEvent(cur[0].cls, cur)
            cur = ArrayList()
        }
        for (p in points) {
            val last = cur.lastOrNull()
            if (last != null && (p.cls != last.cls || p.wallMs - last.wallMs !in 1..EVENT_STEP_MS)) flush()
            if (p.cls in MARKED) cur += p
        }
        flush()
        return out
    }

    /** 走行ごとの窓から、段差・凸凹のまとまり(走行をまたいではまとめない) */
    fun events(sessions: Collection<List<MapPoint>>): List<MapEvent> = sessions.flatMap { events(it) }

    /** 段差のピンの FeatureCollection。1 か所に 1 つ、決定関数の値が最大の窓の位置に立てる */
    fun stepsGeoJson(events: List<MapEvent>): String =
        collection(events.filter { it.cls == "step" }.map {
            """{"type":"Feature","properties":{},"geometry":{"type":"Point","coordinates":${coord(it.representative)}}}"""
        })

    /**
     * 凸凹の区間の FeatureCollection。続いた窓の位置をつないだ線にする。
     * GPS は 1 秒ごとなので、窓の位置が全部同じになることがある。そのときは線にならないので、点にする(地図では帯と同じ見た目の丸)
     */
    fun roughGeoJson(events: List<MapEvent>): String =
        collection(events.filter { it.cls == "rough" }.map { e ->
            val coords = e.points.map { coord(it) }.fold(ArrayList<String>()) { acc, c -> if (acc.lastOrNull() != c) acc += c; acc }
            if (coords.size >= 2) """{"type":"Feature","properties":{},"geometry":{"type":"LineString","coordinates":[${coords.joinToString(",")}]}}"""
            else """{"type":"Feature","properties":{},"geometry":{"type":"Point","coordinates":${coords[0]}}}"""
        })

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
