package com.example.roaddetector.upload

import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** サーバー(apps/server)への HTTP。ネットワークの失敗(つながらない・切れた)は IOException で伝える。 */
interface ApiClient {
    class Response(val code: Int, val body: String)

    fun postJson(path: String, json: String): Response

    /** 署名付き URL へファイルを PUT する。HTTP のステータスを返す(API は通さない。Lambda は 6 MB を超えて受けられない) */
    fun putFile(url: String, file: File): Int
}

class HttpApiClient(private val baseUrl: String, private val apiKey: String) : ApiClient {
    override fun postJson(path: String, json: String): ApiClient.Response {
        val conn = URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 10_000
            conn.readTimeout = 30_000
            conn.doOutput = true
            conn.setRequestProperty("content-type", "application/json")
            conn.setRequestProperty("x-api-key", apiKey)
            val bytes = json.toByteArray(Charsets.UTF_8)
            conn.setFixedLengthStreamingMode(bytes.size)
            conn.outputStream.use { it.write(bytes) }
            val code = conn.responseCode
            val stream = if (code >= 400) conn.errorStream else conn.inputStream
            return ApiClient.Response(code, stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: "")
        } finally {
            conn.disconnect()
        }
    }

    override fun putFile(url: String, file: File): Int {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "PUT"
            conn.connectTimeout = 10_000
            conn.readTimeout = 120_000
            conn.doOutput = true
            // ファイル全体をメモリに載せず、そのまま流す(50〜160 MB になる)
            conn.setFixedLengthStreamingMode(file.length())
            file.inputStream().use { input -> conn.outputStream.use { input.copyTo(it, 64 * 1024) } }
            val code = conn.responseCode
            (if (code >= 400) conn.errorStream else conn.inputStream)?.close()
            return code
        } catch (e: IOException) {
            throw e
        } finally {
            conn.disconnect()
        }
    }
}
