package com.example.roaddetector.map

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.annotation.DrawableRes
import androidx.core.content.ContextCompat
import com.example.roaddetector.BuildConfig
import com.example.roaddetector.R
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
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.sources.GeoJsonSource

/**
 * MapLibre(OSM のデータ。タイルは BuildConfig.MAP_STYLE_URL)で、判定結果を描く。
 * 何を描くか(GeoJSON)は MapData が作る。Google マップに替えるときは、このクラスだけを差し替える。
 *
 * 重ねる順(下から): 過去の道(灰色) → 今回の道(青) → 段差 ▲・凸凹 ◆ の印 → 今の位置
 * - 印は色に加えて形で区別する(色だけで伝えない)。重なる印は 1 つだけ出す(窓は約 0.5 m ごとで、1 つの段差で数窓が続くため)
 * - 地図の地名は、日本語の名前(name:ja)を優先して出す(OpenFreeMap の liberty は、英語と現地の名前を並べて出すため)
 */
class DetectionMap(mapView: MapView, onReady: (DetectionMap) -> Unit) {
    companion object {
        private const val PAST_LINES = "past-lines"
        private const val LIVE_LINES = "live-lines"
        private const val MARKS = "marks"
        private const val CURRENT = "current"
        private const val IMG_STEP = "mark-step"
        private const val IMG_ROUGH = "mark-rough"
    }

    private val context: Context = mapView.context
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
                useJapaneseNames(s)
                addLayers(s)
                onReady(this)
            }
        }
    }

    private fun color(id: Int) = ContextCompat.getColor(context, id)
    private fun hex(id: Int) = String.format("#%06X", 0xFFFFFF and color(id))

    private fun bitmap(@DrawableRes id: Int, sizeDp: Int): Bitmap {
        val px = (sizeDp * context.resources.displayMetrics.density).toInt()
        val d = ContextCompat.getDrawable(context, id)!!
        return Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888).also { b ->
            d.setBounds(0, 0, px, px); d.draw(Canvas(b))
        }
    }

    /** 地名を出す層を、日本語の名前 → 現地の名前 の順で出すように替える(道路の番号など、名前でない層はそのまま) */
    private fun useJapaneseNames(s: Style) {
        for (layer in s.layers) {
            if (layer !is SymbolLayer) continue
            val expr = layer.textField.expression?.toString() ?: continue
            if ("name" !in expr) continue
            layer.setProperties(PropertyFactory.textField(Expression.coalesce(Expression.get("name:ja"), Expression.get("name"))))
        }
    }

    private fun addLayers(s: Style) {
        s.addImage(IMG_STEP, bitmap(R.drawable.ic_mark_step, 22))
        s.addImage(IMG_ROUGH, bitmap(R.drawable.ic_mark_rough, 22))
        for (id in listOf(PAST_LINES, LIVE_LINES, MARKS, CURRENT)) s.addSource(GeoJsonSource(id))
        s.addLayer(LineLayer(PAST_LINES, PAST_LINES).withProperties(
            PropertyFactory.lineColor(hex(R.color.line_past)), PropertyFactory.lineWidth(4f), PropertyFactory.lineOpacity(0.7f),
            PropertyFactory.lineCap("round"), PropertyFactory.lineJoin("round")))
        s.addLayer(LineLayer(LIVE_LINES, LIVE_LINES).withProperties(
            PropertyFactory.lineColor(hex(R.color.line_live)), PropertyFactory.lineWidth(5f), PropertyFactory.lineOpacity(0.85f),
            PropertyFactory.lineCap("round"), PropertyFactory.lineJoin("round")))
        s.addLayer(SymbolLayer(MARKS, MARKS).withProperties(
            PropertyFactory.iconImage(Expression.match(Expression.get("class"), Expression.literal(IMG_ROUGH),
                Expression.stop("step", Expression.literal(IMG_STEP)))),
            PropertyFactory.iconSize(Expression.interpolate(Expression.linear(), Expression.zoom(),
                Expression.stop(12, 0.6f), Expression.stop(16, 0.9f), Expression.stop(19, 1.2f))),
            // 重なる印は 1 つだけ出す(ほかの印を隠し、ほかの印に隠される)。印のすぐ下の地名は隠れることがある
            PropertyFactory.iconAllowOverlap(false), PropertyFactory.iconIgnorePlacement(false)))
        s.addLayer(CircleLayer(CURRENT, CURRENT).withProperties(
            PropertyFactory.circleRadius(9f), PropertyFactory.circleColor(Expression.color(color(R.color.line_live))),
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

    /** bounds は MapData.bounds の形(minLat, minLon, maxLat, maxLon)。上下は、画面に重ねたカードとボタンの分をあける */
    fun fit(bounds: DoubleArray, top: Int, bottom: Int, side: Int) {
        val m = map ?: return
        if (bounds[0] == bounds[2] && bounds[1] == bounds[3]) { moveTo(bounds[0], bounds[1], 17.0, false); return }
        val b = LatLngBounds.Builder().include(LatLng(bounds[0], bounds[1])).include(LatLng(bounds[2], bounds[3])).build()
        m.moveCamera(CameraUpdateFactory.newLatLngBounds(b, side, top, side, bottom))
    }
}
