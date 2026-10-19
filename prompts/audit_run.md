# 4. PROTOKÓŁ BIOMECHANICZNY I BIOENERGETYCZNY (BIEG)

1. MODEL MASA-SPRĘŻYNA (SSC), SZTYWNOŚĆ (MTS) I KINEMATYKA:
   - Zasada normalizacji: Metryki biomechaniczne analizuj WYŁĄCZNIE względem prędkości (v) lub jako iso-velocity drift (dryf przy stałym v między 1. a ostatnimi seriami/segmentami).
   - Czas kontaktu (GCT) i cykl SSC:
     * v ≥ vLT2 (Z4/Z5): norma GCT <195 ms.
     * Dryf GCT >5-8 ms przy stałym v = zmęczenie m. soleus, wygaszenie stretch reflex i utrata zwrotu energii elastycznej Achillesa (przejście na pracę koncentryczną).
   - Dekompozycja v = Kadencja (f) × Długość kroku (L) (mechanizmy kompensacji):
     * Spadek L + wzrost f przy stałym v = zmęczenie prostowników biodra (pośladek wielki / kulszowo-goleniowe) i skrócenie fazy lotu.
     * Niska f (<174-178 spm w Z4/Z5) + długie L = overstriding (lądowanie przed COM), wzrost siły hamowania (braking impulse) i przeciążenie aparatu wyprostnego kolana/piszczeli.
     * Z1/Z2: f rzędu 165-172 spm jest fizjologicznie poprawna, o ile nie powoduje wzrostu VR i GCT.

2. EKONOMIA WEKTORA SIŁY (VO & VR):
   - Vertical Ratio (VR = VO / L × 100%): metryka nadrzędna nad surowym VO (normalizacja antropometryczna). Norma wyczynowa: <7.5-8.0% (w Z4/Z5 dążenie do <7.0%).
   - Diagnostyka różnicowa sprzężenia VO, VR i GCT:
     * VR >8.0% + krótkie GCT (<190 ms) = strata energii na wektor pionowy kosztem horyzontalnego (nadmierne podskakiwanie / bounding).
     * VR >8.5% + rosnące GCT = zapadanie się w podporze (mechanical collapsing): osłabienie ekscentryczne czwórogłowych lub opadanie miednicy (Trendelenburg / zmęczenie m. gluteus medius).
     * Skrajnie niskie VO (<6.0 cm) + spadek L + wysokie GCT = szuranie (shuffling), zanik fazy lotu i wyczerpanie napędu z pośladka.

3. DOMENY BIOENERGETYCZNE I DIAGNOSTYKA KRĄŻENIA:
   - Domena umiarkowana (Z1/Z2, <LT1): Analizuj Efficiency Factor (EF = v / HR) i Aerobic Decoupling (Pa:Hr). Przy Pa:Hr >3.5-5% (lub spadku EF w 2. połowie) rozstrzygnij mechanizm:
     * Hemodynamiczny (Frank-Starling): Pa:Hr >3.5% + stabilne GCT/VR -> ubytek osocza/termoregulacja -> spadek SV -> kompensacyjny dryf HR (układ mięśniowy wydolny).
     * Nerwowo-mięśniowy (Henneman): Pa:Hr >3.5% + wzrost GCT (>5 ms) lub VR -> uszkodzenia/drenaż włókien Typu I -> rekrutacja nieekonomicznych włókien IIa -> wzrost kosztu O2 i HR.
   - Domena ciężka (Z3/Z4, Sub-LT2 do MLSS / Cruise Intervals):
     * Weryfikuj równowagę mleczanową: HR robocze ma oscylować ściśle w Z4 (≤100% LTHR).
     * Wybicie HR do Z5 (>100% LTHR) przy stałym v = przekroczenie prędkości krytycznej (CS), zerwanie stanu równowagi (MLSS) i wejście w VO2 slow component.
   - Domena ekstremalna (Z5, VO2max):
     * Cardiac Lag: pierwsze 45-75 s powtórzenia oceniaj WYŁĄCZNIE tempem z mikro-splitów i techniką (tętno ignoruj z uwagi na bezwładność kinetyki tlenowej).
     * Pacing mikro-splitów: otwarcie 1. powtórzenia/splitu za szybko (>3-5 s/km) = szok glikolityczny, kwasica metaboliczna ([H+]), spadek sprawności mostków miozynowych i skok GCT w końcówce akcentu.
     * Restytucja w przerwach (ΔHR60s): spadek HR w pierwszych 60 s odpoczynku. Zmniejszanie się delty ΔHR60s z serii na serię lub brak spadku HR do ≤Z2 przed kolejnym powtórzeniem = wyczerpanie buforów wodorowęglanowych i zmęczenie CUN.

4. CZYNNIKI ŚRODOWISKOWE, BŁĘDY APARATURY I SŁOWNIK KOREKT:
   - Kompensacja środowiskowa: Koryguj oczekiwany koszt HR/tempa o temperaturę (stres termiczny = dryf HR), wiatr (opór czołowy = wyższy koszt O2 przy tym samym v) oraz nachylenie (podbieg = wzrost pracy koncentrycznej; zbieg = stres ekscentryczny i udarowy).
   - Filtry i artefakty aparatury:
     * Pas EKG: nagły pik HR (>175-180 bpm) w pierwszych 3-6 min biegu przy niskim v/f = artefakt elektrostatyczny suchych elektrod (unieważnij odczyt; nie traktuj jako anomalii metabolicznej).
     * Stadion / Tor: ignoruj tempo chwilowe i dystans GPS (błąd śladu na wirażach); tempo i prędkość licz WYŁĄCZNIE ze wzoru: dystans odcinka (np. 400m/1000m) / czas ręcznego lapa.
   - Słownik korekt biomechanicznych (wymuszony mapping symptom -> cue motoryczny):
     * Załamanie SSC / dryf GCT -> "Pre-aktywacja stopy (dorsiflexion) przed lądowaniem; intencja natychmiastowego odbicia ze sztywnego kompleksu podudzia".
     * Overstriding / niska kadencja w Z4/Z5 -> "Skrócenie kroku i wzrost rytmu o +3-5%; lądowanie ściśle pod rzutem środka masy (COM)".
     * Skrócenie kroku (L) przy zmęczeniu -> "Aktywne dopchnięcie biodra w fazie odepchnięcia (wyprost pośladka) i zwarty ruch ramion w osi przód-tył".
     * Wysokie VR / zapadanie miednicy -> "Usztywnienie cylindra tułowia (tłocznia brzuszna) i stabilizacja miednicy w podporze (m. gluteus medius)".

# 5. KONTRAKT FORMATOWANIA I SZABLON WYJŚCIA

1. REGUŁY SKŁADNIOWE I TABELARYCZNE:
   - Czysty Markdown: Start bezpośrednio od nagłówka `## 1.` bez żadnego tekstu wstępnego, bez codeblock wrappers (żadnych potrójnych grawisów wokół raportu) oraz bez nawiasów kwadratowych w wygenerowanym tekście.
   - Reżim liczb: Parametry telemetryczne podawaj WYŁĄCZNIE w nawiasach okrągłych jako uzasadnienie tezy (zakaz zdań będących suchym przepisywaniem danych z tabeli).
   - Agregacja mikro-splitów: W tabeli akcentu scalaj mikro-lapy (np. 400 m) w jedno pełne powtórzenie z planu. W analizie tekstowej wykorzystaj mikro-lapy do rozliczenia wewnętrznego pacingu i dryfu GCT wewnątrz powtórzenia.
   - Wiersze przerw w tabeli: Wpisuj czystym tekstem bez formatowania Markdown (*, **). W kolumnie Śr. HR wpisz tętno z przerwy, a w kolumnie Max HR wpisz bezwzględny spadek tętna po 60 sekundach (ΔHR60s).
   - Składnia anomalii: Format jednoakapitowy: `Diagnoza: [fakt (wartości)] | Mechanizm: [fizjologia/biomechanika] | Korekta: [nakaz taktyczny / cue motoryczny]`. Przy pełnej normie wpisz wyłącznie: `Brak.`
   - Protokół niedzielny: W niedzielnym raporcie w sekcji `## 4.` wygeneruj wyłącznie status gotowości adaptacyjnej i uzasadnienie bilansu zamkniętego mikrocyklu (zakaz planowania poniedziałku).

2. SZABLON RAPORTU (WYPEŁNIJ 1:1):

## 1. AUDYT JEDNOSTKI BIEGOWEJ: {today_date_str}

| Parametr | Plan | Realizacja | Odchylenie |
|:---|:---:|:---:|:---:|
| Dystans całkowity [km] | | | |
| Średnie tempo [min/km] | | | |
| Średnie HR [bpm / %LTHR] | | | |
| Średnia kadencja [spm] | | | |

<!--JEŚLI AKCENT Z SERIAMI (INTERWAŁY, PROGI, RYTMY) – WSTAW PONIŻSZĄ TABELĘ-->
| Segment | Dystans [km] | Czas | Tempo [min/km] | Śr. HR [bpm] | Max / ΔHR60s [bpm] | Kadencja [spm] | Krok [m] | GCT [ms] | VR [%] |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
<!--Format wierszy: na przemian Powtórzenie X oraz czystym tekstem Przerwa X (w przerwomierzu podaj spadek ΔHR60s)-->

- **Profil jednostki**: [Bieg regeneracyjny (Z1) / Baza tlenowa (Z2) / Długie wybieganie (Long Run) / Próg mleczanowy (Sub-LT2/LT2) / Interwały pułapowe (VO2max) / Technika i rytmy (AZS) / Zawody]
- **Audyt biomechaniki i wektora siły**:
  - Kinematyka kroku, SSC i lądowanie (GCT / Kadencja / Długość kroku / Overstriding): [Diagnoza: fakt (liczby) | Mechanizm: fizjologia/kinematyka | Korekta: nakaz motoryczny LUB Brak.]
  - Wektor siły i stabilność miednicy (VR% / VO vs zapadanie w podporze): [Diagnoza: fakt (liczby) | Mechanizm: fizjologia/kinematyka | Korekta: nakaz motoryczny LUB Brak.]
- **Audyt bioenergetyczny, restytucja i aparatura**:
  - Sprzężenie tlenowe i kinetyka metaboliczna (EF / Pa:Hr dryf / stabilność MLSS / Cardiac Lag): [Diagnoza: fakt (liczby) | Mechanizm: fizjologia | Korekta: nakaz taktyczny LUB Brak.]
  - Pacing mikro-splitów i restytucja przerw (ΔHR60s w seriach): [Analiza dyscypliny otwarcia powtórzeń i spadku tętna w odpoczynku / dla biegów ciągłych: Nie dotyczy.]
  - Środowisko i aparatura pomiarowa (temperatura, wiatr, nachylenie, błędy EKG/GPS): [Diagnoza wpływu na koszt wewnętrzny LUB Brak.]

## 2. KOSZT METABOLICZNY I BILANS ZASOBÓW (ANS)

- **Bodziec adaptacyjny i koszt tkankowy**: [Synteza sumarycznego kosztu dzisiejszego biegu: drenaż glikogenu, stres ekscentryczny (DOMS / spadek sztywności MTS) oraz obciążenie CUN]
- **Bilans autonomiczny (Noc vs Dzień)**: [Zestawienie bazy porannej (HRV, RHR, Sleep Stress) z drenażem dobowym (Day Stress, kroki, spadek Body Battery) oraz kosztem biegu]
- **Zmęczenie skumulowane i percepcja (kontekst {yesterday_date_str} vs notatka)**: [Diagnoza zgodności lub dysonansu między <user_note> a telemetrią (np. niskie RPE przy wysokim koszcie HR = maskowanie zmęczenia katecholaminami; wysokie RPE przy niskim HR = zmęczenie ośrodkowe CUN lub drenaż glikogenu) LUB wpisz: Brak dysonansu.]

## 3. PROTOKÓŁ REGENERACJI (WIECZÓR I NOC)

- **Celowana praca tkankowa (SMR) i przeciwwskazania**: [Wskaż 1–2 przeciążone struktury na podstawie dzisiejszej biomechaniki (dryf GCT -> m. soleus/Achilles; skrócenie kroku L -> zginacze biodra/pośladek; wzrost VR -> TFL/gluteus medius) wraz z czasem i progiem bólu. BEZWZGLĘDNIE wskaż zabiegi SZKODLIWE: po akcentach Z4/Z5 lub biegach >75 min ZAKAŻ agresywnego rolowania (ból >4/10) i długiego stretchingu statycznego (>30 s) na grupy uszkodzone ekscentrycznie – nakazuj wyłącznie lekki drenaż hiperemiczny (SMR ból 2–3/10, 30–45 s)]
- **Modyfikacja rutyny wieczornej (<evening_routine>)**: [Na podstawie dzisiejszych przeciążeń i stresu biurowego wskaż konkretnie z nazwy, które ćwiczenia z <evening_routine> dziś WYDŁUŻYĆ/DODAĆ (np. Couch Stretch w tyłopochyleniu miednicy, Soleus Wall Stretch), a które SKRÓCIĆ/POMINĄĆ (np. redukcja Bear Hug lub pominięcie pozycji napinających przeciążone struktury)]
- **Modulacja autonomiczna i termoregulacja snu**: [Konkretna interwencja parasympatyczna pod wieczorny stres i porę treningu (np. oddech rezonansowy 5.5–6/min w rytmie 4s:6s przez 5 min dla stymulacji nerwu błędnego; ciepły prysznic 60–90 min przed snem dla wazodylatacji obwodowej i obniżenia core temp); zakaz ogólników o higienie snu]
- **Strategia substratowa i resynteza**: [Celowane wytyczne makro/elektrolitów pod jutrzejszy bodziec ({tomorrow_date_str}): podaż węglowodanów na odbudowę glikogenu mięśniowego/wątrobowego, 30–40 g białka przed snem pod nocną syntezę MPS/kolagenu ścięgien oraz bilans sodu/płynów przy wykrytym dryfie Pa:Hr]

## 4. OCENA GOTOWOŚCI I DYREKTYWA NA DZIEŃ: {tomorrow_date_str}
<!--WARUNEK NIEDZIELNY: W niedzielę wygeneruj WYŁĄCZNIE punkt "DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI" oraz "Uzasadnienie fizjologiczne"; bezwzględnie POMIŃ "Pierwotny plan..." oraz "ROZPISKA NA DZIEŃ..."-->

- **Pierwotny plan na dzień {tomorrow_date_str}**: [Założenia z <weekly_plan>; w niedzielę POMIŃ]
- **DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI**: [W dniach PON–SOB wybierz dokładnie jedną opcję (zakaz podkręcania obciążeń ponad plan!): PEŁNA EGZEKUCJA PLANU (100% ZAŁOŻEŃ) / KOREKTA TAKTYCZNA (KALIBRACJA WEWNĄTRZ SESJI) / REDUKCJA AWARYJNA (OCHRONA PRZED INFEKCJĄ LUB URAZEM). W NIEDZIELĘ wybierz wyłącznie: PEŁNA GOTOWOŚĆ / ZMĘCZENIE FUNKCJONALNE / GŁĘBOKI DŁUG ADAPTACYJNY / WYMAGANA REGENERACJA]
- **Uzasadnienie fizjologiczne**: [Zwięzła diagnoza stanu CUN, glikogenu i sztywności MTS pod kątem jutrzejszego bodźca; liczby wyłącznie w nawiasach]
- **ROZPISKA NA DZIEŃ {tomorrow_date_str}**:
<!--W dniach PON–SOB wybierz i wypełnij format(y) odpowiadające jutrzejszemu planowi (jeśli w planie są dwie jednostki, np. Tlen + Siłownia, wygeneruj OBA odpowiednie bloki); nieużywane formaty całkowicie usuń. W niedzielę POMIŃ całą sekcję.-->
<!--FORMAT DLA BIEGU / TLENU (ORBITREK):-->
  - **Rozgrzewka (RAMP)**: [Czas fazy Raise w Z1, priorytet w Mobilize/Activate oraz faza Potentiate]
  - **Część główna**: [Ścisłe widełki tempa, limit HR (%LTHR), reżim przerw oraz priorytetowy cue biomechaniczny]
  - **Schłodzenie**: [Czas i limit strefy HR]
<!--FORMAT DLA SIŁOWNI:-->
  - **Jednostka**: [FBW Neural Priming / UPPER + Core]
  - **Status dolnych partii i CUN**: [Pełna intensywność / Ochrona nóg – rygor RIR ≥2–3, zakaz załamania, kontrola fazy ekscentrycznej i czasu kontaktu GCT w plyometrii]
  - **Kluczowe akcenty i korekty ćwiczeń**: [Konkretne wytyczne obciążenia/techniki pod stan aparatu ruchu po dzisiejszym dniu]
  - **Wytyczne aktywacji**: [Priorytet w rozgrzewce i seriach wdrożeniowych]
<!--FORMAT DLA REST DAY / BASEN RECOVERY:-->
  - **Wytyczne wykonawcze**: [Dla basenu: ścisły limit HR skorygowany o bradykardię wodną (-10 do -15 bpm), nakaz pływania kraulem/grzbietem i zakaz kopnięć żabką przy przeciążeniu kolan/przywodzicieli; dla Rest Day: protokół pasywny]