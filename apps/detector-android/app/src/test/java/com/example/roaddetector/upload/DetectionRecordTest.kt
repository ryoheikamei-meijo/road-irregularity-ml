package com.example.roaddetector.upload

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** サーバーの Zod スキーマ(apps/server/src/schemas.ts)と同じ名前・形で送ること */
class DetectionRecordTest {
    private val scores = mapOf("flat" to 1.25, "step" to -0.5, "rough" to -0.75)

    @Test fun `位置つきの JSON の形`() {
        val j = JSONObject(DetectionRecord(123_456L, 1_793_510_619_944L, 2.0, "step", scores, Fix(35.1815, 136.9066, 8.5f, 1_793_510_621_000L)).toJson())
        assertEquals(123_456L, j.getLong("window_start_ms"))
        assertEquals(1_793_510_619_944L, j.getLong("window_wall_ms"))
        assertEquals(2.0, j.getDouble("window_s"), 0.0)
        assertEquals("step", j.getString("class"))
        assertEquals(setOf("flat", "step", "rough"), j.getJSONObject("scores").keys().asSequence().toSet())
        assertEquals(35.1815, j.getDouble("lat"), 1e-9); assertEquals(136.9066, j.getDouble("lon"), 1e-9)
        assertEquals(8.5, j.getDouble("accuracy_m"), 1e-6)
        assertEquals(1_793_510_621_000L, j.getLong("located_at_ms"))
    }

    @Test fun `位置が無いときは、位置の項目を付けない(lat だけ、は不正になるため)`() {
        val j = JSONObject(DetectionRecord(1L, 2L, 2.0, "flat", scores, null).toJson())
        for (k in listOf("lat", "lon", "accuracy_m", "located_at_ms")) assertFalse(k, j.has(k))
        assertTrue(j.has("window_start_ms"))
    }

    @Test fun `精度が無い位置でも、lat と lon は両方つく`() {
        val j = JSONObject(DetectionRecord(1L, 2L, 2.0, "flat", scores, Fix(1.0, 2.0, null, 3L)).toJson())
        assertTrue(j.has("lat") && j.has("lon")); assertFalse(j.has("accuracy_m"))
    }

    @Test fun `1 行に収まる(端末に 1 行 1 件で残すため)`() {
        assertFalse('\n' in DetectionRecord(1L, 2L, 2.0, "flat", scores, Fix(1.0, 2.0, 3f, 4L)).toJson())
    }
}

class DetectionRecordRobustnessTest {
    private val ok = mapOf("flat" to 1.0, "step" to -0.5, "rough" to -0.7)

    @Test fun `スコアが NaN なら、送らない(null)`() {
        assertNull(DetectionRecord(1L, 2L, 2.0, "flat", ok + ("step" to Double.NaN), null).toJsonOrNull())
        assertNull(DetectionRecord(1L, 2L, 2.0, "flat", ok + ("rough" to Double.POSITIVE_INFINITY), null).toJsonOrNull())
    }

    @Test fun `位置だけが壊れているときは、位置を外して送る`() {
        val j = JSONObject(DetectionRecord(1L, 2L, 2.0, "flat", ok, Fix(Double.NaN, 2.0, 3f, 4L)).toJsonOrNull()!!)
        assertFalse(j.has("lat")); assertFalse(j.has("lon")); assertFalse(j.has("located_at_ms"))
    }

    @Test fun `精度だけが壊れているときは、精度を外して位置は送る`() {
        val j = JSONObject(DetectionRecord(1L, 2L, 2.0, "flat", ok, Fix(1.0, 2.0, Float.NaN, 4L)).toJsonOrNull()!!)
        assertTrue(j.has("lat") && j.has("lon")); assertFalse(j.has("accuracy_m"))
    }
}
