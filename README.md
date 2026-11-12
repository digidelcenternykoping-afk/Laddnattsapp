# Laddnattsapp

Hittar den billigaste natten att ladda elbilen i elområde SE3.

Projektet byggs i steg:

1. **Prisprognos** (`forecast/`): förutspår timpriser sex dagar längre fram än de kända day-ahead-priserna och rangordnar de kommande sju nätterna. *(pågår)*
2. **Android-app**: visar nätterna, håller koll på batteriet och skickar en notis på eftermiddagen.
3. **Automatik**: känner av körning via Android Auto och Bluetooth, justerar för kyla.

## Prisprognosen

Körs automatiskt varje dag strax efter att morgondagens priser publicerats och skriver
[`public/forecast_SE3.json`](public/forecast_SE3.json) med:

- `nights`: de sju kommande nätterna (kl. 22-06) med medelpris för de billigaste tre
  sammanhängande timmarna, bästa starttid och ett osäkerhetsintervall (p10-p90).
- `hours`: pris per timme, kända priser först och därefter prognos.

Priserna är i SEK/kWh exklusive moms, elskatt och nätavgift.

**Så räknar modellen.** Den lär sig från historiken hur priset rör sig relativt den senaste
veckans nivå beroende på vindprognos (sex punkter i Sverige, Finland och Danmark),
temperatur, veckodag, helgdagar och årstid. Kärnkraftsstopp, vattenmagasin, grannländernas
priser och överföringskapacitet fångas än så länge bara indirekt via prisnivån och läggs
till som egna indata i nästa steg.

**Köra själv**

```
pip install -r forecast/requirements.txt
cd forecast && python -m pytest -q                 # enhetstester
cd .. && PYTHONPATH=forecast python -m laddnatt.backtest   # test mot historik
PYTHONPATH=forecast python -m laddnatt.daily      # dagens prognos
```

**Datakällor.** Spotpriser från [elprisetjustnu.se](https://www.elprisetjustnu.se/elpris-api).
Väder från [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).
