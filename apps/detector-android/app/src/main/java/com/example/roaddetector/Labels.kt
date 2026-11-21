package com.example.roaddetector

import android.content.Context
import androidx.annotation.ColorRes
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.core.content.ContextCompat

/**
 * 判定の名前・色・印を、画面に出す形にする。利用者向けなので日本語(段差・凸凹・平坦)にする。
 * 受け取る名前は、モデルのクラス(dansa・dekobo・flat)でも、サーバーへ送る名前(step・rough・flat)でもよい。
 * 印は地図と同じ見た目にし、色に加えて形と絵でも区別する(段差は丸いピンに階段、凸凹は点の模様の帯、平坦 ●)。
 * 色だけで伝えないため(デジタル庁デザインシステムの「アクセシビリティ」)。
 */
object Labels {
    private enum class Kind(@StringRes val label: Int, @ColorRes val text: Int, @DrawableRes val icon: Int) {
        STEP(R.string.class_step, R.color.mark_step, R.drawable.ic_pin_step),
        ROUGH(R.string.class_rough, R.color.text_rough, R.drawable.ic_legend_rough),
        FLAT(R.string.class_flat, R.color.text_flat, R.drawable.ic_mark_flat),
    }

    private fun kind(cls: String?): Kind? = when (cls) {
        "dansa", "step" -> Kind.STEP
        "dekobo", "rough" -> Kind.ROUGH
        "flat" -> Kind.FLAT
        else -> null
    }

    fun name(context: Context, cls: String?): String = kind(cls)?.let { context.getString(it.label) } ?: context.getString(R.string.class_none)

    fun textColor(context: Context, cls: String?): Int =
        ContextCompat.getColor(context, kind(cls)?.text ?: R.color.on_surface)

    @DrawableRes
    fun icon(cls: String?): Int? = kind(cls)?.icon
}
