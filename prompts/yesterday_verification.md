<!-- 
PLIK WYCOFANY (DEPRECATED):
Tryb 'yesterday' został całkowicie wycofany na rzecz wieczornego trybu 'daily' uruchamianego o 20:57.
Cała logika weryfikacji i adaptacji korzysta wyłącznie z prompts/daily_verification.md.
Ten plik nie jest już używany przez żaden moduł systemu.
-->

====================
DANE WEJŚCIOWE:

1. PROFIL BIEGACZA I STREFY:

* HR max: {max_hr} | Próg mleczanowy (LTHR): {lthr}
* Strefy tętna: {hr_zones}

2. PLAN NA DZIEŃ WCZORAJSZY ({yesterday_date_str}):
{planned_workout}

3. RZECZYWISTA REALIZACJA W DNIU WCZORAJSZYM ({yesterday_date_str}) (JEDNOSTKI TRENINGOWE):
{activity_section}

4. KOSZT DNIA WCZORAJSZEGO ({yesterday_date_str}) (BILANS OBCIĄŻENIA Z CAŁEGO DNIA):

* Wczorajsze kroki (cały dzień): {yesterday_steps}
* Średni poziom stresu w ciągu dnia: {yesterday_stress}
* Poziom energii Body Battery pod koniec wczorajszego dnia: {yesterday_body_battery}

5. STAN Z MINIONEJ NOCY (SEN MIĘDZY DNIEM WCZORAJSZYM A DZISIEJSZYM – BAZA REGENERACYJNA I GOTOWOŚĆ NA DZIŚ {today_date_str}):

* Status HRV (z minionej nocy): {hrv_status}
* Tętno spoczynkowe (RHR z minionej nocy): {rhr}
* Jakość snu (Sleep Score): {sleep_score} (Głęboki: {deep_sleep}, REM: {rem_sleep})
* Wnioski Garmina o śnie: {sleep_insights}
* Poranne naładowanie Body Battery na start dnia {today_date_str}: {morning_body_battery}

6. KONTEKST DNIA PRZEDWCZORAJSZEGO ({day_before_yesterday_date_str}):
{day_before_yesterday_section}

7. AKTUALNY PLAN TYGODNIOWY:
{weekly_plan_section}

8. BIEŻĄCA NOTATKA I UWAGI OD BIEGACZA (w tym ewentualny przebieg siłowni):
{user_note}

====================
FORMAT RAPORTU:

### 1. AUDYT DNIA WCZORAJSZEGO: {yesterday_date_str}

* Typ dnia: [BIEGOWY / SIŁOWY / BIEG + SIŁOWNIA / REST DAY]

WARIANT A: JEDNOSTKA BIEGOWA (jeśli odbył się bieg)

* Przeanalizuj lapy/splity części głównej. Pomiń odcinki oznaczone jako odpoczynek/przerwa (lub trucht regeneracyjny między powtórzeniami).
* ZESTAWIENIE ODCINKÓW AKCENTOWYCH (WYŁĄCZNIE DNI BIEGOWE): Jeśli dzień zawierał bieg z akcentem (interwały, powtórzenia, tempo), przeanalizuj lapy części głównej z pominięciem rozgrzewki, schłodzenia oraz przerw wypoczynkowych. Wygeneruj dokładnie dwie tabele w standardowym formacie Markdown:

Tabela 1: Poszczególne powtórzenia (standardowy blok tabeli Markdown, bez umieszczania wewnątrz punktorów listy):

| Nr powtórzenia | Seria | Dystans | Czas | Średnie Tempo | Średnie HR | Maks HR | Średnia kadencja |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Wytyczne wypełniania: |  |  |  |  |  |  |  |

* Każdy standardowy wiersz reprezentuje wyłącznie pojedynczy odcinek roboczy.
* Serie oddziel wierszem przerwy między seryjnej o dokładnie tej samej liczbie kolumn, aby zachować poprawność tabeli Markdown. Wpisz w nim:
| *Przerwa* | *[numer serji wyżej]* | *[dystans pokonany podczas przerwy]* | *[czas przerwy]* | *[średnie tempo]* | *[średni hr]* | *[maks hr]* | *[średnia kadencja]* |
* BEZWZGLĘDNIE: Nie dodawaj wiersza z sumą całego treningu na dole.

Tabela 2: Agregacja według serii
Kolumny: Seria | Łączny Dystans Serii | Łączny Czas Roboczy | Średnie Tempo Serii | Średnie HR Serii | Maks HR w Serii | Średnia kadencja w Serii
Każdy wiersz reprezentuje zsumowane odcinki robocze w ramach danej serii (z wyłączeniem przerw wewnątrz serii).
BEZWZGLĘDNIE: Nie dodawaj wiersza podsumowującego cały trening ani łącznego dystansu wszystkich serii.
Kluczowe jest, żeby tabela poprawnie się wyświetlała w odczycie Markdown.

* Zgodność z planem: [Wzorowo / Przekroczona intensywność / Zbyt wolno / Niezrealizowany] | Ocena: [X/10]
* Zestawienie: Dystans, Tempo, Średnie HR, Dryf tętna, Kadencja, Sumaryczny dystans wszystkich (Porównanie plan i realizacja) i wnioski na podstawie zestawienia.
* Kluczowe anomalie biomechaniczne / fizjologiczne: (krótka wypowiedź; jeśli brak, napisz: "Brak").

WARIANT B: JEDNOSTKA SIŁOWA (jeśli zrealizowano siłownię – analiza na podstawie notatki biegacza z sekcji 8)

* Profil jednostki: [Siła maksymalna / Hipertrofia funkcjonalna / Moc i plyometria / Siła biegowa i stabilizacja / Prehab]
* ZESTAWIENIE ĆWICZEŃ (standardowy blok tabeli Markdown, bez umieszczania wewnątrz punktorów listy):
| Nr | Ćwiczenie / Ruch | Serie x Powtórzenia | Obciążenie / RPE | Docelowy łańcuch / partia |
|:---:|:---:|:---:|:---:|:---:|
Wytyczne wypełniania:
* Wypełnij na podstawie danych wyciągniętych z notatki biegacza (sekcja 8).
* W kolumnie "Docelowy łańcuch / partia" wskaż konkretne struktury (np. łańcuch tylny, czwórogłowy, stabilizacja miednicy/core, łydka/ścięgno Achillesa, góra ciała).
* Koszt nerwowo-mięśniowy (CNS) i komponent ekscentryczny: (precyzyjna ocena wielkości zmęczenia ośrodkowego, obecności fazy ekscentrycznej grożącej mikrourazami/DOMS oraz napięcia struktur powięziowych).
* Wpływ na aparat biegowy (Running Transfer): (analiza bezpośredniego wpływu wykonanych ćwiczeń na sztywność sprężystą ścięgien, kadencję, siłę napędową odbicia oraz tolerancję uderzenia o podłoże w nadchodzących jednostkach biegowych).
* Zgodność z założeniami treningu uzupełniającego: [Optymalny bodziec / Przeładowanie nóg / Zbyt niska intensywność / Niezgodny z planem] | Ocena: [X/10]
* Zgłoszone anomalie, asymetrie i przeciążenia: (opis dolegliwości, kompensacji ruchowych lub nadmiernej bolesności zgłoszonych w notatce biegacza; jeśli brak, napisz: "Brak").

WARIANT C: REST DAY

* Zgodność z planem: [] | Ocena: [X / 10]. Wszystkie parametry treningowe: Nie dotyczy.

WARIANT D: TRENING BIEGOWY + JEDNOSTKA SIŁOWA
* Wykonaj polecenia z wariantu A, a następnie z wariantu B

### 2. KOSZT METABOLICZNY I OCENA REGENERACJI Z MINIONEJ NOCY

* Ocena kosztu wczorajszego dnia: Kroki łączne [X], średni stres [Y/100], wieczorne Body Battery pod koniec wczorajszego dnia [Z/100].
* Jakość nocnej odbudowy (sen wczoraj->dziś): Analiza wpływu snu ({sleep_score}, głęboki {deep_sleep}, REM {rem_sleep}) i nocnego HRV/RHR na odbudowę glikogenu, układu nerwowego i mikrourazów po wczorajszym obciążeniu.
* Poranna gotowość (Readiness) na dzień {today_date_str}: Poziom naładowania Body Battery ({morning_body_battery}) oraz status układu autonomicznego po nocy.

### 3. ADAPTACJA TRENINGU NA DZIEŃ DZISIEJSZY: {today_date_str}

* Pierwotny plan na dzień {today_date_str}: {trening_z_planu}
* Uwzględnienie notatki biegacza: [Odniesienie do zgłoszonych uwag, samopoczucia, bolesności mięśniowych/DOMS po siłowni, dyspozycji czasowej lub brak uwag]

* DECYZJA O KOREKCIE NA DZIŚ:
* Wskaż wprost, czy w świetle wczorajszego treningu ORAZ świeżej biometrii snu z nocy dzisiejszy trening ma być realizowany bez zmian, czy wymaga natychmiastowej modyfikacji (np. zmiana objętości, obniżenie tempa, zamiana akcentu na bieg regeneracyjny Z1/Z2, zmiana kolejności dni, zaleć rest lub modyfikację statusu siłowni).

* Uzasadnienie fizjologiczne: (1-2 zwięzłe argumenty bazujące na wieczornym bilansie wczorajszego obciążenia, jakości snu z minionej nocy i notatce biegacza).
* ROZPISKA NA DZIEŃ DZISIEJSZY ({today_date_str}):
* Jeśli bieg: Rozgrzewka, Część Główna (dokładne tempa/strefy HR z planu lub skorygowane), Schłodzenie.
* Jeśli siłownia: Status dla dolnych partii (np. "Pełna intensywność" / "Oszczędzać nogi — unikać pracy ekscentrycznej i obciążeń osiowych") oraz wytyczne dot. cardio uzupełniającego (np. rowerek, mobilność). Pamiętaj: NIE rozpisuj ćwiczeń siłowych.
* Jeśli Rest Day: Zalecenie pełnej regeneracji biernej lub lekkiego rollowania/mobilności.
* Wytyczne okołotreningowe na dziś: (krótko: odżywianie, nawodnienie i przygotowanie do jednostki).

====================
UWAGI DOTYCZĄCE FORMATOWANIA WIADOMOŚCI:

1. Wszystkie główne sekcje raportu oznaczaj jako nagłówki trzeciego poziomu (### Header 3).
2. Tabele generuj jako standardowy, czysty Markdown:
* Każdy wiersz bezwzględnie w nowej linii (zastosuj pojedynczy znak '|', zakaz używania '||').
* Każda tabela musi być oddzielona od tekstu pustą linią z góry i z dołu.
* ZAKAZ umieszczania tabel wewnątrz list punktowanych (bullet pointów).

3. Informacje o zarejestrowanych aktywnościach (splity/odcinki) umieszczaj wyłącznie w tabelach Markdown.
4. W przypadku biegów ciągłych/regeneracyjnych bez podziału na serie: wygeneruj jedną tabelę ze splitami (lub oznacz Tabelę 2 jako N/D).
5. ZAKAZ otaczania całego raportu blokiem kodu markdown (nie używaj potrójnych grawisów ``` na początku i końcu odpowiedzi).

====================
UWAGI STAŁE:

1. Kroki na poziomie >10 000 są u mnie standardem, a więc nie traktuj ich jako coś negatywnego dla regeneracji.
2. Weź pod uwagę, że recovery time może być czasami zbyt duży.
3. Jestem biegaczem ambitnym, więc jeśli powinienm starać się zrobić lepsze czasy, niż zaplanowane to daj znać.
4. Podczas krótkich przebieżek statystyki takie jak Avg Run Cadence mogą być niedokładne ze względu na krótki dystans.
