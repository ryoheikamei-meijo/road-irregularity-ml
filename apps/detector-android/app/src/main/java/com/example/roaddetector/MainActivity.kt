package com.example.roaddetector

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updateLayoutParams
import com.example.roaddetector.map.DetectionMap
import com.example.roaddetector.map.JsonlTail
import com.example.roaddetector.map.MapData
import com.example.roaddetector.map.MapEvent
import com.example.roaddetector.map.MapPoint
import com.example.roaddetector.upload.UploadSettings
import com.example.roaddetector.upload.UploadWorker
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.floatingactionbutton.ExtendedFloatingActionButton
import com.google.android.material.snackbar.Snackbar
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
 * 見た目は Material Design 3 の部品で作り、文字・色・ボタンはデジタル庁デザインシステムを参考にする(layout/activity_main.xml)。
 *
 * - 地図: 端末に残る判定結果を描く。段差はピン、凸凹は帯(続いた判定を 1 つにまとめる。MapData)、
 *   通った道の線(今回は青、これまでは灰色)、現在地(Google マップと同じく、青い丸・精度の円・向き。止まっていても出す)。
 *   走行中は 1 秒ごとに今の走行の detections.jsonl を読み足し、今の位置を追う(指で動かすと追うのをやめ、「現在地」で戻る)。
 * - カードの下のチップ: 段差・凸凹の数(か所・区間)を出し、押すと地図に出す・隠すを切り替える(凡例を兼ねる)。
 * - 判定: 「判定を始める」で DetectionService(フォアグラウンドサービス)を始める。画面を消しても続く。
 *   位置の権限が無いときは、先に日本語で理由を説明してから、OS の許可の画面を出す(OS の画面は端末の言語で出る)。
 * - 「開発用」: DevActivity(決定関数の値・送信のスイッチ・再生)。
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
    private lateinit var top: View
    private lateinit var chipStep: Chip
    private lateinit var chipRough: Chip
    private lateinit var bottom: View
    private lateinit var statusView: TextView
    private lateinit var resultRow: View
    private lateinit var resultIcon: ImageView
    private lateinit var resultView: TextView
    private lateinit var countView: TextView
    private lateinit var infoView: TextView
    private lateinit var runButton: ExtendedFloatingActionButton

    private val ui = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()

    // 以下はメインのスレッドだけで触る
    /** 過去の走行(フォルダ → 位置の付いた窓)。今の走行は含めない */
    private var past: Map<String, List<MapPoint>> = emptyMap()
    /** past・live から作った、段差・凸凹のまとまり */
    private var pastEvents: List<MapEvent> = emptyList()
    private var liveEvents: List<MapEvent> = emptyList()
    private var liveDir: String? = null
    private var liveTail: JsonlTail? = null
    private val live = ArrayList<MapPoint>()
    private var follow = true
    private var cameraSet = false
    private var pastLoaded = false
    private var lastCam: Pair<Double, Double>? = null
    private var lastRunning: Boolean? = null

    /** 位置の権限を求めている間に待たせている操作(走行の開始、または現在地へ移る) */
    private var afterPermission: (() -> Unit)? = null
    private val statusListener: (LiveStatus.Snapshot) -> Unit = { show(it) }
    private val poll = object : Runnable {
        override fun run() { pollLive(); ui.postDelayed(this, POLL_MS) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MapLibre.getInstance(this)
        setContentView(R.layout.activity_main)
        bindViews(savedInstanceState)
        // 画面の作り直し(回転・メモリの回収のあと)では、起動の指定をもう一度は処理しない(走行を二重に始めないため)
        if (savedInstanceState == null) handleLaunch(intent) else enqueueIncomplete(this)
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

    private fun bindViews(savedInstanceState: Bundle?) {
        mapView = findViewById<MapView>(R.id.map).apply { onCreate(savedInstanceState) }
        top = findViewById(R.id.top)
        chipStep = findViewById(R.id.chipStep)
        chipRough = findViewById(R.id.chipRough)
        // 隠しているときは印も消し、塗りと枠の違いに加えて形でも状態が分かるようにする(色だけで伝えない)
        chipStep.setOnCheckedChangeListener { _, on -> chipStep.isChipIconVisible = on; map?.showSteps(on) }
        chipRough.setOnCheckedChangeListener { _, on -> chipRough.isChipIconVisible = on; map?.showRough(on) }
        renderMarks()
        bottom = findViewById(R.id.bottom)
        statusView = findViewById(R.id.status)
        resultRow = findViewById(R.id.resultRow)
        resultIcon = findViewById(R.id.resultIcon)
        resultView = findViewById(R.id.result)
        countView = findViewById(R.id.counts)
        infoView = findViewById(R.id.info)
        runButton = findViewById(R.id.run)
        runButton.setOnClickListener { if (LiveStatus.current.running) DetectionService.stop(this) else requestStart(0) }
        findViewById<View>(R.id.here).setOnClickListener {
            follow = true; lastCam = null
            withLocation(R.string.permission_message_location, listOf(Manifest.permission.ACCESS_FINE_LOCATION)) { centerOnCurrent(userAsked = true) }
        }
        findViewById<View>(R.id.dev).setOnClickListener { startActivity(Intent(this, DevActivity::class.java)) }

        // 地図は画面の端まで描き、カードとボタンだけを、ステータスバーとナビゲーションバーの内側に寄せる
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            top.updateLayoutParams<android.widget.FrameLayout.LayoutParams> { topMargin = bars.top + dp(8) }
            bottom.updateLayoutParams<android.widget.FrameLayout.LayoutParams> { bottomMargin = bars.bottom + dp(44) }
            insets
        }

        DetectionMap(mapView) { m ->
            map = m
            m.onUserMoved = { follow = false }
            m.showSteps(chipStep.isChecked); m.showRough(chipRough.isChecked)
            if (hasLocation()) m.enableMyLocation()
            renderPast(); renderLive(); show(LiveStatus.current); initCamera()
        }
    }

    private fun show(s: LiveStatus.Snapshot) {
        if (lastRunning != s.running) {
            lastRunning = s.running
            statusView.setText(if (s.running) R.string.status_running else R.string.status_stopped)
            statusView.setBackgroundResource(if (s.running) R.drawable.bg_status_running else R.drawable.bg_status_stopped)
            statusView.setTextColor(ContextCompat.getColor(this, if (s.running) R.color.status_running_text else R.color.on_surface))
            runButton.setText(if (s.running) R.string.button_stop else R.string.button_start)
            runButton.setIconResource(if (s.running) R.drawable.ic_stop else R.drawable.ic_play_arrow)
        }
        val info = mutableListOf<String>()
        if (s.running) {
            resultView.text = Labels.name(this, s.label)
            resultView.setTextColor(Labels.textColor(this, s.label))
            val icon = Labels.icon(s.label)
            resultIcon.visibility = if (icon == null) View.GONE else View.VISIBLE
            icon?.let { resultIcon.setImageResource(it) }
            resultRow.visibility = View.VISIBLE
            countView.text = getString(R.string.counts_running, liveEvents.count { it.cls == "step" }, liveEvents.count { it.cls == "rough" })
            if (s.lat == null) info += getString(R.string.info_waiting_gps)
        } else {
            // 止まっているときは、直近の判定の行を出さない(状態の表示と重なるため)
            resultRow.visibility = View.GONE
            countView.text = getString(R.string.counts_stopped, past.count { it.value.isNotEmpty() })
        }
        if (!UploadSettings.isEnabled(this)) info += getString(R.string.info_upload_off)
        infoView.text = info.joinToString("\n")
        infoView.visibility = if (info.isEmpty()) View.GONE else View.VISIBLE

        val m = map ?: return
        // 現在地の丸は、地図(DetectionMap の現在地の表示)が描く。ここでは、走行中に地図を今の位置へ動かすだけ
        if (s.running && s.lat != null && s.lon != null) {
            if (follow && lastCam != (s.lat to s.lon)) {
                m.moveTo(s.lat, s.lon, FOLLOW_ZOOM, animate = lastCam != null)
                lastCam = s.lat to s.lon
                cameraSet = true
            }
        }
    }

    // ===== 地図に載せるデータ =====

    /** 走行中は今の走行のファイルを読み足す。止まったら、今の走行を過去の走行に移す */
    private fun pollLive() {
        val s = LiveStatus.current
        val dir = s.dir
        if (s.running && dir != null) {
            if (dir != liveDir) {
                liveDir = dir; liveTail = JsonlTail(File(dir, "detections.jsonl")); live.clear(); liveEvents = emptyList()
                follow = true; lastCam = null
                renderLive(); loadPast()
            }
            val tail = liveTail ?: return
            io.execute {
                val pts = tail.readNew()
                if (pts.isNotEmpty()) ui.post { if (tail === liveTail) { live += pts; liveEvents = MapData.events(live); renderLive() } }
            }
        } else if (liveDir != null) {
            liveDir = null; liveTail = null; live.clear(); liveEvents = emptyList()
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
                past = loaded; pastEvents = MapData.events(loaded.values); pastLoaded = true
                Log.i(TAG, "MAP 過去の走行 ${loaded.size} 本、位置つきの窓 ${loaded.values.sumOf { it.size }}、" +
                    "段差 ${pastEvents.count { it.cls == "step" }} か所、凸凹 ${pastEvents.count { it.cls == "rough" }} 区間")
                renderPast(); show(LiveStatus.current); initCamera()
            }
        }
    }

    // チップの数は、地図(style)を読み込めていなくても出す
    private fun renderPast() {
        map?.setPastLines(MapData.linesGeoJson(past.values))
        renderMarks()
    }

    private fun renderLive() {
        map?.setLiveLines(MapData.linesGeoJson(listOf(live)))
        renderMarks()
    }

    /** 段差のピン・凸凹の帯と、チップの数(これまでと今回の合計) */
    private fun renderMarks() {
        val all = pastEvents + liveEvents
        chipStep.text = getString(R.string.chip_step, all.count { it.cls == "step" })
        chipRough.text = getString(R.string.chip_rough, all.count { it.cls == "rough" })
        val m = map ?: return
        m.setSteps(MapData.stepsGeoJson(all))
        m.setRough(MapData.roughGeoJson(all))
    }

    /** 最初に 1 回だけ: 走行中なら今の位置、そうでなければ全部の走行が入る範囲、何も無ければ最後に分かっている位置 */
    private fun initCamera() {
        val m = map ?: return
        if (cameraSet || !pastLoaded) return
        val s = LiveStatus.current
        if (s.running && s.lat != null) return  // show() が追う
        val b = MapData.bounds(past.values.asSequence().flatten() + live.asSequence())
        if (b != null) m.fit(b, top = top.bottom + dp(24), bottom = mapView.height - bottom.top + dp(24), side = dp(32))
        else centerOnCurrent()
        cameraSet = true
    }

    /**
     * 今の位置へ地図を動かす。走行中はサービスの GPS、止まっているときは地図の現在地の表示が受け取った位置、
     * それも無ければ端末が最後に知っている位置。
     * 位置が分からないとき: 「現在地」を押したのなら、取得中だと知らせて地図は動かさない。起動したときなら、日本の全体を出す
     */
    @SuppressLint("MissingPermission")
    private fun centerOnCurrent(userAsked: Boolean = false) {
        val m = map ?: return
        val s = LiveStatus.current
        if (s.running && s.lat != null && s.lon != null) { m.moveTo(s.lat, s.lon, FOLLOW_ZOOM, animate = true); lastCam = s.lat to s.lon; return }
        if (hasLocation()) m.enableMyLocation()
        val last = m.myLocation() ?: if (hasLocation()) {
            val lm = getSystemService(LOCATION_SERVICE) as LocationManager
            listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                .mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }.maxByOrNull { it.time }
        } else null
        when {
            last != null -> m.moveTo(last.latitude, last.longitude, FOLLOW_ZOOM, animate = true)
            userAsked -> Snackbar.make(findViewById(R.id.root), R.string.info_waiting_location, Snackbar.LENGTH_LONG).setAnchorView(bottom).show()
            else -> m.moveTo(36.2, 138.25, 4.5, animate = false)
        }
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

    private fun requestStart(durationS: Int) =
        withLocation(R.string.permission_message, missingPermissions()) { DetectionService.start(this, durationS) }

    /**
     * 位置の権限があれば action をすぐ行う。無ければ、OS の許可の画面の前に日本語で理由を説明し(OS の画面は端末の言語で出るため)、
     * 許可されたら action を行う
     */
    private fun withLocation(@androidx.annotation.StringRes message: Int, permissions: List<String>, action: () -> Unit) {
        if (hasLocation()) { action(); return }
        afterPermission = action
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.permission_title)
            .setMessage(message)
            .setPositiveButton(R.string.permission_next) { _, _ ->
                ActivityCompat.requestPermissions(this, permissions.toTypedArray(), REQ_PERMISSIONS)
            }
            .setNegativeButton(R.string.permission_cancel) { _, _ -> afterPermission = null }
            .setOnCancelListener { afterPermission = null }
            .show()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMISSIONS) return
        val action = afterPermission ?: return
        afterPermission = null
        if (hasLocation()) { map?.enableMyLocation(); action(); return }
        Snackbar.make(findViewById(R.id.root), R.string.permission_denied, Snackbar.LENGTH_LONG)
            .setAnchorView(bottom)
            .setAction(R.string.permission_open_settings) {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
            }
            .show()
    }

    // ===== 地図の部品の生存期間(MapView に渡す) =====

    override fun onStart() {
        super.onStart()
        mapView.onStart()
        LiveStatus.observe(statusListener)
        // 設定の画面で位置を許可して戻ってきたときにも、現在地を出す
        if (hasLocation()) map?.enableMyLocation()
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
