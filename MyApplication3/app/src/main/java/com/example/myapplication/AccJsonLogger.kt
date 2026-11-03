package com.example.myapplication

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.FileWriter

class AccJsonLogger(context: Context) {

    private val file = File(context.getExternalFilesDir(null), "acc_log.jsonl")

    @Synchronized
    fun append(
        timestamp: Long,
        elapsed: Float,
        x: Float,
        y: Float,
        z: Float
    ) {
        val json = JSONObject().apply {
            put("timestamp", timestamp)
            put("elapsed_ms", elapsed)
            put("acc_x", x)
            put("acc_y", y)
            put("acc_z", z)
        }

        FileWriter(file, true).use { writer ->
            writer.append(json.toString())
            writer.append("\n")
        }
    }
}
