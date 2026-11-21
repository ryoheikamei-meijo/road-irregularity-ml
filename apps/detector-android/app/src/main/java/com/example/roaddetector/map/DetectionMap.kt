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
import org.maplibre.android.style.layers.Property
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.sources.GeoJsonSource

/**
 * MapLibre(OSM のデータ。タイルは BuildConfig.MAP_STYLE_URL)で、判定結果を描く。
 * 何を描くか(GeoJSON)は MapData が作る。Google マップに替えるときは、このクラスだけを差し替える。
 *
 * 重ねる順(下から): 過去の道(灰色) → 今回の道(青) → 凸凹の帯 → 段差のピン → 今の位置
 * - 段差は一瞬なのでピン(赤い丸に階段の絵)、凸凹は続く路面なので帯(濃い縁・黄色・点の模様)。
 *   続いた窓は MapData で 1 つにまとめてある。色だけで伝えないよう、形と絵でも区別する
 * - 地図の土台は灰色の positron(gradle.properties)。道路の黄色・橙と、段差・凸凹の色がぶつからないようにするため
 * - 重なるピンは 1 つだけ出す(同じ段差を続けて通ると、近くにピンが並ぶため)
 * - 地図の地名は、日本語の名前(name:ja)を優先して出す(OpenFreeMap の style は、英語と現地の名前を並べて出すため)
 */
class DetectionMap(mapView: MapView, onReady: (DetectionMap) -> Unit) {
    companion object {
        private const val PAST_LINES = "past-lines"
        private const val LIVE_LINES = "live-lines"
        private const val STEPS = "steps"
        private const val ROUGH = "rough"
        private const val CURRENT = "current"
        private const val IMG_STEP = "pin-step"
        /** 凸凹の帯を描く層(縁・位置が 1 つだけの区間の丸・中・点の模様)。出す・隠すをまとめて切り替える */
        private val ROUGH_LAYERS = listOf("rough-edge", "rough-dot", "rough-fill", "rough-texture")
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

    private fun roundLine(id: String, source: String, colorRes: Int, width: Float) =
        LineLayer(id, source).withProperties(
            PropertyFactory.lineColor(hex(colorRes)), PropertyFactory.lineWidth(width),
            PropertyFactory.lineCap(Property.LINE_CAP_ROUND), PropertyFactory.lineJoin(Property.LINE_JOIN_ROUND))

    private fun addLayers(s: Style) {
        s.addImage(IMG_STEP, bitmap(R.drawable.ic_pin_step, 30))
        for (id in listOf(PAST_LINES, LIVE_LINES, ROUGH, STEPS, CURRENT)) s.addSource(GeoJsonSource(id))
        s.addLayer(roundLine(PAST_LINES, PAST_LINES, R.color.line_past, 5f).withProperties(PropertyFactory.lineOpacity(0.85f)))
        s.addLayer(roundLine(LIVE_LINES, LIVE_LINES, R.color.line_live, 5f).withProperties(PropertyFactory.lineOpacity(0.9f)))

        // 凸凹の帯: 濃い縁(12) → 黄色の中(8) → 点の模様。位置が 1 つだけの区間は、同じ見た目の丸にする
        val onlyLines = Expression.eq(Expression.geometryType(), Expression.literal("LineString"))
        val onlyPoints = Expression.eq(Expression.geometryType(), Expression.literal("Point"))
        s.addLayer(roundLine(ROUGH_LAYERS[0], ROUGH, R.color.rough_edge, 12f).withFilter(onlyLines))
        s.addLayer(CircleLayer(ROUGH_LAYERS[1], ROUGH).withFilter(onlyPoints).withProperties(
            PropertyFactory.circleRadius(5f), PropertyFactory.circleColor(hex(R.color.rough_fill)),
            PropertyFactory.circleStrokeColor(hex(R.color.rough_edge)), PropertyFactory.circleStrokeWidth(2.5f)))
        s.addLayer(roundLine(ROUGH_LAYERS[2], ROUGH, R.color.rough_fill, 8f).withFilter(onlyLines))
        // 長さ 0 の線を丸い端で描くと点になる。間隔は線の太さ(2)の倍数で、6 px ごと
        s.addLayer(roundLine(ROUGH_LAYERS[3], ROUGH, R.color.rough_edge, 2f).withFilter(onlyLines)
            .withProperties(PropertyFactory.lineDasharray(arrayOf(0f, 3f))))

        s.addLayer(SymbolLayer(STEPS, STEPS).withProperties(
            PropertyFactory.iconImage(IMG_STEP),
            PropertyFactory.iconSize(Expression.interpolate(Expression.linear(), Expression.zoom(),
                Expression.stop(12, 0.6f), Expression.stop(16, 0.9f), Expression.stop(19, 1.1f))),
            // 重なるピンは 1 つだけ出す(ほかのピンを隠し、ほかのピンに隠される)。ピンのすぐ下の地名は隠れることがある
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
    fun setSteps(geoJson: String) = set(STEPS, geoJson)
    fun setRough(geoJson: String) = set(ROUGH, geoJson)

    /** 段差のピンを出す・隠す(画面のチップから) */
    fun showSteps(show: Boolean) = setVisible(listOf(STEPS), show)

    /** 凸凹の帯を出す・隠す(画面のチップから) */
    fun showRough(show: Boolean) = setVisible(ROUGH_LAYERS, show)

    private fun setVisible(ids: List<String>, show: Boolean) {
        val s = style ?: return
        for (id in ids) s.getLayer(id)?.setProperties(PropertyFactory.visibility(if (show) Property.VISIBLE else Property.NONE))
    }

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
