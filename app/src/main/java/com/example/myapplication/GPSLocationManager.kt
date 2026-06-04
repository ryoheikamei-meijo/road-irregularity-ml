package com.example.myapplication

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import androidx.core.app.ActivityCompat

class GPSLocationManager(private val context: Context) {

    private val locationManager =
        context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    private var currentLocation: Location? = null

    private val locationListener = LocationListener { location ->
        currentLocation = location
    }

    @SuppressLint("MissingPermission")
    fun startLocationUpdates() {

        if (ActivityCompat.checkSelfPermission(
                context,
                Manifest.permission.ACCESS_FINE_LOCATION
            ) != PackageManager.PERMISSION_GRANTED
        ) return

        locationManager.requestLocationUpdates(
            LocationManager.GPS_PROVIDER,
            1000L,
            0f,
            locationListener
        )
    }

    fun getCurrentLocation(): Location? {
        return currentLocation
    }

    fun stopLocationUpdates() {
        locationManager.removeUpdates(locationListener)
    }
}
