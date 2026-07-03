package com.example.myapplication

import android.content.Context
import java.io.File

class SessionResultLogger(private val context: Context) {

    private fun csvRootDir(): File {
        val dir = File(context.getExternalFilesDir(null), "csv")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    private fun sessionDir(sessionId: String): File {
        val dir = File(csvRootDir(), sessionId)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    @Synchronized
    fun appendResult(
        sessionId: String,
        result: String,
        reason: String?,
        startedAt: Long,
        endedAt: Long,
        weightKg: Float?
    ) {
        val durationMs = endedAt - startedAt
        writeSessionResult(sessionId, result, reason, startedAt, endedAt, durationMs, weightKg)
        appendIndex(sessionId, result, reason, startedAt, endedAt, durationMs, weightKg)
    }

    private fun writeSessionResult(
        sessionId: String,
        result: String,
        reason: String?,
        startedAt: Long,
        endedAt: Long,
        durationMs: Long,
        weightKg: Float?
    ) {
        val file = File(sessionDir(sessionId), "session_result.csv")
        file.writeText(
            buildString {
                append("session_id,result,reason,started_at_ms,ended_at_ms,duration_ms,weight_kg\n")
                append(
                    buildCsvLine(
                        sessionId,
                        result,
                        reason ?: "",
                        startedAt.toString(),
                        endedAt.toString(),
                        durationMs.toString(),
                        weightKg?.toString() ?: ""
                    )
                )
            }
        )
    }

    private fun appendIndex(
        sessionId: String,
        result: String,
        reason: String?,
        startedAt: Long,
        endedAt: Long,
        durationMs: Long,
        weightKg: Float?
    ) {
        val file = File(csvRootDir(), "sessions_index.csv")
        if (!file.exists()) {
            file.writeText("session_id,result,reason,started_at_ms,ended_at_ms,duration_ms,weight_kg\n")
        }

        file.appendText(
            buildCsvLine(
                sessionId,
                result,
                reason ?: "",
                startedAt.toString(),
                endedAt.toString(),
                durationMs.toString(),
                weightKg?.toString() ?: ""
            )
        )
    }

    private fun buildCsvLine(vararg values: String): String {
        return values.joinToString(",") { escapeCsv(it) } + "\n"
    }

    private fun escapeCsv(value: String): String {
        val escaped = value.replace("\"", "\"\"")
        return "\"$escaped\""
    }
}
