package se.laddnatt.app

import android.content.Context
import android.content.SharedPreferences
import se.laddnatt.core.BatteryReading
import se.laddnatt.core.Settings
import java.time.LocalDate

/** Allt appen sparar ligger lokalt på telefonen. */
class Store(context: Context) {
    private val p: SharedPreferences = context.getSharedPreferences("laddnatt", Context.MODE_PRIVATE)

    var settings: Settings
        get() {
            val d = Settings()
            return Settings(
                batteryKwh = d.batteryKwh,
                kmWeekday = p.getFloat("kmWeekday", d.kmWeekday.toFloat()).toDouble(),
                kmWeekend = p.getFloat("kmWeekend", d.kmWeekend.toFloat()).toDouble(),
                chargerKw = p.getFloat("chargerKw", d.chargerKw.toFloat()).toDouble(),
                minPercent = p.getFloat("minPercent", d.minPercent.toFloat()).toDouble(),
                targetPercent = p.getFloat("targetPercent", d.targetPercent.toFloat()).toDouble(),
            )
        }
        set(s) {
            p.edit()
                .putFloat("kmWeekday", s.kmWeekday.toFloat())
                .putFloat("kmWeekend", s.kmWeekend.toFloat())
                .putFloat("chargerKw", s.chargerKw.toFloat())
                .putFloat("minPercent", s.minPercent.toFloat())
                .putFloat("targetPercent", s.targetPercent.toFloat())
                .apply()
        }

    var battery: BatteryReading
        get() = BatteryReading(
            p.getFloat("batteryPercent", 60f).toDouble(),
            LocalDate.parse(p.getString("batteryDate", null) ?: LocalDate.now().toString()),
        )
        set(b) {
            p.edit()
                .putFloat("batteryPercent", b.percent.toFloat())
                .putString("batteryDate", b.date.toString())
                .apply()
        }

    var forecastJson: String?
        get() = p.getString("forecastJson", null)
        set(v) = p.edit().putString("forecastJson", v).apply()
}
