# Laddnattsapp

Hittar den billigaste natten att ladda elbilen i elområde SE3.

Projektet byggs i steg:

1. **Prisprognos** (`forecast/`): förutspår timpriser sex dagar längre fram än de kända day-ahead-priserna och rangordnar de kommande sju nätterna. *(pågår)*
2. **Android-app**: visar nätterna, håller koll på batteriet och skickar en notis på eftermiddagen.
3. **Automatik**: känner av körning via Android Auto och Bluetooth, justerar för kyla.
