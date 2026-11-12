package se.laddnatt.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class PlannerTest {
    private val today = LocalDate.of(2026, 11, 16) // måndag
    private val s = Settings()

    /** Prognos med ett pris per natt (kväll -> pris); dagtid kostar 2 kr. */
    private fun forecast(nightPrices: List<Double>, temp: Double = 10.0): Forecast {
        val hours = mutableListOf<HourPrice>()
        for (d in 0..nightPrices.size) {
            val date = today.plusDays(d.toLong())
            for (h in 0..23) {
                val p = when {
                    h >= 22 && d < nightPrices.size -> nightPrices[d]
                    h < 6 && d >= 1 -> nightPrices[d - 1]
                    else -> 2.0
                }
                hours += HourPrice(date, h, d <= 1, p * 0.8, p, p * 1.2)
            }
        }
        val temps = (-5..20).associate { today.plusDays(it.toLong()) to temp }
        return Forecast("test", hours, temps)
    }

    @Test fun consumptionRisesInCold() {
        assertEquals(15.0, Planner.consumptionPer100Km(20.0), 1e-9)
        assertEquals(21.0, Planner.consumptionPer100Km(-10.0), 1e-9)
        assertEquals(24.0, Planner.consumptionPer100Km(-40.0), 1e-9)
    }

    @Test fun batteryDrainsFasterWhenCold() {
        val r = BatteryReading(80.0, today)
        val mild = Planner.percentAtEvening(r, today.plusDays(3), mapOf(), s.copy())
        val cold = Planner.percentAtEvening(r, today.plusDays(3),
            (0..3).associate { today.plusDays(it.toLong()) to -10.0 }, s)
        assertTrue(cold < mild)
        // 4 vardagar à 40 km vid -10 grader: 4 * 0.4 * 21 / 41 = 81,95 % av batteriet -> tomt
        assertEquals(0.0, cold, 1e-9)
    }

    @Test fun chargeHoursFromEnergyNeeded() {
        // 20 -> 80 % av 41 kWh = 24,6 kWh, 11 kW * 0,9 = 9,9 kW -> 3 timmar
        assertEquals(3, Planner.chargeHours(20.0, s))
        assertEquals(1, Planner.chargeHours(79.0, s))
        assertEquals(8, Planner.chargeHours(0.0, s.copy(chargerKw = 2.3)))
    }

    @Test fun waitsForCheaperNightWhenBatteryLasts() {
        val f = forecast(listOf(1.0, 0.9, 0.3, 1.2, 1.5, 1.5, 1.5))
        // Ca 16 % per vardag vid 10 grader: 80 % räcker till onsdag kväll.
        val d = Planner.decide(f, BatteryReading(80.0, today), today, s)
        assertEquals(Action.WAIT, d.action)
        assertEquals(today.plusDays(2), d.best!!.evening)
    }

    @Test fun chargesTonightWhenCheapestNightIsTooLate() {
        // 30 % räcker inte till onsdag kväll (ca 16 % per vardag vid 10 grader), så den billiga natten nås inte.
        val f = forecast(listOf(1.0, 1.1, 0.3, 1.2, 1.5, 1.5, 1.5))
        val d = Planner.decide(f, BatteryReading(30.0, today), today, s)
        assertEquals(Action.CHARGE_TONIGHT, d.action)
        assertFalse(d.nights[2].allowed)
    }

    @Test fun chargesTonightWhenTonightIsCheapest() {
        val f = forecast(listOf(0.3, 0.9, 0.8, 1.2, 1.5, 1.5, 1.5))
        assertEquals(Action.CHARGE_TONIGHT, Planner.decide(f, BatteryReading(60.0, today), today, s).action)
    }

    @Test fun doesNotWaitForMarginalSaving() {
        val f = forecast(listOf(1.0, 0.95, 1.2, 1.2, 1.5, 1.5, 1.5))
        assertEquals(Action.CHARGE_TONIGHT, Planner.decide(f, BatteryReading(70.0, today), today, s).action)
    }

    @Test fun noNeedWhenBatteryOutlastsForecast() {
        val f = forecast(listOf(0.3, 0.9, 0.8, 1.2, 1.5, 1.5, 1.5))
        val d = Planner.decide(f, BatteryReading(100.0, today), today, s.copy(kmWeekday = 5.0, kmWeekend = 5.0))
        assertEquals(Action.NO_NEED, d.action)
    }

    @Test fun noDataWhenForecastIsOld() {
        val f = forecast(listOf(1.0, 1.0))
        val d = Planner.decide(f, BatteryReading(50.0, today), today.plusDays(10), s)
        assertEquals(Action.NO_DATA, d.action)
        assertNull(d.tonight)
    }

    @Test fun parsesForecastJson() {
        val json = """{"generated":"2026-11-16T13:40:00+01:00","daily_temp":{"2026-11-16":-3.5},
            "hours":[{"date":"2026-11-16","hour":22,"known":true,"p10":0.5,"p50":0.5,"p90":0.5},
                     {"date":"2026-11-17","hour":0,"known":false,"p10":0.1,"p50":0.2,"p90":0.3}]}"""
        val f = Forecast.parse(json)
        assertEquals(2, f.hours.size)
        assertEquals(-3.5, f.dailyTemp[today]!!, 1e-9)
        assertEquals(0.2, f.at(today.plusDays(1), 0)!!.p50, 1e-9)
        assertTrue(f.at(today, 22)!!.known)
    }

    @Test fun textsForWaitAndCharge() {
        val f = forecast(listOf(1.0, 0.9, 0.3, 1.2, 1.5, 1.5, 1.5))
        val wait = Planner.decide(f, BatteryReading(80.0, today), today, s)
        assertEquals("Vänta med laddningen", Texts.headline(wait))
        val text = Texts.detail(wait, today)
        assertTrue(text, text.startsWith("Natten mot tors 19/11 väntas bli billigast, ca 0,38 kr/kWh"))
        assertTrue(text, text.contains("I natt kostar det 1,25 kr/kWh"))

        val charge = Planner.decide(f, BatteryReading(30.0, today), today, s)
        assertEquals("Ladda i natt", Texts.headline(charge))
        assertTrue(Texts.detail(charge, today).contains("Batteriet räcker inte till en billigare natt"))
        assertTrue(Texts.nightRow(charge.nights[0], charge, today).startsWith("★ I natt: 1,25 kr/kWh från kl. 22:00"))
    }
}
