package com.example.myapplication

import android.content.Context
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.*

class AccCsvLogger(private val context: Context) {

    private var currentFile: File? = null

    private fun createSessionFile(sessionId: String): File {
        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        val sessionDir = File(dir, sessionId)
        if (!sessionDir.exists()) sessionDir.mkdirs()

        return File(sessionDir, "acc.csv")
    }

    @Synchronized
    fun startNewSession(sessionId: String) {
        currentFile = createSessionFile(sessionId)
    }

    @Synchronized
    fun endSession() {
        currentFile = null
    }

    fun append(
        timestamp: Long,
        elapsed: Float,
        accX: Float,
        accY: Float,
        accZ: Float,
        speedMps: Float?,
        rotX: Float?,
        rotY: Float?,
        rotZ: Float?,
        rotW: Float?
    ) {

        val file = currentFile ?: return

        val isNewFile = !file.exists()

        FileWriter(file, true).use { writer ->

            // ヘッダ自動追加
            if (isNewFile) {
                writer.append("timestamp,elapsed,accX,accY,accZ,speedMps,rotX,rotY,rotZ,rotW\n")
            }

            val speedValue = speedMps?.toString() ?: ""
            val rotXValue = rotX?.toString() ?: ""
            val rotYValue = rotY?.toString() ?: ""
            val rotZValue = rotZ?.toString() ?: ""
            val rotWValue = rotW?.toString() ?: ""
            writer.append(
                "$timestamp,$elapsed,$accX,$accY,$accZ,$speedValue,$rotXValue,$rotYValue,$rotZValue,$rotWValue\n"
            )
        }
    }
}
