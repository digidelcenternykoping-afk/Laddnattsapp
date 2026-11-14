package se.laddnatt.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

object Notifier {
    private const val CHANNEL = "laddning"
    private const val ID_DAILY = 1
    private const val ID_UPDATE = 2

    private fun canNotify(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun show(context: Context, id: Int, title: String, text: String, intent: Intent) {
        if (!canNotify(context)) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Laddning", NotificationManager.IMPORTANCE_DEFAULT))
        val pending = PendingIntent.getActivity(
            context, id, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(id, n)
        } catch (e: SecurityException) {
            // Tillståndet togs bort precis innan; inget att göra.
        }
    }

    fun daily(context: Context, title: String, text: String) =
        show(context, ID_DAILY, title, text, Intent(context, MainActivity::class.java))

    fun update(context: Context, url: String) =
        show(context, ID_UPDATE, "Ny version av Laddnatt", "Tryck för att hämta uppdateringen.",
            Intent(Intent.ACTION_VIEW, Uri.parse(url)))
}
