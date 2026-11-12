package se.laddnatt.app

import org.json.JSONObject
import se.laddnatt.core.Forecast
import java.net.HttpURLConnection
import java.net.URL

/** Nätverksanrop. Måste köras utanför huvudtråden. */
object Net {
    private const val REPO = "digidelcenternykoping-afk/Laddnattsapp"
    private const val FORECAST_URL = "https://raw.githubusercontent.com/$REPO/main/public/forecast_SE3.json"
    private const val RELEASE_URL = "https://api.github.com/repos/$REPO/releases/latest"

    private fun get(url: String): String {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 15_000
        c.readTimeout = 15_000
        c.setRequestProperty("User-Agent", "Laddnatt-app")
        try {
            if (c.responseCode != 200) throw RuntimeException("HTTP ${c.responseCode}")
            return c.inputStream.bufferedReader().use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    /** Hämtar prognosen och sparar den. Faller tillbaka på den senast sparade. */
    fun forecast(store: Store): Forecast? {
        try {
            val json = get(FORECAST_URL)
            val f = Forecast.parse(json)
            store.forecastJson = json
            return f
        } catch (e: Exception) {
            return try {
                store.forecastJson?.let { Forecast.parse(it) }
            } catch (e2: Exception) {
                null
            }
        }
    }

    /** Länk till en nyare version, eller null. Versioner taggas v<versionCode>. */
    fun newerVersionUrl(currentVersionCode: Int): String? {
        return try {
            val o = JSONObject(get(RELEASE_URL))
            val latest = o.getString("tag_name").removePrefix("v").toInt()
            if (latest > currentVersionCode) o.getString("html_url") else null
        } catch (e: Exception) {
            null
        }
    }
}
