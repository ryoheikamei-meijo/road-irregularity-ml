package com.example.roaddetector.upload

import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

/**
 * 1 つの走行を、サーバーに送って同期する。通信の失敗や 5xx では、残して false を返す(次の機会にやり直す。何度送っても二重にならない)。
 *   1. 走行の登録(POST /sessions)
 *   2. 判定結果(POST /sessions/:id/detections)。端末に残した分を、先頭から送れた分だけ進める
 *   3. 生データ: 署名付き URL を受け取り(raw-upload-url)、ファイルを直接 PUT して、完了を通知する(raw-complete)
 * 判定結果は走行中に何度も呼ぶ(どの回線でも)。生データは走行後、Wi-Fi のとき(UploadWorker)。
 */
class SessionSync(
    private val state: SessionState,
    private val store: PendingStore,
    private val api: ApiClient,
    private val rawFile: File,
    private val log: (String) -> Unit = {},
) {
    companion object {
        const val MAX_BATCH = 500  // サーバーの上限は 2000

        // 同じ走行を、走行中の送信と UploadWorker が同時に動かさないようにする
        private val locks = ConcurrentHashMap<String, Any>()
    }

    private val lock: Any get() = locks.getOrPut(state.id) { Any() }

    fun syncAll(): Boolean = synchronized(lock) { flushDetectionsLocked() && uploadRawLocked() }

    /** 残っている判定結果を全部送れたら true */
    fun flushDetections(): Boolean = synchronized(lock) { flushDetectionsLocked() }

    fun uploadRaw(): Boolean = synchronized(lock) { uploadRawLocked() }

    private fun call(path: String, json: String): ApiClient.Response? =
        try { api.postJson(path, json) } catch (e: IOException) { log("通信できない: $path ${e.message}"); null }

    private fun registerLocked(): Boolean {
        if (state.registered) return true
        val r = call("/sessions", state.registerBody()) ?: return false
        return when (r.code) {
            200, 201 -> { state.registered = true; true }
            else -> { log("走行を登録できない: ${r.code} ${r.body}"); false }
        }
    }

    private fun flushDetectionsLocked(): Boolean {
        var reRegistered = false
        while (true) {
            val batch = store.pending(MAX_BATCH)
            if (batch.isEmpty()) return true
            if (!registerLocked()) return false
            val r = call("/sessions/${state.id}/detections", """{"detections":[${batch.joinToString(",")}]}""") ?: return false
            when (r.code) {
                200 -> store.markSent(batch.size)
                // サーバーの DB が作り直されたなど。1 回だけ登録をやり直す
                404 -> {
                    if (reRegistered) return false
                    reRegistered = true
                    state.registered = false
                }
                // 1 件でも不正だと、バッチ全体が 400 になる。1 件ずつ送り直して、不正な 1 件だけを退ける
                400 -> if (!isolate(batch)) return false
                else -> { log("判定結果を送れない: ${r.code} ${r.body}"); return false }
            }
        }
    }

    private fun isolate(batch: List<String>): Boolean {
        for (line in batch) {
            val r = call("/sessions/${state.id}/detections", """{"detections":[$line]}""") ?: return false
            when (r.code) {
                200 -> store.markSent(1)
                400 -> { log("不正な判定結果を退けた: ${r.body}"); store.reject(line); store.markSent(1) }
                else -> return false
            }
        }
        return true
    }

    private fun uploadRawLocked(): Boolean {
        if (state.rawDone) return true
        if (!rawFile.isFile) { log("生データが無い: $rawFile"); return true }
        if (!registerLocked()) return false
        val size = rawFile.length()
        val sha256 = sha256Hex(rawFile)
        val urlRes = call("/sessions/${state.id}/raw-upload-url", "{}") ?: return false
        if (urlRes.code != 200) { log("署名付き URL を受け取れない: ${urlRes.code} ${urlRes.body}"); return false }
        val url = JSONObject(urlRes.body).getString("url")
        val putCode = try { api.putFile(url, rawFile) } catch (e: IOException) { log("生データの PUT に失敗: ${e.message}"); return false }
        if (putCode != 200) { log("生データの PUT が $putCode"); return false }
        val done = call("/sessions/${state.id}/raw-complete", JSONObject().put("size_bytes", size).put("sha256", sha256).toString())
            ?: return false
        if (done.code != 200) { log("完了を通知できない: ${done.code} ${done.body}"); return false }
        state.rawDone = true
        return true
    }

    private fun sha256Hex(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) { val n = input.read(buf); if (n < 0) break; md.update(buf, 0, n) }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
