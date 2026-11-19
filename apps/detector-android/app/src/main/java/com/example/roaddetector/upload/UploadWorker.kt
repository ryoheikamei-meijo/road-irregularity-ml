package com.example.roaddetector.upload

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.example.roaddetector.BuildConfig
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * 走行後に、残りの判定結果と生データ(input.csv)を、Wi-Fi などの従量課金でない回線に つながったときに送る。
 * 失敗したら WorkManager が間隔をあけてやり直す(再起動しても残る)。何度送っても二重にならない。
 */
class UploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        // 送信を切ったあとに残っていたジョブは、送らずに終える(入れ直したときに、もう一度入れる)
        if (!UploadSettings.isEnabled(applicationContext)) {
            Log.i(TAG, "UPLOAD ${inputData.getString(KEY_DIR)} 送信はオフ。送らずに終える")
            return Result.success()
        }
        val dir = File(inputData.getString(KEY_DIR) ?: return Result.failure())
        val state = SessionState.load(dir) ?: return Result.failure()
        val sync = SessionSync(state, PendingStore(dir), HttpApiClient(BuildConfig.API_URL, BuildConfig.API_KEY),
            File(dir, "input.csv")) { Log.w(TAG, it) }
        val ok = try { sync.syncAll() } catch (e: Exception) { Log.w(TAG, "送信で例外", e); false }
        Log.i(TAG, "UPLOAD ${dir.name} ${if (ok) "完了" else "やり直し"}")
        return if (ok) Result.success() else Result.retry()
    }

    companion object {
        private const val TAG = "RoadDetector"
        private const val KEY_DIR = "session_dir"

        /** 走行ごとに 1 つだけ(同じ走行をもう一度入れても、動いている分を残す) */
        fun enqueue(context: Context, sessionDir: File) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setInputData(workDataOf(KEY_DIR to sessionDir.absolutePath))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload-${sessionDir.name}", ExistingWorkPolicy.KEEP, request)
        }

        /**
         * アプリを起動したとき・送信を入れ直したとき、送り終えていない走行(落ちた・電波が無かった・送信を切っていた)を、送る対象に入れ直す。
         * 走行中の分(exclude)は除く(生データをまだ書いているため)
         */
        fun enqueueIncomplete(context: Context, sessionsDir: File, exclude: File? = null) {
            sessionsDir.listFiles { f -> f.isDirectory }?.forEach { dir ->
                if (exclude != null && dir.absoluteFile == exclude.absoluteFile) return@forEach
                val state = SessionState.load(dir) ?: return@forEach
                val store = PendingStore(dir)
                if (!state.rawDone || store.pendingCount() > 0) enqueue(context, dir)
            }
        }
    }
}
