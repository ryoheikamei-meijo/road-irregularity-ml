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
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.github.mikephil.charting.charts.LineChart
import com.github.mikephil.charting.components.LimitLine
import com.github.mikephil.charting.data.Entry
import com.github.mikephil.charting.data.LineData
import com.github.mikephil.charting.data.LineDataSet
import java.util.concurrent.locks.ReentrantLock

class MainActivity : AppCompatActivity(), SensorEventListener {

    private lateinit var sensorManager: SensorManager
    private lateinit var gpsLocationManager: GPSLocationManager

    private lateinit var accLogger: AccCsvLogger
    private lateinit var dansaLogger: DansaCsvLogger
    private lateinit var dekoboLogger: DekoboCsvLogger

    private var accX = 0f
    private var accY = 0f
    private var accZ = 0f

    private val accLock = ReentrantLock()

    private var startFlag = false
    private var stopFlag = false
    private var scrollStarted = false

    private var lastGpsTime = 0L
    private val GPS_INTERVAL_MS = 1000L

    @Volatile
    private var currentElapsed = 0f

    private var isDekoboRecording = false

    private val xDispMax = 5000f

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
        setupChart(chart)

        // ===== ボタン処理 =====

        findViewById<Button>(R.id.start_button).setOnClickListener {
            if (!startFlag) {
                stopFlag = false
                PlotThread().start()
            }
        }

        findViewById<Button>(R.id.stop_button).setOnClickListener {
            stopFlag = true
        }

        findViewById<Button>(R.id.clear_button).setOnClickListener {
            stopFlag = true
            chart.data.clearValues()
            chart.xAxis.removeAllLimitLines()
            chart.invalidate()

            currentElapsed = 0f
            lastGpsTime = 0L
            scrollStarted = false
        }

        findViewById<Button>(R.id.dansa_start_button).setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.RED, 2f)
            recordEvent("dansa_start")
        }

        findViewById<Button>(R.id.dansa_stop_button).setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.RED, 5f)
            recordEvent("dansa_stop")
        }

        findViewById<Button>(R.id.dekobo_start_button).setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.BLUE, 2f)
            isDekoboRecording = true
            recordEvent("dekobo_start")
        }

        findViewById<Button>(R.id.dekobo_stop_button).setOnClickListener {
            addVerticalLine(chart, currentElapsed, Color.BLUE, 5f)
            isDekoboRecording = false
            recordEvent("dekobo_stop")
        }
    }

    override fun onResume() {
        super.onResume()
        val accSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        sensorManager.registerListener(this, accSensor, SensorManager.SENSOR_DELAY_NORMAL)
    }

    override fun onPause() {
        super.onPause()
        sensorManager.unregisterListener(this)
    }

    // ===== 加速度取得 =====

    override fun onSensorChanged(event: SensorEvent) {
        accLock.lock()
        accX = event.values[0]
        accY = event.values[1]
        accZ = event.values[2]
        accLock.unlock()
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // ===== イベント＋GPS記録 =====

    private fun recordEvent(event: String) {

        val timestamp = System.currentTimeMillis()
        val location = gpsLocationManager.getCurrentLocation()

        location?.let {

            when {
                event.startsWith("dansa") -> {
                    dansaLogger.append(
                        timestamp,
                        currentElapsed,
                        accX,
                        accY,
                        accZ,
                        it.latitude,
                        it.longitude,
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
                        it.latitude,
                        it.longitude,
                        event
                    )
                }
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

                val timestamp = System.currentTimeMillis()

                // ===== 加速度CSV保存 =====

                accLogger.append(
                    timestamp,
                    currentElapsed,
                    x,
                    y,
                    z
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
