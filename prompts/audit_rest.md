# 3. PROTOKÓŁ ANALIZY DNIA REGENERACYJNEGO

Koreluj pasywny i aktywny drenaż organizmu (kroki, stres dzienny, dynamika Body Battery) ze wskaźnikami odnowy autonomicznego układu nerwowego (ANS: HRV, RHR, jakość snu) oraz notatką zawodnika. Brak jednostki treningowej nie oznacza braku kosztu fizjologicznego.

- Zastój limfatyczno-krążeniowy (całkowity bezruch):
  - Warunek: Kroki < 4 000.
  - Diagnoza: Brak pracy pompy mięśniowej; zaleganie płynów śródmiąższowych i spowolniony drenaż metabolitów.
  - Zalecenie: Wdróż 15-20 min luźnego spaceru lub lekką sesję mobilności bioder i stawów skokowych przed snem.
- Stres / przeciążenie układu nerwowego:
  - Warunek: DayStress > 35 + spadek Body Battery w ciągu dnia o > 45 pkt przy braku treningu.
  - Diagnoza: Dominacja układu współczulnego wywołana stresem poznawczym/emocjonalnym; podwyższony kortyzol blokujący procesy naprawcze.
  - Zalecenie: Bezwzględne odcięcie ekranów min. 60 min przed snem, techniki oddechowe (np. wydłużony wydech 4-7-8) i suplementacja magnezu.
- Pozorne nasycenie przywspółczulne:
  - Warunek: Skok HRV > 3.0 powyżej bazy + spadek RHR o >= 4 bpm poniżej normy.
  - Diagnoza: Reakcja obronna ANS na skrajne przemęczenie; fałszywy sygnał „super-gotowości” w algorytmach zegarka.
  - Zalecenie: Unikaj mocnych bodźców termicznych; lekki rozruch adaptacyjny rano przed jutrzejszym biegiem.

3. FILTRY APARATURY I STANU ZAWODNIKA (ZIGNORUJ JAKO BŁĄD):
- Drzemki w ciągu dnia: Chwilowy spadek HR i skok BB podczas popołudniowego spoczynku jest zjawiskiem pożądanym, nie anomalią.
- Późny posiłek / obciążenie trawienne: Skok nocnego tętna (RHR) i spadek HRV w pierwszych 3h snu po kolacji traktuj jako koszt trawienny, nie załamanie wydolności.
- Bolesność mięśniowa (DOMS): Szczyt bolesności przypada na 24–48h po mocnym akcencie lub siłowni. Obecność bolesności bez asymetrii i bez ostrego bólu ścięgien jest prawidłową odpowiedzią adaptacyjną.

# 4. ZASADY FORMATOWANIA I SZABLON WYJŚCIA

1. REGUŁY RAPORTU:
- Format wyjścia: Czysty Markdown. Zacznij bezpośrednio od ## 1. (bez wstępów i bloków kodu).
- W przypadku braku danych dla sekcji: Mocne strony odnowy, Błędy i zakłócenia oraz Kontekst fizjologiczny – całkowicie pomiń daną sekcję.

2. SZABLON RAPORTU:

## 1. AUDYT DNIA REGENERACYJNEGO (REST DAY): {today_date_str}

| Wskaźnik | Wartość | Zakres optymalny | Status |
|:---|:---:|:---:|:---:|
| Kroki (NEAT) | {today_steps} | 6 000 – 10 000 | |
| Stres dzienny | {today_stress} | < 25 | |
| Bilans Body Battery | {morning_body_battery} -> {body_battery} | Δ < 35 pkt | |
| Nocne HRV / RHR | {hrv_last_night} ms / {rhr} bpm | [{hrv_baseline_range}] / {rhr_baseline} | |

* **Typ dnia:** Pełna regeneracja / Rest Day
* **Mocne strony odnowy:** {max 2 parametry sprzyjające adaptacji, poparte danymi; każda obserwacja od nowej linii}
* **Błędy i zakłócenia:** {błędy regeneracji (np. nadmierny NEAT, stres poznawczy, zastój); opis; korekta; od nowej linii}
* **Kontekst fizjologiczny:** {ocena odbudowy zasobów glikogenu, redukcji stanów zapalnych i stanu ANS; od nowej linii}
* **Podsumowanie i gotowość na jutro:** {max 2 zdania podsumowania odnowy; max 2 zdania prognozy pod kątem jutrzejszego treningu z planu.}

## 2. STAN ZASOBÓW I BILANS HOMEOSTAZY

- **Stan układu ruchu**: {1-2 zdania: regeneracja powięziowo-mięśniowa, status mikrourazów i napięć z poprzednich jednostek}
- **Równowaga autonomiczna (ANS)**: {1-2 zdania: poziom wyciszenia współczulnego i jakość doładowania zasobów}
