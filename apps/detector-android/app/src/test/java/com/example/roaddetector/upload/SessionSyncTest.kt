package com.example.roaddetector.upload

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.security.MessageDigest

/** サーバー(apps/server)の動きを真似た偽のサーバー: 走行の登録、(走行, 窓の始まり)での重複の排除、400、404、署名付き URL への PUT */
private class FakeServer : ApiClient {
    val sessions = mutableSetOf<String>()
    val detections = linkedMapOf<Pair<String, Long>, JSONObject>()  // 保存された判定結果(重複は入らない)
    var putBytes: ByteArray? = null
    var completed: JSONObject? = null

    var down = false                 // true の間は、通信できない(IOException)
    var dropResponses = 0            // 保存はしたが、返事が届かなかった回数(再送で二重にならないことの確認)
    var putStatus = 200
    var requests = 0

    override fun postJson(path: String, json: String): ApiClient.Response {
        requests++
        if (down) throw IOException("つながらない")
        val parts = path.trim('/').split('/')
        val res = when {
            parts == listOf("sessions") -> {
                val id = JSONObject(json).getString("id")
                if (sessions.add(id)) ApiClient.Response(201, "{}") else ApiClient.Response(200, "{}")
            }
            parts.size == 3 && parts[2] == "detections" -> {
                if (parts[1] !in sessions) return ApiClient.Response(404, """{"error":"session_not_found"}""")
                val arr = JSONObject(json).getJSONArray("detections")
                val items = (0 until arr.length()).map { arr.getJSONObject(it) }
                // 1 件でも不正(class が flat/step/rough 以外)なら、バッチ全体が 400(サーバーの Zod と同じ)
                if (items.any { it.getString("class") !in setOf("flat", "step", "rough") }) return ApiClient.Response(400, """{"error":"validation"}""")
                for (d in items) detections.putIfAbsent(parts[1] to d.getLong("window_start_ms"), d)
                ApiClient.Response(200, "{}")
            }
            parts.size == 3 && parts[2] == "raw-upload-url" -> ApiClient.Response(200, """{"url":"http://storage.test/put","key":"k"}""")
            parts.size == 3 && parts[2] == "raw-complete" -> { completed = JSONObject(json); ApiClient.Response(200, "{}") }
            else -> ApiClient.Response(500, "?")
        }
        if (dropResponses > 0) { dropResponses--; throw IOException("返事が届かない") }
        return res
    }

    override fun putFile(url: String, file: File): Int {
        requests++
        if (down) throw IOException("つながらない")
        putBytes = file.readBytes()
        return putStatus
    }
}

class SessionSyncTest {
    private lateinit var dir: File
    private lateinit var server: FakeServer
    private lateinit var store: PendingStore
    private lateinit var state: SessionState
    private lateinit var sync: SessionSync
    private val logs = mutableListOf<String>()

    private fun record(startMs: Long, cls: String = "flat", fix: Fix? = Fix(35.18, 136.90, 6f, startMs + 1000)) =
        DetectionRecord(startMs, 1_793_000_000_000L + startMs, 2.0, cls, mapOf("flat" to 1.0, "step" to -0.5, "rough" to -0.7), fix).toJson()

    @Before fun setUp() {
        dir = Files.createTempDirectory("sync").toFile()
        server = FakeServer()
        store = PendingStore(dir)
        state = SessionState.create(dir, "11111111-2222-3333-4444-555555555555", "dev-1", "2026-11-18T14:00:00+09:00", "0.1.0", "v4_20261118")
        File(dir, "input.csv").writeText("timestamp,accX\n1,2\n3,4\n")
        sync = SessionSync(state, store, server, File(dir, "input.csv")) { logs += it }
    }

    @After fun tearDown() { dir.deleteRecursively() }

    @Test fun `登録して判定結果を送り、送れた件数が進む`() {
        for (i in 0 until 5) store.append(record(i * 500L))
        assertTrue(sync.flushDetections())
        assertEquals(5, server.detections.size)
        assertEquals(5, store.sentCount()); assertEquals(0, store.pendingCount())
        assertTrue(state.registered)
        assertEquals(1, server.sessions.size)
    }

    @Test fun `送るものが無いときは、通信しない`() {
        assertTrue(sync.flushDetections())
        assertEquals(0, server.requests)
    }

    @Test fun `通信できないときは残し、つながったら続きから送る`() {
        for (i in 0 until 3) store.append(record(i * 500L))
        server.down = true
        assertFalse(sync.flushDetections())
        assertEquals(3, store.pendingCount()); assertEquals(0, server.detections.size)
        store.append(record(1500L))   // つながらない間も判定は続く
        server.down = false
        assertTrue(sync.flushDetections())
        assertEquals(4, server.detections.size)
        assertEquals(0, store.pendingCount())
    }

    @Test fun `保存されたが返事が届かなかったバッチを再送しても、二重にならない`() {
        for (i in 0 until 4) store.append(record(i * 500L))
        server.dropResponses = 2         // 登録の返事と、判定結果の返事が届かない
        assertFalse(sync.flushDetections())
        assertFalse(sync.flushDetections())
        assertEquals(4, store.pendingCount())   // 端末は送れたと知らないので、残している
        assertTrue(sync.flushDetections())
        assertEquals(4, server.detections.size) // サーバーには 1 件ずつだけ
    }

    @Test fun `バッチの上限を超える分は、何回かに分けて送る`() {
        val n = SessionSync.MAX_BATCH * 2 + 7
        for (i in 0 until n) store.append(record(i * 500L))
        assertTrue(sync.flushDetections())
        assertEquals(n, server.detections.size)
    }

    @Test fun `不正な 1 件だけを退け、残りは送る`() {
        store.append(record(0)); store.append(record(500, cls = "bump")); store.append(record(1000))
        assertTrue(sync.flushDetections())
        assertEquals(setOf(0L, 1000L), server.detections.keys.map { it.second }.toSet())
        assertEquals(0, store.pendingCount())
        assertEquals(1, File(dir, "rejected.jsonl").readLines().size)
    }

    @Test fun `サーバーが走行を忘れていたら(404)、登録し直して送る`() {
        store.append(record(0))
        assertTrue(sync.flushDetections())
        server.sessions.clear(); server.detections.clear()   // サーバーの DB が作り直された
        store.append(record(500))
        assertTrue(sync.flushDetections())
        assertEquals(setOf(500L), server.detections.keys.map { it.second }.toSet())
        assertEquals(1, server.sessions.size)
    }

    @Test fun `端末を再起動しても、送れた件数が残っている`() {
        for (i in 0 until 3) store.append(record(i * 500L))
        assertTrue(sync.flushDetections())
        store.append(record(1500L))
        val reopened = PendingStore(dir)
        assertEquals(3, reopened.sentCount()); assertEquals(listOf(record(1500L)), reopened.pending(10))
        val loaded = SessionState.load(dir)!!
        assertEquals(state.id, loaded.id); assertTrue(loaded.registered); assertFalse(loaded.rawDone)
    }

    @Test fun `生データは署名付き URL に PUT し、大きさとハッシュを通知する`() {
        assertTrue(sync.uploadRaw())
        assertEquals(File(dir, "input.csv").readText(), String(server.putBytes!!))
        val c = server.completed!!
        assertEquals(File(dir, "input.csv").length(), c.getLong("size_bytes"))
        assertEquals(MessageDigest.getInstance("SHA-256").digest(File(dir, "input.csv").readBytes()).joinToString("") { "%02x".format(it) }, c.getString("sha256"))
        assertTrue(state.rawDone)
        val before = server.requests
        assertTrue(sync.uploadRaw())        // 送り終えた走行は、もう通信しない
        assertEquals(before, server.requests)
    }

    @Test fun `生データの PUT に失敗したら、完了にせず、やり直せる`() {
        server.putStatus = 500
        assertFalse(sync.uploadRaw()); assertFalse(state.rawDone); assertNull(server.completed)
        server.putStatus = 200
        assertTrue(sync.uploadRaw()); assertTrue(state.rawDone)
    }

    @Test fun `syncAll は判定結果と生データの両方を送る`() {
        store.append(record(0))
        assertTrue(sync.syncAll())
        assertEquals(1, server.detections.size); assertTrue(state.rawDone)
    }
}
