package se.laddnatt.core

import org.json.JSONObject
import java.time.LocalDate

data class HourPrice(
    val date: LocalDate,
    val hour: Int,
    val known: Boolean,
    val p10: Double,
    val p50: Double,
    val p90: Double,
)

/** Prognosfilen public/forecast_SE3.json. Priser i SEK/kWh exkl. moms. */
data class Forecast(
    val generated: String,
    val hours: List<HourPrice>,
    val dailyTemp: Map<LocalDate, Double>,
) {
    private val byKey = hours.associateBy { it.date to it.hour }
    fun at(date: LocalDate, hour: Int): HourPrice? = byKey[date to hour]

    companion object {
        fun parse(json: String): Forecast {
            val o = JSONObject(json)
            val arr = o.getJSONArray("hours")
            val hours = (0 until arr.length()).map { i ->
                val h = arr.getJSONObject(i)
                HourPrice(
                    LocalDate.parse(h.getString("date")), h.getInt("hour"), h.getBoolean("known"),
                    h.getDouble("p10"), h.getDouble("p50"), h.getDouble("p90"),
                )
            }
            val temps = mutableMapOf<LocalDate, Double>()
            o.optJSONObject("daily_temp")?.let { t ->
                for (k in t.keys()) temps[LocalDate.parse(k)] = t.getDouble(k)
            }
            return Forecast(o.optString("generated"), hours, temps)
        }
    }
}
