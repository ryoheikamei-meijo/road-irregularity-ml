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
    private fun line(wall: Long, cls: String, lat: Double? = 35.0, lon: Double? = 137.0): String =
        DetectionRecord(wall, wall, 2.0, cls, mapOf("flat" to 0.0, "step" to 0.0, "rough" to 0.0),
            if (lat != null && lon != null) Fix(lat, lon, 5f, wall) else null).toJson()

    @Test fun `アプリが書く行を読める。位置の無い行と壊れた行は飛ばす`() {
        val p = MapData.parseLine(line(1000, "step", 35.1, 136.9))!!
        assertEquals(MapPoint(35.1, 136.9, "step", 1000), p)
        assertNull(MapData.parseLine(line(1000, "flat", null, null)))
        assertNull(MapData.parseLine("\u0000\u0000\u0000"))
        assertNull(MapData.parseLine("""{"class":"step","lat":95.0,"lon":137.0}"""))
    }

    @Test fun `線は間が 5 秒より空いたら切る。時刻が戻っても切る`() {
        val pts = listOf(0L, 500L, 1000L, 7000L, 7500L, 7000L).map { MapPoint(35.0, 137.0, "flat", it) }
        assertEquals(listOf(3, 2, 1), MapData.tracks(pts).map { it.size })
    }

    @Test fun `点は step と rough だけ。線は 2 点以上だけ。どちらも正しい GeoJSON`() {
        val pts = listOf(MapPoint(35.0, 137.0, "flat", 0), MapPoint(35.001, 137.001, "step", 500),
            MapPoint(35.002, 137.002, "rough", 1000), MapPoint(35.003, 137.003, "flat", 10_000))
        val marks = JSONObject(MapData.marksGeoJson(pts.asSequence())).getJSONArray("features")
        assertEquals(2, marks.length())
        assertEquals("step", marks.getJSONObject(0).getJSONObject("properties").getString("class"))
        // GeoJSON の座標は 経度, 緯度 の順
        assertEquals(137.001, marks.getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates").getDouble(0), 0.0)
        val lines = JSONObject(MapData.linesGeoJson(listOf(pts))).getJSONArray("features")
        assertEquals(1, lines.length())  // 最後の 1 点は、間が空いて 1 点だけの線になるので描かない
        assertEquals(3, lines.getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates").length())
        assertEquals(0, JSONObject(MapData.pointGeoJson(null, null)).getJSONArray("features").length())
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
