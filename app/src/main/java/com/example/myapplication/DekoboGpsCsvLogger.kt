package com.example.myapplication

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

class DekoboCsvLogger(private val context: Context) {

    private val dateFormat =
        SimpleDateFormat("yyyy-MM-dd", Locale.JAPAN)

    private fun getTodayFile(): File {

        val dateStr = dateFormat.format(Date())

        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        val file = File(dir, "dekobo_$dateStr.csv")

        // 新規作成時のみヘッダ追加
        if (!file.exists()) {
            file.writeText(
                "timestamp_ms,elapsed_ms,acc_x,acc_y,acc_z,latitude,longitude,event\n"
            )
        }

        return file
    }

    @Synchronized
    fun append(
        timestamp: Long,
        elapsed: Float,
        accX: Float,
        accY: Float,
        accZ: Float,
        lat: Double,
        lon: Double,
        event: String
    ) {

        val file = getTodayFile()

        val line =
            "$timestamp,$elapsed,$accX,$accY,$accZ,$lat,$lon,$event\n"

        file.appendText(line)
    }
}
