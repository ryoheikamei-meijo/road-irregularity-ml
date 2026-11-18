package com.example.roaddetector

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.example.roaddetector.core.CoreFeatureExtractor
import com.example.roaddetector.core.OnnxClassifier
import com.example.roaddetector.upload.DetectionRecord
import com.example.roaddetector.upload.HttpApiClient
import com.example.roaddetector.upload.LocationTracker
import com.example.roaddetector.upload.PendingStore
import com.example.roaddetector.upload.SessionState
import com.example.roaddetector.upload.SessionSync
import com.example.roaddetector.upload.UploadWorker
import java.io.BufferedWriter
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPInputStream
import kotlin.math.max
import kotlin.math.roundToLong
import kotlin.math.sqrt

/**
 * スマホの上(エッジ)で路面を判定する、最小限のアプリ。
 *
 * - 判定: 加速度と姿勢(rotation vector)を約 333 Hz で受け取り、2.0 秒の窓を 0.5 秒ごとに core の特徴量にして、
 *   ONNX Runtime で flat / step / rough を判定する。結果を画面に出し、CSV に残す。
 *   (外部ストレージのアプリ用フォルダ /Android/data/com.example.roaddetector/files/sessions/<日時>/)
 *     input.csv : 判定に使ったサンプル(時刻・加速度・姿勢・ジャイロ)。PC で同じ判定になるかを後で確かめるため。ジャイロは直近の値(判定には使わない)
 *     judge.csv : 窓ごとの特徴量・判定・計算時間
 *     session.json・detections.jsonl・detections.sent : サーバーへ送る走行の情報と、判定結果(端末に残し、送れた件数を持つ)
 * - 送信: 判定結果は GPS の位置を付けて、5 秒ごとにサーバー(apps/server)へ送る(どの回線でも。失敗したら残して次に送る)。
 *   走行を止めたあと、Wi-Fi など従量課金でない回線につながったとき、残りの判定結果と input.csv を送る(UploadWorker)。
 * - 再生: アプリに入れた記録済みのセッション(デバッグ版の assets/replay)を同じ処理に流し、PC(Python)の判定と比べる。
 *   adb shell am start -n com.example.roaddetector/.MainActivity --ez replay true でも起動できる(結果は logcat の RoadDetector)。
 * - 動作確認用に、--ei live_s <秒> を付けて起動すると、その秒数だけ判定して止まる(結果は logcat の LIVE_DONE)。
 */
class MainActivity : AppCompatActivity(), SensorEventListener {
    companion object {
        private const val TAG = "RoadDetector"
        private const val REQ_LOCATION = 1
        private const val FLUSH_PERIOD_S = 5L
        // 計測用アプリ(MyApplication3)と同じ。要求は 2 ms で、多くの端末では約 3 ms にそろう
        private const val SAMPLING_PERIOD_US = 2_000
        private const val MIN_INTERVAL_NS = 2_000_000L
        private val COLORS = mapOf("flat" to Color.rgb(46, 125, 50), "dansa" to Color.rgb(198, 40, 40),
            "dekobo" to Color.rgb(239, 108, 0))
    }

    private lateinit var sensorManager: SensorManager
    private lateinit var classifier: OnnxClassifier
    private var modelVersion = "?"
    private var tiltRef: CoreFeatureExtractor.TiltReference = CoreFeatureExtractor.TiltReference.StartMean(10_000.0)
    private lateinit var labelView: TextView
    private lateinit var scoreView: TextView
    private lateinit var statsView: TextView
    private lateinit var logView: TextView
    private lateinit var syncView: TextView
    private lateinit var runButton: Button
    private lateinit var replayButton: Button

    private val sensorThread = HandlerThread("sensor").apply { start() }
    private val inferExecutor = Executors.newSingleThreadExecutor()
    private val replayExecutor = Executors.newSingleThreadExecutor()
    private val netExecutor = Executors.newSingleThreadScheduledExecutor()
    private lateinit var locationTracker: LocationTracker

    // 以下はセンサーのスレッドだけで触る
    private var running = false
    private lateinit var extractor: CoreFeatureExtractor
    private var quat: DoubleArray? = null
    private var lastAccNs = 0L
    private var nSamples = 0L
    private var firstNs = 0L
    private var inputWriter: BufferedWriter? = null
    private var gyro: FloatArray? = null  // 直近のジャイロ(input.csv に残すだけ)
    private var gyroSamples = 0L

    // 送信(走行を始めるときに作り、止めるまで使う)
    @Volatile private var sessionDir: File? = null
    @Volatile private var store: PendingStore? = null
    @Volatile private var sync: SessionSync? = null
    @Volatile private var wallOffsetMs = 0.0  // 壁時計(epoch ms) − センサーのタイムスタンプ[ms]。窓の始まりの壁時計を出すのに使う
    private var flushTask: ScheduledFuture<*>? = null

    // 以下は判定のスレッドだけで触る
    private var judgeWriter: BufferedWriter? = null
    private var nWindows = 0
    private val counts = mutableMapOf("flat" to 0, "dansa" to 0, "dekobo" to 0)
    private var featureNsSum = 0L
    private var inferNsSum = 0L
    private var inferNsMax = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        classifier = OnnxClassifier(assets.open("core_svm.onnx").use { it.readBytes() })
        val info = assets.open("model_info.json").use { org.json.JSONObject(it.bufferedReader().readText()) }
        modelVersion = info.optString("version", "?")
        // 特徴量の傾きの基準は、モデルを学習したときと同じにする
        tiltRef = CoreFeatureExtractor.TiltReference.parse(info.getString("tilt_ref"))
        Log.i(TAG, "MODEL $modelVersion tilt_ref=${info.getString("tilt_ref")}")
        locationTracker = LocationTracker(this)
        if (!locationTracker.hasPermission()) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), REQ_LOCATION)
        }
        buildUi()
        // 前回、送り終えていない走行(落ちた・電波が無かった)を、送る対象に入れ直す
        UploadWorker.enqueueIncomplete(this, File(getExternalFilesDir(null), "sessions"))
        if (intent.getBooleanExtra("replay", false)) startReplay()
        val liveS = intent.getIntExtra("live_s", 0)
        if (liveS > 0) {
            toggleRun()
            Handler(mainLooper).postDelayed({ toggleRun() }, liveS * 1000L)
        }
    }

    private fun buildUi() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad, pad, pad) }
        fun text(size: Float, bold: Boolean = false) = TextView(this).apply {
            textSize = size; if (bold) setTypeface(typeface, Typeface.BOLD)
        }
        labelView = text(56f, true).apply { gravity = Gravity.CENTER; text = "—" }
        scoreView = text(14f).apply { gravity = Gravity.CENTER; typeface = Typeface.MONOSPACE }
        statsView = text(14f).apply { typeface = Typeface.MONOSPACE }
        syncView = text(13f).apply { typeface = Typeface.MONOSPACE; text = "サーバー ${BuildConfig.API_URL}" }
        runButton = Button(this).apply { text = "判定を始める"; setOnClickListener { toggleRun() } }
        replayButton = Button(this).apply {
            text = "記録済みのデータで PC と比べる（再生）"
            isEnabled = replayAssets().isNotEmpty()
            setOnClickListener { startReplay() }
        }
        logView = text(12f).apply { typeface = Typeface.MONOSPACE }
        col.addView(text(13f).apply { text = "モデル $modelVersion: core（5 個）+ SVM、ONNX Runtime、窓 2.0 秒・0.5 秒ごと" })
        col.addView(labelView); col.addView(scoreView); col.addView(runButton); col.addView(statsView); col.addView(syncView)
        col.addView(replayButton); col.addView(logView)
        // targetSdk 35 では画面の端まで描かれるので、ステータスバーの分だけ内側に寄せる
        setContentView(ScrollView(this).apply { fitsSystemWindows = true; addView(col) })
    }

    // ===== 走りながらの判定 =====

    private fun toggleRun() {
        Handler(sensorThread.looper).post { if (running) stopRun() else startRun() }
    }

    private fun startRun() {
        val dir = File(getExternalFilesDir(null), "sessions/" +
                SimpleDateFormat("yyyyMMddHHmmss", Locale.JAPAN).format(Date())).apply { mkdirs() }
        inputWriter = File(dir, "input.csv").bufferedWriter().apply {
            // timestamp はセンサーの時刻(起動からの ms)。研究リポジトリの core_model.load_raw でそのまま読める(列名で読む。ジャイロは空欄から始まる)
            write("timestamp,accX,accY,accZ,rotX,rotY,rotZ,rotW,gyroX,gyroY,gyroZ,wallMs\n")
        }
        gyro = null; gyroSamples = 0L
        startSync(dir)
        extractor = CoreFeatureExtractor(tiltRef)
        quat = null; lastAccNs = 0L; nSamples = 0L; firstNs = 0L
        inferExecutor.execute {
            judgeWriter = File(dir, "judge.csv").bufferedWriter().apply {
                write("start_ms,${CoreFeatureExtractor.FEATURES.joinToString(",")},n_samples,pred," +
                        OnnxClassifier.CLASSES.joinToString(",") { "score_$it" } + ",feature_us,infer_us,wallMs\n")
            }
            nWindows = 0; counts.keys.forEach { counts[it] = 0 }
            featureNsSum = 0L; inferNsSum = 0L; inferNsMax = 0L
        }
        val handler = Handler(sensorThread.looper)
        sensorManager.registerListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER),
            SAMPLING_PERIOD_US, handler)
        sensorManager.registerListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR),
            SAMPLING_PERIOD_US, handler)
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            sensorManager.registerListener(this, it, SAMPLING_PERIOD_US, handler)
        } ?: Log.w(TAG, "ジャイロが無い端末。input.csv のジャイロ列は空欄になる")
        val located = locationTracker.start(Looper.getMainLooper())
        Log.i(TAG, "LOCATION ${if (located) "GPS を使う" else "位置なし(権限が無い、または GPS が無効)"}")
        running = true
        runOnUiThread {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            runButton.text = "判定を止める"
            logView.text = "保存先: ${dir.absolutePath}"
        }
    }

    private fun stopRun() {
        sensorManager.unregisterListener(this)
        locationTracker.stop()
        running = false
        inputWriter?.close(); inputWriter = null
        val finishedDir = sessionDir
        val rate = if (nSamples > 1) (nSamples - 1) / ((lastAccNs - firstNs) / 1e9) else 0.0
        val samples = nSamples
        inferExecutor.execute {
            judgeWriter?.close(); judgeWriter = null
            // 判定結果をすべて端末に残し終えた(同じスレッドで順に処理される)ので、送信を止めて残りを送る
            finishSync(finishedDir)
            Log.i(TAG, "LIVE_DONE サンプル $samples（${"%.1f".format(rate)} Hz） 窓 $nWindows " +
                    "flat ${counts["flat"]} step ${counts["dansa"]} rough ${counts["dekobo"]} " +
                    "推論 平均 ${"%.3f".format(inferNsSum / 1e6 / max(1, nWindows))} ms 最大 ${"%.3f".format(inferNsMax / 1e6)} ms " +
                    "特徴量 平均 ${"%.3f".format(featureNsSum / 1e6 / max(1, nWindows))} ms")
        }
        runOnUiThread {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            runButton.text = "判定を始める"
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (!running) return
        when (event.sensor.type) {
            Sensor.TYPE_ROTATION_VECTOR -> {
                val v = event.values
                val w = if (v.size >= 4) v[3].toDouble()
                else sqrt(max(0.0, 1.0 - v[0] * v[0] - v[1] * v[1] - v[2] * v[2].toDouble()))
                // 壊れた姿勢(全部 0 や NaN。走り始めに届くことがある)は使わず、直前の姿勢のままにする
                val norm = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2] + w * w)
                if (norm.isFinite() && norm >= CoreFeatureExtractor.MIN_QUAT_NORM) {
                    quat = doubleArrayOf(v[0].toDouble(), v[1].toDouble(), v[2].toDouble(), w)
                }
            }
            Sensor.TYPE_GYROSCOPE -> { gyro = event.values.copyOf(3); gyroSamples++ }
            Sensor.TYPE_ACCELEROMETER -> {
                val q = quat ?: return  // 姿勢がまだ届いていない
                if (lastAccNs != 0L && event.timestamp - lastAccNs < MIN_INTERVAL_NS) return
                lastAccNs = event.timestamp
                if (firstNs == 0L) firstNs = event.timestamp
                nSamples++
                val tMs = event.timestamp / 1e6
                val a = event.values
                val g = gyro
                val gyroCols = if (g != null) "${g[0]},${g[1]},${g[2]}" else ",,"
                inputWriter?.write("$tMs,${a[0]},${a[1]},${a[2]},${q[0]},${q[1]},${q[2]},${q[3]},$gyroCols,${System.currentTimeMillis()}\n")
                val t0 = SystemClock.elapsedRealtimeNanos()
                val windows = extractor.push(tMs, a[0].toDouble(), a[1].toDouble(), a[2].toDouble(), q[0], q[1], q[2], q[3])
                val featureNs = SystemClock.elapsedRealtimeNanos() - t0
                for (w in windows) inferExecutor.execute { judge(w, featureNs) }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    private fun judge(w: CoreFeatureExtractor.Window, featureNs: Long) {
        val t0 = SystemClock.elapsedRealtimeNanos()
        val r = classifier.predict(w.features)
        val inferNs = SystemClock.elapsedRealtimeNanos() - t0
        nWindows++; counts[r.label] = (counts[r.label] ?: 0) + 1
        featureNsSum += featureNs; inferNsSum += inferNs; inferNsMax = max(inferNsMax, inferNs)
        // 送る分の保存に失敗しても、判定は続ける(1 件のせいで、判定のスレッドごとアプリが落ちないようにする)
        runCatching { saveDetection(w, r) }.onFailure { Log.w(TAG, "判定結果を残せない: ${it.message}") }
        judgeWriter?.write("${w.startMs},${w.features.joinToString(",")},${w.nSamples},${r.label}," +
                "${r.scores.joinToString(",")},${featureNs / 1000},${inferNs / 1000},${System.currentTimeMillis()}\n")
        val rate = if (nSamples > 1) (nSamples - 1) / ((lastAccNs - firstNs) / 1e9) else 0.0
        val stats = "窓 $nWindows（flat ${counts["flat"]} / step ${counts["dansa"]} / rough ${counts["dekobo"]}）\n" +
                "サンプリング ${"%.0f".format(rate)} Hz、窓のサンプル ${w.nSamples}\n" +
                "推論 平均 ${"%.3f".format(inferNsSum / 1e6 / nWindows)} ms・最大 ${"%.3f".format(inferNsMax / 1e6)} ms\n" +
                "特徴量 平均 ${"%.3f".format(featureNsSum / 1e6 / nWindows)} ms"
        runOnUiThread { showResult(r); statsView.text = stats }
    }

    // ===== サーバーへの送信 =====

    private fun deviceId(): String {
        val prefs = getSharedPreferences("roaddetector", MODE_PRIVATE)
        return prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also { prefs.edit().putString("device_id", it).apply() }
    }

    private fun startSync(dir: File) {
        val startedAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date())
        val state = SessionState.create(dir, UUID.randomUUID().toString(), deviceId(), startedAt, BuildConfig.VERSION_NAME, modelVersion)
        val s = PendingStore(dir)
        store = s
        sessionDir = dir
        sync = SessionSync(state, s, HttpApiClient(BuildConfig.API_URL, BuildConfig.API_KEY), File(dir, "input.csv")) { Log.w(TAG, it) }
        // センサーのタイムスタンプは、端末の起動からの時間(SystemClock.elapsedRealtimeNanos と同じ時計)
        wallOffsetMs = System.currentTimeMillis() - SystemClock.elapsedRealtimeNanos() / 1e6
        flushTask = netExecutor.scheduleWithFixedDelay({ flushDetections() }, FLUSH_PERIOD_S, FLUSH_PERIOD_S, TimeUnit.SECONDS)
        Log.i(TAG, "SESSION ${state.id} device=${state.deviceId} server=${BuildConfig.API_URL}")
    }

    private fun flushDetections() {
        val sy = sync ?: return
        val st = store ?: return
        val ok = try { sy.flushDetections() } catch (e: Exception) { Log.w(TAG, "送信で例外", e); false }
        val text = "送信: ${st.sentCount()} / ${st.total()} 窓${if (ok) "" else "（つながらない。残して次に送る）"}"
        runOnUiThread { syncView.text = text }
    }

    /** 判定結果を端末に残す(送信は 5 秒ごとに別のスレッドで)。位置は、その時点の最新の GPS(古すぎれば付けない) */
    private fun saveDetection(w: CoreFeatureExtractor.Window, r: OnnxClassifier.Result) {
        val st = store ?: return
        val wallStart = (w.startMs + wallOffsetMs).roundToLong()
        val windowEndWall = wallStart + 2000L
        val scores = OnnxClassifier.CLASSES.indices.associate { OnnxClassifier.DISPLAY.getValue(OnnxClassifier.CLASSES[it]) to r.scores[it].toDouble() }
        val json = DetectionRecord(
            windowStartMs = w.startMs.roundToLong(), windowWallMs = wallStart, windowS = 2.0,
            cls = OnnxClassifier.DISPLAY.getValue(r.label), scores = scores, fix = locationTracker.fixFor(windowEndWall),
        ).toJsonOrNull()
        if (json == null) Log.w(TAG, "判定結果に NaN などが入っていたので、送らない: 窓 ${w.startMs}") else st.append(json)
    }

    /** 走行を止めたあと(判定結果をすべて残し終えてから)。走行中の送信を止め、残りを今送ってみて、Wi-Fi のときのジョブに渡す */
    private fun finishSync(dir: File?) {
        flushTask?.cancel(false); flushTask = null
        val d = dir ?: return
        netExecutor.execute {
            flushDetections()
            UploadWorker.enqueue(this, d)
            Log.i(TAG, "SYNC_ENQUEUED ${d.name} 送信済み ${store?.sentCount()} / ${store?.total()} 窓")
        }
        sessionDir = null
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_LOCATION && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && running) {
            locationTracker.start(Looper.getMainLooper())
        }
    }

    private fun showResult(r: OnnxClassifier.Result) {
        labelView.text = OnnxClassifier.DISPLAY[r.label]
        labelView.setTextColor(COLORS[r.label] ?: Color.GRAY)
        scoreView.text = OnnxClassifier.CLASSES.indices.joinToString("  ") {
            "${OnnxClassifier.DISPLAY[OnnxClassifier.CLASSES[it]]} ${"%.2f".format(r.scores[it])}"
        }
    }

    // ===== 再生(記録済みのデータで PC と比べる) =====

    // ビルドで .gz が展開されて入る(名前から .gz が外れる)ことがあるので、どちらでも読めるようにする
    private fun replayAssets(): Map<String, String> =
        (assets.list("replay") ?: emptyArray()).filter { it.endsWith("_input.csv") || it.endsWith("_input.csv.gz") }
            .associateBy { it.substringBefore("_input.csv") }

    private fun startReplay() {
        replayButton.isEnabled = false
        logView.text = "再生中…"
        replayExecutor.execute {
            val lines = StringBuilder()
            for ((session, file) in replayAssets().toSortedMap()) {
                val line = replayOne(session, file)
                Log.i(TAG, "REPLAY $line")
                lines.append(line).append('\n')
                runOnUiThread { logView.text = lines.toString() }
            }
            Log.i(TAG, "REPLAY_DONE")
            runOnUiThread { replayButton.isEnabled = true }
        }
    }

    private fun replayOne(session: String, file: String): String {
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
        if (running) Handler(sensorThread.looper).post { stopRun() }
        sensorThread.quitSafely()
        inferExecutor.shutdown(); replayExecutor.shutdown(); netExecutor.shutdown()
        classifier.close()
    }
}
