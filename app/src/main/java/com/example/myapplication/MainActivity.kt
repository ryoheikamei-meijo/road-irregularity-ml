package com.example.myapplication

import android.Manifest
import android.app.AlertDialog
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.SystemClock
import android.text.InputType
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.github.mikephil.charting.charts.LineChart
import com.github.mikephil.charting.components.LimitLine
import com.github.mikephil.charting.data.Entry
import com.github.mikephil.charting.data.LineData
import com.github.mikephil.charting.data.LineDataSet
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.locks.ReentrantLock

class MainActivity : AppCompatActivity(), SensorEventListener {

    private lateinit var sensorManager: SensorManager
    private lateinit var gpsLocationManager: GPSLocationManager

    private lateinit var accLogger: AccCsvLogger
    private lateinit var gyroLogger: SensorCsvLogger
    private lateinit var linearAccLogger: SensorCsvLogger
    private lateinit var dansaLogger: DansaCsvLogger
    private lateinit var dekoboLogger: DekoboCsvLogger
    private lateinit var gpsLogger: GpsCsvLogger
    private lateinit var statusTextView: TextView
    private lateinit var speedTextView: TextView
    private lateinit var weightTextView: TextView
    private lateinit var wheelchairTextView: TextView
    private lateinit var sessionKindTextView: TextView
    private lateinit var memoEditText: EditText
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var clearButton: Button
    private lateinit var missButton: Button
    private lateinit var weightButton: Button
    private lateinit var wheelchairButton: Button
    private lateinit var sessionKindButton: Button
    private lateinit var dansaUpStartButton: Button
    private lateinit var dansaDownStartButton: Button
    private lateinit var dansaStopHaltButton: Button
    private lateinit var dansaStopClimbButton: Button
    private lateinit var dansaStopButton: Button
    private lateinit var dansaCancelButton: Button
    private lateinit var dekoboStartButton: Button
    private lateinit var dekoboStopButton: Button
    private lateinit var sessionResultLogger: SessionResultLogger
    private lateinit var prefs: SharedPreferences

    private var accX = 0f
    private var accY = 0f
    private var accZ = 0f
    private var rotX: Float? = null
    private var rotY: Float? = null
    private var rotZ: Float? = null
    private var rotW: Float? = null
    private var gameRotX: Float? = null
    private var gameRotY: Float? = null
    private var gameRotZ: Float? = null
    private var gameRotW: Float? = null

    private val accLock = ReentrantLock()

    @Volatile
    private var startFlag = false

    @Volatile
    private var stopFlag = false
    private var scrollStarted = false
    private var clearRequested = false

    // 段差・凹凸の記録中に経路を残すためのGPS定期保存(1秒ごと)
    private var lastDansaGpsTime = 0L
    private var lastDekoboGpsTime = 0L
    // ボタンに関係なく、計測中ずっと残すGPS(gps.csv、1秒ごと)
    private var lastGpsLogTime = 0L
    private val GPS_INTERVAL_MS = 1000L

    @Volatile
    private var currentElapsed = 0f

    private var isDekoboRecording = false

    // 段差の1回の通過(START〜STOP)。dansa.csvのpass_id・directionに記録する
    private data class DansaPass(val id: Int, val direction: String)

    // 記録中の通過(記録中でなければnull)
    @Volatile
    private var currentDansaPass: DansaPass? = null
    // 取り消しボタンの対象(記録中、または直前に終えた通過)。取り消したらnull
    private var cancelableDansaPass: DansaPass? = null
    private var dansaPassCount = 0
    private val isDansaRecording get() = currentDansaPass != null
    private var currentSessionId: String? = null
    private var sessionStartedAt: Long? = null
    private var currentWeightKg: Float? = null
    private var sessionWeightKg: Float? = null
    // 使う車椅子(WHEELCHAIR_*)。体重と同じく、計測開始時の値をそのセッションに記録する
    private var currentWheelchair: String? = null
    private var sessionWheelchair: String? = null
    // セッションの種類(SESSION_KIND_*)とメモ。計測開始時の値をそのセッションに記録する
    private var currentSessionKind: String? = null
    private var sessionKind: String? = null
    private var sessionMemo: String? = null

    private val xDispMax = 5000f
    private val sessionDateFormat = SimpleDateFormat("yyyyMMddHHmmss", Locale.JAPAN)

    // 加速度のCSV保存間隔: 500 Hz = 2 ms
    // 200 Hzを超えるレートで登録するにはHIGH_SAMPLING_RATE_SENSORS権限が必要(AndroidManifest.xml参照)。
    // 端末のセンサーが対応していない場合はSensor.getMinDelay()相当の実測レートに自動的にクランプされる。
    private val ACC_SAMPLING_PERIOD_US = 2_000
    private val ACC_SAMPLING_PERIOD_NS = ACC_SAMPLING_PERIOD_US * 1_000L
    @Volatile
    private var measurementStartElapsedRealtimeNs = 0L
    private var lastAccLoggedTimestampNs = 0L
    private var lastGyroLoggedTimestampNs = 0L
    private var lastLinearAccLoggedTimestampNs = 0L

    companion object {
        private const val PREFS_NAME = "measurement_prefs"
        private const val KEY_WEIGHT_KG = "weight_kg"
        private const val KEY_WHEELCHAIR = "wheelchair"

        // session_result.csvのwheelchairの値
        private const val WHEELCHAIR_ORIGINAL = "original"  // 元々使っていた車椅子
        private const val WHEELCHAIR_STANDARD = "standard"  // 新しく買った汎用の車椅子
        private val WHEELCHAIRS = listOf(WHEELCHAIR_ORIGINAL, WHEELCHAIR_STANDARD)

        private const val KEY_SESSION_KIND = "session_kind"

        // session_result.csvのsession_kindの値(解析のラベル名と同じ)
        private const val SESSION_KIND_FLAT = "flat"
        private const val SESSION_KIND_STEP = "step"
        private const val SESSION_KIND_ROUGH = "rough"
        private val SESSION_KINDS = listOf(SESSION_KIND_FLAT, SESSION_KIND_STEP, SESSION_KIND_ROUGH)

        // dansa.csvのdirection・pass_typeの値
        private const val DIRECTION_UP = "up"
        private const val DIRECTION_DOWN = "down"
        private const val PASS_TYPE_STOP = "stop"    // 上りで段差にぶつかって止まった
        private const val PASS_TYPE_CLIMB = "climb"  // 上りで止まらずに乗り越えた
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // ===== 初期化 =====

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        gpsLocationManager = GPSLocationManager(this)

        accLogger = AccCsvLogger(this)
        // ジャイロ(rad/s)と、重力を除いた加速度(TYPE_LINEAR_ACCELERATION, m/s²)。どちらも端末の座標系。
        gyroLogger = SensorCsvLogger(this, "gyro.csv", listOf("gyroX", "gyroY", "gyroZ"))
        linearAccLogger = SensorCsvLogger(this, "linear_acc.csv", listOf("linAccX", "linAccY", "linAccZ"))
        dansaLogger = DansaCsvLogger(this)
        dekoboLogger = DekoboCsvLogger(this)
        gpsLogger = GpsCsvLogger(this)
        sessionResultLogger = SessionResultLogger(this)

        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        currentWeightKg = if (prefs.contains(KEY_WEIGHT_KG)) {
            prefs.getFloat(KEY_WEIGHT_KG, 0f)
        } else {
            null
        }
        currentWheelchair = prefs.getString(KEY_WHEELCHAIR, null)?.takeIf { it in WHEELCHAIRS }
        currentSessionKind = prefs.getString(KEY_SESSION_KIND, null)?.takeIf { it in SESSION_KINDS }

        // ===== GPS Permission =====

        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),
            1000
        )

        // ===== GPS 連続取得開始 =====

        gpsLocationManager.startLocationUpdates()

        // ===== グラフ =====

        val chart = findViewById<LineChart>(R.id.line_chart)
        statusTextView = findViewById(R.id.statusTextView)
        speedTextView = findViewById(R.id.speedTextView)
        weightTextView = findViewById(R.id.weightTextView)
        wheelchairTextView = findViewById(R.id.wheelchairTextView)
        sessionKindTextView = findViewById(R.id.sessionKindTextView)
        memoEditText = findViewById(R.id.memo_edit_text)
        startButton = findViewById(R.id.start_button)
        stopButton = findViewById(R.id.stop_button)
        clearButton = findViewById(R.id.clear_button)
        missButton = findViewById(R.id.miss_button)
        weightButton = findViewById(R.id.weight_button)
        wheelchairButton = findViewById(R.id.wheelchair_button)
        sessionKindButton = findViewById(R.id.session_kind_button)
        dansaUpStartButton = findViewById(R.id.dansa_up_start_button)
        dansaDownStartButton = findViewById(R.id.dansa_down_start_button)
        dansaStopHaltButton = findViewById(R.id.dansa_stop_halt_button)
        dansaStopClimbButton = findViewById(R.id.dansa_stop_climb_button)
        dansaStopButton = findViewById(R.id.dansa_stop_button)
        dansaCancelButton = findViewById(R.id.dansa_cancel_button)
        dekoboStartButton = findViewById(R.id.dekobo_start_button)
        dekoboStopButton = findViewById(R.id.dekobo_stop_button)
        setupChart(chart)
        updateUiState(isMeasuring = false, isStopping = false)
        updateWeightDisplay()
        updateWheelchairDisplay()
        updateSessionKindDisplay()

        // ===== ボタン処理 =====

        startButton.setOnClickListener {
            if (!startFlag) {
                startFlag = true
                stopFlag = false
                val sessionId = sessionDateFormat.format(Date())
                currentSessionId = sessionId
                sessionStartedAt = System.currentTimeMillis()
                sessionWeightKg = currentWeightKg
                sessionWheelchair = currentWheelchair
                sessionKind = currentSessionKind
                // CSVの1行に収まるよう、改行は空白にする
                sessionMemo = memoEditText.text.toString().replace(Regex("[\\r\\n]+"), " ").trim()
                lastGpsLogTime = 0L
                currentDansaPass = null
                cancelableDansaPass = null
                dansaPassCount = 0
                measurementStartElapsedRealtimeNs = SystemClock.elapsedRealtimeNanos()
                lastAccLoggedTimestampNs = 0L
                lastGyroLoggedTimestampNs = 0L
                lastLinearAccLoggedTimestampNs = 0L
                accLogger.startNewSession(sessionId)
                gyroLogger.startNewSession(sessionId)
                linearAccLogger.startNewSession(sessionId)
                dansaLogger.startNewSession(sessionId)
                dekoboLogger.startNewSession(sessionId)
                gpsLogger.startNewSession(sessionId)
                updateUiState(isMeasuring = true, isStopping = false)
                PlotThread().start()
            }
        }

        weightButton.setOnClickListener {
            showWeightInputDialog()
        }

        wheelchairButton.setOnClickListener {
            showWheelchairSelectDialog()
        }

        sessionKindButton.setOnClickListener {
            showSessionKindSelectDialog()
        }

        stopButton.setOnClickListener {
            stopMeasurement("success", null)
        }

        clearButton.setOnClickListener {
            if (startFlag || currentSessionId != null) {
                stopMeasurement("failed", "cleared")
                clearRequested = true
            } else {
                clearRequested = false
                clearChart()
                updateUiState(isMeasuring = false, isStopping = false)
            }
        }

        missButton.setOnClickListener {
            stopMeasurement("failed", "button_miss")
        }

        // 段差は1回の通過ごとにSTART・STOPを押す。上りはSTOPで止まった/乗り越えたを選ぶ
        dansaUpStartButton.setOnClickListener {
            startDansaPass(chart, DIRECTION_UP)
        }

        dansaDownStartButton.setOnClickListener {
            startDansaPass(chart, DIRECTION_DOWN)
        }

        dansaStopHaltButton.setOnClickListener {
            stopDansaPass(chart, PASS_TYPE_STOP)
        }

        dansaStopClimbButton.setOnClickListener {
            stopDansaPass(chart, PASS_TYPE_CLIMB)
        }

        dansaStopButton.setOnClickListener {
            stopDansaPass(chart, null)
        }

        dansaCancelButton.setOnClickListener {
            cancelDansaPass(chart)
        }

        dekoboStartButton.setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.BLUE, 2f)
            isDekoboRecording = true
            lastDekoboGpsTime = System.currentTimeMillis()
            updateUiState(isMeasuring = true, isStopping = false)
            recordEvent("dekobo_start")
        }

        dekoboStopButton.setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.BLUE, 5f)
            isDekoboRecording = false
            updateUiState(isMeasuring = true, isStopping = false)
            recordEvent("dekobo_stop")
        }
    }

    override fun onResume() {
        super.onResume()
        val accSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        val rotationSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        val gameRotationSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)
        val gyroSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        val linearAccSensor = sensorManager.getDefaultSensor(Sensor.TYPE_LINEAR_ACCELERATION)
        if (accSensor != null && accSensor.minDelay > ACC_SAMPLING_PERIOD_US) {
            Log.w(
                "MainActivity",
                "端末の加速度センサーは要求周期(${ACC_SAMPLING_PERIOD_US}us)に対応していません。" +
                    "実際は最速でも${accSensor.minDelay}us間隔にクランプされます。"
            )
        }
        sensorManager.registerListener(this, accSensor, ACC_SAMPLING_PERIOD_US)
        // 姿勢は世界座標系への変換に使うため、加速度と同じ周期で登録する
        // (以前はSENSOR_DELAY_NORMALで、約5 Hzでしか更新されていなかった)。
        // 端末にないセンサーは登録しない(CSVの該当列・ファイルが空になる)。
        for (sensor in listOf(rotationSensor, gameRotationSensor, gyroSensor, linearAccSensor)) {
            if (sensor == null) continue
            if (sensor.minDelay > ACC_SAMPLING_PERIOD_US) {
                Log.w("MainActivity", "${sensor.name}は最速でも${sensor.minDelay}us間隔にクランプされます。")
            }
            sensorManager.registerListener(this, sensor, ACC_SAMPLING_PERIOD_US)
        }
    }

    override fun onPause() {
        super.onPause()
        sensorManager.unregisterListener(this)
    }

    // ===== 加速度取得 =====

    override fun onSensorChanged(event: SensorEvent) {
        accLock.lock()
        try {
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> {
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    val rx: Float?
                    val ry: Float?
                    val rz: Float?
                    val rw: Float?
                    val grx: Float?
                    val gry: Float?
                    val grz: Float?
                    val grw: Float?

                    accLock.lock()
                    try {
                        accX = x
                        accY = y
                        accZ = z
                        rx = rotX
                        ry = rotY
                        rz = rotZ
                        rw = rotW
                        grx = gameRotX
                        gry = gameRotY
                        grz = gameRotZ
                        grw = gameRotW
                    } finally {
                        accLock.unlock()
                    }

                    // センサーイベントを直接CSVへ保存する。端末が50 Hzより高頻度で
                    // 通知した場合も、20 ms未満のイベントは保存しない。
                    if (
                        startFlag &&
                        event.timestamp >= measurementStartElapsedRealtimeNs &&
                        event.timestamp - lastAccLoggedTimestampNs >= ACC_SAMPLING_PERIOD_NS
                    ) {
                        val timestamp = System.currentTimeMillis()
                        val elapsed = (event.timestamp - measurementStartElapsedRealtimeNs) / 1_000_000f
                        val location = gpsLocationManager.getCurrentLocation()
                        val speedMps = if (location?.hasSpeed() == true) location.speed else null

                        accLogger.append(
                            timestamp, elapsed, x, y, z, speedMps, rx, ry, rz, rw,
                            grx, gry, grz, grw, event.timestamp
                        )
                        lastAccLoggedTimestampNs = event.timestamp
                    }
                }

                Sensor.TYPE_ROTATION_VECTOR -> {
                    rotX = event.values.getOrNull(0)
                    rotY = event.values.getOrNull(1)
                    rotZ = event.values.getOrNull(2)
                    rotW = event.values.getOrNull(3)
                }

                Sensor.TYPE_GAME_ROTATION_VECTOR -> {
                    gameRotX = event.values.getOrNull(0)
                    gameRotY = event.values.getOrNull(1)
                    gameRotZ = event.values.getOrNull(2)
                    gameRotW = event.values.getOrNull(3)
                }

                Sensor.TYPE_GYROSCOPE -> {
                    if (shouldLog(event.timestamp, lastGyroLoggedTimestampNs)) {
                        gyroLogger.append(
                            System.currentTimeMillis(), elapsedMs(event.timestamp), event.timestamp, event.values
                        )
                        lastGyroLoggedTimestampNs = event.timestamp
                    }
                }

                Sensor.TYPE_LINEAR_ACCELERATION -> {
                    if (shouldLog(event.timestamp, lastLinearAccLoggedTimestampNs)) {
                        linearAccLogger.append(
                            System.currentTimeMillis(), elapsedMs(event.timestamp), event.timestamp, event.values
                        )
                        lastLinearAccLoggedTimestampNs = event.timestamp
                    }
                }
            }
        } finally {
            accLock.unlock()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // 加速度と同じ条件(計測中、計測開始後、保存間隔以上)でCSVに保存するか
    private fun shouldLog(eventTimestampNs: Long, lastLoggedNs: Long): Boolean =
        startFlag &&
            eventTimestampNs >= measurementStartElapsedRealtimeNs &&
            eventTimestampNs - lastLoggedNs >= ACC_SAMPLING_PERIOD_NS

    private fun elapsedMs(eventTimestampNs: Long): Float =
        (eventTimestampNs - measurementStartElapsedRealtimeNs) / 1_000_000f

    private fun startDansaPass(chart: LineChart, direction: String) {
        addVerticalLine(chart, currentElapsed, Color.RED, 2f)
        dansaPassCount++
        val pass = DansaPass(dansaPassCount, direction)
        currentDansaPass = pass
        cancelableDansaPass = pass
        lastDansaGpsTime = System.currentTimeMillis()
        updateUiState(isMeasuring = true, isStopping = false)
        recordEvent("dansa_start", pass)
    }

    // passType: 上りはPASS_TYPE_STOPかPASS_TYPE_CLIMB、下りはnull
    private fun stopDansaPass(chart: LineChart, passType: String?) {
        val pass = currentDansaPass ?: return
        addVerticalLine(chart, currentElapsed, Color.RED, 5f)
        currentDansaPass = null
        updateUiState(isMeasuring = true, isStopping = false)
        recordEvent("dansa_stop", pass, passType)
    }

    // 押し間違えた通過を無効にする。行は消さず、dansa_cancelを記録して解析で除く
    private fun cancelDansaPass(chart: LineChart) {
        val pass = cancelableDansaPass ?: return
        addVerticalLine(chart, currentElapsed, Color.GRAY, 5f)
        if (currentDansaPass == pass) currentDansaPass = null
        cancelableDansaPass = null
        updateUiState(isMeasuring = true, isStopping = false)
        recordEvent("dansa_cancel", pass)
    }

    private fun stopMeasurement(result: String, reason: String?) {
        stopFlag = true
        // 段差の通過の途中で計測を終了した場合は、STOPのない通過として取り消す
        currentDansaPass?.let {
            currentDansaPass = null
            recordEvent("dansa_cancel", it)
        }
        cancelableDansaPass = null
        isDekoboRecording = false
        finalizeSession(result, reason)
        accLogger.endSession()
        gyroLogger.endSession()
        linearAccLogger.endSession()
        dansaLogger.endSession()
        dekoboLogger.endSession()
        gpsLogger.endSession()
        updateUiState(isMeasuring = true, isStopping = true)
    }

    private fun finalizeSession(result: String, reason: String?) {
        val sessionId = currentSessionId ?: return
        val startedAt = sessionStartedAt ?: System.currentTimeMillis()
        val endedAt = System.currentTimeMillis()

        sessionResultLogger.appendResult(
            sessionId = sessionId,
            result = result,
            reason = reason,
            startedAt = startedAt,
            endedAt = endedAt,
            weightKg = sessionWeightKg,
            wheelchair = sessionWheelchair,
            sessionKind = sessionKind,
            memo = sessionMemo
        )

        currentSessionId = null
        sessionStartedAt = null
        sessionWeightKg = null
        sessionWheelchair = null
        sessionKind = null
        sessionMemo = null
    }

    private fun showWeightInputDialog() {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            hint = getString(R.string.weight_dialog_hint)
            currentWeightKg?.let { setText(it.toString()) }
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.weight_dialog_title)
            .setView(input)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val weight = input.text.toString().toFloatOrNull()
                if (weight == null || weight <= 0f || weight > 300f) {
                    android.widget.Toast.makeText(
                        this,
                        R.string.weight_dialog_error,
                        android.widget.Toast.LENGTH_SHORT
                    ).show()
                    return@setPositiveButton
                }
                currentWeightKg = weight
                prefs.edit().putFloat(KEY_WEIGHT_KG, weight).apply()
                updateWeightDisplay()
            }
            .setNegativeButton(R.string.weight_dialog_cancel, null)
            .show()
    }

    private fun showWheelchairSelectDialog() {
        val labels = WHEELCHAIRS.map { wheelchairLabel(it) }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle(R.string.wheelchair_dialog_title)
            .setSingleChoiceItems(labels, WHEELCHAIRS.indexOf(currentWheelchair)) { dialog, which ->
                val wheelchair = WHEELCHAIRS[which]
                currentWheelchair = wheelchair
                prefs.edit().putString(KEY_WHEELCHAIR, wheelchair).apply()
                updateWheelchairDisplay()
                dialog.dismiss()
            }
            .setNegativeButton(R.string.weight_dialog_cancel, null)
            .show()
    }

    private fun wheelchairLabel(wheelchair: String): String = getString(
        when (wheelchair) {
            WHEELCHAIR_ORIGINAL -> R.string.wheelchair_original
            else -> R.string.wheelchair_standard
        }
    )

    private fun updateWheelchairDisplay() {
        wheelchairTextView.text = currentWheelchair?.let {
            getString(R.string.wheelchair_format, wheelchairLabel(it))
        } ?: getString(R.string.wheelchair_unavailable)
    }

    private fun showSessionKindSelectDialog() {
        val labels = SESSION_KINDS.map { sessionKindLabel(it) }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle(R.string.session_kind_dialog_title)
            .setSingleChoiceItems(labels, SESSION_KINDS.indexOf(currentSessionKind)) { dialog, which ->
                val kind = SESSION_KINDS[which]
                currentSessionKind = kind
                prefs.edit().putString(KEY_SESSION_KIND, kind).apply()
                updateSessionKindDisplay()
                dialog.dismiss()
            }
            .setNegativeButton(R.string.weight_dialog_cancel, null)
            .show()
    }

    private fun sessionKindLabel(kind: String): String = getString(
        when (kind) {
            SESSION_KIND_FLAT -> R.string.session_kind_flat
            SESSION_KIND_STEP -> R.string.session_kind_step
            else -> R.string.session_kind_rough
        }
    )

    private fun updateSessionKindDisplay() {
        sessionKindTextView.text = currentSessionKind?.let {
            getString(R.string.session_kind_format, sessionKindLabel(it))
        } ?: getString(R.string.session_kind_unavailable)
    }

    private fun updateWeightDisplay() {
        weightTextView.text = currentWeightKg?.let {
            getString(R.string.weight_format, it)
        } ?: getString(R.string.weight_unavailable)
    }

    private fun clearChart() {
        val chart = findViewById<LineChart>(R.id.line_chart)
        setupChart(chart)
        chart.xAxis.removeAllLimitLines()
        chart.invalidate()

        currentElapsed = 0f
        lastDansaGpsTime = 0L
        lastDekoboGpsTime = 0L
        scrollStarted = false
        currentDansaPass = null
        cancelableDansaPass = null
        isDekoboRecording = false
        speedTextView.text = getString(R.string.speed_unavailable)
    }

    private fun updateUiState(isMeasuring: Boolean, isStopping: Boolean) {
        runOnUiThread {
            statusTextView.text = when {
                isStopping -> getString(R.string.status_stopping)
                isMeasuring -> getString(R.string.status_measuring)
                else -> getString(R.string.status_idle)
            }
            startButton.isEnabled = !isMeasuring && !isStopping
            stopButton.isEnabled = isMeasuring && !isStopping
            clearButton.isEnabled = !isStopping
            missButton.isEnabled = isMeasuring && !isStopping
            val dansaDirection = currentDansaPass?.direction
            dansaUpStartButton.isEnabled = isMeasuring && !isStopping && !isDansaRecording
            dansaDownStartButton.isEnabled = isMeasuring && !isStopping && !isDansaRecording
            dansaStopHaltButton.isEnabled = isMeasuring && !isStopping && dansaDirection == DIRECTION_UP
            dansaStopClimbButton.isEnabled = isMeasuring && !isStopping && dansaDirection == DIRECTION_UP
            dansaStopButton.isEnabled = isMeasuring && !isStopping && dansaDirection == DIRECTION_DOWN
            dansaCancelButton.isEnabled = isMeasuring && !isStopping && cancelableDansaPass != null
            dekoboStartButton.isEnabled = isMeasuring && !isStopping && !isDekoboRecording
            dekoboStopButton.isEnabled = isMeasuring && !isStopping && isDekoboRecording
        }
    }

    private fun updateSpeedDisplay(speedMps: Float?) {
        runOnUiThread {
            speedTextView.text = if (speedMps != null) {
                getString(R.string.speed_format, speedMps)
            } else {
                getString(R.string.speed_unavailable)
            }
        }
    }

    // ===== イベント＋GPS記録 =====

    // dansaPass・passType: 段差の通過の記録(dansa.csvのpass_id・direction・pass_type)。それ以外は空
    private fun recordEvent(event: String, dansaPass: DansaPass? = null, passType: String? = null) {

        val timestamp = System.currentTimeMillis()
        // acc.csvのelapsedと同じ時計(センサーの時刻の基準)で数えた、計測開始からの時間
        val sensorElapsed = elapsedMs(SystemClock.elapsedRealtimeNanos())
        val location = gpsLocationManager.getCurrentLocation()
        val latitude = location?.latitude
        val longitude = location?.longitude

        when {
            event.startsWith("dansa") -> {
                dansaLogger.append(
                    timestamp,
                    currentElapsed,
                    accX,
                    accY,
                    accZ,
                    latitude,
                    longitude,
                    event,
                    sensorElapsed,
                    dansaPass?.id,
                    dansaPass?.direction,
                    passType
                )
            }

            event.startsWith("dekobo") -> {
                dekoboLogger.append(
                    timestamp,
                    currentElapsed,
                    accX,
                    accY,
                    accZ,
                    latitude,
                    longitude,
                    event,
                    sensorElapsed
                )
            }
        }
    }

    // ===== グラフ描画スレッド =====

    private inner class PlotThread : Thread() {

        override fun run() {

            val chart = findViewById<LineChart>(R.id.line_chart)
            val startTime = System.currentTimeMillis()

            startFlag = true
            scrollStarted = false

            while (true) {

                accLock.lock()
                val x = accX
                val y = accY
                val z = accZ
                accLock.unlock()

                currentElapsed = (System.currentTimeMillis() - startTime).toFloat()

                val location = gpsLocationManager.getCurrentLocation()
                val speedMps = if (location?.hasSpeed() == true) location.speed else null
                updateSpeedDisplay(speedMps)

                // ===== 段差・凹凸中 GPS 定期保存 =====

                val now = System.currentTimeMillis()

                val dansaPass = currentDansaPass
                if (dansaPass != null && now - lastDansaGpsTime >= GPS_INTERVAL_MS) {
                    lastDansaGpsTime = now
                    recordEvent("dansa_during", dansaPass)
                }

                if (isDekoboRecording && now - lastDekoboGpsTime >= GPS_INTERVAL_MS) {
                    lastDekoboGpsTime = now
                    recordEvent("dekobo_during")
                }

                if (now - lastGpsLogTime >= GPS_INTERVAL_MS) {
                    lastGpsLogTime = now
                    gpsLogger.append(now, elapsedMs(SystemClock.elapsedRealtimeNanos()), location)
                }

                // ===== グラフ更新 =====

                runOnUiThread {

                    if (currentElapsed > xDispMax && !scrollStarted) {
                        scrollStarted = true
                        chart.xAxis.resetAxisMinimum()
                        chart.xAxis.resetAxisMaximum()
                    }

                    chart.data.addEntry(Entry(currentElapsed, x), 0)
                    chart.data.addEntry(Entry(currentElapsed, y), 1)
                    chart.data.addEntry(Entry(currentElapsed, z), 2)

                    chart.notifyDataSetChanged()
                    chart.setVisibleXRangeMaximum(xDispMax)
                    chart.moveViewToX(currentElapsed)
                }

                if (stopFlag) break

                sleep(250)
            }

            startFlag = false
            stopFlag = false
            if (clearRequested) {
                clearRequested = false
                runOnUiThread { clearChart() }
            }
            updateUiState(isMeasuring = false, isStopping = false)
        }
    }

    // ===== グラフ設定 =====

    private fun setupChart(chart: LineChart) {

        chart.setBackgroundColor(Color.LTGRAY)

        chart.axisLeft.axisMinimum = -30f
        chart.axisLeft.axisMaximum = 30f

        chart.axisRight.isEnabled = false
        chart.description.isEnabled = false

        val sets = listOf(
            LineDataSet(ArrayList(), "X").apply {
                color = Color.RED
                setDrawValues(false)
                setDrawCircles(false)
            },
            LineDataSet(ArrayList(), "Y").apply {
                color = Color.BLUE
                setDrawValues(false)
                setDrawCircles(false)
            },
            LineDataSet(ArrayList(), "Z").apply {
                color = Color.YELLOW
                setDrawValues(false)
                setDrawCircles(false)
            }
        )

        chart.data = LineData(sets)
        chart.invalidate()
    }

    // ===== 縦線追加 =====

    private fun addVerticalLine(chart: LineChart, x: Float, color: Int, width: Float) {

        val line = LimitLine(x).apply {
            lineColor = color
            lineWidth = width
        }

        chart.xAxis.addLimitLine(line)
        chart.invalidate()
    }
}
