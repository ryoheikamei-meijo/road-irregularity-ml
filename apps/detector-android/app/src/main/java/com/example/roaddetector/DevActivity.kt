package com.example.roaddetector

import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import com.example.roaddetector.core.CoreFeatureExtractor
import com.example.roaddetector.core.OnnxClassifier
import com.example.roaddetector.upload.UploadSettings
import java.util.concurrent.Executors
import java.util.zip.GZIPInputStream
import kotlin.math.max

/**
 * 開発用の画面。地図の画面(MainActivity)の「開発用」から開く。
 * - 走行中の判定の詳しい様子(決定関数の値、サンプリングの速さ、計算時間)と、送信の状態
 * - 「サーバーへ送る」のスイッチ(UploadSettings。実機では切る)
 * - 再生: アプリに入れた記録済みのセッション(デバッグ版の assets/replay)を同じ処理に流し、PC(Python)の判定と比べる。
 *   adb shell am start -n com.example.roaddetector/.MainActivity --ez replay true でも起動できる(結果は logcat の RoadDetector)
 */
class DevActivity : AppCompatActivity() {
    companion object {
        private const val TAG = "RoadDetector"
        const val EXTRA_REPLAY = "replay"
        val COLORS = mapOf("flat" to Color.rgb(46, 125, 50), "dansa" to Color.rgb(198, 40, 40),
            "dekobo" to Color.rgb(239, 108, 0))
    }

    private var modelVersion = "?"
    private var tiltRef: CoreFeatureExtractor.TiltReference = CoreFeatureExtractor.TiltReference.StartMean(10_000.0)
    private lateinit var labelView: TextView
    private lateinit var scoreView: TextView
    private lateinit var statsView: TextView
    private lateinit var logView: TextView
    private lateinit var syncView: TextView
    private lateinit var replayButton: Button
    private lateinit var uploadSwitch: SwitchCompat

    private val replayExecutor = Executors.newSingleThreadExecutor()
    @Volatile private var replayRunning = false
    private val statusListener: (LiveStatus.Snapshot) -> Unit = { show(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val info = assets.open("model_info.json").use { org.json.JSONObject(it.bufferedReader().readText()) }
        modelVersion = info.optString("version", "?")
        // 特徴量の傾きの基準は、モデルを学習したときと同じにする(再生で使う)
        tiltRef = CoreFeatureExtractor.TiltReference.parse(info.getString("tilt_ref"))
        buildUi()
        if (savedInstanceState == null && intent.getBooleanExtra(EXTRA_REPLAY, false)) startReplay()
    }

    override fun onStart() {
        super.onStart()
        uploadSwitch.isChecked = UploadSettings.isEnabled(this)
        LiveStatus.observe(statusListener)
    }

    override fun onStop() {
        LiveStatus.remove(statusListener)
        super.onStop()
    }

    private fun buildUi() {
        title = "開発用"
        val pad = (16 * resources.displayMetrics.density).toInt()
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad, pad, pad) }
        fun text(size: Float, bold: Boolean = false) = TextView(this).apply {
            textSize = size; if (bold) setTypeface(typeface, Typeface.BOLD)
        }
        labelView = text(40f, true).apply { gravity = Gravity.CENTER; text = "—" }
        scoreView = text(14f).apply { gravity = Gravity.CENTER; typeface = Typeface.MONOSPACE }
        statsView = text(14f).apply { typeface = Typeface.MONOSPACE }
        syncView = text(13f).apply { typeface = Typeface.MONOSPACE }
        uploadSwitch = SwitchCompat(this).apply {
            text = "サーバーへ送る（${BuildConfig.API_URL}）"
            isChecked = UploadSettings.isEnabled(this@DevActivity)
            setOnCheckedChangeListener { _, on -> setUpload(this@DevActivity, on) }
        }
        replayButton = Button(this).apply {
            text = "記録済みのデータで PC と比べる（再生）"
            isEnabled = replayAssets().isNotEmpty()
            setOnClickListener { startReplay() }
        }
        logView = text(12f).apply { typeface = Typeface.MONOSPACE }
        col.addView(text(13f).apply { text = "モデル $modelVersion: core（5 個）+ SVM、ONNX Runtime、窓 2.0 秒・0.5 秒ごと" })
        col.addView(labelView); col.addView(scoreView); col.addView(statsView)
        col.addView(uploadSwitch); col.addView(syncView)
        col.addView(replayButton); col.addView(logView)
        // targetSdk 35 では画面の端まで描かれるので、ステータスバーの分だけ内側に寄せる
        setContentView(ScrollView(this).apply { fitsSystemWindows = true; addView(col) })
    }

    private fun show(s: LiveStatus.Snapshot) {
        s.label?.let { label ->
            labelView.text = OnnxClassifier.DISPLAY[label]
            labelView.setTextColor(COLORS[label] ?: Color.GRAY)
        }
        s.scores?.let { sc ->
            scoreView.text = OnnxClassifier.CLASSES.indices.joinToString("  ") {
                "${OnnxClassifier.DISPLAY[OnnxClassifier.CLASSES[it]]} ${"%.2f".format(sc[it])}"
            }
        }
        statsView.text = s.stats
        syncView.text = s.sync
        if (s.message.isNotEmpty() && !replayRunning) logView.text = s.message
    }

    // ===== 再生(記録済みのデータで PC と比べる) =====

    // ビルドで .gz が展開されて入る(名前から .gz が外れる)ことがあるので、どちらでも読めるようにする
    private fun replayAssets(): Map<String, String> =
        (assets.list("replay") ?: emptyArray()).filter { it.endsWith("_input.csv") || it.endsWith("_input.csv.gz") }
            .associateBy { it.substringBefore("_input.csv") }

    private fun startReplay() {
        replayButton.isEnabled = false
        replayRunning = true
        logView.text = "再生中…"
        replayExecutor.execute {
            val lines = StringBuilder()
            OnnxClassifier(assets.open("core_svm.onnx").use { it.readBytes() }).use { classifier ->
                for ((session, file) in replayAssets().toSortedMap()) {
                    val line = replayOne(classifier, session, file)
                    Log.i(TAG, "REPLAY $line")
                    lines.append(line).append('\n')
                    runOnUiThread { logView.text = lines.toString() }
                }
            }
            Log.i(TAG, "REPLAY_DONE")
            runOnUiThread { replayButton.isEnabled = true; replayRunning = false }
        }
    }

    private fun replayOne(classifier: OnnxClassifier, session: String, file: String): String {
        val ext = CoreFeatureExtractor(tiltRef)
        val windows = ArrayList<CoreFeatureExtractor.Window>()
        var featureNs = 0L
        val raw = assets.open("replay/$file")
        val stream = if (file.endsWith(".gz")) GZIPInputStream(raw) else raw
        stream.bufferedReader().use { r ->
            val h = r.readLine().split(",")
            val idx = listOf("timestamp", "accX", "accY", "accZ", "rotX", "rotY", "rotZ", "rotW").map { h.indexOf(it) }
            r.lineSequence().forEach { line ->
                val c = line.split(",")
                val v = DoubleArray(8) { c[idx[it]].toDouble() }
                val t0 = SystemClock.elapsedRealtimeNanos()
                windows.addAll(ext.push(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]))
                featureNs += SystemClock.elapsedRealtimeNanos() - t0
            }
        }
        var inferNs = 0L; var inferMax = 0L
        val preds = windows.map {
            val t0 = SystemClock.elapsedRealtimeNanos()
            val p = classifier.predict(it.features)
            val dt = SystemClock.elapsedRealtimeNanos() - t0
            inferNs += dt; inferMax = max(inferMax, dt)
            p.label
        }
        val expected = assets.open("replay/${session}_expected.csv").bufferedReader().readLines().drop(1)
            .filter { it.isNotBlank() }.map { it.split(",") }
        var agree = 0; var startOk = 0
        for ((i, w) in windows.withIndex()) {
            if (i >= expected.size) break
            if (kotlin.math.abs(expected[i][0].toDouble() - w.startMs) < 1e-6) startOk++
            if (expected[i][1] == preds[i]) agree++
        }
        return "$session 窓 ${windows.size}（PC ${expected.size}）始まりが一致 $startOk 判定が一致 $agree " +
                "推論 平均 ${"%.3f".format(inferNs / 1e6 / max(1, windows.size))} ms 最大 ${"%.3f".format(inferMax / 1e6)} ms " +
                "特徴量 1 窓あたり ${"%.3f".format(featureNs / 1e6 / max(1, windows.size))} ms"
    }

    override fun onDestroy() {
        super.onDestroy()
        replayExecutor.shutdown()
    }
}
