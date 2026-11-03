package com.example.myapplication

import android.content.Context
import java.io.File

class SessionResultLogger(private val context: Context) {

    companion object {
        // dansa_cont / dekobo_cont: 段差継続・でこぼこ継続STARTを1回でも押したらtrue。
        // 継続ボタンは廃止したので、今は常にfalseを書く(過去のセッションと列をそろえるため残している)
        // wheelchair: 使った車椅子(original/standard、未設定なら空)。2026/10末に追加
        // session_kind: セッションの種類(flat/step/rough、未設定なら空)、memo: 自由記述。2026/10/31に追加
        private const val HEADER =
            "session_id,result,reason,started_at_ms,ended_at_ms,duration_ms,weight_kg,dansa_cont,dekobo_cont," +
                "wheelchair,session_kind,memo"
        private const val COLUMN_COUNT = 12
        private const val BASE_COLUMN_COUNT = 7
        // dansa_cont,dekobo_cont までの列数(wheelchairを追加する前の形式)
        private const val CONT_FORMAT_COLUMN_COUNT = 9
        // wheelchair までの列数(session_kind,memoを追加する前の形式)
        private const val WHEELCHAIR_FORMAT_COLUMN_COUNT = 10
        // 一時期のバージョンで使っていた continuous,dansa_cont_count,dekobo_cont_count 形式の列数。
        // 今の形式と列数が同じなので、ヘッダで見分ける
        private const val COUNT_FORMAT_COLUMN_COUNT = 10
        private const val COUNT_FORMAT_HEADER_MARKER = "dansa_cont_count"
    }

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
        weightKg: Float?,
        wheelchair: String?,
        sessionKind: String?,
        memo: String?
    ) {
        val line = buildCsvLine(
            sessionId,
            result,
            reason ?: "",
            startedAt.toString(),
            endedAt.toString(),
            (endedAt - startedAt).toString(),
            weightKg?.toString() ?: "",
            "false",
            "false",
            wheelchair ?: "",
            sessionKind ?: "",
            memo ?: ""
        )
        writeSessionResult(sessionId, line)
        appendIndex(line)
    }

    private fun writeSessionResult(sessionId: String, line: String) {
        val file = File(sessionDir(sessionId), "session_result.csv")
        file.writeText("$HEADER\n$line")
    }

    private fun appendIndex(line: String) {
        val file = File(csvRootDir(), "sessions_index.csv")
        if (!file.exists()) {
            file.writeText("$HEADER\n")
        } else {
            migrateLegacyIndex(file)
        }
        file.appendText(line)
    }

    // 古いバージョンで作られたsessions_index.csvは、ヘッダと列数が揃うよう現在の形式に書き換える
    private fun migrateLegacyIndex(file: File) {
        val lines = file.readLines()
        if (lines.firstOrNull() == HEADER) return

        val isCountFormat = lines.firstOrNull()?.contains(COUNT_FORMAT_HEADER_MARKER) == true
        val migrated = buildString {
            append("$HEADER\n")
            lines.drop(1).filter { it.isNotEmpty() }.forEach {
                append(buildCsvLine(*normalizeRow(parseCsvLine(it), isCountFormat).toTypedArray()))
            }
        }
        file.writeText(migrated)
    }

    private fun normalizeRow(values: List<String>, isCountFormat: Boolean): List<String> {
        val base = values.take(BASE_COLUMN_COUNT)
            .plus(List((BASE_COLUMN_COUNT - values.size).coerceAtLeast(0)) { "" })
        val contFlags = when {
            isCountFormat && values.size == COUNT_FORMAT_COLUMN_COUNT -> values.subList(8, 10).map {
                ((it.toIntOrNull() ?: 0) > 0).toString()
            }
            values.size >= CONT_FORMAT_COLUMN_COUNT ->
                values.subList(BASE_COLUMN_COUNT, CONT_FORMAT_COLUMN_COUNT)
            else -> listOf("", "")
        }
        // その列を追加する前の形式の行は、値が分からないので空にする
        val wheelchair = if (!isCountFormat && values.size >= WHEELCHAIR_FORMAT_COLUMN_COUNT) {
            values[WHEELCHAIR_FORMAT_COLUMN_COUNT - 1]
        } else {
            ""
        }
        val kindAndMemo = if (!isCountFormat && values.size == COLUMN_COUNT) {
            values.subList(WHEELCHAIR_FORMAT_COLUMN_COUNT, COLUMN_COUNT)
        } else {
            listOf("", "")
        }
        return base + contFlags + wheelchair + kindAndMemo
    }

    // buildCsvLineで書いた行(全項目をダブルクォートで囲む形式)を読み戻す
    private fun parseCsvLine(line: String): List<String> {
        val values = mutableListOf<String>()
        val current = StringBuilder()
        var inQuotes = false
        var i = 0
        while (i < line.length) {
            val c = line[i]
            when {
                inQuotes && c == '"' && line.getOrNull(i + 1) == '"' -> {
                    current.append('"')
                    i++
                }
                c == '"' -> inQuotes = !inQuotes
                c == ',' && !inQuotes -> {
                    values.add(current.toString())
                    current.clear()
                }
                else -> current.append(c)
            }
            i++
        }
        values.add(current.toString())
        return values
    }

    private fun buildCsvLine(vararg values: String): String {
        return values.joinToString(",") { escapeCsv(it) } + "\n"
    }

    private fun escapeCsv(value: String): String {
        val escaped = value.replace("\"", "\"\"")
        return "\"$escaped\""
    }
}
