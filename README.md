# Notatki

Funkcja get_gemini_models() w pliku coach_gemini nie weryfikuje, czy model ma poprawną nazwę. W przypadku niepoprawnej nazwy skrypt nie wykona się poprawnie.

# Coach Gemini AI (Garmin Running Assistant)

Inteligentny asystent treningowy integrujący dane biometryczne i biegowe z **Garmin Connect** z modelami językowymi **Google Gemini** oraz powiadomieniami na **Telegramie**.

Skrypt analizuje całodobową biometrię (sen, HRV, RHR, Body Battery, stres, bilans kroków), biomechanikę biegową (splity, kadencja, czas kontaktu z podłożem, moc, przewyższenia) oraz historię treningową z ostatnich 42 dni (6 tygodni), proponując optymalne plany treningowe i codzienne adaptacje obciążeń.

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
GEMINI_MODELS="gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.0-flash-lite"

# Dane logowania Garmin Connect (wymagane w trybie online)
GARMIN_EMAIL="twoj_email@example.com"
GARMIN_PASSWORD="twoje_haslo"

# Tryb lokalny (true = wczytuje dane z pliku input/garmin_dump.json bez łączenia z Garminem)
USE_LOCAL_DATA="false"

# Konfiguracja powiadomień Telegram (opcjonalne)
TELEGRAM_BOT_TOKEN="twój_token_z_botfather"
TELEGRAM_CHAT_ID="twój_chat_id"
```

---

## Tryby Uruchomienia (Modes)

Skrypt `coach_gemini.py` przyjmuje jeden pozycyjny argument określający tryb działania:

| Tryb | Opis działania |
| :--- | :--- |
| **`daily`** *(domyślny)* | **Inteligentny tryb automatyczny**: Automatycznie decyduje o wyborze zakresu weryfikacji na podstawie pory dnia:<br>• **Przed godziną 12:00**: Automatycznie uruchamia audyt wczorajszego dnia (`yesterday`) i adaptację na dziś po nocy regeneracyjnej.<br>• **Od godziny 12:00**: Automatycznie uruchamia weryfikację dzisiejszego dnia (`today`) i adaptację na jutro.<br>Uruchamiany także przy wywołaniu bez argumentów (`python coach_gemini.py`). |
| **`today`** | **Weryfikacja bieżącego dnia i adaptacja na jutro**: Pobiera dane z dzisiejszego dnia (wykonany trening, kroki, stres) oraz minionej nocy (HRV, RHR, jakość snu, Body Battery). Ocenia realizację założeń i wyznacza adaptację planu na kolejny dzień. Zapisuje raport do `output/last_daily_report.md` oraz archiwizuje w `trainings_history/`. |
| **`yesterday`** | **Audyt wczorajszego dnia i adaptacja na dziś**: Audytuje dzień wczorajszy (treningi, obciążenie, stres, wieczorne Body Battery) oraz minioną noc i dzisiejszy poranek (HRV z nocy, RHR, sen, poranne Body Battery). Dokonuje natychmiastowej korekty i adaptacji treningu na dzień dzisiejszy. Standardowy tryb porannego harmonogramu GitHub Actions. |
| **`suggest`** | **Sugestia podziału dni i typów treningu**: Model analizuje cele biegacza, fazę przygotowań oraz historię ostatnich 42 dni (6 tygodni), proponując optymalny układ jednostek (Easy, Tempo, Siłownia, Rest Day) na nadchodzący tydzień. Zapisuje propozycję do `input/weekly_preferences.md`. |
| **`plan`** | **Układanie pełnego planu tygodniowego**: Generuje kompletny 7-dniowy plan treningowy od poniedziałku do niedzieli. Wykorzystuje preferencje z `input/weekly_preferences.md`, profil z `input/training_config.json`, bazę ćwiczeń z `input/strength_routines.md` oraz 42-dniową historię. Zapisuje plan do `output/weekly_plan.md`. |

> [!NOTE]
> Po każdym pomyślnym wykonaniu dowolnego trybu, zawartość pliku `prompts/user_note.md` jest automatycznie czyszczona, aby jednorazowe notatki nie przechodziły na kolejne dni.

---

## Flagi CLI

| Flaga | Typ | Domyślnie | Opis |
| :--- | :---: | :---: | :--- |
| **`--debug`** | flaga | `False` | Włącza tryb debugowania. Zapisuje pełną treść promptu przesłanego do Gemini do pliku `debug_log.md` oraz izoluje wyniki w katalogu `debug/`. |
| **`--date YYYY-MM-DD`** | string | data bieżąca | Uruchamia skrypt z określoną datą referencyjną zamiast dzisiejszej (np. `--date 2026-09-22`). Przydatne do testów, symulacji oraz ponownego przeliczania raportów archiwalnych. |
| **`-h`, `--help`** | flaga | — | Wyświetla wbudowaną pomoc CLI i listę dostępnych opcji. |

---

## Przykłady Użycia

```bash
# 1. Inteligentny tryb daily (przed 12:00 weryfikuje wczoraj, po 12:00 dzisiaj)
python coach_gemini.py
# lub jawnie:
python coach_gemini.py daily

# 2. Wymuszenie audytu dnia wczorajszego i adaptacji na dziś (np. rano)
python coach_gemini.py yesterday

# 3. Wymuszenie weryfikacji dzisiejszego treningu i adaptacji na jutro (np. wieczorem)
python coach_gemini.py today

# 4. Wygenerowanie sugestii podziału dni na nadchodzący tydzień
python coach_gemini.py suggest

# 5. Rozpisanie szczegółowego planu na cały tydzień
python coach_gemini.py plan

# 6. Uruchomienie w trybie debugowania (piaskownica w debug/)
python coach_gemini.py daily --debug

# 7. Audyt historyczny dla konkretnego dnia
python coach_gemini.py yesterday --date 2026-09-20
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
│   ├── training_config.json  # Profil biegacza, cele startowe, strefy tętna (Z1-Z5)
│   ├── weekly_preferences.md # Podział dni treningowych na dany tydzień (dla trybu 'plan')
│   ├── strength_routines.md  # Baza własnych zestawów ćwiczeń siłowych (FBW, UPPER, LOWER)
│   └── garmin_dump.json      # Zrzut danych Garmin Connect (dla USE_LOCAL_DATA=true)
├── output/
│   ├── weekly_plan.md        # Aktualny plan treningowy na tydzień
│   └── last_daily_report.md  # Ostatni wygenerowany raport trenerski
├── prompts/
│   ├── weekly_suggestions.md # Szablon prompta dla trybu 'suggest'
│   ├── weekly_plan.md        # Szablon prompta dla trybu 'plan'
│   ├── daily_verification.md # Szablon prompta dla trybu 'daily'
│   ├── yesterday_verification.md # Szablon prompta dla trybu 'yesterday'
│   └── user_note.md          # Jednorazowa notatka biegacza do trenera (czyszczona po uruchomieniu)
└── trainings_history/        # Archiwum wygenerowanych raportów dziennych (YYYY-MM-DD.md)
```
