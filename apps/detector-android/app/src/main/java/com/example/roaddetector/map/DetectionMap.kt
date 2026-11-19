package com.example.roaddetector.map

import android.graphics.Color
import com.example.roaddetector.BuildConfig
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.sources.GeoJsonSource

/**
 * MapLibre(OSM のデータ。タイルは BuildConfig.MAP_STYLE_URL)で、判定結果を描く。
 * 何を描くか(GeoJSON)は MapData が作る。Google マップに替えるときは、このクラスだけを差し替える。
 *
 * 重ねる順(下から): 過去の走行の道(灰色) → 今の走行の道(青) → step・rough の点 → 今の位置
 */
class DetectionMap(mapView: MapView, onReady: (DetectionMap) -> Unit) {
    companion object {
        val STEP_COLOR = Color.rgb(198, 40, 40)
        val ROUGH_COLOR = Color.rgb(239, 108, 0)
        val LIVE_COLOR = Color.rgb(30, 136, 229)
        private const val PAST_LINES = "past-lines"
        private const val LIVE_LINES = "live-lines"
        private const val MARKS = "marks"
        private const val CURRENT = "current"
    }

    private var map: MapLibreMap? = null
    private var style: Style? = null

    /** 利用者が地図を指で動かしたとき(今の位置を追うのをやめるため) */
    var onUserMoved: () -> Unit = {}

    init {
        mapView.getMapAsync { m ->
            map = m
            m.uiSettings.isRotateGesturesEnabled = false
            m.uiSettings.isTiltGesturesEnabled = false
            m.addOnCameraMoveStartedListener { reason ->
                if (reason == MapLibreMap.OnCameraMoveStartedListener.REASON_API_GESTURE) onUserMoved()
            }
            m.setStyle(Style.Builder().fromUri(BuildConfig.MAP_STYLE_URL)) { s ->
                style = s
                addLayers(s)
                onReady(this)
            }
        }
    }

    private fun addLayers(s: Style) {
        for (id in listOf(PAST_LINES, LIVE_LINES, MARKS, CURRENT)) s.addSource(GeoJsonSource(id))
        s.addLayer(LineLayer(PAST_LINES, PAST_LINES).withProperties(
            PropertyFactory.lineColor("#616161"), PropertyFactory.lineWidth(3f), PropertyFactory.lineOpacity(0.6f),
            PropertyFactory.lineCap("round"), PropertyFactory.lineJoin("round")))
        s.addLayer(LineLayer(LIVE_LINES, LIVE_LINES).withProperties(
            PropertyFactory.lineColor(hex(LIVE_COLOR)), PropertyFactory.lineWidth(4f), PropertyFactory.lineOpacity(0.8f),
            PropertyFactory.lineCap("round"), PropertyFactory.lineJoin("round")))
        // 窓は 0.5 秒(約 0.5 m)ごとで、1 つの段差で数窓が続けて step になり、点が重なる。
        // 縁取りを付けると、重なった点の縁が白い弧になって見づらいので、縁取りは付けず、少し透かす。大きさは拡大の具合に合わせる
        s.addLayer(CircleLayer(MARKS, MARKS).withProperties(
            PropertyFactory.circleRadius(Expression.interpolate(Expression.linear(), Expression.zoom(),
                Expression.stop(12, 2.5f), Expression.stop(16, 4.5f), Expression.stop(19, 8f))),
            PropertyFactory.circleColor(Expression.match(Expression.get("class"), Expression.color(Color.GRAY),
                Expression.stop("step", Expression.color(STEP_COLOR)), Expression.stop("rough", Expression.color(ROUGH_COLOR)))),
            PropertyFactory.circleOpacity(0.85f)))
        s.addLayer(CircleLayer(CURRENT, CURRENT).withProperties(
            PropertyFactory.circleRadius(8f), PropertyFactory.circleColor(Expression.color(LIVE_COLOR)),
            PropertyFactory.circleStrokeColor("#FFFFFF"), PropertyFactory.circleStrokeWidth(3f)))
    }

    private fun set(id: String, geoJson: String) {
        style?.getSourceAs<GeoJsonSource>(id)?.setGeoJson(geoJson)
    }

    fun setPastLines(geoJson: String) = set(PAST_LINES, geoJson)
    fun setLiveLines(geoJson: String) = set(LIVE_LINES, geoJson)
    fun setMarks(geoJson: String) = set(MARKS, geoJson)
    fun setCurrent(geoJson: String) = set(CURRENT, geoJson)

    fun moveTo(lat: Double, lon: Double, zoom: Double, animate: Boolean) {
        val m = map ?: return
        val u = CameraUpdateFactory.newLatLngZoom(LatLng(lat, lon), zoom)
        if (animate) m.animateCamera(u) else m.moveCamera(u)
    }

    /** bounds は MapData.bounds の形(minLat, minLon, maxLat, maxLon) */
    fun fit(bounds: DoubleArray, paddingPx: Int) {
        val m = map ?: return
        if (bounds[0] == bounds[2] && bounds[1] == bounds[3]) { moveTo(bounds[0], bounds[1], 17.0, false); return }
        val b = LatLngBounds.Builder().include(LatLng(bounds[0], bounds[1])).include(LatLng(bounds[2], bounds[3])).build()
        m.moveCamera(CameraUpdateFactory.newLatLngBounds(b, paddingPx))
    }

    private fun hex(c: Int) = String.format("#%06X", 0xFFFFFF and c)
}
