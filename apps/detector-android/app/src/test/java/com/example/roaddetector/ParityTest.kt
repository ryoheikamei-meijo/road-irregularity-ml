package com.example.roaddetector

import com.example.roaddetector.core.CoreFeatureExtractor
import com.example.roaddetector.core.OnnxClassifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.max

/**
 * アプリの実装(Kotlin の特徴量 + ONNX Runtime)が、PC(Python)と同じ判定を出すかを確かめる。
 *
 * 正解は研究リポジトリの src/experiments/e20261116_export_onnx.py が書き出した
 * data/analysis/20261116_export_onnx/parity/<session>.csv(Python の特徴量・scikit-learn の判定・ONNX の判定)。
 * 入力は wheelchair_data/<day>/<session>/acc.csv を 1 行ずつ流す(アプリでセンサーから受け取るのと同じ順番)。
 * Kotlin の結果は data/analysis/20261116_android_parity/<session>.csv に書き出す(メモの図に使う)。
 * 生データや正解が手元に無いときは、テストを飛ばす。
 */
class ParityTest {
    private val root = File(System.getProperty("repoRoot") ?: "../../..")
    private val parityDir = File(root, "data/analysis/20261116_export_onnx/parity")
    private val outDir = File(root, "data/analysis/20261116_android_parity")
    // gradle.properties の roaddetector.modelVersion で選んだ版(models/<版>/core_svm.onnx)
    private val model = File(System.getProperty("modelDir"), "core_svm.onnx")

    private fun readCsv(file: File): Pair<List<String>, List<List<String>>> {
        val lines = file.readLines()
        return lines[0].split(",") to lines.drop(1).filter { it.isNotBlank() }.map { it.split(",") }
    }

    @Test
    fun kotlinAndOnnxMatchPython() {
        val summary = File(root, "data/analysis/20261116_export_onnx/parity_summary.csv")
        assumeTrue("PC の正解が無い: $summary", summary.exists())
        val (sHeader, sRows) = readCsv(summary)
        val sessions = sRows.map { it[sHeader.indexOf("session")] to it[sHeader.indexOf("day")] }
        outDir.mkdirs()

        // 傾きの基準は、モデルと一緒に書き出した model_info.json の tilt_ref に合わせる
        val info = File(model.parentFile, "model_info.json").readText()
        val tiltName = Regex("\"tilt_ref\"\\s*:\\s*\"([^\"]+)\"").find(info)!!.groupValues[1]
        val tiltRef = CoreFeatureExtractor.TiltReference.parse(tiltName)
        println("モデル: ${model.parentFile.name}  傾きの基準: $tiltName")
        OnnxClassifier(model.readBytes()).use { clf ->
            var nAll = 0; var nAgreeOnnx = 0; var nAgreeSk = 0; var worstRel = 0.0; var worstTiltAbs = 0.0
            var featureNs = 0L; var inferNs = 0L
            val report = StringBuilder("session,n_windows,n_python,agree_onnx,agree_sklearn,max_rel_err_except_tilt,max_tilt_abs_err_deg\n")
            for ((session, day) in sessions) {
                val acc = File(root, "wheelchair_data/$day/$session/acc.csv")
                assumeTrue("生データが無い: $acc", acc.exists())
                val ext = CoreFeatureExtractor(tiltRef)
                val windows = ArrayList<CoreFeatureExtractor.Window>()
                acc.bufferedReader().use { r ->
                    val h = r.readLine().split(",")
                    val idx = listOf("timestamp", "accX", "accY", "accZ", "rotX", "rotY", "rotZ", "rotW").map { h.indexOf(it) }
                    val t0 = System.nanoTime()
                    r.lineSequence().forEach { line ->
                        val c = line.split(",")
                        val v = DoubleArray(8) { c[idx[it]].toDouble() }
                        windows.addAll(ext.push(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]))
                    }
                    featureNs += System.nanoTime() - t0
                }
                val t1 = System.nanoTime()
                val preds = windows.map { clf.predict(it.features) }  // アプリと同じく 1 窓ずつ判定する
                inferNs += System.nanoTime() - t1

                val (ph, pr) = readCsv(File(parityDir, "$session.csv"))
                assertEquals("$session の窓の数", pr.size, windows.size)
                var agreeOnnx = 0; var agreeSk = 0; var rel = 0.0; var tiltAbs = 0.0
                val out = StringBuilder("start_ms,${CoreFeatureExtractor.FEATURES.joinToString(",")},kt_pred," +
                        OnnxClassifier.CLASSES.joinToString(",") { "kt_score_$it" } + ",py_onnx_pred,py_sk_pred\n")
                for ((i, w) in windows.withIndex()) {
                    val row = pr[i]
                    assertEquals("$session の窓 $i の始まり", row[ph.indexOf("start_ms")].toDouble(), w.startMs, 1e-6)
                    for ((j, name) in CoreFeatureExtractor.FEATURES.withIndex()) {
                        val py = row[ph.indexOf(name)].toDouble()
                        if (name == "tilt_range") {
                            // 傾きは arccos(内積) で、内積が 1 の近くでは丸めの差が角度で約 1e-6 度になる
                            // (arccos(1 − 1.1e-16) = 8.5e-7 度)。そのため相対誤差ではなく、角度の差で見る
                            tiltAbs = max(tiltAbs, abs(w.features[j] - py))
                        } else {
                            rel = max(rel, abs(w.features[j] - py) / max(abs(py), 1e-9))
                        }
                    }
                    if (preds[i].label == row[ph.indexOf("onnx_pred")]) agreeOnnx++
                    if (preds[i].label == row[ph.indexOf("sk_pred")]) agreeSk++
                    out.append("${w.startMs},${w.features.joinToString(",")},${preds[i].label}," +
                            "${preds[i].scores.joinToString(",")},${row[ph.indexOf("onnx_pred")]},${row[ph.indexOf("sk_pred")]}\n")
                }
                File(outDir, "$session.csv").writeText(out.toString())
                report.append("$session,${windows.size},${pr.size},$agreeOnnx,$agreeSk,$rel,$tiltAbs\n")
                println("$session: 窓 ${windows.size}  ONNX(PC)と一致 $agreeOnnx  scikit-learn と一致 $agreeSk  tilt 以外の最大の相対誤差 ${"%.2e".format(rel)}  tilt_range の最大の差 ${"%.2e".format(tiltAbs)} 度")
                nAll += windows.size; nAgreeOnnx += agreeOnnx; nAgreeSk += agreeSk
                worstRel = max(worstRel, rel); worstTiltAbs = max(worstTiltAbs, tiltAbs)
            }
            File(outDir, "summary.csv").writeText(report.toString())
            println("合計: 窓 $nAll  ONNX(PC)と一致 $nAgreeOnnx  scikit-learn と一致 $nAgreeSk  tilt 以外の最大の相対誤差 ${"%.2e".format(worstRel)}  tilt_range の最大の差 ${"%.2e".format(worstTiltAbs)} 度")
            println("JVM での時間: 特徴量(CSV の読み込みを含む) ${"%.1f".format(featureNs / 1e6)} ms、" +
                    "判定 1 窓あたり ${"%.3f".format(inferNs / 1e6 / nAll)} ms")
            assertTrue("特徴量の相対誤差が大きい: $worstRel", worstRel < 1e-9)
            assertTrue("tilt_range の差が大きい: $worstTiltAbs 度", worstTiltAbs < 1e-5)
            assertEquals("ONNX(PC)と判定が違う窓がある", nAll, nAgreeOnnx)
        }
    }
}
