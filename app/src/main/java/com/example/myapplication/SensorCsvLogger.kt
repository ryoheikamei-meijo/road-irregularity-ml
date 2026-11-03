package com.example.myapplication

import android.content.Context
import java.io.BufferedWriter
import java.io.File
import java.io.FileWriter

/**
 * 3軸センサー(ジャイロ・重力を除いた加速度など)の値を、セッションごとのCSVに保存する。
 *
 * 加速度とは別のセンサーイベントで届くため、acc.csvには混ぜず、
 * イベント自身のタイムスタンプ(eventTimestampNs)を付けて別ファイルに保存する。
 * 後処理では、eventTimestampNs(acc.csvにも同じ列がある)で時刻を合わせる。
 * 高頻度(数百Hz)で書き込むため、セッション中はファイルを開いたままにする。
 */
class SensorCsvLogger(
    private val context: Context,
    private val fileName: String,
    private val valueColumns: List<String>
) {

    private var writer: BufferedWriter? = null

    private fun createSessionFile(sessionId: String): File {
        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()

        val sessionDir = File(dir, sessionId)
        if (!sessionDir.exists()) sessionDir.mkdirs()

        return File(sessionDir, fileName)
    }

    @Synchronized
    fun startNewSession(sessionId: String) {
        writer?.close()
        writer = BufferedWriter(FileWriter(createSessionFile(sessionId), false)).apply {
            append("timestamp,elapsed,eventTimestampNs,${valueColumns.joinToString(",")}\n")
        }
    }

    @Synchronized
    fun endSession() {
        writer?.close()
        writer = null
    }

    @Synchronized
    fun append(timestamp: Long, elapsed: Float, eventTimestampNs: Long, values: FloatArray) {
        val w = writer ?: return
        w.append("$timestamp,$elapsed,$eventTimestampNs")
        for (i in valueColumns.indices) {
            w.append(",${values.getOrNull(i) ?: ""}")
        }
        w.append("\n")
    }
}
