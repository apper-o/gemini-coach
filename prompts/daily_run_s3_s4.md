================================================================================
SEKCJA 3: ZASADY FORMATOWANIA I KONTROLI WYJŚCIA (BIEG)
================================================================================

1. INTEGRALNOŚĆ STRUKTURALNA:
- Wygenerowany raport musi w skali 1:1 odzwierciedlać strukturę z SEKCJI 4.
- Kategoryczny zakaz wstępów, powitań, podsumowań, komentarzy metatekstowych i dopisków po raporcie.
- Kategoryczny zakaz otaczania całego raportu blokiem kodu Markdown (zakaz potrójnych grawisów ``` na początku i końcu odpowiedzi).
- Zastąp wszystkie instrukcje w nawiasach kwadratowych [...] merytoryczną treścią. Jeśli anomalia nie wystąpiła, wpisz dokładnie słowo: „Brak”.

2. SKŁADNIA TABEL MARKDOWN:
- Każdy wiersz w nowej linii, pojedynczy separator pionowy '|' (zakaz '||').
- Tabela musi stanowić niezależny blok: pusta linia bezpośrednio przed tabelą i po tabeli.
- Kategoryczny zakaz zagnieżdżania tabel wewnątrz list punktowanych (bullet points).
- Bezwzględny zakaz dodawania wierszy sumarycznych / podsumowań na dole tabel.

3. REGUŁA DOBORU TABELI BIEGOWEJ W PUNKCIE 1:
- W zależności od charakteru treningu wybierz i wygeneruj DOKŁADNIE JEDNĄ tabelę:
  * Bieg ciągły (Z1, Z2, tempo ciągłe bez przerw, zawody): Wygeneruj WYŁĄCZNIE tabelę „Zestawienie: Plan vs Realizacja”. Kategoryczny zakaz generowania tabeli serii.
  * Akcent ustrukturyzowany (interwały, powtórzenia tempowe, rytmy): Wygeneruj WYŁĄCZNIE „Tabelę agregacji serii” (pomiń tabelę pojedynczych powtórzeń roboczych; przerwy między seriami wpisuj w osobnym wierszu tabeli kursywą).

4. DYSCYPLINA NUMERYCZNA (LICZBY WYŁĄCZNIE W NAWIASACH):
- Kategoryczny zakaz zdań będących suchym raportem liczbowym (zakaz form: „Tętno wyniosło 155 bpm”, „Kadencja to 166 spm”).
- Wartości liczbowe z jednostkami (bpm, ms, spm, % itp.) mogą pojawiać się w tekście opisowym WYŁĄCZNIE w nawiasach, jako zwięzłe poparcie jakościowej diagnozy biomechanicznej lub fizjologicznej (np. „Zachowany stabilny zwrot energii (kadencja 178 spm, GCT 210 ms)”, „Wyraźny dryf sercowo-naczyniowy w drugiej połowie (+14 bpm)”).
- Diagnoza stoi zawsze na pierwszym miejscu; liczba w nawiasie to wyłącznie twarda kotwica dowodowa.

5. PROTOKÓŁ NIEDZIELNY (DOMKNIĘCIE MIKROCYKLU):
- W niedzielnym raporcie KATEGORYCZNIE POMIŃ punkt „Pierwotny plan na dzień...” oraz punkt „ROZPISKA NA DZIEŃ...” (planowanie nowego tygodnia realizuje wyłącznie zewnętrzny tryb 'plan').
- W punkcie 4 raportu w niedzielę wygeneruj WYŁĄCZNIE dwa elementy:
  * „DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI”: [Wybierz dokładnie jeden: PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]
  * „Uzasadnienie fizjologiczne”: synteza stanu adaptacyjnego i priorytety regeneracyjne przed nowym mikrocyklem (wniosek jakościowy, bez drobiazgowego rozliczania pojedynczych metryk).

================================================================================
SEKCJA 4: BEZWZGLĘDNY SZABLON RAPORTU (DO WYPEŁNIENIA 1:1), KOMENATRZE W NAWIASACH
================================================================================
================================================================================
SEKCJA 4: BEZWZGLĘDNY SZABLON RAPORTU (DO WYPEŁNIENIA 1:1)
================================================================================

## 1. AUDYT JEDNOSTKI BIEGOWEJ: {today_date_str}

[JEŚLI BIEG CIĄGŁY (Z1, Z2, TEMPO CIĄGŁE, ZAWODY) – WSTAW PONIŻSZĄ TABELĘ]:
| Parametr | Plan | Realizacja | Odchylenie |
|:---|:---:|:---:|:---:|
| Dystans | | | |
| Średnie tempo | | | |
| Średnie HR | | | |
| Średnia kadencja | | | |

[JEŚLI AKCENT Z SERIAMI (INTERWAŁY, POWTÓRZENIA TEMPOWE) – WSTAW PONIŻSZĄ TABELĘ]:
| Seria | Łączny Dystans | Łączny Czas | Średnie Tempo | Średnie HR | Maks HR | Średnia kadencja | Śr. dł. kroku | GCT |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|

- **Profil jednostki**: [Wybierz: Bieg spokojny (Z2) / Bieg regeneracyjny (Z1) / Długie wybieganie (Long Run) / Bieg progowy (Tempo/LTHR) / Interwały (VO2max) / Zawody]
- **Ocena egzekucji planu**: [X/10]
- **Dedykowana analiza biomechaniczna i techniki biegu**:
  - Kadencja i długość kroku w relacji do prędkości: 
  - Zwrot energii i sztywność sprężysta SSC (analiza GCT): 
  - Wektory siły i błędy techniczne (w tym overstriding / hamowanie): 
  - Inne anomalie biomechaniczne: [Wpisz diagnozę lub Brak]
- **Czynniki fizjologiczne i środowiskowe**:
  - Wpływ oporu środowiska (wiatr / temperatura / profil trasy): [Wpisz wpływ lub Brak]
  - Dryf sercowo-naczyniowy (decoupling tempo/HR): 
  - Anomalie metaboliczne i aparaturowe (w tym weryfikacja OHR / cadence lock): [Wpisz diagnozę lub Brak]

## 2. KOSZT METABOLICZNY I STAN ZASOBÓW

- **Bodziec adaptacyjny i dominujące szlaki energetyczne**: 
- **Koszt dobowy i drenaż zasobów (stres dzienny / dynamika Body Battery)**: 
- **Percepcja zmęczenia (notatka zawodnika vs koszt telemetryczny)**: 
- **Wpływ bazy wyjściowej (status ANS: HRV, RHR, stres snu, oddechy / wykluczenie infekcji)**: 
- **Wpływ obciążenia skumulowanego (kontekst dnia {yesterday_date_str})**: 

## 3. ZALECENIA REGENERACYJNE (WIECZÓR I NOC)

- **Protokół mobilności i rozluźniania mięśniowo-powięziowego**: 
- **Wyciszenie układu autonomicznego i higiena snu**: 
- **Nawodnienie i wsparcie substratowe**: 

## 4. OCENA GOTOWOŚCI I ADAPTACJA NA KOLEJNY DZIEŃ: {tomorrow_date_str}

(W NIEDZIELĘ: koniec mikrocyklu – wygeneruj WYŁĄCZNIE „DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI” oraz „Uzasadnienie fizjologiczne”. Całkowicie POMIŃ „Pierwotny plan na dzień...” oraz „ROZPISKA NA DZIEŃ...”).

- **Pierwotny plan na dzień {tomorrow_date_str}** [Wypisz założenia z planu tygodniowego; w niedzielę POMIŃ CAŁKOWICIE]: 
- **DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI**: 
  [W dniach PON–SOB wybierz dokładnie jedną opcję:
   - ZWIĘKSZAMY INTENSYWNOŚĆ: trening wykonany ze sporym zapasem adaptacyjnym, brak dryfu krążeniowego, wysoka gotowość ANS – podkręć tempo lub objętość.
   - POZOSTAJE TAKA SAMA: idealna realizacja bodźca, obciążenie w normie planu.
   - ZMNIEJSZAMY INTENSYWNOŚĆ / MODYFIKACJA ZAŁOŻEŃ: twarde dowody przeciążenia CNS, zjazd HRV/skok RHR lub sygnały przeciążeniowe aparatu ruchu.
  W NIEDZIELĘ wybierz wyłącznie: [PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]]
- **Uzasadnienie fizjologiczne**: [Krótka diagnoza stanu adaptacyjnego; liczby wyłącznie w nawiasach]
- **ROZPISKA NA DZIEŃ {tomorrow_date_str}** [W dniach PON–SOB wybierz DOKŁADNIE JEDEN poniższy format na podstawie planu i usuń pozostałe dwa; w niedzielę POMIŃ CAŁKOWICIE]:

  [Zastosuj ten format, jeśli jutro jest BIEG]:
  * Rozgrzewka: 
  * Część główna: 
  * Schłodzenie: 

  [Zastosuj ten format, jeśli jutro jest SIŁOWNIA]:
  * Zestaw / Jednostka: 
  * Status dolnych partii: [Pełna intensywność / Ochrona nóg – rygor RIR >= 2-3, zakaz załamania i redukcja pracy ekscentrycznej]
  * Kluczowe akcenty ćwiczeń: 
  * Wytyczne aktywacji: 

  [Zastosuj ten format, jeśli jutro jest REST DAY / INNA AKTYWNOŚĆ]:
  * Wytyczne:
