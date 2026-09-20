# Garmin Coach AI (Gemini Running Assistant)

Inteligentny trener biegania zasilany przez modele Google Gemini oraz integrację z Garmin Connect. Skrypt analizuje biometrię biegacza (sen, HRV, RHR, Body Battery, obciążenie treningowe, biomechanikę biegów) oraz własne bazy ćwiczeń, proponując zbalansowane mikrocykle i codzienne adaptacje treningów.

---

## Szybki Start (Instalacja)

Automatyczne przygotowanie środowiska:
```bash
chmod +x setup.sh run_with_retry.sh
./setup.sh
```

Lub ręcznie:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Konfiguracja (`.env`)

Upewnij się, że plik `.env` zawiera niezbędne zmienne (wzorzec w `.env.example`):
```env
# Klucz Google Gemini API (wymagany)
GEMINI_API_KEY="twój_klucz_api"
GEMINI_MODEL="gemini-3.6-flash"

# Dane logowania Garmin Connect (wymagane w trybie daily, gdy USE_LOCAL_DATA="false")
GARMIN_EMAIL="twoj_email@example.com"
GARMIN_PASSWORD="twoje_haslo"

# Tryb lokalny bez łączenia z serwerami Garmina (wczytuje input/garmin_dump.json)
USE_LOCAL_DATA="true"

# Tryb debugowania
DEBUG="true"
```

---

## Tryby Działania

### 1. Zwykłe uruchomienie:
```bash
python3 garmin_coach.py suggest   # 1. Sugestia podziału dni tygodnia
python3 garmin_coach.py week      # 2. Pełny plan tygodnia z uwzględnieniem strength_routines.md
python3 garmin_coach.py daily     # 3. Codzienna weryfikacja i adaptacja na kolejny dzień
```

### 2. Uruchomienie z automatycznym ponawianiem (Auto-Retry do skutku):
Jeśli Gemini API napotka limit zapytań (429 / 503 / timeout), skrypt ponawia zapytanie z wykładniczym czasem oczekiwania (4s, 8s, 16s, 32s, 64s, 128s, 256s, max 5 min):

```bash
# Wersja Python:
python3 run_with_retry.py suggest
python3 run_with_retry.py week
python3 run_with_retry.py daily

# Lub wersja Bash:
./run_with_retry.sh week
```

---

## Struktura Katalogów

```
├── garmin_coach.py           # Główny skrypt aplikacji
├── run_with_retry.py         # Runner z automatycznym ponawianiem (Python)
├── run_with_retry.sh         # Runner z automatycznym ponawianiem (Bash)
├── requirements.txt          # Zależności Python
├── setup.sh                  # Skrypt instalacji środowiska venv
├── .env                      # Plik konfiguracji i kluczy API
├── .env.example              # Szablon pliku .env
├── input/
│   ├── training_config.json  # Profil biegacza, cele, strefy tętna (Z1-Z5) i tempa
│   ├── weekly_preferences.md # Preferencje podziału dni na dany tydzień
│   ├── strength_routines.md  # Baza własnych zestawów siłowych (UPPER, LOWER, FBW)
│   └── garmin_dump.json      # Zrzut danych Garmin Connect (dla USE_LOCAL_DATA=true)
├── output/
│   ├── weekly_plan.md        # Aktualny tygodniowy plan treningowy
│   └── last_daily_report.md  # Ostatni wygenerowany raport dzienny
├── prompts/
│   ├── weekly_suggestions.md # Szablon prompta dla trybu 'suggest'
│   ├── weekly_plan.md        # Szablon prompta dla trybu 'week'
│   ├── daily_verification.md # Szablon prompta dla trybu 'daily'
│   └── user_note.md          # Bieżące notatki i uwagi biegacza do trenera
└── trainings_history/        # Archiwalne raporty dzienne (YYYY-MM-DD.md)
```
