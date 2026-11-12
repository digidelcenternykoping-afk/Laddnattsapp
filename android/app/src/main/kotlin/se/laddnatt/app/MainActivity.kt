package se.laddnatt.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import se.laddnatt.core.Action
import se.laddnatt.core.BatteryReading
import se.laddnatt.core.Forecast
import se.laddnatt.core.Planner
import se.laddnatt.core.Texts
import java.time.LocalDate
import java.time.LocalTime
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    private lateinit var store: Store
    private var forecast: Forecast? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = Store(this)

        findViewById<TextView>(R.id.version).text = "Version ${BuildConfig.VERSION_NAME}"
        findViewById<Button>(R.id.setBattery).setOnClickListener { askBattery() }
        findViewById<Button>(R.id.charged).setOnClickListener {
            store.battery = BatteryReading(store.settings.targetPercent, LocalDate.now())
            render()
        }
        findViewById<Button>(R.id.save).setOnClickListener { saveSettings() }
        showSettings()

        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        DailyWorker.schedule(this)
    }

    override fun onResume() {
        super.onResume()
        thread {
            val f = Net.forecast(store)
            runOnUiThread {
                forecast = f
                render()
            }
        }
    }

    private fun render() {
        val headline = findViewById<TextView>(R.id.headline)
        val detail = findViewById<TextView>(R.id.detail)
        val list = findViewById<LinearLayout>(R.id.nights)
        list.removeAllViews()
        val f = forecast
        if (f == null) {
            headline.text = "Ingen prognos"
            detail.text = "Kunde inte hämta priserna. Kontrollera internetanslutningen."
            return
        }
        val today = LocalDate.now()
        val d = Planner.decide(f, store.battery, today, store.settings)
        headline.text = Texts.headline(d)
        detail.text = Texts.detail(d, today)
        for (n in d.nights) {
            val row = TextView(this)
            row.text = Texts.nightRow(n, d, today)
            row.setPadding(0, 12, 0, 12)
            if (d.best?.evening == n.evening && d.action != Action.NO_DATA) {
                row.setTypeface(row.typeface, Typeface.BOLD)
            }
            list.addView(row)
        }
        findViewById<TextView>(R.id.updated).text =
            "Priser inklusive moms, utan elskatt och nätavgift. Prognos från ${f.generated.take(16).replace('T', ' ')}."
    }

    private fun askBattery() {
        val input = EditText(this)
        input.inputType = InputType.TYPE_CLASS_NUMBER
        input.hint = "Procent enligt bilens instrument"
        AlertDialog.Builder(this)
            .setTitle("Batterinivå just nu")
            .setView(input)
            .setPositiveButton("Spara") { _, _ ->
                val p = input.text.toString().toDoubleOrNull()
                if (p == null || p < 0 || p > 100) {
                    Toast.makeText(this, "Ange ett tal mellan 0 och 100", Toast.LENGTH_SHORT).show()
                } else {
                    // Efter lunch antas dagens körning vara gjord, så nivån gäller från i morgon bitti.
                    val date = if (LocalTime.now().hour >= 12) LocalDate.now().plusDays(1) else LocalDate.now()
                    store.battery = BatteryReading(p, date)
                    render()
                }
            }
            .setNegativeButton("Avbryt", null)
            .show()
    }

    private fun num(id: Int): Double? =
        findViewById<EditText>(id).text.toString().replace(',', '.').toDoubleOrNull()

    private fun showSettings() {
        val s = store.settings
        fun set(id: Int, v: Double) = findViewById<EditText>(id).setText(String.format(Locale.US, "%.1f", v))
        set(R.id.kmWeekday, s.kmWeekday)
        set(R.id.kmWeekend, s.kmWeekend)
        set(R.id.chargerKw, s.chargerKw)
        set(R.id.minPercent, s.minPercent)
        set(R.id.targetPercent, s.targetPercent)
    }

    private fun saveSettings() {
        val s = store.settings
        val updated = s.copy(
            kmWeekday = num(R.id.kmWeekday)?.coerceIn(0.0, 1000.0) ?: s.kmWeekday,
            kmWeekend = num(R.id.kmWeekend)?.coerceIn(0.0, 1000.0) ?: s.kmWeekend,
            chargerKw = num(R.id.chargerKw)?.coerceIn(1.0, 22.0) ?: s.chargerKw,
            minPercent = num(R.id.minPercent)?.coerceIn(0.0, 90.0) ?: s.minPercent,
            targetPercent = num(R.id.targetPercent)?.coerceIn(10.0, 100.0) ?: s.targetPercent,
        )
        store.settings = updated
        showSettings()
        render()
        Toast.makeText(this, "Sparat", Toast.LENGTH_SHORT).show()
    }
}
