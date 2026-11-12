package se.laddnatt.core

import java.time.DayOfWeek
import java.time.LocalDate
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

data class Settings(
    val batteryKwh: Double = 41.0,       // Zoe Z.E. 40
    val kmWeekday: Double = 40.0,
    val kmWeekend: Double = 20.0,
    val chargerKw: Double = 11.0,
    val minPercent: Double = 20.0,       // ladda innan batteriet går under detta
    val targetPercent: Double = 80.0,    // ladda upp till detta
)

/** Senast kända batterinivå. Gäller på morgonen angivet datum, före dagens körning. */
data class BatteryReading(val percent: Double, val date: LocalDate)

data class Night(
    val evening: LocalDate,         // natten börjar kl. 22 detta datum
    val known: Boolean,             // alla priser är fastställda
    val startDate: LocalDate,
    val startHour: Int,
    val chargeHours: Int,
    val price: Double,              // medel för de billigaste timmarna, SEK/kWh exkl. moms
    val priceLow: Double,
    val priceHigh: Double,
    val percentBefore: Double,      // uppskattad batterinivå den kvällen
    val allowed: Boolean,           // batteriet räcker fram till den här kvällen
)

enum class Action { CHARGE_TONIGHT, WAIT, NO_NEED, NO_DATA }

data class Decision(
    val action: Action,
    val percentNow: Double,
    val tonight: Night?,
    val best: Night?,
    val nights: List<Night>,
)

object Planner {
    private const val DEFAULT_TEMP = 5.0
    private const val CHARGE_EFFICIENCY = 0.9
    /** Vänta bara om en senare natt väntas bli minst så här mycket billigare. */
    private const val WAIT_MARGIN = 0.9
    private val NIGHT_HOURS = listOf(22, 23, 0, 1, 2, 3, 4, 5)

    /** kWh per 100 km. Ca 15 i milt väder, stiger i kyla till ca 21 vid -10 grader. */
    fun consumptionPer100Km(tempC: Double): Double =
        min(24.0, 15.0 + max(0.0, 15.0 - tempC) * 0.24)

    fun percentUsed(day: LocalDate, tempC: Double, s: Settings): Double {
        val weekend = day.dayOfWeek == DayOfWeek.SATURDAY || day.dayOfWeek == DayOfWeek.SUNDAY
        val km = if (weekend) s.kmWeekend else s.kmWeekday
        return km / 100.0 * consumptionPer100Km(tempC) / s.batteryKwh * 100.0
    }

    /** Uppskattad nivå på kvällen [day], efter den dagens körning. */
    fun percentAtEvening(reading: BatteryReading, day: LocalDate, temps: Map<LocalDate, Double>,
                         s: Settings): Double {
        var p = reading.percent
        var d = reading.date
        while (!d.isAfter(day)) {
            p -= percentUsed(d, temps[d] ?: DEFAULT_TEMP, s)
            d = d.plusDays(1)
        }
        return max(0.0, p)
    }

    fun chargeHours(percentBefore: Double, s: Settings): Int {
        val kwh = max(0.0, s.targetPercent - percentBefore) / 100.0 * s.batteryKwh
        return ceil(kwh / (s.chargerKw * CHARGE_EFFICIENCY)).toInt().coerceIn(1, NIGHT_HOURS.size)
    }

    /** Billigaste sammanhängande fönstret natten som börjar kvällen [evening], eller null om priser saknas. */
    fun night(f: Forecast, evening: LocalDate, percentBefore: Double, allowed: Boolean, s: Settings): Night? {
        val hrs = NIGHT_HOURS.map { h -> f.at(if (h >= 22) evening else evening.plusDays(1), h) ?: return null }
        val n = chargeHours(percentBefore, s)
        val start = (0..hrs.size - n).minByOrNull { i -> hrs.subList(i, i + n).sumOf { it.p50 } }!!
        val w = hrs.subList(start, start + n)
        return Night(
            evening, hrs.all { it.known }, w[0].date, w[0].hour, n,
            w.sumOf { it.p50 } / n, w.sumOf { it.p10 } / n, w.sumOf { it.p90 } / n,
            percentBefore, allowed,
        )
    }

    fun decide(f: Forecast, reading: BatteryReading, today: LocalDate, s: Settings): Decision {
        val percentNow = percentAtEvening(reading, today, f.dailyTemp, s)
        val nights = mutableListOf<Night>()
        var k = 0L
        while (true) {
            val evening = today.plusDays(k)
            val p = percentAtEvening(reading, evening, f.dailyTemp, s)
            // Natt 0 (i kväll) är alltid tillåten. Senare nätter bara om batteriet räcker dit.
            val allowed = k == 0L || p >= s.minPercent
            nights += night(f, evening, p, allowed, s) ?: break
            k++
        }
        val tonight = nights.firstOrNull() ?: return Decision(Action.NO_DATA, percentNow, null, null, nights)
        val candidates = nights.takeWhile { it.allowed }
        // Batteriet räcker längre än prognosen: ingen anledning att ladda än.
        if (candidates.size == nights.size && nights.size > 1 &&
            percentAtEvening(reading, nights.last().evening.plusDays(1), f.dailyTemp, s) >= s.minPercent) {
            return Decision(Action.NO_NEED, percentNow, tonight, candidates.minByOrNull { it.price }, nights)
        }
        val later = candidates.drop(1).minByOrNull { it.price }
        return if (later != null && later.price < tonight.price * WAIT_MARGIN) {
            Decision(Action.WAIT, percentNow, tonight, later, nights)
        } else {
            Decision(Action.CHARGE_TONIGHT, percentNow, tonight, tonight, nights)
        }
    }
}
