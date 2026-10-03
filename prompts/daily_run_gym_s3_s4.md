================================================================================
SEKCJA 3: ZASADY FORMATOWANIA I KONTROLI WYJŚCIA
================================================================================

1. Twoja odpowiedź MUSI bezwzględnie i dokładnie odzwierciedlać strukturę z SEKCJI 4.
2. ZAKAZ dodawania jakichkolwiek wstępów, powitań, zdań podsumowujących, komentarzy metatekstowych czy dodatkowych nagłówków.
3. Wszystkie tabele muszą być sformatowane w czystym Markdown:
   * Każdy wiersz w nowej linii, pojedynczy znak '|', brak podwójnych kresek '||'.
   * Tabela musi być oddzielona od tekstu pustą linią z góry i z dołu.
   * ZAKAZ umieszczania tabel wewnątrz list punktowanych (bullet pointów).

4. ZASADY GENEROWANIA TABEL BIEGOWYCH I SIŁOWYCH:
   - Wypełnij obie sekcje (biegową i siłową).
   - W biegach ciągłych: ZAKAZ tworzenia tabeli serii. Wypełnij WYŁĄCZNIE tabelę "Zestawienie: Plan vs Realizacja".
   - W biegach z ustrukturyzowanym akcentem: wygeneruj WYŁĄCZNIE JEDNĄ tabelę – Tabelę agregacji serii.
   - Tabelę "Zestawienie: Plan vs Realizacja" generuj jako samodzielny blok tabeli Markdown.

5. UŻYCIE LICZB WYŁĄCZNIE JAKO DOPRECYZOWANIE DIAGNOZY (ZAKAZ SUCHEGO PRZEPISYWANIA):
* Kategoryczny zakaz tworzenia zdań opartych wyłącznie na surowym raportowaniu liczb (ZAKAZ pisania w stylu: „tętno spoczynkowe wyniosło 49 bpm”, „sen trwał 7h 15m”, „kadencja wynosiła 166 spm”). Użytkownik widzi te liczby w telemetrii i tabelach.
* ZEZWOLENIE NA LICZBY W NAWIASACH JAKO DOWÓD DIAGNOSTYCZNY: wartość liczbową z jednostką wolno umieścić w tekście WYŁĄCZNIE w nawiasie, jako zwięzłe poparcie i doprecyzowanie jakościowej diagnozy fizjologicznej lub biomechanicznej.
* Prawidłowo: „Głębokie wyciszenie układu autonomicznego i niski puls spoczynkowy (49 bpm)”, „Ostry dryf krążeniowy w końcówce (+18 bpm)”, „Utrata sztywności i ociężały krok (spadek kadencji do 164 spm)”.
* Niedopuszczalnie: „Puls wynosił 49 bpm”, „Twoje HRV to 42 ms, a Body Battery spadło do 15”.
* Liczba nigdy nie może zastępować wniosku – diagnoza jakościowa i techniczna stoi zawsze na pierwszym miejscu, a wartość w nawiasie stanowi jedynie twardą kotwicę telemetryczną.


6. Zastąp wszystkie znaczniki w nawiasach ostrokątnych <...> właściwą, bezkompromisową treścią. Jeśli anomalia nie wystąpiła, wpisz dokładnie słowo: "Brak".
7. ZAKAZ otaczania całego wygenerowanego raportu blokiem kodu markdown (nie używaj potrójnych grawisów ``` na początku i na końcu odpowiedzi).
8. ZASADA OPEROWANIA LICZBAMI W CZĘŚCIACH OPISOWYCH:
   * Zakaz tworzenia zdań będących suchym raportem liczbowym bez wniosku.
   * Wartości liczbowe wraz z jednostkami (bpm, ms, spm, % itp.) mogą pojawiać się w tekście WYŁĄCZNIE w nawiasach, jako zwięzłe doprecyzowanie jakościowej diagnozy (np. "Stabilny rytm bez załamania kadencji (178 spm)", "Prawidłowa resynchronizacja CUN i niskie tętno spoczynkowe (49 bpm)").
9. WYJĄTEK DLA NIEDZIELI (KONIEC MIKROCYKLU):
   * W niedzielnym raporcie ZAKAZ generowania punktu "Pierwotny plan na dzień..." oraz punktu "ROZPISKA NA DZIEŃ..." (w niedzielę kończy się mikrocykl tygodniowy; za nowy plan na kolejny tydzień odpowiada wyłącznie tryb 'plan').
   * W Sekcji 4 w niedzielę wygeneruj WYŁĄCZNIE dwa punkty:
     - "DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI": [PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]
     - "Uzasadnienie fizjologiczne": zwięzła diagnoza gotowości i wytyczne regeneracyjne przed nowym mikrocyklem (bez cytowania liczb).

================================================================================
SEKCJA 4: BEZWZGLĘDNY SZABLON RAPORTU (DO WYPEŁNIENIA 1:1), KOMENATRZE W NAWIASACH
================================================================================

# 1. AUDYT DNIA: {today_date_str}

## CZĘŚĆ BIEGOWA

| Seria | Łączny Dystans | Łączny Czas | Średnie Tempo | Średnie HR | Maks HR | Średnia kadencja | Śr. dł. kroku | GCT |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|

* **Profil jednostki**: [Bieg spokojny (Z2) / Bieg regeneracyjny (Z1) / Długie wybieganie (Long Run) / Bieg progowy (Tempo / MP) / Interwały (VO2max) / Zawody]
* **Ocena treningu**: [X/10]

Zestawienie: Plan vs Realizacja:

| Parametr | Plan | Realizacja | Odchylenie |
|:---|:---:|:---:|:---:|
| Dystans |  |  |  |
| Średnie tempo |  |  |  |
| Średnie HR |  |  |  |
| Średnia kadencja |  |  |  |

* **Dedykowana analiza biomechaniczna i techniki biegu**:
  - Ocena kadencji: 
  - Ekonomia i zwrot energii (SSC): 
  - Bezwzględne błędy techniczne: 
  - Inne anomalie biomechaniczne: 
* **Czynniki fizjologiczne**:
  - Dryf tętna: 
  - Inne anomalie fizjologiczne:

## CZĘŚĆ SIŁOWA

| Nr | Ćwiczenie | Serie x Powtórzenia | Ciężar | Docelowa partia |
|:---:|:---:|:---:|:---:|:---:|

* **Profil jednostki**: 
* **Ocena treningu**: [X/10]

* **Koszt nerwowo-mięśniowy (CNS) i komponent ekscentryczny**: 
* **Wpływ na aparat biegowy (Running Transfer)**: 
* **Zgłoszone anomalie, asymetrie i przeciążenia**: 

## KOSZT METABOLICZNY I STAN ZASOBÓW

* **Bodziec fizjologiczny i szlaki energetyczne**: 
* **Koszt dzienny i stan zasobów (stres / Body Battery / aktywność pozatreningowa)**: 
* **Subiektywny koszt i percepcja zmęczenia (uwzględnij faktyczne dane i notatkę jeśli występuje)**: 
* **Wpływ bazy wyjściowej (sen/HRV):**: 
* **Wpływ tła dnia poprzedniego ({yesterday_date_str})**: 

## ZALECENIA REGENERACYJNE PO TRENINGU (WIECZÓR I NOC)

* **Protokół rolowania i mobilności**:
* **Sen i regeneracja układu nerwowego**: 
* **Nawodnienie i protokół żywieniowy**: 

### 4. OCENA GOTOWOŚCI I ADAPTACJA NA DZIEŃ KOLEJNY: {tomorrow_date_str}

(W NIEDZIELĘ: koniec mikrocyklu – wygeneruj WYŁĄCZNIE dwa poniższe punkty: DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI oraz Uzasadnienie fizjologiczne. W niedzielę całkowicie POMIŃ "Pierwotny plan na dzień..." oraz "ROZPISKA NA DZIEŃ...", gdyż za nowy plan na cały tydzień odpowiada tryb 'plan').

* **Pierwotny plan na dzień {tomorrow_date_str}** (generuj WYŁĄCZNIE od poniedziałku do soboty; w niedzielę POMIŃ CAŁKOWICIE): {trening_z_planu}
* **DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI**: 
  (W dniach poniedziałek-sobota wybierz jedną z opcji adaptacji:
   - ZWIĘKSZAMY INTENSYWNOŚĆ: trening wykonany ze sporym zapasem, stabilne tętno, dobre HRV/sen – bez wahania zażądaj szybszego tempa lub wyższych obciążeń.
   - POZOSTAJE TAKA SAMA: idealna realizacja założeń, obciążenie w normie planu.
   - ZMNIEJSZAMY INTENSYWNOŚĆ / MODYFIKACJA ZAŁOŻEŃ: wyłącznie przy twardych dowodach przeciążenia CUN, załamaniu HRV/RHR lub alarmujących sygnałach bólowych w notatce.
   W NIEDZIELĘ wybierz wyłącznie ogólny stopień gotowości: [PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]).
* **Uzasadnienie fizjologiczne**: (nie cytuj liczb)
* **ROZPISKA NA DZIEŃ {tomorrow_date_str}** (generuj WYŁĄCZNIE od poniedziałku do soboty; w niedzielę POMIŃ CAŁKOWICIE. Na podstawie planu wybierz właściwy scenariusz i wypisz TYLKO parametry dla planowanego treningu. Zrezygnuj całkowicie z warunkowych etykiet typu "Jeśli bieg:", "Jeśli siłownia:". Od razu wypisz kluczowe punkty):
  
  [Zastosuj ten format dla biegu]:
  * Rozgrzewka: 
  * Część Główna: 
  * Schłodzenie: 
  
  [Zastosuj ten format dla treningu siłowego]:
  * Zestaw / Trening: 
  * Status dolnych partii: [Pełna intensywność / Oszczędzać nogi – rygor RIR >= 2-3, unikać pracy ekscentrycznej i obciążeń osiowych]
  * Potwierdzenie i modyfikacje ćwiczeń: 
  * Wytyczne cardio / rozgrzewki:
  
  [Zastosuj ten format dla Rest Day oraz trenigu innego niż bieg i siłownia]:
  * Wytyczne:
