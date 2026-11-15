# Laddnattsapp

Hittar den billigaste natten att ladda elbilen i elområde SE3.

Projektet byggs i steg:

1. **Prisprognos** (`forecast/`): förutspår timpriser sex dagar längre fram än de kända day-ahead-priserna och rangordnar de kommande sju nätterna. *(pågår)*
2. **Android-app** (`android/`): visar nätterna, håller koll på batteriet och skickar en notis på eftermiddagen. *(första versionen)*
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
temperatur, veckodag, helgdagar och årstid. Grannländernas priser och överföringskapacitet
fångas än så länge bara indirekt via prisnivån.

**Kärnkraft och vattenmagasin** är testade som egna indata men inte påslagna, eftersom de
inte gav säkert bättre val av natt i det ärliga testet (november 2025 till november 2026):
kärnkraft gjorde valen sämre i alla fyra kvartalen, och vattenmagasin gav knappt 1 öre/kWh
billigare nätter men sämre timpriser. Testet mot historik jämför dem på nytt vid varje
ändring, och de slås på i `forecast/laddnatt/features.py` om de börjar hjälpa när det
finns mer historik.

**Köra själv**

```
pip install -r forecast/requirements.txt
cd forecast && python -m pytest -q                 # enhetstester
cd .. && PYTHONPATH=forecast python -m laddnatt.backtest   # test mot historik
PYTHONPATH=forecast python -m laddnatt.daily      # dagens prognos
```

**Datakällor.** Spotpriser från [elprisetjustnu.se](https://www.elprisetjustnu.se/elpris-api).
Väder från [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).
I testet även svensk kärnkraftsproduktion från [Energy-Charts](https://api.energy-charts.info/)
och norska magasin från [NVE](https://www.nve.no/energi/analyser-og-statistikk/om-magasinstatistikken/).

## Android-appen

Appen läser prognosfilen, uppskattar batterinivån och ger varje eftermiddag (ca kl. 15) ett av
råden *ladda i natt* eller *vänta*. De dagar batteriet räcker längre än prognosen är den tyst.

- **Batteriet** anges för hand än så länge. Mellan gångerna räknar appen ner nivån med dina
  vanliga körsträckor och högre förbrukning när det är kallt (ca 15 kWh/100 km i milt väder,
  ca 21 vid -10 grader).
- **Valet av natt**: bland de nätter batteriet räcker till väljs den billigaste. Appen väntar
  bara om en senare natt väntas bli minst 10 % billigare än i natt.
- **Allt sparas på telefonen.** Appen skickar ingen data någonstans. Den hämtar bara
  prognosfilen och kollar om det finns en ny version.

Beslutslogiken ligger i `android/core` (ren Kotlin) och testas utan Android:

```
cd android && CORE_ONLY=1 gradle :core:test
```

**Installera.** Varje ändring i `android/` som når `main` bygger en ny version under
[Releases](../../releases). Ladda ner `laddnatt.apk` på telefonen och öppna filen. Appen säger
själv till när det finns en nyare version.

Bygget kräver två hemligheter i repot (Settings, Secrets and variables, Actions):
`SIGNING_KEYSTORE_B64` (signeringsnyckeln, base64-kodad) och `SIGNING_PASSWORD`.
