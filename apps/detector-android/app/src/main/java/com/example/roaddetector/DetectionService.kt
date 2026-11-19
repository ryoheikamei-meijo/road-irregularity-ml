package com.example.roaddetector

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.example.roaddetector.core.CoreFeatureExtractor
import com.example.roaddetector.core.OnnxClassifier
import com.example.roaddetector.upload.DetectionRecord
import com.example.roaddetector.upload.HttpApiClient
import com.example.roaddetector.upload.LocationTracker
import com.example.roaddetector.upload.PendingStore
import com.example.roaddetector.upload.SessionState
import com.example.roaddetector.upload.SessionSync
import com.example.roaddetector.upload.UploadSettings
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
import kotlin.math.max
import kotlin.math.roundToLong
import kotlin.math.sqrt

/**
 * 走りながらの判定を受け持つ、フォアグラウンドサービス(通知を出して動き続ける仕組み)。
 * 画面を消しても、ほかのアプリに切り替えても、判定・GPS・記録・送信が続く(docs/knowledge/2026-11-19/20261119_android_map_plan.md)。
 *
 * - 判定: 加速度と姿勢(rotation vector)を約 333 Hz で受け取り、2.0 秒の窓を 0.5 秒ごとに core の特徴量にして、
 *   ONNX Runtime で flat / step / rough を判定する。結果を LiveStatus で画面に渡し、CSV に残す。
 *   (外部ストレージのアプリ用フォルダ /Android/data/com.example.roaddetector/files/sessions/<日時>/)
 *     input.csv : 判定に使ったサンプル(時刻・加速度・姿勢・ジャイロ)。PC で同じ判定になるかを後で確かめるため。ジャイロは直近の値(判定には使わない)
 *     judge.csv : 窓ごとの特徴量・判定・計算時間
 *     session.json・detections.jsonl・detections.sent : サーバーへ送る走行の情報と、判定結果(端末に残し、送れた件数を持つ)
 * - 送信: 判定結果は GPS の位置を付けて、5 秒ごとにサーバー(apps/server)へ送る(どの回線でも。失敗したら残して次に送る)。
 *   走行を止めたあと、Wi-Fi など従量課金でない回線につながったとき、残りの判定結果と input.csv を送る(UploadWorker)。
 *   送信を切っている(UploadSettings)ときは、端末に残すだけにする。
 * - 画面が消えても CPU が止まらないよう、走行中は PARTIAL_WAKE_LOCK を持つ。
 * - 位置の権限が無いと、Android 14 以降は位置の種類のフォアグラウンドサービスを始められない。権限は画面の側で先に求める。
 */
class DetectionService : Service(), SensorEventListener {
    companion object {
        private const val TAG = "RoadDetector"
        private const val ACTION_START = "com.example.roaddetector.START"
        private const val ACTION_STOP = "com.example.roaddetector.STOP"
        private const val EXTRA_DURATION_S = "duration_s"
        private const val CHANNEL_ID = "detection"
        private const val NOTIFICATION_ID = 1
        private const val FLUSH_PERIOD_S = 5L
        // 計測用アプリ(MyApplication3)と同じ。要求は 2 ms で、多くの端末では約 3 ms にそろう
        private const val SAMPLING_PERIOD_US = 2_000
        private const val MIN_INTERVAL_NS = 2_000_000L
        // 止め忘れても、電池を使い切らないための上限(1 回の走行はこれより十分短い想定)
        private const val WAKE_LOCK_MAX_MS = 6 * 60 * 60 * 1000L

        /** 走行を始める。durationS > 0 なら、その秒数で止める(adb からの動作確認用) */
        fun start(context: Context, durationS: Int = 0) {
            val i = Intent(context, DetectionService::class.java).setAction(ACTION_START).putExtra(EXTRA_DURATION_S, durationS)
            ContextCompat.startForegroundService(context, i)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, DetectionService::class.java).setAction(ACTION_STOP))
        }
    }

    private lateinit var sensorManager: SensorManager
    private lateinit var classifier: OnnxClassifier
    private var modelVersion = "?"
    private var tiltRef: CoreFeatureExtractor.TiltReference = CoreFeatureExtractor.TiltReference.StartMean(10_000.0)
    private lateinit var locationTracker: LocationTracker
    private var wakeLock: PowerManager.WakeLock? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var autoStop: Runnable? = null

    private val sensorThread = HandlerThread("sensor").apply { start() }
    private val sensorHandler = Handler(sensorThread.looper)
    private val inferExecutor = Executors.newSingleThreadExecutor()
    private val netExecutor = Executors.newSingleThreadScheduledExecutor()

    // 以下はセンサーのスレッドだけで触る
    private var running = false
    private lateinit var extractor: CoreFeatureExtractor
    private var quat: DoubleArray? = null
    private var lastAccNs = 0L
    private var nSamples = 0L
    private var firstNs = 0L
    private var inputWriter: BufferedWriter? = null
    private var gyro: FloatArray? = null  // 直近のジャイロ(input.csv に残すだけ)

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

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        classifier = OnnxClassifier(assets.open("core_svm.onnx").use { it.readBytes() })
        val info = assets.open("model_info.json").use { org.json.JSONObject(it.bufferedReader().readText()) }
        modelVersion = info.optString("version", "?")
        // 特徴量の傾きの基準は、モデルを学習したときと同じにする
        tiltRef = CoreFeatureExtractor.TiltReference.parse(info.getString("tilt_ref"))
        locationTracker = LocationTracker(this) { f -> LiveStatus.update { it.copy(lat = f.lat, lon = f.lon) } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                if (!enterForeground()) { stopSelf(); return START_NOT_STICKY }
                val durationS = intent.getIntExtra(EXTRA_DURATION_S, 0)
                sensorHandler.post { if (!running) startRun() }
                if (durationS > 0) {
                    autoStop?.let { mainHandler.removeCallbacks(it) }
                    autoStop = Runnable { requestStop() }.also { mainHandler.postDelayed(it, durationS * 1000L) }
                }
            }
            ACTION_STOP -> requestStop()
        }
        // 落とされたら、走行は再開しない(送り終えていない分は、次にアプリを開いたときに UploadWorker が送る)
        return START_NOT_STICKY
    }

    private fun enterForeground(): Boolean {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW))
        }
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, notification(getString(R.string.notification_starting)), ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } else {
                startForeground(NOTIFICATION_ID, notification(getString(R.string.notification_starting)))
            }
            true
        } catch (e: Exception) {
            // Android 14 以降で位置の権限が無い、バックグラウンドから始めようとした、など
            Log.w(TAG, "フォアグラウンドサービスを始められない", e)
            LiveStatus.update { it.copy(message = "判定を始められない: ${e.message}") }
            false
        }
    }

    private fun notification(text: String): Notification {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, DetectionService::class.java).setAction(ACTION_STOP), flags)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_road)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .addAction(R.drawable.ic_stop, getString(R.string.notification_stop), stop)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateNotification(text: String) {
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIFICATION_ID, notification(text))
    }

    private fun requestStop() {
        autoStop?.let { mainHandler.removeCallbacks(it) }; autoStop = null
        sensorHandler.post {
            if (running) stopRun { mainHandler.post { finishService() } } else mainHandler.post { finishService() }
        }
    }

    private fun finishService() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // ===== 走りながらの判定(センサーのスレッド) =====

    private fun startRun() {
        val dir = File(getExternalFilesDir(null), "sessions/" +
                SimpleDateFormat("yyyyMMddHHmmss", Locale.JAPAN).format(Date())).apply { mkdirs() }
        inputWriter = File(dir, "input.csv").bufferedWriter().apply {
            // timestamp はセンサーの時刻(起動からの ms)。研究リポジトリの core_model.load_raw でそのまま読める(列名で読む。ジャイロは空欄から始まる)
            write("timestamp,accX,accY,accZ,rotX,rotY,rotZ,rotW,gyroX,gyroY,gyroZ,wallMs\n")
        }
        gyro = null
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
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RoadDetector:detection").apply { acquire(WAKE_LOCK_MAX_MS) }
        sensorManager.registerListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER),
            SAMPLING_PERIOD_US, sensorHandler)
        sensorManager.registerListener(this, sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR),
            SAMPLING_PERIOD_US, sensorHandler)
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            sensorManager.registerListener(this, it, SAMPLING_PERIOD_US, sensorHandler)
        } ?: Log.w(TAG, "ジャイロが無い端末。input.csv のジャイロ列は空欄になる")
        // 位置の受け取りはメインのスレッドで行う(受け取った値は Volatile で持つ)
        mainHandler.post {
            val located = locationTracker.start(Looper.getMainLooper())
            Log.i(TAG, "LOCATION ${if (located) "GPS を使う" else "位置なし(権限が無い、または GPS が無効)"}")
        }
        running = true
        LiveStatus.update {
            LiveStatus.Snapshot(running = true, dir = dir.absolutePath, sync = syncText(null), message = "保存先: ${dir.absolutePath}")
        }
    }

    /** 判定結果をすべて残し、送信を片付けてから done を呼ぶ */
    private fun stopRun(done: () -> Unit) {
        sensorManager.unregisterListener(this)
        mainHandler.post { locationTracker.stop() }
        running = false
        inputWriter?.close(); inputWriter = null
        wakeLock?.takeIf { it.isHeld }?.release(); wakeLock = null
        val finishedDir = sessionDir
        val rate = if (nSamples > 1) (nSamples - 1) / ((lastAccNs - firstNs) / 1e9) else 0.0
        val samples = nSamples
        inferExecutor.execute {
            judgeWriter?.close(); judgeWriter = null
            Log.i(TAG, "LIVE_DONE サンプル $samples（${"%.1f".format(rate)} Hz） 窓 $nWindows " +
                    "flat ${counts["flat"]} step ${counts["dansa"]} rough ${counts["dekobo"]} " +
                    "推論 平均 ${"%.3f".format(inferNsSum / 1e6 / max(1, nWindows))} ms 最大 ${"%.3f".format(inferNsMax / 1e6)} ms " +
                    "特徴量 平均 ${"%.3f".format(featureNsSum / 1e6 / max(1, nWindows))} ms")
            // 判定結果をすべて端末に残し終えた(同じスレッドで順に処理される)ので、送信を止めて残りを送る
            finishSync(finishedDir, done)
        }
        LiveStatus.update { it.copy(running = false, dir = null) }
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
            Sensor.TYPE_GYROSCOPE -> gyro = event.values.copyOf(3)
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
                val rate = if (nSamples > 1) (nSamples - 1) / ((lastAccNs - firstNs) / 1e9) else 0.0
                for (w in windows) inferExecutor.execute { judge(w, featureNs, rate) }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // ===== 判定(判定のスレッド) =====

    private fun judge(w: CoreFeatureExtractor.Window, featureNs: Long, rate: Double) {
        val t0 = SystemClock.elapsedRealtimeNanos()
        val r = classifier.predict(w.features)
        val inferNs = SystemClock.elapsedRealtimeNanos() - t0
        nWindows++; counts[r.label] = (counts[r.label] ?: 0) + 1
        featureNsSum += featureNs; inferNsSum += inferNs; inferNsMax = max(inferNsMax, inferNs)
        // 送る分の保存に失敗しても、判定は続ける(1 件のせいで、判定のスレッドごとアプリが落ちないようにする)
        runCatching { saveDetection(w, r) }.onFailure { Log.w(TAG, "判定結果を残せない: ${it.message}") }
        judgeWriter?.write("${w.startMs},${w.features.joinToString(",")},${w.nSamples},${r.label}," +
                "${r.scores.joinToString(",")},${featureNs / 1000},${inferNs / 1000},${System.currentTimeMillis()}\n")
        val stats = "窓 $nWindows（平坦 ${counts["flat"]}・段差 ${counts["dansa"]}・凸凹 ${counts["dekobo"]}）\n" +
                "サンプリング ${"%.0f".format(rate)} Hz、窓のサンプル ${w.nSamples}\n" +
                "推論 平均 ${"%.3f".format(inferNsSum / 1e6 / nWindows)} ms・最大 ${"%.3f".format(inferNsMax / 1e6)} ms\n" +
                "特徴量 平均 ${"%.3f".format(featureNsSum / 1e6 / nWindows)} ms"
        LiveStatus.update {
            it.copy(label = r.label, scores = r.scores, stats = stats, windows = nWindows,
                steps = counts["dansa"] ?: 0, roughs = counts["dekobo"] ?: 0)
        }
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

    // ===== サーバーへの送信(送信のスレッド) =====

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
        Log.i(TAG, "SESSION ${state.id} device=${state.deviceId} server=${BuildConfig.API_URL} upload=${UploadSettings.isEnabled(this)}")
    }

    private fun syncText(ok: Boolean?): String {
        val st = store ?: return ""
        return when {
            !UploadSettings.isEnabled(this) -> getString(R.string.sync_off, st.total())
            ok == false -> getString(R.string.sync_failed, st.sentCount(), st.total())
            else -> getString(R.string.sync_progress, st.sentCount(), st.total())
        }
    }

    /** 5 秒ごと。送信を切っているときは送らない(切り替えは走行中でも効く。入れ直せば、たまった分も送る) */
    private fun flushDetections() {
        val sy = sync ?: return
        var ok: Boolean? = null
        if (UploadSettings.isEnabled(this)) {
            ok = try { sy.flushDetections() } catch (e: Exception) { Log.w(TAG, "送信で例外", e); false }
        }
        val text = syncText(ok)
        LiveStatus.update { it.copy(sync = text) }
        val c = counts.toMap()  // 判定のスレッドと競合しても、表示が 1 窓ずれるだけ
        updateNotification(getString(R.string.notification_text, c["dansa"] ?: 0, c["dekobo"] ?: 0, c.values.sum()) + "\n" + text)
    }

    /** 走行を止めたあと(判定結果をすべて残し終えてから)。走行中の送信を止め、残りを今送ってみて、Wi-Fi のときのジョブに渡す */
    private fun finishSync(dir: File?, done: () -> Unit) {
        flushTask?.cancel(false); flushTask = null
        netExecutor.execute {
            try {
                if (dir != null) {
                    flushDetections()
                    if (UploadSettings.isEnabled(this)) {
                        UploadWorker.enqueue(this, dir)
                        Log.i(TAG, "SYNC_ENQUEUED ${dir.name} 送信済み ${store?.sentCount()} / ${store?.total()} 窓")
                    } else {
                        Log.i(TAG, "SYNC_OFF ${dir.name} 端末に ${store?.total()} 窓を残した（送信はオフ）")
                    }
                }
            } finally {
                sessionDir = null
                done()
            }
        }
    }

    override fun onDestroy() {
        // 走行中に落とされる(電池の節約など)ときも、書いた分を閉じる
        if (running) sensorHandler.post { stopRun {} }
        sensorHandler.post {
            // 判定と送信の残りが済んでから、モデルを閉じる
            inferExecutor.execute { netExecutor.execute { classifier.close() }; netExecutor.shutdown() }
            inferExecutor.shutdown()
            sensorThread.quitSafely()
        }
        super.onDestroy()
    }
}
