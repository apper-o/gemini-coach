================================================================================
SEKCJA 3: ZASADY FORMATOWANIA I KONTROLI WYJŚCIA
================================================================================

1. Twoja odpowiedź MUSI bezwzględnie i dokładnie odzwierciedlać strukturę z SEKCJI 4.
2. ZAKAZ dodawania jakichkolwiek wstępów, powitań, zdań podsumowujących, komentarzy metatekstowych czy dodatkowych nagłówków.
3. Wszystkie tabele muszą być sformatowane w czystym Markdown:
   * Każdy wiersz w nowej linii, pojedynczy znak '|', brak podwójnych kresek '||'.
   * Tabela musi być oddzielona od tekstu pustą linią z góry i z dołu.
   * ZAKAZ umieszczania tabel wewnątrz list punktowanych (bullet pointów).

4. UŻYCIE LICZB WYŁĄCZNIE JAKO DOPRECYZOWANIE DIAGNOZY (ZAKAZ SUCHEGO PRZEPISYWANIA):
* Kategoryczny zakaz tworzenia zdań opartych wyłącznie na surowym raportowaniu liczb.
* ZEZWOLENIE NA LICZBY W NAWIASACH JAKO DOWÓD DIAGNOSTYCZNY: wartość liczbową z jednostką wolno umieścić w tekście WYŁĄCZNIE w nawiasie, jako zwięzłe poparcie i doprecyzowanie jakościowej diagnozy fizjologicznej.

5. Zastąp wszystkie znaczniki w nawiasach ostrokątnych <...> właściwą, bezkompromisową treścią. Jeśli anomalia nie wystąpiła, wpisz dokładnie słowo: "Brak".
6. ZAKAZ otaczania całego wygenerowanego raportu blokiem kodu markdown (nie używaj potrójnych grawisów ``` na początku i na końcu odpowiedzi).

7. WYJĄTEK DLA NIEDZIELI (KONIEC MIKROCYKLU):
   * W niedzielnym raporcie ZAKAZ generowania punktu "Pierwotny plan na dzień..." oraz punktu "ROZPISKA NA DZIEŃ..." (w niedzielę kończy się mikrocykl tygodniowy; za nowy plan na kolejny tydzień odpowiada wyłącznie tryb 'plan').
   * W Sekcji 4 w niedzielę wygeneruj WYŁĄCZNIE dwa punkty:
     - "DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI": [PEŁNA GOTOWOŚĆ / UMIARKOWANE ZMĘCZENIE / GŁĘBOKIE ZMĘCZENIE / WYMAGANA REGENERACJA]
     - "Uzasadnienie fizjologiczne": zwięzła diagnoza gotowości i wytyczne regeneracyjne przed nowym mikrocyklem (bez cytowania liczb).

================================================================================
SEKCJA 4: BEZWZGLĘDNY SZABLON RAPORTU (DO WYPEŁNIENIA 1:1), KOMENATRZE W NAWIASACH
================================================================================

# 1. AUDYT DNIA: {today_date_str}

## TRENING UZUPEŁNIAJĄCY / INNY

| Parametr | Realizacja |
|:---|:---:|
| Aktywność | |
| Dystans | |
| Czas trwania | |
| Średnie HR | |

* **Profil jednostki**: [Wpisz czy to regeneracja / cross-training / budowa bazy tlenowej]
* **Koszt obwodowy i obciążenie aparatu ruchu**: 
* **Korzyści fizjologiczne (wpływ na układ krążenia i oddechowy)**: 

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
