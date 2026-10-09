# Notatki

Funkcja get_gemini_models() w pliku coach_gemini nie weryfikuje, czy model ma poprawną nazwę. W przypadku niepoprawnej nazwy skrypt nie wykona się poprawnie.

# Coach Gemini AI (Garmin Running Assistant)

Inteligentny asystent treningowy integrujący dane biometryczne i biegowe z **Garmin Connect** z modelami językowymi **Google Gemini** oraz powiadomieniami na **Telegramie**.

Skrypt analizuje całodobową biometrię (sen, HRV, RHR, Body Battery, stres, bilans kroków), biomechanikę biegową (splity, kadencja, czas kontaktu z podłożem, moc, przewyższenia), uwagi i notatki zawodnika z Telegrama oraz historię treningową z ostatnich 42 dni (6 tygodni), proponując optymalne plany treningowe i codzienne adaptacje obciążeń.

---

## Szybki Start (Instalacja)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Konfiguracja (`.env`)

Utwórz plik `.env` w katalogu głównym na podstawie wzorca `.env.example`:

```env
# Modele Google Gemini (kaskada modeli oddzielona przecinkami: główny -> zapasowe)
GEMINI_API_KEY="twój_klucz_api"
GEMINI_MODELS="gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash,gemini-2.5-flash-lite"

# Dane logowania Garmin Connect (wymagane w trybie online)
GARMIN_EMAIL="twoj_email@example.com"
GARMIN_PASSWORD="twoje_haslo"


# Konfiguracja powiadomień Telegram (opcjonalne)
TELEGRAM_BOT_TOKEN="twój_token_z_botfather"
TELEGRAM_CHAT_ID="twój_chat_id"

# Opcjonalny token sesji w base64 (zalecany w GitHub Actions / CI/CD, aby uniknąć błędu 429 Rate Limit)
# GARMIN_TOKENS_BASE64="ey..."
```

### Konfiguracja GitHub Actions (CI/CD)

W ustawieniach repozytorium GitHub (**Settings -> Secrets and variables -> Actions**) zdefiniuj sekrety:
* `GARMIN_EMAIL` oraz `GARMIN_PASSWORD` – dane konta Garmin Connect.
* `GARMIN_TOKENS_BASE64` *(zalecane)* – zawartość lokalnego pliku sesji `~/.garminconnect/garmin_tokens.json` zakodowana w base64. Garmin blokuje logowanie hasłem z serwerów chmurowych (błąd HTTP 429 Rate Limited), dlatego przekazanie gotowego tokena pozwala na bezpośrednie odpytywanie API bez przechodzenia przez SSO.
  * Wygenerowanie na maszynie lokalnej:
    ```bash
    base64 -w 0 ~/.garminconnect/garmin_tokens.json
    ```
* `GEMINI_API_KEY` – klucz API Google AI Studio.
* `TELEGRAM_BOT_TOKEN` oraz `TELEGRAM_CHAT_ID` – dane bota Telegram do wysyłki raportów.

---

## Tryby Uruchomienia (Modes)

Skrypt `coach_gemini.py` przyjmuje jeden pozycyjny argument określający tryb działania:

| Tryb | Opis działania |
| :--- | :--- |
| **`daily`** *(domyślny)* | **Główny wieczorny tryb audytu i adaptacji (uruchamiany codziennie o 20:57)**:<br>• **Główny priorytet**: Dogłębny audyt wykonanego dzisiaj treningu (bieg ze szczegółowymi splitami, tętno, kadencja, tempo vs założenia, trening siłowy/notatki z Telegrama, koszt OUN).<br>• **Biometria**: Analiza nocnej bazy regeneracyjnej przed dzisiejszym wysiłkiem (sen, HRV, RHR), obciążenia całodniowego (stres, kroki, wieczorne Body Battery) oraz kontekstu historycznego z dnia poprzedniego.<br>• **Zalecenia regeneracyjne**: Praktyczne wytyczne na wieczór i noc (zapotrzebowanie na sen pod kątem regeneracji OUN, dedykowana sesja rolowania/mobilności ze wskazaniem konkretnych partii mięśniowych, nawodnienie).<br>• **Gotowość i adaptacja**: Ocena gotowości na jutrzejszy trening wraz z jednoznacznym werdyktem: `[ZWIĘKSZAMY INTENSYWNOŚĆ / POZOSTAJE TAKA SAMA / ZMNIEJSZAMY INTENSYWNOŚĆ / MODYFIKACJA ZAŁOŻEŃ]` i gotową rozpiską.<br>Zapisuje raport do `output/last_daily_report.md` oraz archiwizuje w `trainings_history/YYYY-MM-DD.md`. |
| **`suggest`** | **Sugestia podziału dni i typów treningu**: Model analizuje cele biegacza, fazę przygotowań oraz historię ostatnich 42 dni (6 tygodni), proponując optymalny układ jednostek (Easy, Tempo, Siłownia, Rest Day) na nadchodzący tydzień. Zapisuje propozycję do `input/weekly_preferences.md`. |
| **`plan`** | **Układanie pełnego planu tygodniowego**: Generuje kompletny 7-dniowy plan treningowy od poniedziałku do niedzieli. Wykorzystuje preferencje z `input/weekly_preferences.md`, profil z `input/personal_data.json`, bazę ćwiczeń i aktualne wagi z `input/strength_routines.json` oraz 42-dniową historię. Zapisuje plan do `output/weekly_plan.md`. |

> [!NOTE]
> Wszelkie uwagi, samopoczucie oraz raporty z treningu siłowego przekazywane są bezpośrednio z czatu **Telegrama**. Po każdym pomyślnym wykonaniu analizy stan przeczytanych wiadomości jest zapisywany w `input/telegram_state.json`, dzięki czemu wiadomości nie są dublowane.

---

## Formatowanie Notatek z Telegrama (Komunikacja Zawodnik -> Trener)

Wszelkie uwagi, samopoczucie oraz raporty z treningu siłowego przekazywane są bezpośrednio z czatu **Telegrama**. System automatycznie rozróżnia typ przesyłanej wiadomości na podstawie **pierwszej linijki tekstu**:

### 1. Trening siłowy / uzupełniający (Strength Workout)
- W 1. niepustej linijce musi znajdować się **wyłącznie nazwa zestawu** ze zbioru `STRENGTH_WORKOUT_NAMES` (`upper`, `lower`, `fbw`, `core`, `push`, `pull`, `legs`). Wielkość liter nie ma znaczenia.
- Następnie opcjonalnie data/godzina oraz wykaz wykonanych ćwiczeń, serii, powtórzeń i obciążeń (np. bezpośredni eksport z aplikacji Hevy).
- Treść trafia w całości do sekcji jednostki siłowej promptu, a w archiwum raportu zapisywany jest wskaźnik zaangażowanych partii mięśniowych (`GÓRA`, `DÓŁ`, `GÓRA + DÓŁ`, `CORE / STABILIZACJA`).

**Przykład wiadomości z treningiem siłowym (Hevy):**
```text
upper
Thursday, Sep 24, 2026 at 2:19pm

Bench Press (Barbell)
Set 1: 60 kg x 8
Set 2: 60 kg x 8
Set 3: 60 kg x 8

Lat Pulldown (Cable)
Set 1: 54 kg x 10
Set 2: 55 kg x 8
Set 3: 55 kg x 10
Set 4: 55 kg x 10

Incline Dumbbell Curl
Set 1: 12 kg x 10
Set 2: 12 kg x 10
Set 3: 12 kg x 8

Triceps Pushdown
Set 1: 45 kg x 12
Set 2: 50 kg x 10
Set 3: 50 kg x 10

Ab Wheel
Set 1: 10 reps
Set 2: 10 reps
Set 3: 10 reps
```

### 2. Notatka i uwagi biegacza (Runner Note)
- Wiadomość **zawsze rozpoczyna się od słowa kluczowego `NOTE`** w pierwszej linijce (i tylko tego słowa, wielkość liter dowolna).
- Kolejne linie to pary:
  ```text
  nagłówek_i
  notatka do nagłówka_i
  ```
- Słowo `NOTE` jest automatycznie usuwane (stripowane) podczas wczytywania, dzięki czemu Trener Gemini otrzymuje czyste uwagi z nagłówkami.

**Przykład wiadomości z uwagami biegacza:**
```text
NOTE
Samopoczucie i zmęczenie
Czułem lekkie zmęczenie nóg po wczorajszej siłowni, ale bieg w strefie Z2 wszedł stabilnie. Tętno w normie.

Dolegliwości bólowe
Lekkie spięcie w lewym pasmie biodrowo-piszczelowym pod koniec 8. kilometra, ustąpiło po rolowaniu.

Dieta i nawodnienie
Wypite 3 litry wody z elektrolitami, posiłek regeneracyjny zjedzony 30 min po biegu.
```

### 3. Wiadomości ogólne (Fallback)
Jeśli wiadomość nie zawiera słowa `NOTE` w pierwszej linii ani nazwy treningu siłowego, system traktuje ją tolerancyjnie jako ogólną uwagę biegacza i dołącza do promptu bez modyfikacji.

### 4. Ochrona przed dublowaniem wiadomości
Po każdym pomyślnym wykonaniu analizy identyfikator ostatnio odczytanej wiadomości zapisywany jest w pliku `input/telegram_state.json`, dzięki czemu wiadomości nie są dublowane przy kolejnych uruchomieniach. W trybie `--debug` stan ten nie jest modyfikowany.

---

## Ustandaryzowany Format Archiwum (`trainings_history/YYYY-MM-DD.md`)

Każdy zarchiwizowany raport treningowy zawiera na początku ustandaryzowany blok 6 linii metadanych:
```markdown
# AUDYT DZIENNY: YYYY-MM-DD (DzieńTygodnia, YYYY-MM-DD)
- Typ dnia: BIEG | SIŁOWNIA | BIEG + SIŁOWNIA | REGENERACJA
- Bieg: TAK (X.XX km, sesje: Y) | NIE (0.00 km, sesje: 0)
- Typ treningu biegowego: [nazwa / profil jednostki]
- Struktura biegu: Rozgrzewka: ... | Główna seria: ... | Schłodzenie: ...
- Siłownia: TAK (NAZWA) | NIE
- Partie mięśniowe (siłownia): GÓRA | DÓŁ | GÓRA + DÓŁ | CORE / STABILIZACJA | BRAK
```
Dzięki temu moduł wczytywania historii (`coach_prompts.py`) przetwarza historię 42 dni w złożoności $\mathcal{O}(1)$ bez konieczności przeszukiwania całych plików Markdown czy parsowania tabel serii siłowych.

---

## Flagi CLI

| Flaga | Typ | Domyślnie | Opis |
| :--- | :---: | :---: | :--- |
| **`--debug`** | flaga | `False` | Włącza tryb debugowania. Zapisuje pełną treść promptu przesłanego do Gemini do pliku `debug_log.md` oraz izoluje wyniki w katalogu `debug/`. |
| **`--send_debug`** | flaga | `False` | Włącza tryb debugowania ORAZ wysyła wygenerowany (testowy) raport na Telegram. |
| **`--date YYYY-MM-DD`** | string | data bieżąca | Uruchamia skrypt z określoną datą referencyjną zamiast dzisiejszej (np. `--date 2026-09-22`). Przydatne do testów, symulacji oraz ponownego przeliczania raportów archiwalnych. |
| **`-h`, `--help`** | flaga | — | Wyświetla wbudowaną pomoc CLI i listę dostępnych opcji. |

---

## Przykłady Użycia

```bash
# 1. Główny wieczorny audyt dnia i adaptacja na jutro (godz. 20:57)
python coach_gemini.py
# lub jawnie:
python coach_gemini.py daily

# 2. Wygenerowanie sugestii podziału dni na nadchodzący tydzień
python coach_gemini.py suggest

# 3. Rozpisanie szczegółowego planu na cały tydzień
python coach_gemini.py plan

# 4. Uruchomienie w trybie debugowania (piaskownica w debug/)
python coach_gemini.py daily --debug

# 5. Audyt historyczny dla konkretnego dnia
python coach_gemini.py daily --date 2026-09-20
```

---

## Struktura Projektu

```
├── coach_gemini.py           # Główny skrypt aplikacji (CLI, kaskada Gemini API, orkiestracja trybów)
├── garmin_service.py         # Moduł komunikacji z Garmin Connect oraz parserów biometrii i biegów
├── coach_prompts.py          # Moduł prompt engineeringu, historii 42 dni i archiwizacji raportów
├── send_telegram.py          # Integracja z Telegram Bot API (wysyłka raportów HTML, odczyt uwag/Hevy)
├── requirements.txt          # Zależności Python
├── .env                      # Konfiguracja środowiskowa i klucze API (lokalna, ignorowana przez git)
├── .env.example              # Wzorzec pliku konfiguracyjnego .env
├── input/
│   ├── personal_data.json  # Profil biegacza, cel główny i poboczny (primary_goal, secondary_goal), wzrost, waga, rekordy życiowe (PB), strefy tętna (Z1-Z5)
│   ├── weekly_preferences.md # Podział dni treningowych na dany tydzień (dla trybu 'plan')
│   ├── strength_routines.json # Baza własnych zestawów ćwiczeń siłowych oraz aktualnych wag (FBW, UPPER, LOWER)
├── output/
│   ├── weekly_plan.md        # Aktualny plan treningowy na tydzień
│   └── last_daily_report.md  # Ostatni wygenerowany raport trenerski
├── prompts/
│   ├── weekly_suggestions.md # Szablon prompta dla trybu 'suggest'
│   ├── weekly_plan.md        # Szablon prompta dla trybu 'plan'
│   └── daily_verification.md # Szablon prompta dla wieczornego trybu 'daily' (audyt, regeneracja, adaptacja)
└── trainings_history/        # Archiwum wygenerowanych raportów dziennych (YYYY-MM-DD.md)
```
