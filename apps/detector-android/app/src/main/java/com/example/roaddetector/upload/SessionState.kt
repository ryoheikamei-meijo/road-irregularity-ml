package com.example.roaddetector.upload

import org.json.JSONObject
import java.io.File

/**
 * 走行ごとの情報(session.json)。サーバーに登録できたか、生データを送り終えたかを持つ。
 * id はアプリが作る UUID。再送しても同じ走行として扱われる(冪等)。
 */
class SessionState private constructor(private val file: File, private val json: JSONObject) {
    val id: String get() = json.getString("id")
    val deviceId: String get() = json.getString("device_id")
    val startedAt: String get() = json.getString("started_at")
    val appVersion: String get() = json.getString("app_version")
    val modelVersion: String get() = json.getString("model_version")

    var registered: Boolean
        get() = json.optBoolean("registered", false)
        set(v) { json.put("registered", v); save() }
    var rawDone: Boolean
        get() = json.optBoolean("raw_done", false)
        set(v) { json.put("raw_done", v); save() }

    /** サーバーの POST /sessions の本文 */
    fun registerBody(): String = JSONObject()
        .put("id", id).put("device_id", deviceId).put("started_at", startedAt)
        .put("app_version", appVersion).put("model_version", modelVersion).toString()

    @Synchronized
    private fun save() {
        val tmp = File(file.parentFile, "session.json.tmp")
        tmp.writeText(json.toString())
        check(tmp.renameTo(file)) { "session.json を更新できない" }
    }

    companion object {
        const val FILE_NAME = "session.json"

        fun create(dir: File, id: String, deviceId: String, startedAt: String, appVersion: String, modelVersion: String): SessionState {
            val json = JSONObject().put("id", id).put("device_id", deviceId).put("started_at", startedAt)
                .put("app_version", appVersion).put("model_version", modelVersion)
                .put("registered", false).put("raw_done", false)
            return SessionState(File(dir, FILE_NAME), json).also { it.save() }
        }

        fun load(dir: File): SessionState? {
            val f = File(dir, FILE_NAME)
            return if (f.isFile) runCatching { SessionState(f, JSONObject(f.readText())) }.getOrNull() else null
        }
    }
}
