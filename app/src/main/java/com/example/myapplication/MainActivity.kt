package com.example.myapplication

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.widget.Button
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
    private lateinit var dansaLogger: DansaCsvLogger
    private lateinit var dekoboLogger: DekoboCsvLogger
    private lateinit var statusTextView: TextView
    private lateinit var speedTextView: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var clearButton: Button
    private lateinit var dansaStartButton: Button
    private lateinit var dansaStopButton: Button
    private lateinit var dekoboStartButton: Button
    private lateinit var dekoboStopButton: Button

    private var accX = 0f
    private var accY = 0f
    private var accZ = 0f
    private var rotX: Float? = null
    private var rotY: Float? = null
    private var rotZ: Float? = null
    private var rotW: Float? = null

    private val accLock = ReentrantLock()

    private var startFlag = false
    private var stopFlag = false
    private var scrollStarted = false
    private var clearRequested = false

    private var lastGpsTime = 0L
    private val GPS_INTERVAL_MS = 1000L

    @Volatile
    private var currentElapsed = 0f

    private var isDekoboRecording = false
    private var isDansaRecording = false

    private val xDispMax = 5000f
    private val sessionDateFormat = SimpleDateFormat("yyyyMMddHHmmss", Locale.JAPAN)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // ===== 初期化 =====

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        gpsLocationManager = GPSLocationManager(this)

        accLogger = AccCsvLogger(this)
        dansaLogger = DansaCsvLogger(this)
        dekoboLogger = DekoboCsvLogger(this)

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
        startButton = findViewById(R.id.start_button)
        stopButton = findViewById(R.id.stop_button)
        clearButton = findViewById(R.id.clear_button)
        dansaStartButton = findViewById(R.id.dansa_start_button)
        dansaStopButton = findViewById(R.id.dansa_stop_button)
        dekoboStartButton = findViewById(R.id.dekobo_start_button)
        dekoboStopButton = findViewById(R.id.dekobo_stop_button)
        setupChart(chart)
        updateUiState(isMeasuring = false, isStopping = false)

        // ===== ボタン処理 =====

        startButton.setOnClickListener {
            if (!startFlag) {
                stopFlag = false
                val sessionId = sessionDateFormat.format(Date())
                accLogger.startNewSession(sessionId)
                dansaLogger.startNewSession(sessionId)
                dekoboLogger.startNewSession(sessionId)
                updateUiState(isMeasuring = true, isStopping = false)
                PlotThread().start()
            }
        }

        stopButton.setOnClickListener {
            stopMeasurement()
        }

        clearButton.setOnClickListener {
            if (startFlag) {
                stopMeasurement()
                clearRequested = true
            } else {
                clearRequested = false
                clearChart()
                updateUiState(isMeasuring = false, isStopping = false)
            }
        }

        dansaStartButton.setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.RED, 2f)
            isDansaRecording = true
            updateUiState(isMeasuring = true, isStopping = false)
            recordEvent("dansa_start")
        }

        dansaStopButton.setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.RED, 5f)
            isDansaRecording = false
            updateUiState(isMeasuring = true, isStopping = false)
            recordEvent("dansa_stop")
        }

        dekoboStartButton.setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.BLUE, 2f)
            isDekoboRecording = true
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
        sensorManager.registerListener(this, accSensor, SensorManager.SENSOR_DELAY_NORMAL)
        if (rotationSensor != null) {
            sensorManager.registerListener(this, rotationSensor, SensorManager.SENSOR_DELAY_NORMAL)
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
                    accX = event.values[0]
                    accY = event.values[1]
                    accZ = event.values[2]
                }

                Sensor.TYPE_ROTATION_VECTOR -> {
                    rotX = event.values.getOrNull(0)
                    rotY = event.values.getOrNull(1)
                    rotZ = event.values.getOrNull(2)
                    rotW = event.values.getOrNull(3)
                }
            }
        } finally {
            accLock.unlock()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    private fun stopMeasurement() {
        stopFlag = true
        isDansaRecording = false
        isDekoboRecording = false
        accLogger.endSession()
        dansaLogger.endSession()
        dekoboLogger.endSession()
        updateUiState(isMeasuring = true, isStopping = true)
    }

    private fun clearChart() {
        val chart = findViewById<LineChart>(R.id.line_chart)
        setupChart(chart)
        chart.xAxis.removeAllLimitLines()
        chart.invalidate()

        currentElapsed = 0f
        lastGpsTime = 0L
        scrollStarted = false
        isDansaRecording = false
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
            dansaStartButton.isEnabled = isMeasuring && !isStopping && !isDansaRecording
            dansaStopButton.isEnabled = isMeasuring && !isStopping && isDansaRecording
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

    private fun recordEvent(event: String) {

        val timestamp = System.currentTimeMillis()
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
                    event
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
                    event
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
                val rx = rotX
                val ry = rotY
                val rz = rotZ
                val rw = rotW
                accLock.unlock()

                currentElapsed = (System.currentTimeMillis() - startTime).toFloat()

                val timestamp = System.currentTimeMillis()
                val location = gpsLocationManager.getCurrentLocation()
                val speedMps = if (location?.hasSpeed() == true) location.speed else null
                updateSpeedDisplay(speedMps)

                // ===== 加速度CSV保存 =====

                accLogger.append(
                    timestamp,
                    currentElapsed,
                    x,
                    y,
                    z,
                    speedMps,
                    rx,
                    ry,
                    rz,
                    rw
                )

                // ===== 凹凸中 GPS 定期保存 =====

                if (isDekoboRecording) {
                    val now = System.currentTimeMillis()

                    if (now - lastGpsTime >= GPS_INTERVAL_MS) {
                        lastGpsTime = now
                        recordEvent("dekobo_during")
                    }
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
