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
