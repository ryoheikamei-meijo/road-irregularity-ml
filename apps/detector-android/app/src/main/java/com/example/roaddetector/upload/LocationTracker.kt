package com.example.roaddetector.upload

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import androidx.core.content.ContextCompat

/** GPS の位置を 1 秒ごとに受け取り、判定結果に付ける。位置が古すぎるときは付けない。受け取るたびに onFix を呼ぶ(地図の今の位置) */
class LocationTracker(private val context: Context, private val onFix: (Fix) -> Unit = {}) : LocationListener {
    companion object {
        /** 窓の判定時刻と位置を取った時刻が、これより離れていたら位置は付けない(研究の PC 側の送信と同じ 5 秒) */
        const val MAX_AGE_MS = 5_000L
    }

    @Volatile
    private var latest: Fix? = null
    private val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    fun start(looper: Looper): Boolean {
        if (!hasPermission() || !manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) return false
        latest = null
        manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, this, looper)
        return true
    }

    fun stop() {
        manager.removeUpdates(this)
    }

    /** nowWallMs(壁時計)の時点で使える位置。無い・古いときは null */
    fun fixFor(nowWallMs: Long): Fix? = latest?.takeIf { kotlin.math.abs(nowWallMs - it.wallMs) <= MAX_AGE_MS }

    override fun onLocationChanged(location: Location) {
        val f = Fix(location.latitude, location.longitude, if (location.hasAccuracy()) location.accuracy else null, location.time)
        latest = f
        onFix(f)
    }

    // API 30 未満では、次の 3 つが抽象メソッドのまま。実装しないと実行時に落ちる
    @Deprecated("API 29 まで")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {}
}
