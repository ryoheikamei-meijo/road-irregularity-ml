package com.example.roaddetector

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.roaddetector.core.OnnxClassifier
import com.example.roaddetector.map.DetectionMap
import com.example.roaddetector.map.JsonlTail
import com.example.roaddetector.map.MapData
import com.example.roaddetector.map.MapPoint
import com.example.roaddetector.upload.UploadSettings
import com.example.roaddetector.upload.UploadWorker
import org.maplibre.android.MapLibre
import org.maplibre.android.maps.MapView
import java.io.File
import java.util.concurrent.Executors

private const val TAG = "RoadDetector"

/** 送信のオン・オフ(地図の画面と開発用の画面で共通)。入れ直したら、止めた走行のうち送り終えていないものを送る */
fun setUpload(context: Context, on: Boolean) {
    if (UploadSettings.isEnabled(context) == on) return
    UploadSettings.setEnabled(context, on)
    Log.i(TAG, "UPLOAD ${if (on) "on" else "off"}")
    if (on) enqueueIncomplete(context)
}

/** 送り終えていない走行(落ちた・電波が無かった・送信を切っていた)を、送る対象に入れ直す(走行中の分は除く) */
fun enqueueIncomplete(context: Context) {
    if (!UploadSettings.isEnabled(context)) return
    UploadWorker.enqueueIncomplete(context, File(context.getExternalFilesDir(null), "sessions"),
        exclude = LiveStatus.current.dir?.let { File(it) })
}

/**
 * 地図の画面(アプリを開いて最初に出る)。docs/knowledge/2026-11-19/20261119_android_map_plan.md
 *
 * - 地図: 端末に残る判定結果を描く。step・rough の窓を色分けの点、通った道を線(過去の走行は灰色、今の走行は青)、今の位置を青い丸。
 *   走行中は 1 秒ごとに今の走行の detections.jsonl を読み足し、今の位置を追う(指で動かすと追うのをやめ、「現在地」で戻る)。
 * - 判定: 「判定を始める」で DetectionService(フォアグラウンドサービス)を始める。画面を消しても続く。
 * - 「開発用」: DevActivity(詳しい様子・送信のスイッチ・再生)。
 * - adb から(動作確認用): --ei live_s <秒>(その秒数だけ判定)、--ez upload true/false(送信)、--ez replay true(再生。開発用の画面で)
 */
class MainActivity : AppCompatActivity() {
    companion object {
        private const val REQ_PERMISSIONS = 1
        private const val POLL_MS = 1000L
        private const val FOLLOW_ZOOM = 17.0
    }

    private lateinit var mapView: MapView
    private var map: DetectionMap? = null
    private lateinit var labelView: TextView
    private lateinit var countView: TextView
    private lateinit var infoView: TextView
    private lateinit var runButton: Button

    private val ui = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()

    // 以下はメインのスレッドだけで触る
    /** 過去の走行(フォルダ → 位置の付いた窓)。今の走行は含めない */
    private var past: Map<String, List<MapPoint>> = emptyMap()
    private var liveDir: String? = null
    private var liveTail: JsonlTail? = null
    private val live = ArrayList<MapPoint>()
    private var follow = true
    private var cameraSet = false
    private var pastLoaded = false
    private var lastCam: Pair<Double, Double>? = null
    private var message = ""

    /** 位置の権限を求めている間に待たせている、走行の開始(秒数。0 は止めるまで) */
    private var pendingStartS: Int? = null
    private val statusListener: (LiveStatus.Snapshot) -> Unit = { show(it) }
    private val poll = object : Runnable {
        override fun run() { pollLive(); ui.postDelayed(this, POLL_MS) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MapLibre.getInstance(this)
        buildUi(savedInstanceState)
        // 画面の作り直し(回転・メモリの回収のあと)では、起動の指定をもう一度は処理しない(走行を二重に始めないため)
        if (savedInstanceState == null) handleLaunch(intent) else enqueueIncomplete(this)
        if (missingPermissions().isNotEmpty() && pendingStartS == null) requestPermissions()
    }

    /** すでに開いている画面に、adb から指定が届いたとき(launchMode が singleTop) */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLaunch(intent)
    }

    /** 起動の指定(adb からの動作確認用): --ez upload true/false、--ez replay true、--ei live_s <秒> */
    private fun handleLaunch(i: Intent) {
        if (i.hasExtra("upload")) setUpload(this, i.getBooleanExtra("upload", true))
        // 前回、送り終えていない走行を、送る対象に入れ直す
        enqueueIncomplete(this)
        if (i.getBooleanExtra("replay", false)) {
            startActivity(Intent(this, DevActivity::class.java).putExtra(DevActivity.EXTRA_REPLAY, true))
        }
        val liveS = i.getIntExtra("live_s", 0)
        if (liveS > 0 && !LiveStatus.current.running) requestStart(liveS)
    }

    // ===== 画面 =====

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun buildUi(savedInstanceState: Bundle?) {
        val root = FrameLayout(this).apply { fitsSystemWindows = true }
        mapView = MapView(this).apply { onCreate(savedInstanceState) }
        root.addView(mapView, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        fun card() = GradientDrawable().apply { setColor(Color.argb(235, 255, 255, 255)); cornerRadius = dp(12).toFloat() }
        // 上: 今の判定と数、凡例
        val top = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; background = card(); setPadding(dp(14), dp(10), dp(14), dp(10)); elevation = dp(4).toFloat()
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        labelView = TextView(this).apply { textSize = 26f; setTypeface(typeface, Typeface.BOLD); text = "—"; setTextColor(Color.DKGRAY) }
        countView = TextView(this).apply { textSize = 14f; setTextColor(Color.DKGRAY); setPadding(dp(12), 0, 0, 0) }
        row.addView(labelView); row.addView(countView)
        infoView = TextView(this).apply { textSize = 12f; setTextColor(Color.GRAY) }
        top.addView(row); top.addView(TextView(this).apply { textSize = 12f; text = legend() }); top.addView(infoView)
        root.addView(top, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP)
            .apply { setMargins(dp(12), dp(12), dp(12), 0) })

        // 下: 現在地・開始と停止・開発用
        val bottom = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val here = Button(this).apply { text = "現在地"; setOnClickListener { follow = true; lastCam = null; centerOnCurrent() } }
        runButton = Button(this).apply {
            text = "判定を始める"; textSize = 16f
            setOnClickListener { if (LiveStatus.current.running) DetectionService.stop(this@MainActivity) else requestStart(0) }
        }
        val dev = Button(this).apply { text = "開発用"; setOnClickListener { startActivity(Intent(this@MainActivity, DevActivity::class.java)) } }
        bottom.addView(here, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        bottom.addView(runButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(dp(8), 0, dp(8), 0) })
        bottom.addView(dev, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        // 地図の出典の表示(下の端)に重ならないよう、少し上げる
        root.addView(bottom, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM)
            .apply { setMargins(dp(12), 0, dp(12), dp(36)) })
        setContentView(root)

        DetectionMap(mapView) { m ->
            map = m
            m.onUserMoved = { follow = false }
            renderPast(); renderLive(); show(LiveStatus.current); initCamera()
        }
    }

    private fun legend(): CharSequence {
        val b = SpannableStringBuilder()
        fun add(text: String, color: Int) {
            val start = b.length; b.append(text)
            b.setSpan(ForegroundColorSpan(color), start, start + 1, 0)
        }
        add("● step（段差）  ", DetectionMap.STEP_COLOR)
        add("● rough（凸凹）  ", DetectionMap.ROUGH_COLOR)
        add("━ 今の走行  ", DetectionMap.LIVE_COLOR)
        add("━ これまで", Color.rgb(97, 97, 97))
        return b
    }

    private fun show(s: LiveStatus.Snapshot) {
        runButton.text = if (s.running) "判定を止める" else "判定を始める"
        if (s.running) {
            val label = s.label
            labelView.text = if (label == null) "—" else OnnxClassifier.DISPLAY[label]
            labelView.setTextColor(DevActivity.COLORS[label] ?: Color.DKGRAY)
            countView.text = "窓 ${s.windows}（step ${s.steps}・rough ${s.roughs}）"
            val gps = if (s.lat == null) "GPS の位置を待っています。" else ""
            infoView.text = listOf(gps, s.sync, message).filter { it.isNotEmpty() }.joinToString("  ")
        } else {
            labelView.text = "停止中"
            labelView.setTextColor(Color.DKGRAY)
            val all = past.values.flatten()
            countView.text = "これまで ${past.count { it.value.isNotEmpty() }} 走行（step ${all.count { it.cls == "step" }}・rough ${all.count { it.cls == "rough" }}）"
            infoView.text = listOf(if (UploadSettings.isEnabled(this)) "" else "送信: オフ", message).filter { it.isNotEmpty() }.joinToString("  ")
        }
        val m = map ?: return
        if (s.running && s.lat != null && s.lon != null) {
            m.setCurrent(MapData.pointGeoJson(s.lat, s.lon))
            if (follow && lastCam != (s.lat to s.lon)) {
                m.moveTo(s.lat, s.lon, FOLLOW_ZOOM, animate = lastCam != null)
                lastCam = s.lat to s.lon
                cameraSet = true
            }
        } else {
            m.setCurrent(MapData.pointGeoJson(null, null))
        }
    }

    // ===== 地図に載せるデータ =====

    /** 走行中は今の走行のファイルを読み足す。止まったら、今の走行を過去の走行に移す */
    private fun pollLive() {
        val s = LiveStatus.current
        val dir = s.dir
        if (s.running && dir != null) {
            if (dir != liveDir) {
                liveDir = dir; liveTail = JsonlTail(File(dir, "detections.jsonl")); live.clear()
                follow = true; lastCam = null
                renderLive(); loadPast()
            }
            val tail = liveTail ?: return
            io.execute {
                val pts = tail.readNew()
                if (pts.isNotEmpty()) ui.post { if (tail === liveTail) { live += pts; renderLive() } }
            }
        } else if (liveDir != null) {
            liveDir = null; liveTail = null; live.clear()
            renderLive()
            // 判定の残り(止めた直後に書かれる数窓)を待ってから、過去の走行として読み直す
            ui.postDelayed({ loadPast() }, 1500)
        }
    }

    private fun loadPast() {
        val exclude = LiveStatus.current.takeIf { it.running }?.dir
        io.execute {
            val dirs = File(getExternalFilesDir(null), "sessions").listFiles { f -> f.isDirectory }?.sortedBy { it.name } ?: emptyList()
            val loaded = dirs.filter { it.absolutePath != exclude }
                .associate { it.absolutePath to MapData.readFile(File(it, "detections.jsonl")) }
            ui.post {
                past = loaded; pastLoaded = true
                Log.i(TAG, "MAP 過去の走行 ${loaded.size} 本、位置つきの窓 ${loaded.values.sumOf { it.size }}")
                renderPast(); show(LiveStatus.current); initCamera()
            }
        }
    }

    private fun renderPast() {
        val m = map ?: return
        m.setPastLines(MapData.linesGeoJson(past.values))
        renderMarks()
    }

    private fun renderLive() {
        val m = map ?: return
        m.setLiveLines(MapData.linesGeoJson(listOf(live)))
        renderMarks()
    }

    private fun renderMarks() {
        map?.setMarks(MapData.marksGeoJson(past.values.asSequence().flatten() + live.asSequence()))
    }

    /** 最初に 1 回だけ: 走行中なら今の位置、そうでなければ全部の走行が入る範囲、何も無ければ最後に分かっている位置 */
    private fun initCamera() {
        val m = map ?: return
        if (cameraSet || !pastLoaded) return
        val s = LiveStatus.current
        if (s.running && s.lat != null) return  // show() が追う
        val b = MapData.bounds(past.values.asSequence().flatten() + live.asSequence())
        if (b != null) m.fit(b, dp(64)) else centerOnCurrent()
        cameraSet = true
    }

    @SuppressLint("MissingPermission")
    private fun centerOnCurrent() {
        val m = map ?: return
        val s = LiveStatus.current
        if (s.running && s.lat != null && s.lon != null) { m.moveTo(s.lat, s.lon, FOLLOW_ZOOM, animate = true); lastCam = s.lat to s.lon; return }
        val last = if (hasLocation()) {
            val lm = getSystemService(LOCATION_SERVICE) as LocationManager
            listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }.maxByOrNull { it.time }
        } else null
        // 位置が分からなければ、日本の全体
        if (last != null) m.moveTo(last.latitude, last.longitude, 16.0, animate = true) else m.moveTo(36.2, 138.25, 4.5, animate = false)
    }

    // ===== 権限と、走行の開始 =====

    /** 位置は必須(地図に載せるため。Android 14 以降は、無いと位置の種類のフォアグラウンドサービスを始められない)。通知は Android 13 以降で求める */
    private fun missingPermissions(): List<String> {
        val wanted = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        return wanted.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
    }

    private fun hasLocation() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun requestPermissions() {
        ActivityCompat.requestPermissions(this, missingPermissions().toTypedArray(), REQ_PERMISSIONS)
    }

    private fun requestStart(durationS: Int) {
        if (hasLocation()) { message = ""; DetectionService.start(this, durationS); return }
        pendingStartS = durationS
        requestPermissions()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMISSIONS) return
        val start = pendingStartS ?: return
        pendingStartS = null
        if (hasLocation()) { message = ""; DetectionService.start(this, start) }
        else { message = "位置の権限が無いと、判定を始められません（地図に載せるため）。設定から許可してください。"; show(LiveStatus.current) }
    }

    // ===== 地図の部品の生存期間(MapView に渡す) =====

    override fun onStart() {
        super.onStart()
        mapView.onStart()
        LiveStatus.observe(statusListener)
        loadPast()
        ui.post(poll)
    }

    override fun onResume() { super.onResume(); mapView.onResume() }
    override fun onPause() { mapView.onPause(); super.onPause() }

    override fun onStop() {
        ui.removeCallbacks(poll)
        LiveStatus.remove(statusListener)
        mapView.onStop()
        super.onStop()
    }

    override fun onSaveInstanceState(outState: Bundle) { super.onSaveInstanceState(outState); mapView.onSaveInstanceState(outState) }
    override fun onLowMemory() { super.onLowMemory(); mapView.onLowMemory() }

    override fun onDestroy() {
        // 走行はサービスが続ける(画面を閉じても止めない。止めるのはボタンか通知から)
        mapView.onDestroy()
        io.shutdown()
        super.onDestroy()
    }
}
