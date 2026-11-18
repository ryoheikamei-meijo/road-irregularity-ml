package com.example.roaddetector.core

import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.sqrt

/**
 * 判定に使う core の 5 個の特徴量を、センサーのサンプルを 1 つずつ受け取りながら計算する。
 *
 * 研究リポジトリの基準の実装 src/roadml/core_model.py と同じ手順。傾きの基準(tilt_ref)は、モデルの model_info.json の値に合わせる。
 * - 世界座標系の加速度 = 姿勢(rotation vector の四元数 x, y, z, w)で端末座標の加速度を回したもの
 * - z = 世界の鉛直 − 重力、h = √(x² + y²)
 * - 傾き = 端末の座標系で見た世界の上向きと、基準の向きとのなす角 [度]。基準は TiltReference
 *   (mean10: 直近 10 秒の上向きの平均 = Mizell 2003 の窓の平均。サンプルごとに取り直す。v3。mean30 は v2。
 *    startmean10: 窓の最初のサンプルの時点の mean10 を、その窓の中で固定して使う。v4。ema30: 時定数 30 秒の指数移動平均)
 * - 窓: 長さ 2.0 秒、0.5 秒ずつずらす。最初の窓は最初のサンプルの時刻から始まる。
 *   窓の中のサンプルが想定(窓の長さ / サンプル間隔の中央値)の 8 割に満たない窓は出さない
 *
 * 特徴量の順番は FEATURES(ONNX のモデルの入力と同じ)。
 */
class CoreFeatureExtractor(
    private val tiltRef: TiltReference = TiltReference.StartMean(10_000.0),
    private val windowMs: Double = 2000.0,
    private val strideMs: Double = 500.0,
    private val minFill: Double = 0.8,
    private val gravity: Double = 9.80665,
) {
    companion object {
        val FEATURES = listOf("z_rms", "z_kurt", "h_std", "h_crest", "tilt_range")
        /** これより短い四元数は、姿勢として使えない(壊れたサンプル) */
        const val MIN_QUAT_NORM = 1e-6
    }

    /** 傾きの基準の取り方。名前は model_info.json の tilt_ref と同じ(例: "startmean10"、"mean30"、"ema30")。 */
    sealed class TiltReference {
        /** 直近 spanMs の上向きの平均(長さ 1 にそろえる)。サンプルごとに取り直すので、窓の中でも基準が動く。 */
        data class PastMean(val spanMs: Double) : TiltReference()
        /** 窓の最初のサンプルの時点での PastMean(spanMs) を、その窓の中で固定して使う。 */
        data class StartMean(val spanMs: Double) : TiltReference()
        /** 時定数 tauMs の指数移動平均(長さ 1 にそろえる)。 */
        data class Ema(val tauMs: Double) : TiltReference()

        companion object {
            fun parse(name: String): TiltReference = when {
                name.startsWith("startmean") -> StartMean(name.removePrefix("startmean").toDouble() * 1000.0)
                name.startsWith("mean") -> PastMean(name.removePrefix("mean").toDouble() * 1000.0)
                name.startsWith("ema") -> Ema(name.removePrefix("ema").toDouble() * 1000.0)
                else -> throw IllegalArgumentException("未対応の tilt_ref: $name")
            }
        }
    }

    class Window(val startMs: Double, val nSamples: Int, val features: DoubleArray)

    private var ts = DoubleArray(4096)
    private var zs = DoubleArray(4096)
    private var hs = DoubleArray(4096)
    private var tilts = DoubleArray(4096)
    // StartMean 用: サンプルごとの上向きと、その時点の基準(窓の最初のサンプルの基準で、窓の中の傾きを求め直す)
    private var uxs = DoubleArray(4096)
    private var uys = DoubleArray(4096)
    private var uzs = DoubleArray(4096)
    private var rxs = DoubleArray(4096)
    private var rys = DoubleArray(4096)
    private var rzs = DoubleArray(4096)
    private var head = 0  // バッファの先頭(まだ使う一番古いサンプル)
    private var size = 0

    private var nextStartMs = Double.NaN
    private var lastTsMs = Double.NaN
    private var refX = 0.0
    private var refY = 0.0
    private var refZ = 0.0

    // PastMean 用: 直近の上向き(時刻と 3 成分)と、その合計
    private var upTs = DoubleArray(16384)
    private var upX = DoubleArray(16384)
    private var upY = DoubleArray(16384)
    private var upZ = DoubleArray(16384)
    private var upHead = 0
    private var upSize = 0
    private var sumX = 0.0
    private var sumY = 0.0
    private var sumZ = 0.0

    /** サンプルを 1 つ足し、それで出そろった窓を返す(多くの場合は空)。時刻は単調に増える前提。 */
    fun push(tsMs: Double, ax: Double, ay: Double, az: Double,
             qx: Double, qy: Double, qz: Double, qw: Double): List<Window> {
        // 壊れたサンプルは、状態に触れずに捨てる。走り始めに、姿勢が全部 0 のサンプルが届くことがあり(エミュレーターで確認)、
        // 長さ 0 で割ると NaN になる。直近の平均の合計に NaN が入ると、引き算しても消えず、その走行の傾きが以後ずっと NaN になる。
        if (!(tsMs.isFinite() && ax.isFinite() && ay.isFinite() && az.isFinite() &&
                    qx.isFinite() && qy.isFinite() && qz.isFinite() && qw.isFinite())) return emptyList()
        // 四元数を長さ 1 にそろえる(scipy の Rotation.from_quat と同じ)
        val n = sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
        if (n < MIN_QUAT_NORM) return emptyList()
        val x = qx / n; val y = qy / n; val z = qz / n; val w = qw / n
        // 回転行列の 3 行目 = 世界の鉛直の成分、かつ端末の座標系で見た世界の上向き
        val r20 = 2 * (x * z - y * w)
        val r21 = 2 * (y * z + x * w)
        val r22 = 1 - 2 * (x * x + y * y)
        val worldX = (1 - 2 * (y * y + z * z)) * ax + 2 * (x * y - z * w) * ay + 2 * (x * z + y * w) * az
        val worldY = 2 * (x * y + z * w) * ax + (1 - 2 * (x * x + z * z)) * ay + 2 * (y * z - x * w) * az
        val worldZ = r20 * ax + r21 * ay + r22 * az

        if (lastTsMs.isNaN()) nextStartMs = tsMs
        updateReference(tsMs, r20, r21, r22)
        lastTsMs = tsMs
        val dot = (r20 * refX + r21 * refY + r22 * refZ).coerceIn(-1.0, 1.0)

        val out = ArrayList<Window>(1)
        // このサンプルの時刻で、終わりを迎えた窓を出す(窓は [start, start + 長さ) のサンプルを使う)
        while (nextStartMs + windowMs <= tsMs) {
            evaluate(nextStartMs)?.let { out.add(it) }
            nextStartMs += strideMs
            dropBefore(nextStartMs)
        }
        append(tsMs, worldZ - gravity, hypot(worldX, worldY), Math.toDegrees(acos(dot)), r20, r21, r22)
        return out
    }

    private fun updateReference(tsMs: Double, ux: Double, uy: Double, uz: Double) {
        when (val ref = tiltRef) {
            is TiltReference.Ema -> {
                if (lastTsMs.isNaN()) {
                    refX = ux; refY = uy; refZ = uz
                } else {
                    val alpha = 1.0 - exp(-(tsMs - lastTsMs) / ref.tauMs)
                    refX += alpha * (ux - refX); refY += alpha * (uy - refY); refZ += alpha * (uz - refZ)
                    val rn = sqrt(refX * refX + refY * refY + refZ * refZ)
                    refX /= rn; refY /= rn; refZ /= rn
                }
            }
            is TiltReference.PastMean -> updatePastMean(tsMs, ux, uy, uz, ref.spanMs)
            is TiltReference.StartMean -> updatePastMean(tsMs, ux, uy, uz, ref.spanMs)
        }
    }

    private fun updatePastMean(tsMs: Double, ux: Double, uy: Double, uz: Double, spanMs: Double) {
        // 今のサンプルを足し、時刻が (今 − spanMs) より前のサンプルを外す(core_model._past_mean と同じ範囲)
        if (upSize == upTs.size) growUp()
        val i = (upHead + upSize) % upTs.size
        upTs[i] = tsMs; upX[i] = ux; upY[i] = uy; upZ[i] = uz
        upSize++
        sumX += ux; sumY += uy; sumZ += uz
        val from = tsMs - spanMs
        while (upSize > 0 && upTs[upHead] < from) {
            sumX -= upX[upHead]; sumY -= upY[upHead]; sumZ -= upZ[upHead]
            upHead = (upHead + 1) % upTs.size
            upSize--
        }
        val rn = sqrt(sumX * sumX + sumY * sumY + sumZ * sumZ)
        refX = sumX / rn; refY = sumY / rn; refZ = sumZ / rn
    }

    private fun growUp() {
        val cap = upTs.size * 2
        fun copy(a: DoubleArray) = DoubleArray(cap).also { b -> for (k in 0 until upSize) b[k] = a[(upHead + k) % a.size] }
        upTs = copy(upTs); upX = copy(upX); upY = copy(upY); upZ = copy(upZ)
        upHead = 0
    }

    private fun evaluate(start: Double): Window? {
        val end = start + windowMs
        var lo = -1
        var hi = -1
        for (k in 0 until size) {
            val t = ts[(head + k) % ts.size]
            if (lo < 0 && t >= start) lo = k
            if (t >= end) { hi = k; break }
        }
        if (lo < 0) return null
        if (hi < 0) hi = size
        val count = hi - lo
        if (count < 2) return null
        // サンプル間隔の中央値から、想定のサンプル数を出す
        val dts = DoubleArray(count - 1) { at(ts, lo + it + 1) - at(ts, lo + it) }
        dts.sort()
        val medianDt = if (dts.size % 2 == 1) dts[dts.size / 2] else (dts[dts.size / 2 - 1] + dts[dts.size / 2]) / 2
        if (count < minFill * windowMs / medianDt) return null

        var zSum = 0.0; var hSum = 0.0; var zSq = 0.0; var hSq = 0.0
        var hAbsMax = 0.0; var tMin = Double.POSITIVE_INFINITY; var tMax = Double.NEGATIVE_INFINITY
        val fixedRef = tiltRef is TiltReference.StartMean
        val rx = at(rxs, lo); val ry = at(rys, lo); val rz = at(rzs, lo)  // 窓の最初のサンプルの時点の基準
        for (k in lo until hi) {
            val zv = at(zs, k); val hv = at(hs, k)
            val tv = if (fixedRef) {
                Math.toDegrees(acos((at(uxs, k) * rx + at(uys, k) * ry + at(uzs, k) * rz).coerceIn(-1.0, 1.0)))
            } else at(tilts, k)
            zSum += zv; hSum += hv; zSq += zv * zv; hSq += hv * hv
            if (abs(hv) > hAbsMax) hAbsMax = abs(hv)
            if (tv < tMin) tMin = tv
            if (tv > tMax) tMax = tv
        }
        val zMean = zSum / count
        val hMean = hSum / count
        var m2 = 0.0; var m4 = 0.0; var hVar = 0.0
        for (k in lo until hi) {
            val dz = at(zs, k) - zMean
            m2 += dz * dz; m4 += dz * dz * dz * dz
            val dh = at(hs, k) - hMean
            hVar += dh * dh
        }
        m2 /= count; m4 /= count; hVar /= count
        val zRms = sqrt(zSq / count)
        val hRms = sqrt(hSq / count)
        val features = doubleArrayOf(
            zRms,
            if (m2 > 0) m4 / (m2 * m2) - 3.0 else 0.0,  // 超過尖度(scipy.stats.kurtosis と同じ、偏りの補正なし)
            sqrt(hVar),
            if (hRms > 0) hAbsMax / hRms else 0.0,
            tMax - tMin,
        )
        return Window(start, count, features)
    }

    private fun at(arr: DoubleArray, k: Int): Double = arr[(head + k) % arr.size]

    private fun dropBefore(t: Double) {
        while (size > 0 && ts[head] < t) {
            head = (head + 1) % ts.size
            size--
        }
    }

    private fun append(t: Double, z: Double, h: Double, tilt: Double, ux: Double, uy: Double, uz: Double) {
        if (size == ts.size) grow()
        val i = (head + size) % ts.size
        ts[i] = t; zs[i] = z; hs[i] = h; tilts[i] = tilt
        uxs[i] = ux; uys[i] = uy; uzs[i] = uz; rxs[i] = refX; rys[i] = refY; rzs[i] = refZ
        size++
    }

    private fun grow() {
        val cap = ts.size * 2
        fun copy(a: DoubleArray) = DoubleArray(cap).also { b -> for (k in 0 until size) b[k] = a[(head + k) % a.size] }
        ts = copy(ts); zs = copy(zs); hs = copy(hs); tilts = copy(tilts)
        uxs = copy(uxs); uys = copy(uys); uzs = copy(uzs); rxs = copy(rxs); rys = copy(rys); rzs = copy(rzs)
        head = 0
    }
}
