package com.example.roaddetector

import com.example.roaddetector.core.CoreFeatureExtractor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sin

/**
 * 壊れたサンプル(姿勢が全部 0、NaN)が混ざっても、そのサンプルを捨てるだけで、結果が変わらないこと。
 * 実際に、エミュレーターで走り始めに姿勢が全部 0 のサンプルが届き、NaN が傾きの基準に入ってアプリが落ちた(2026-11-18)。
 */
class CoreFeatureExtractorRobustnessTest {
    private class Sample(val t: Double, val a: DoubleArray, val q: DoubleArray)

    private fun clean(seconds: Int = 30): List<Sample> = (0 until seconds * 100).map { i ->
        val t = 1000.0 + i * 10.0
        // 揺れと、ゆっくり変わる姿勢(傾きが 0 でなくなるように)
        val tilt = 0.02 * sin(i / 150.0)
        val q = doubleArrayOf(sin(tilt / 2), 0.0, 0.0, kotlin.math.cos(tilt / 2))
        Sample(t, doubleArrayOf(0.3 * sin(i / 3.0), 0.2 * sin(i / 5.0), 9.8 + 0.5 * sin(i / 2.0)), q)
    }

    private fun run(samples: List<Sample>, extra: Map<Int, Sample> = emptyMap()): List<CoreFeatureExtractor.Window> {
        val ext = CoreFeatureExtractor(CoreFeatureExtractor.TiltReference.StartMean(10_000.0))
        val out = ArrayList<CoreFeatureExtractor.Window>()
        samples.forEachIndexed { i, s ->
            extra[i]?.let { b -> out += ext.push(b.t, b.a[0], b.a[1], b.a[2], b.q[0], b.q[1], b.q[2], b.q[3]) }
            out += ext.push(s.t, s.a[0], s.a[1], s.a[2], s.q[0], s.q[1], s.q[2], s.q[3])
        }
        return out
    }

    @Test fun `姿勢が全部 0 のサンプルや NaN が混ざっても、結果は変わらない`() {
        val base = clean()
        val expected = run(base)
        assertTrue("窓が出ること", expected.size > 40)
        val bad = mapOf(
            0 to Sample(base[0].t - 10, doubleArrayOf(0.0, 9.8, 0.8), doubleArrayOf(0.0, 0.0, 0.0, 0.0)),            // 走り始めの全部 0
            700 to Sample(base[700].t - 5, doubleArrayOf(Double.NaN, 1.0, 9.8), base[700].q),                          // 加速度が NaN
            1500 to Sample(base[1500].t - 5, doubleArrayOf(0.0, 0.0, 9.8), doubleArrayOf(Double.NaN, 0.0, 0.0, 1.0)),  // 姿勢が NaN
            2000 to Sample(base[2000].t - 5, doubleArrayOf(0.0, 0.0, 9.8), doubleArrayOf(0.0, 0.0, 0.0, 0.0)),          // 途中の全部 0
        )
        val actual = run(base, bad)
        assertEquals(expected.size, actual.size)
        for (i in expected.indices) {
            assertEquals(expected[i].startMs, actual[i].startMs, 0.0)
            for (k in expected[i].features.indices) {
                assertEquals("窓 $i 特徴量 $k", expected[i].features[k], actual[i].features[k], 0.0)
                assertTrue("窓 $i 特徴量 $k が有限", actual[i].features[k].isFinite())
            }
        }
    }
}
