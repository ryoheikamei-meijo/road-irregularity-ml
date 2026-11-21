package com.example.roaddetector.map

import com.example.roaddetector.upload.DetectionRecord
import com.example.roaddetector.upload.Fix
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** 端末に残る判定結果から、地図に描く点と線を作る(地図の土台には依存しない部分) */
class MapDataTest {
    private fun line(wall: Long, cls: String, lat: Double? = 35.0, lon: Double? = 137.0, score: Double = 0.0): String =
        DetectionRecord(wall, wall, 2.0, cls, mapOf("flat" to 0.0, "step" to 0.0, "rough" to 0.0) + (cls to score),
            if (lat != null && lon != null) Fix(lat, lon, 5f, wall) else null).toJson()

    /** 0.5 秒ごとの窓。classes の 1 文字が 1 窓(s: step、r: rough、f: flat)。位置は窓ごとに北へずらす */
    private fun windows(classes: String, start: Long = 0L): List<MapPoint> = classes.mapIndexed { i, c ->
        val cls = when (c) { 's' -> "step"; 'r' -> "rough"; else -> "flat" }
        MapPoint(35.0 + i * 1e-5, 137.0, cls, start + i * 500L)
    }

    @Test fun `アプリが書く行を読める。位置の無い行と壊れた行は飛ばす`() {
        val p = MapData.parseLine(line(1000, "step", 35.1, 136.9, score = 1.5))!!
        assertEquals(MapPoint(35.1, 136.9, "step", 1000, 1.5), p)
        assertNull(MapData.parseLine(line(1000, "flat", null, null)))
        assertNull(MapData.parseLine("\u0000\u0000\u0000"))
        assertNull(MapData.parseLine("""{"class":"step","lat":95.0,"lon":137.0}"""))
    }

    @Test fun `線は間が 5 秒より空いたら切る。時刻が戻っても切る`() {
        val pts = listOf(0L, 500L, 1000L, 7000L, 7500L, 7000L).map { MapPoint(35.0, 137.0, "flat", it) }
        assertEquals(listOf(3, 2, 1), MapData.tracks(pts).map { it.size })
    }

    @Test fun `続いた窓を 1 つにまとめる。3 窓に満たないもの、ほかの判定が挟まったところは切る`() {
        // 段差 4 窓 → 平坦 → 段差 2 窓(少ないので描かない) → 凸凹 3 窓 → 段差 3 窓(凸凹のすぐ後でも、別のまとまり)
        val ev = MapData.events(windows("ssssfssrrrsss"))
        assertEquals(listOf("step" to 4, "rough" to 3, "step" to 3), ev.map { it.cls to it.points.size })
    }

    @Test fun `時間が空いたら(位置の無い窓・壊れた行が挟まった)、同じ判定でも切る。走行をまたいではまとめない`() {
        val pts = windows("sss") + windows("sss", start = 2500L)  // 1500 ms の空き
        assertEquals(listOf(3, 3), MapData.events(pts).map { it.points.size })
        assertEquals(listOf(3), MapData.events(windows("sssss").take(3)).map { it.points.size })
        // 走行の終わりと次の走行の始まりが、それぞれ 2 窓ずつなら、どちらも描かない
        assertEquals(0, MapData.events(listOf(windows("ss"), windows("ss", start = 1000L))).size)
    }

    @Test fun `段差のピンは、決定関数の値が最大の窓の位置に 1 つ立てる`() {
        val pts = windows("sss").mapIndexed { i, p -> p.copy(score = listOf(0.4, 1.8, 0.9)[i]) }
        val f = JSONObject(MapData.stepsGeoJson(MapData.events(pts))).getJSONArray("features")
        assertEquals(1, f.length())
        // GeoJSON の座標は 経度, 緯度 の順。2 つ目の窓(北へ 1e-5)
        val c = f.getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates")
        assertEquals(137.0, c.getDouble(0), 0.0)
        assertEquals(35.00001, c.getDouble(1), 1e-9)
    }

    @Test fun `凸凹は区間の線にする。位置が全部同じ(GPS が更新されていない)ときは点にする`() {
        val moving = windows("rrrr")
        val still = windows("rrr", start = 10_000L).map { it.copy(lat = 35.1) }
        val f = JSONObject(MapData.roughGeoJson(MapData.events(listOf(moving, still)))).getJSONArray("features")
        assertEquals(2, f.length())
        val line = f.getJSONObject(0).getJSONObject("geometry")
        assertEquals("LineString", line.getString("type"))
        assertEquals(4, line.getJSONArray("coordinates").length())
        assertEquals("Point", f.getJSONObject(1).getJSONObject("geometry").getString("type"))
        // 段差のまとまりは、凸凹には入らない
        assertEquals(0, JSONObject(MapData.roughGeoJson(MapData.events(windows("sss")))).getJSONArray("features").length())
    }

    @Test fun `線は 2 点以上だけ描く`() {
        val pts = listOf(MapPoint(35.0, 137.0, "flat", 0), MapPoint(35.001, 137.001, "step", 500),
            MapPoint(35.002, 137.002, "rough", 1000), MapPoint(35.003, 137.003, "flat", 10_000))
        val lines = JSONObject(MapData.linesGeoJson(listOf(pts))).getJSONArray("features")
        assertEquals(1, lines.length())  // 最後の 1 点は、間が空いて 1 点だけの線になるので描かない
        assertEquals(3, lines.getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates").length())
    }

    @Test fun `範囲は全部の点を囲む`() {
        val b = MapData.bounds(sequenceOf(MapPoint(35.0, 137.0, "flat", 0), MapPoint(34.5, 137.5, "step", 0)))!!
        assertEquals(listOf(34.5, 137.0, 35.0, 137.5), b.toList())
        assertNull(MapData.bounds(emptySequence()))
    }

    @Test fun `走行中のファイルは、続きから読む。書きかけの行は次に回す`() {
        val f = Files.createTempFile("detections", ".jsonl").toFile()
        try {
            val tail = JsonlTail(f)
            assertEquals(0, tail.readNew().size)
            f.appendText(line(0, "flat") + "\n" + line(500, "step") + "\n")
            assertEquals(listOf(0L, 500L), tail.readNew().map { it.wallMs })
            val third = line(1000, "rough")
            f.appendText(third.substring(0, 10))  // 書きかけ
            assertEquals(0, tail.readNew().size)
            f.appendText(third.substring(10) + "\n")
            assertEquals(listOf(1000L), tail.readNew().map { it.wallMs })
            assertEquals(0, tail.readNew().size)
            assertEquals(3, MapData.readFile(f).size)
            assertEquals(0, MapData.readFile(File(f.parentFile, "no-such-file")).size)
        } finally {
            f.delete()
        }
    }
}
