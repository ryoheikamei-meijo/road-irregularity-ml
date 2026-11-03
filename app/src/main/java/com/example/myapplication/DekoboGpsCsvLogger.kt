package com.example.myapplication

import android.content.Context
import java.io.File

class DekoboCsvLogger(private val context: Context) {

    private var currentFile: File? = null

    private fun createSessionFile(sessionId: String): File {
        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        val sessionDir = File(dir, sessionId)
        if (!sessionDir.exists()) sessionDir.mkdirs()

        return File(sessionDir, "dekobo.csv")
    }

    @Synchronized
    fun startNewSession(sessionId: String) {
        currentFile = createSessionFile(sessionId)
    }

    @Synchronized
    fun endSession() {
        currentFile = null
    }

    @Synchronized
    fun append(
        timestamp: Long,
        elapsed: Float,
        accX: Float,
        accY: Float,
        accZ: Float,
        lat: Double?,
        lon: Double?,
        event: String,
        sensorElapsed: Float
    ) {

        val file = currentFile ?: return
        if (!file.exists()) {
            file.writeText(
                "timestamp_ms,elapsed_ms,acc_x,acc_y,acc_z,latitude,longitude,event,sensor_elapsed_ms\n"
            )
        }

        val latValue = lat?.toString() ?: ""
        val lonValue = lon?.toString() ?: ""
        val line =
            "$timestamp,$elapsed,$accX,$accY,$accZ,$latValue,$lonValue,$event,$sensorElapsed\n"

        file.appendText(line)
    }
}
