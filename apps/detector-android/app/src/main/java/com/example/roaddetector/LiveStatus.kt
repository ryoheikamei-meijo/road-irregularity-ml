package com.example.roaddetector

import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArraySet

/**
 * 走行中の判定の様子を、サービス(DetectionService)から画面(MainActivity)へ渡す。
 * 画面が閉じていても、サービスは書き続ける。画面は開いたときに最新の値を受け取る。
 */
object LiveStatus {
    data class Snapshot(
        val running: Boolean = false,
        /** 最新の判定(モデルのクラス名 flat・dansa・dekobo)と、決定関数の値 */
        val label: String? = null,
        val scores: FloatArray? = null,
        val stats: String = "",
        /** この走行の窓の数と、そのうち step(dansa)・rough(dekobo)の数 */
        val windows: Int = 0,
        val steps: Int = 0,
        val roughs: Int = 0,
        /** 最新の GPS の位置(地図の今の位置)。まだ無ければ null */
        val lat: Double? = null,
        val lon: Double? = null,
        val sync: String = "",
        /** 走行中のセッションのフォルダ */
        val dir: String? = null,
        val message: String = "",
    )

    @Volatile
    var current = Snapshot()
        private set

    private val listeners = CopyOnWriteArraySet<(Snapshot) -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    /** どのスレッドから呼んでもよい。画面への通知は、メインのスレッドで行う */
    fun update(change: (Snapshot) -> Snapshot) {
        val s = synchronized(this) { change(current).also { current = it } }
        main.post { listeners.forEach { it(s) } }
    }

    /** メインのスレッドで呼ぶ。すぐに今の値を 1 回渡す */
    fun observe(listener: (Snapshot) -> Unit) {
        listeners += listener
        listener(current)
    }

    fun remove(listener: (Snapshot) -> Unit) {
        listeners -= listener
    }
}
