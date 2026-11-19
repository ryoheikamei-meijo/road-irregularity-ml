package com.example.roaddetector

import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.example.roaddetector.core.CoreFeatureExtractor
import com.example.roaddetector.core.OnnxClassifier
import com.example.roaddetector.upload.UploadSettings
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import com.google.android.material.materialswitch.MaterialSwitch
import java.util.concurrent.Executors
import java.util.zip.GZIPInputStream
import kotlin.math.max

/**
 * 開発用の画面。地図の画面(MainActivity)の「開発用」から開く(layout/activity_dev.xml。Material Design 3 の部品)。
 * - 走行中の判定の詳しい様子(決定関数の値、サンプリングの速さ、計算時間)
 * - 「サーバーへ送る」のスイッチ(UploadSettings。実機では切る)と、送信の状態
 * - 再生: アプリに入れた記録済みのセッション(デバッグ版の assets/replay)を同じ処理に流し、PC(Python)の判定と比べる。
 *   adb shell am start -n com.example.roaddetector/.MainActivity --ez replay true でも起動できる(結果は logcat の RoadDetector)
 */
class DevActivity : AppCompatActivity() {
    companion object {
        private const val TAG = "RoadDetector"
        const val EXTRA_REPLAY = "replay"
    }

    private var tiltRef: CoreFeatureExtractor.TiltReference = CoreFeatureExtractor.TiltReference.StartMean(10_000.0)
    private lateinit var labelView: TextView
    private lateinit var scoreView: TextView
    private lateinit var statsView: TextView
    private lateinit var logView: TextView
    private lateinit var syncView: TextView
    private lateinit var replayButton: MaterialButton
    private lateinit var uploadSwitch: MaterialSwitch

    private val replayExecutor = Executors.newSingleThreadExecutor()
    @Volatile private var replayRunning = false
    private val statusListener: (LiveStatus.Snapshot) -> Unit = { show(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_dev)
        val info = assets.open("model_info.json").use { org.json.JSONObject(it.bufferedReader().readText()) }
        // 特徴量の傾きの基準は、モデルを学習したときと同じにする(再生で使う)
        tiltRef = CoreFeatureExtractor.TiltReference.parse(info.getString("tilt_ref"))
        findViewById<MaterialToolbar>(R.id.toolbar).setNavigationOnClickListener { finish() }
        findViewById<TextView>(R.id.model).text = getString(R.string.dev_model, info.optString("version", "?"))
        labelView = findViewById(R.id.label)
        scoreView = findViewById(R.id.scores)
        statsView = findViewById(R.id.stats)
        syncView = findViewById(R.id.sync)
        logView = findViewById(R.id.log)
        findViewById<TextView>(R.id.uploadTarget).text = getString(R.string.dev_upload_target, BuildConfig.API_URL)
        uploadSwitch = findViewById<MaterialSwitch>(R.id.upload).apply {
            isChecked = UploadSettings.isEnabled(this@DevActivity)
            setOnCheckedChangeListener { _, on -> setUpload(this@DevActivity, on) }
        }
        replayButton = findViewById<MaterialButton>(R.id.replay).apply { setOnClickListener { startReplay() } }
        if (replayAssets().isEmpty()) { replayButton.isEnabled = false; logView.setText(R.string.dev_replay_none) }
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

    private fun show(s: LiveStatus.Snapshot) {
        labelView.text = Labels.name(this, s.label)
        labelView.setTextColor(Labels.textColor(this, s.label))
        s.scores?.let { sc ->
            scoreView.text = OnnxClassifier.CLASSES.indices.joinToString("  ") {
                "${Labels.name(this, OnnxClassifier.CLASSES[it])} ${"%.2f".format(sc[it])}"
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
        logView.setText(R.string.dev_replay_running)
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
