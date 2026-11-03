package com.example.myapplication

import android.content.Context
import android.location.Location
import java.io.File

// 計測中、ボタンに関係なく1秒ごとにGPSの位置を記録する(gps.csv)。
// flatのセッションなど、ボタンを押さないセッションでも、どこを走ったかを後から確かめるため。
class GpsCsvLogger(private val context: Context) {

    private var currentFile: File? = null

    private fun createSessionFile(sessionId: String): File {
        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        val sessionDir = File(dir, sessionId)
        if (!sessionDir.exists()) sessionDir.mkdirs()

        return File(sessionDir, "gps.csv")
    }

    @Synchronized
    fun startNewSession(sessionId: String) {
        currentFile = createSessionFile(sessionId)
    }

    @Synchronized
    fun endSession() {
        currentFile = null
    }

    // location: まだ位置が取れていなければnull(その行は位置の列が空になる)
    @Synchronized
    fun append(timestamp: Long, sensorElapsed: Float, location: Location?) {

        val file = currentFile ?: return
        if (!file.exists()) {
            file.writeText(
                "timestamp_ms,sensor_elapsed_ms,latitude,longitude,accuracy_m,speed_mps,fix_age_ms\n"
            )
        }

        val lat = location?.latitude?.toString() ?: ""
        val lon = location?.longitude?.toString() ?: ""
        val accuracy = location?.takeIf { it.hasAccuracy() }?.accuracy?.toString() ?: ""
        val speed = location?.takeIf { it.hasSpeed() }?.speed?.toString() ?: ""
        // 最後に位置が更新されてからの時間。大きければ、GPSが止まって古い位置のままになっている
        val fixAge = location?.let { (timestamp - it.time).toString() } ?: ""
        file.appendText("$timestamp,$sensorElapsed,$lat,$lon,$accuracy,$speed,$fixAge\n")
    }
}
