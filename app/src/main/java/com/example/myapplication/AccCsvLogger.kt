package com.example.myapplication

import android.content.Context
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.*

class AccCsvLogger(private val context: Context) {

    private val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.JAPAN)

    private fun getTodayFile(): File {

        val dateStr = dateFormat.format(Date())

        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        return File(dir, "acc_$dateStr.csv")
    }

    fun append(
        timestamp: Long,
        elapsed: Float,
        accX: Float,
        accY: Float,
        accZ: Float
    ) {

        val file = getTodayFile()

        val isNewFile = !file.exists()

        FileWriter(file, true).use { writer ->

            // ヘッダ自動追加
            if (isNewFile) {
                writer.append("timestamp,elapsed,accX,accY,accZ\n")
            }

            writer.append(
                "$timestamp,$elapsed,$accX,$accY,$accZ\n"
            )
        }
    }
}
