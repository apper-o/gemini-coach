================================================================================
DODATKOWE WYTYCZNE PŁYWACKIE
================================================================================
PROTOKÓŁ BIOMECHANICZNY I FIZJOLOGICZNY (PŁYWANIE):
- Cel treningowy: W zależności od intensywności, pływanie traktuj jako aktywną regenerację (odciążenie stawów skokowych i kolanowych) lub budowę pojemności tlenowej przy użyciu górnych partii mięśniowych.
- Tętno w wodzie: Pamiętaj, że tętno maksymalne i progowe w wodzie jest fizjologicznie niższe o ok. 10-15 bpm niż podczas biegania (środowisko wodne, pozycja horyzontalna). Nie zaniżaj oceny wysiłku tylko dlatego, że wartości HR są mniejsze niż w biegu.
- Zmęczenie mięśniowe: Pływanie obciąża obręcz barkową i najszerszy grzbietu. Mimo mniejszego wpływu na aparat ruchu nóg, duża objętość lub intensywność generuje wysoki koszt dla CUN.

================================================================================
SEKCJA 3: ZASADY FORMATOWANIA I KONTROLI WYJŚCIA
================================================================================

1. INTEGRALNOŚĆ STRUKTURALNA:
- Wygenerowany raport musi w skali 1:1 odzwierciedlać strukturę z SEKCJI 4.
- Kategoryczny zakaz wstępów, powitań, podsumowań, komentarzy metatekstowych i dopisków po raporcie.
- Kategoryczny zakaz otaczania całego raportu blokiem kodu Markdown (zakaz potrójnych grawisów ``` na początku i końcu odpowiedzi).
- Zastąp wszystkie instrukcje w nawiasach kwadratowych [...] merytoryczną treścią. Jeśli anomalia nie wystąpiła, wpisz dokładnie słowo: „Brak”.

2. SKŁADNIA TABEL MARKDOWN:
- Każdy wiersz w nowej linii, pojedynczy separator pionowy '|' (zakaz '||').
- Tabela musi stanowić niezależny blok: pusta linia bezpośrednio przed tabelą i po tabeli.

3. DYSCYPLINA NUMERYCZNA (LICZBY WYŁĄCZNIE W NAWIASACH):
- Kategoryczny zakaz zdań będących suchym raportem liczbowym.
- Wartości liczbowe z jednostkami mogą pojawiać się w tekście opisowym WYŁĄCZNIE w nawiasach, jako zwięzłe poparcie jakościowej diagnozy.

4. PROTOKÓŁ NIEDZIELNY (DOMKNIĘCIE MIKROCYKLU):
- W niedzielnym raporcie KATEGORYCZNIE POMIŃ punkt „Pierwotny plan na dzień...” oraz punkt „ROZPISKA NA DZIEŃ...”.
- W punkcie 4 raportu w niedzielę wygeneruj WYŁĄCZNIE dwa elementy:
  * „DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI”: [Wybierz dokładnie jeden: PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]
  * „Uzasadnienie fizjologiczne”: synteza stanu adaptacyjnego i priorytety regeneracyjne przed nowym mikrocyklem.

================================================================================
SEKCJA 4: BEZWZGLĘDNY SZABLON RAPORTU (DO WYPEŁNIENIA 1:1)
================================================================================

## 1. AUDYT JEDNOSTKI PŁYWACKIEJ: {today_date_str}

| Parametr | Plan | Realizacja | Odchylenie |
|:---|:---:|:---:|:---:|
| Dystans | | | |
| Czas trwania | | | |
| Średnie tempo | | | |
| Średnie HR | | | |

- **Profil jednostki**: [Wybierz: Regeneracja (Z1) / Baza tlenowa (Z2) / Interwały tlenowe (Z3) / Interwały beztlenowe (Z4/Z5)]
- **Ocena egzekucji planu**: [X/10]
- **Dedykowana analiza fizjologiczna pływania**:
  - Wpływ na tętno i układ krążenia w środowisku wodnym: 
  - Obciążenie aparatu ruchu (obręcz barkowa vs odciążenie nóg): 
  - Anomalie metaboliczne i aparaturowe (w tym weryfikacja OHR w wodzie): [Wpisz diagnozę lub Brak]

## 2. KOSZT METABOLICZNY I STAN ZASOBÓW

- **Bodziec adaptacyjny i dominujące szlaki energetyczne**: 
- **Koszt dobowy i drenaż zasobów (stres dzienny / dynamika Body Battery)**: 
- **Percepcja zmęczenia (notatka zawodnika vs koszt telemetryczny)**: 
- **Wpływ bazy wyjściowej (status ANS: HRV, RHR, stres snu / wykluczenie infekcji)**: 
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
