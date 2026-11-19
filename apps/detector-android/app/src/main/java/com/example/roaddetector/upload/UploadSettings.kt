package com.example.roaddetector.upload

import android.content.Context

/**
 * サーバーへ送るかどうか(既定はオン)。本番のサーバーがまだ無いので、実機では切って使う。
 * 切っている間も、判定結果(detections.jsonl)と生データ(input.csv)は端末に残る。入れ直せば、残っている分を送る。
 * (docs/knowledge/2026-11-19/20261119_android_map_plan.md)
 */
object UploadSettings {
    private const val PREFS = "roaddetector"
    private const val KEY = "upload_enabled"

    fun isEnabled(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, true)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY, enabled).apply()
    }
}
