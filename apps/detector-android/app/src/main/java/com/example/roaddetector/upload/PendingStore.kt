package com.example.roaddetector.upload

import java.io.File

/**
 * 判定結果を、端末に 1 行 1 件(JSON)で残す。サーバーに送れた件数は別のファイルに持つ。
 * 通信が切れても、アプリが落ちても、残っている分を次の機会に送れる(サーバーは「走行 ID + 窓の始まり」で重複を弾く)。
 *   detections.jsonl : 判定結果(追記だけ)
 *   detections.sent  : 送れた件数(先頭から数えて)
 *   rejected.jsonl   : サーバーが不正と判断した(400)ので、送らずに退けた判定結果
 */
class PendingStore(dir: File) {
    private val dataFile = File(dir, "detections.jsonl")
    private val sentFile = File(dir, "detections.sent")
    private val sentTmp = File(dir, "detections.sent.tmp")
    private val rejectedFile = File(dir, "rejected.jsonl")

    @Synchronized
    fun append(json: String) {
        require('\n' !in json) { "1 件は 1 行にする" }
        dataFile.appendText(json + "\n")
    }

    @Synchronized
    fun total(): Int = lines().size

    @Synchronized
    fun sentCount(): Int = sentFile.takeIf { it.exists() }?.readText()?.trim()?.toIntOrNull() ?: 0

    @Synchronized
    fun pendingCount(): Int = maxOf(0, total() - sentCount())

    /** まだ送れていない先頭から、最大 max 件 */
    @Synchronized
    fun pending(max: Int): List<String> = lines().drop(sentCount()).take(max)

    /** 先頭から n 件を、送れた(または退けた)ことにする。途中で落ちても壊れないよう、書いてから置き換える */
    @Synchronized
    fun markSent(n: Int) {
        sentTmp.writeText((sentCount() + n).toString())
        check(sentTmp.renameTo(sentFile)) { "送れた件数を更新できない" }
    }

    @Synchronized
    fun reject(line: String) {
        rejectedFile.appendText(line + "\n")
    }

    private fun lines(): List<String> = if (dataFile.exists()) dataFile.readLines().filter { it.isNotBlank() } else emptyList()
}
