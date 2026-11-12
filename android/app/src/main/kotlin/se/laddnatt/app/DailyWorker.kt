package se.laddnatt.app

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import se.laddnatt.core.Action
import se.laddnatt.core.Planner
import se.laddnatt.core.Texts
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.concurrent.TimeUnit

/** Körs en gång per dag på eftermiddagen: hämtar prognosen och skickar dagens råd. */
class DailyWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val store = Store(applicationContext)
        val forecast = Net.forecast(store) ?: return Result.retry()
        val today = LocalDate.now()
        val d = Planner.decide(forecast, store.battery, today, store.settings)
        // Tyst de dagar då ingen laddning behövs.
        if (d.action == Action.CHARGE_TONIGHT || d.action == Action.WAIT) {
            Notifier.daily(applicationContext, Texts.headline(d), Texts.detail(d, today))
        }
        Net.newerVersionUrl(BuildConfig.VERSION_CODE)?.let { Notifier.update(applicationContext, it) }
        return Result.success()
    }

    companion object {
        private val NOTIFY_AT: LocalTime = LocalTime.of(15, 0)

        fun schedule(context: Context) {
            val now = LocalDateTime.now()
            var next = now.toLocalDate().atTime(NOTIFY_AT)
            if (!next.isAfter(now)) next = next.plusDays(1)
            val request = PeriodicWorkRequestBuilder<DailyWorker>(24, TimeUnit.HOURS)
                .setInitialDelay(Duration.between(now, next).toMillis(), TimeUnit.MILLISECONDS)
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            // KEEP: ändra inte tiden för ett redan schemalagt jobb varje gång appen öppnas.
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork("daily", ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
