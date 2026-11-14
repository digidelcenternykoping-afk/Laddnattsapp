package se.laddnatt.core

import java.time.LocalDate
import java.util.Locale
import kotlin.math.roundToInt

/** Svenska texter för appen och notisen. Priser visas inklusive moms. */
object Texts {
    private const val VAT = 1.25
    private val SV: Locale = Locale.forLanguageTag("sv-SE")
    private val DAYS = listOf("mån", "tis", "ons", "tors", "fre", "lör", "sön")

    fun price(sekPerKwh: Double): String = String.format(SV, "%.2f kr/kWh", sekPerKwh * VAT)

    private fun priceNumber(sekPerKwh: Double): String = String.format(SV, "%.2f", sekPerKwh * VAT)

    fun percent(p: Double): String = "${p.roundToInt()} %"

    /** "natten mot lör 14/11" */
    fun nightName(n: Night, today: LocalDate): String {
        if (n.evening == today) return "i natt"
        val m: LocalDate = n.evening.plusDays(1)
        return "natten mot ${DAYS[m.dayOfWeek.value - 1]} ${m.dayOfMonth}/${m.monthValue}"
    }

    fun start(n: Night): String = String.format(SV, "kl. %02d:00", n.startHour)

    fun headline(d: Decision): String = when (d.action) {
        Action.CHARGE_TONIGHT -> "Ladda i natt"
        Action.WAIT -> "Vänta med laddningen"
        Action.NO_NEED -> "Ingen laddning behövs"
        Action.NO_DATA -> "Ingen prognos"
    }

    fun detail(d: Decision, today: LocalDate): String {
        val battery = "Batteriet är på ungefär ${percent(d.percentNow)}."
        return when (d.action) {
            Action.CHARGE_TONIGHT -> {
                val t = d.tonight!!
                val forced = d.nights.any { !it.allowed && it.price < t.price }
                "Billigast från ${start(t)}, ca ${price(t.price)} i ${t.chargeHours} tim. " +
                    (if (forced) "Batteriet räcker inte till en billigare natt. " else "") + battery
            }
            Action.WAIT -> {
                val b = d.best!!
                val name = nightName(b, today).replaceFirstChar { it.uppercase() }
                "$name väntas bli billigast, ca ${price(b.price)} " +
                    "(${priceNumber(b.priceLow)}–${priceNumber(b.priceHigh)}). " +
                    "I natt kostar det ${price(d.tonight!!.price)}. $battery"
            }
            Action.NO_NEED -> "$battery Det räcker längre än prognosen."
            Action.NO_DATA -> "Kunde inte hämta aktuella priser."
        }
    }

    fun nightRow(n: Night, d: Decision, today: LocalDate): String {
        val name = nightName(n, today).replaceFirstChar { it.uppercase() }
        val mark = if (d.best?.evening == n.evening && d.action != Action.NO_DATA) "★ " else ""
        val kind = if (n.known) "" else " (prognos)"
        val late = if (n.allowed) "" else ", batteriet räcker inte dit"
        return "$mark$name: ${price(n.price)}$kind från ${start(n)}, batteri ${percent(n.percentBefore)}$late"
    }
}
