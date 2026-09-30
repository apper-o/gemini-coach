"""
coach_prompts.py - Moduł generowania promptów dla Gemini, zarządzania historią, notatkami i raportami treningowymi.
"""

import os
import json
import datetime
import logging
import re

from send_telegram import (
    fetch_recent_telegram_messages,
    save_telegram_state,
    markdown_to_html_doc,
    finish_run,
)

logger = logging.getLogger(__name__)

# Stałe globalne
NO_DATA = "Brak danych"
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR = "input"
OUTPUT_DIR = "output"
PROMPTS_DIR = "prompts"
HISTORY_DIR = "trainings_history"
DEBUG_DIR = "debug"

TRAINING_CONFIG_KEYS = (
    "primary_goal", "secondary_goal", "phase", "last_event_date", "height", "weight", "max_hr", "lthr",
    "z1", "z2", "z3", "z4", "z5", "personal_records"
)
UNKNOWN_VALUE_KEYWORDS = frozenset({"nieznany", "brak", "none", "null"})

# Globalny zbiór rozpoznawanych nazw treningów siłowych / uzupełniających (zgodny z input/strength_routines.md)
STRENGTH_WORKOUT_NAMES = frozenset({
    "fbw",
    "upper",
    "lower",
    "core",
    "push",
    "pull",
    "legs",
})
NOTE_KEYWORD = "note"

# Prekompilowane wyrażenia regularne dla parsowania historii i metadanych
RE_RUN_META = re.compile(r'^-\s*Bieg:\s*TAK\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\)', re.MULTILINE)
RE_STR_TAK = re.compile(r'^-\s*Siłownia:\s*TAK', re.MULTILINE)
RE_DAY_TYPE = re.compile(r'^-\s*Typ dnia:\s*([^\n]+)', re.MULTILINE)
RE_RUN_W5 = re.compile(r'^-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\))?', re.MULTILINE)
RE_RUN_TYPE = re.compile(r'^-\s*Typ treningu biegowego:\s*([^\n]+)', re.MULTILINE)
RE_RUN_STRUCT = re.compile(r'^-\s*Struktura biegu:\s*([^\n]+)', re.MULTILINE)
RE_STR_W5 = re.compile(r'^-\s*Siłownia:\s*(TAK|NIE)', re.MULTILINE)
RE_MUSCLE = re.compile(r'^-\s*Partie mięśniowe \(siłownia\):\s*([^\n]+)', re.MULTILINE)
RE_DECISION_CORR = re.compile(r'\*\s*DECYZJA O KOREKCIE[^\n:]*:\s*([^\n]+)', re.IGNORECASE)
RE_DECISION_ACC = re.compile(r'\*\s*Zgodność z planem[^\n:]*:\s*([^\n]+)', re.IGNORECASE)

RE_DIST_FLOAT = re.compile(r'([0-9]+(?:[.,][0-9]+)?)')
RE_PLAN_STRUCT = re.compile(r'Dystans:\s*Plan:[^\n\(]*\(([^)]*(?:rozgrzewk|schłodzen|główn|mp|tempo)[^)]*)\)', re.IGNORECASE)


# ==============================================================================
# PLIKI WEJŚCIOWE, NOTATKA BIEGACZA I HISTORIA 42 DNI
# ==============================================================================

def _normalize_training_parameter(raw_value):
    """
    Czyści i normalizuje pojedynczą wartość parametru treningowego:
    - zamienia None, pusty ciąg oraz słowa kluczowe ('brak', 'nieznany') na NO_DATA ('Brak danych'),
    - dla słowników rekursywnie normalizuje klucze i wartości,
    - dla poprawnych ciągów znaków usuwa zbędne spacje brzegowe (strip).
    """
    if raw_value is None:
        return NO_DATA
    if isinstance(raw_value, dict):
        return { k : _normalize_training_parameter(v) for k, v in raw_value.items() }
    if isinstance(raw_value, str):
        cleaned_text = raw_value.strip()
        if not cleaned_text or cleaned_text.lower() in UNKNOWN_VALUE_KEYWORDS:
            return NO_DATA
        return cleaned_text
    return raw_value


def load_training_config(config_filepath=os.path.join(INPUT_DIR, "training_config.json")):
    """
    Wczytuje kontekst treningowy, strefy tętna, antropometrię i rekordy biegacza z pliku JSON.

    Zasada działania:
    1. Jeśli plik nie istnieje: automatycznie tworzy katalog oraz wypełnia plik domyślnym
       szablonem ze stałymi 'Brak danych', po czym zgłasza FileNotFoundError, aby
       użytkownik uzupełnił go przed pierwszym uruchomieniem.
    2. Jeśli plik istnieje: parsuje zawartość JSON i weryfikuje, czy główną strukturą jest słownik.
       W przypadku błędu odczytu I/O lub składni JSON rzuca RuntimeError.
    3. Scala wczytaną konfigurację z kompletem kluczy domyślnych oraz
       przeprowadza sanityzację wartości (zamienia puste pola i napisy 'brak'/'nieznany' na 'Brak danych').

    Returns:
        dict: Znormalizowany słownik parametrów treningowych.
    """
    default_personal_records = {
        "400m": {"time": NO_DATA, "date": NO_DATA},
        "800m": {"time": NO_DATA, "date": NO_DATA},
        "1500m": {"time": NO_DATA, "date": NO_DATA},
        "5km": {"time": NO_DATA, "date": NO_DATA},
        "10km": {"time": NO_DATA, "date": NO_DATA},
        "polmaraton": {"time": NO_DATA, "date": NO_DATA},
        "maraton": {"time": NO_DATA, "date": NO_DATA},
    }

    # 1. Sprawdzenie istnienia pliku i utworzenie szablonu startowego w razie potrzeby
    os.makedirs(os.path.dirname(config_filepath), exist_ok=True)
    if not os.path.exists(config_filepath):
        default_training_profile = {field: NO_DATA for field in TRAINING_CONFIG_KEYS}
        default_training_profile["personal_records"] = default_personal_records
        try:
            with open(config_filepath, "w", encoding="utf-8") as file_handle:
                json.dump(default_training_profile, file_handle, indent=4, ensure_ascii=False)
            logger.info(f"Utworzono pusty szablon konfiguracji treningowej: {config_filepath}")
        except Exception as write_error:
            logger.error(f"Nie udało się utworzyć pliku szablonu {config_filepath}: {write_error}")

        raise FileNotFoundError(
            f"Nie znaleziono pliku konfiguracji '{config_filepath}'. "
            f"Utworzono domyślny szablon – uzupełnij go przed uruchomieniem."
        )

    # 2. Bezpieczny odczyt i parsowanie pliku JSON
    try:
        with open(config_filepath, "r", encoding="utf-8") as file_handle:
            runner_config = json.load(file_handle)
    except Exception as read_error:
        raise RuntimeError(f"Błąd podczas otwierania lub odczytu pliku konfiguracji '{config_filepath}': {read_error}") from read_error

    # 3. Walidacja typu głównej struktury JSON (wymagany słownik)
    if not isinstance(runner_config, dict):
        raise ValueError(
            f"Plik '{config_filepath}' musi zawierać obiekt JSON (słownik), a otrzymano: {type(runner_config).__name__}"
        )

    # Walidacja struktury celów (brak wstecznej kompatybilności - wymagane obiekty słownikowe)
    for goal_key in ("primary_goal", "secondary_goal"):
        goal_val = runner_config.get(goal_key)
        if not isinstance(goal_val, dict):
            raise ValueError(
                f"Klucz '{goal_key}' w '{config_filepath}' musi być obiektem JSON (słownikiem) z polami 'target', 'date', 'stimulus_share'. Otrzymano: {type(goal_val).__name__}"
            )
        if "target" not in goal_val:
            raise ValueError(f"Obiekt '{goal_key}' w '{config_filepath}' musi zawierać pole 'target'.")
        if "stimulus_share" not in goal_val:
            raise ValueError(f"Obiekt '{goal_key}' w '{config_filepath}' musi zawierać pole 'stimulus_share'.")

    # 4. Scalenie z szablonem bazowym (gwarancja obecności wszystkich wymaganych kluczy)
    default_training_profile = {field: NO_DATA for field in TRAINING_CONFIG_KEYS}
    runner_records = runner_config.get("personal_records")
    if isinstance(runner_records, dict):
        merged_records = {**default_personal_records, **runner_records}
    else:
        merged_records = default_personal_records

    complete_training_config = {**default_training_profile, **runner_config}
    complete_training_config["personal_records"] = merged_records

    # 5. Sanityzacja i normalizacja wszystkich pól do jednolitego formatu
    return {
        param_name: _normalize_training_parameter(param_value)
        for param_name, param_value in complete_training_config.items()
    }


def format_personal_records(records):
    """
    Formatuje rekordy życiowe zawodnika (dystans, czas, data uzyskania) do czytelnego bloku tekstu dla promptu.
    Obsługuje dystanse: 400m, 800m, 1500m, 5km, 10km, półmaraton, maraton.
    """
    if not records or not isinstance(records, dict):
        return "- Brak zarejestrowanych rekordów życiowych."

    distance_definitions = [
        ("400m", "400 m"),
        ("800m", "800 m"),
        ("1500m", "1500 m"),
        ("5km", "5 km"),
        ("10km", "10 km"),
        ("polmaraton", "Półmaraton"),
        ("maraton", "Maraton"),
    ]

    formatted_lines = []
    for dist_key, label in distance_definitions:
        data = records.get(dist_key)
        if isinstance(data, dict):
            time_val = data.get("time", NO_DATA)
            date_val = data.get("date", NO_DATA)
            if time_val != NO_DATA and date_val != NO_DATA:
                formatted_lines.append(f"- {label}: {time_val} (data: {date_val})")
            elif time_val != NO_DATA:
                formatted_lines.append(f"- {label}: {time_val}")
            else:
                formatted_lines.append(f"- {label}: {NO_DATA}")
        elif isinstance(data, str) and data != NO_DATA:
            formatted_lines.append(f"- {label}: {data}")
        else:
            formatted_lines.append(f"- {label}: {NO_DATA}")

    return "\n".join(formatted_lines)


def format_goal(goal_data):
    """
    Formatuje cel biegowy z obiektu słownika zawierającego pola:
    - target: treść celu (np. '5km < 20:00')
    - date: termin startu docelowego (YYYY-MM-DD lub None)
    - stimulus_share: udział procentowy bodźca treningowego (np. 0.75 -> 75%)
    """
    if not isinstance(goal_data, dict):
        raise ValueError(f"Oczekiwano słownika dla celu biegowego, a otrzymano: {type(goal_data).__name__}")

    target = str(goal_data.get("target", NO_DATA)).strip()
    date_val = goal_data.get("date")
    share = goal_data.get("stimulus_share")

    share_str = ""
    if share is not None and share != NO_DATA:
        try:
            share_pct = int(round(float(share) * 100))
            share_str = f" | Udział bodźca: {share_pct}%"
        except (ValueError, TypeError):
            share_str = f" | Udział bodźca: {share}"

    if date_val and date_val != NO_DATA:
        return f"{target} (Termin: {date_val}{share_str})"
    else:
        return f"{target} (Termin: brak / cel ciągły{share_str})"


def calculate_time_left(goal_data, ref_date=None):
    """
    Oblicza pozostały czas do startu na podstawie daty celu głównego ze słownika.
    """
    if not isinstance(goal_data, dict):
        return NO_DATA

    target_date_str = goal_data.get("date")
    if not target_date_str or target_date_str == NO_DATA:
        return NO_DATA

    try:
        ref_d = ref_date or datetime.date.today()
        target_d = datetime.date.fromisoformat(str(target_date_str).strip())
        delta = (target_d - ref_d).days

        if delta < 0:
            return f"Cel minął ({abs(delta)} dni temu, data: {target_date_str})"
        elif delta == 0:
            return f"Dziś dzień startu! ({target_date_str})"
        elif delta == 1:
            return f"1 dzień (jutro start! data: {target_date_str})"
        else:
            weeks = delta // 7
            rem_days = delta % 7
            if weeks > 0 and rem_days > 0:
                weeks_detail = f"{weeks} tyg. i {rem_days} dni"
            elif weeks > 0:
                weeks_detail = f"{weeks} tyg."
            else:
                weeks_detail = f"{delta} dni"
            return f"{delta} dni ({weeks_detail}, data startu: {target_date_str})"
    except Exception as e:
        logger.debug(f"Nie udało się obliczyć czasu do celu: {e}")
        return str(target_date_str)


def format_last_event_info(last_event_date, ref_date=None):
    """
    Formatuje informację o dacie ostatniego startu i liczbie dni, które od niego upłynęły.
    """
    if not last_event_date or last_event_date == NO_DATA:
        return NO_DATA
    try:
        ref_d = ref_date or datetime.date.today()
        ev_d = datetime.date.fromisoformat(str(last_event_date).strip())
        days_ago = (ref_d - ev_d).days
        if days_ago == 0:
            return f"{last_event_date} (dzisiaj)"
        elif days_ago == 1:
            return f"{last_event_date} (wczoraj / 1 dzień temu)"
        elif days_ago > 1:
            return f"{last_event_date} ({days_ago} dni temu)"
        else:
            return f"{last_event_date} (za {abs(days_ago)} dni)"
    except Exception:
        return str(last_event_date)


def build_user_profile(training_context, ref_date=None):
    """
    Formatuje profil zawodnika (cele główny i poboczny z udziałami bodźca, faza treningowa,
    czas do startu, data ostatniego startu, antropometria, strefy tętna Z1-Z5 oraz rekordy PB)
    do postaci słownika parametrów dla promptów.
    """
    if not isinstance(training_context, dict):
        raise ValueError(f"Oczekiwano słownika konfiguracji treningowej, a otrzymano: {type(training_context).__name__}")

    profile = dict(training_context)
    z1 = profile.get("z1", NO_DATA)
    z2 = profile.get("z2", NO_DATA)
    z3 = profile.get("z3", NO_DATA)
    z4 = profile.get("z4", NO_DATA)
    z5 = profile.get("z5", NO_DATA)

    profile["hr_zones"] = f"Z1: {z1}, Z2: {z2}, Z3: {z3}, Z4: {z4}, Z5: {z5}"
    profile["personal_records"] = format_personal_records(profile.get("personal_records"))

    raw_primary = profile.get("primary_goal")
    raw_secondary = profile.get("secondary_goal")

    # Formatowanie celów ze słowników
    profile["primary_goal"] = format_goal(raw_primary)
    profile["secondary_goal"] = format_goal(raw_secondary)

    # Wyodrębnienie szczegółowych pól celów i proporcji bodźców
    p_target = raw_primary.get("target", NO_DATA) if isinstance(raw_primary, dict) else NO_DATA
    s_target = raw_secondary.get("target", NO_DATA) if isinstance(raw_secondary, dict) else NO_DATA
    p_share = raw_primary.get("stimulus_share", 0.75) if isinstance(raw_primary, dict) else 0.75
    s_share = raw_secondary.get("stimulus_share", 0.25) if isinstance(raw_secondary, dict) else 0.25
    p_pct = int(round(float(p_share) * 100)) if isinstance(p_share, (int, float)) else str(p_share)
    s_pct = int(round(float(s_share) * 100)) if isinstance(s_share, (int, float)) else str(s_share)

    profile["primary_stimulus_share"] = f"{p_pct}%"
    profile["secondary_stimulus_share"] = f"{s_pct}%"
    profile["stimulus_distribution"] = f"{p_pct}% cel główny ({p_target}) / {s_pct}% cel poboczny ({s_target})"

    # Dynamiczny czas do celu na podstawie daty w primary_goal
    profile["time_left"] = calculate_time_left(raw_primary, ref_date=ref_date)

    # Informacje o ostatnim starcie
    last_event_date = profile.get("last_event_date")
    if last_event_date and last_event_date != NO_DATA:
        ev_info = format_last_event_info(last_event_date, ref_date=ref_date)
        profile["last_event_info"] = ev_info
        raw_phase = profile.get("phase", NO_DATA)
        if raw_phase != NO_DATA and "ostatni start" not in raw_phase.lower():
            profile["phase"] = f"{raw_phase} (ostatni start: {ev_info})"
    else:
        profile["last_event_info"] = NO_DATA

    return profile


def load_weekly_plan(weekly_plan_file):
    """
    Wczytuje treść planu tygodniowego z pliku Markdown.

    Jeśli plik nie istnieje, zwraca None (plan tygodniowy jest opcjonalny).
    W przypadku błędu otwarcia lub odczytu istniejącego pliku zgłasza RuntimeError.

    Args:
        weekly_plan_file (str): Ścieżka do pliku planu tygodniowego.

    Returns:
        str | None: Zawartość planu tygodniowego lub None, gdy plik nie istnieje.
    """
    if not weekly_plan_file or not os.path.exists(weekly_plan_file):
        return None

    try:
        with open(weekly_plan_file, "r", encoding="utf-8") as file_handle:
            return file_handle.read()
    except Exception as read_error:
        raise RuntimeError(
            f"Błąd podczas otwierania lub odczytu pliku planu tygodniowego '{weekly_plan_file}': {read_error}"
        ) from read_error


def load_strength_routines(strength_routines_file=None):
    """
    Wczytuje bazę własnych zestawów siłowych biegacza (FBW, UPPER, LOWER) z pliku Markdown.

    Jeśli plik nie istnieje, zwraca None (baza ćwiczeń jest opcjonalna).
    W przypadku błędu otwarcia lub odczytu istniejącego pliku zgłasza RuntimeError.

    Args:
        strength_routines_file (str, optional): Ścieżka do pliku z zestawami siłowymi.
            Domyślnie: input/strength_routines.md.

    Returns:
        str | None: Zawartość bazy ćwiczeń siłowych lub None, gdy plik nie istnieje lub jest pusty.
    """
    filepath = strength_routines_file or os.path.join(INPUT_DIR, "strength_routines.md")

    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as file_handle:
            content = file_handle.read().strip()
        if content:
            logger.info(f"Wczytano bazę zestawów siłowych z pliku: {filepath}")
            return content
        return None
    except Exception as read_error:
        raise RuntimeError(
            f"Błąd podczas otwierania lub odczytu pliku zestawów siłowych '{filepath}': {read_error}"
        ) from read_error


def load_prompt_template(filename, **kwargs):
    """
    Wczytuje szablon prompta z folderu prompts/ i podstawia przekazane zmienne {nazwa_zmiennej}.
    """
    prompt_path = os.path.join(PROMPTS_DIR, filename)
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Nie znaleziono pliku szablonu prompta: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    for key, val in kwargs.items():
        template = template.replace(f"{{{key}}}", str(val) if val is not None else "")
    return template


def _classify_telegram_message(body: str) -> tuple[str, str]:
    """
    Klasyfikuje treść pojedynczego bloku wiadomości z Telegrama na podstawie pierwszej linii tekstu.

    Zasady klasyfikacji:
    1. Trening siłowy: Pierwsza niepusta linia zawiera WYŁĄCZNIE nazwę treningu ze zbioru
       STRENGTH_WORKOUT_NAMES (np. 'upper', 'lower', 'fbw', 'core', 'push', 'pull', 'legs').
       Zwraca ('strength', body.strip()).
    2. Notatka biegacza: Pierwsza niepusta linia to WYŁĄCZNIE słowo 'NOTE' (wielkość liter dowolna).
       Kolejne linie zawierają sekcje w formacie:
           nagłówek_i
           notatka do nagłówka_i
       Słowo 'NOTE' z 1. linii jest automatycznie usuwane (stripowane).
       Zwraca ('note', clean_body).
    3. Wiadomość ogólna: Jeśli pierwsza linia nie zawiera ani 'NOTE', ani nazwy treningu siłowego,
       treść jest traktowana jako notatka użytkownika bez zmian.
       Zwraca ('general', body.strip()).

    Returns:
        tuple[str, str]: (typ_wiadomości, przetworzona_treść)
    """
    if not body or not body.strip():
        return ("empty", "")

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ("empty", "")

    first_line_clean = lines[0].strip(":.,!- #*[]()\"'").lower()

    # 1. Kwalifikacja jako trening siłowy
    if first_line_clean in STRENGTH_WORKOUT_NAMES:
        return ("strength", body.strip())

    # 2. Kwalifikacja jako notatka biegacza ze znacznikiem NOTE
    if first_line_clean == NOTE_KEYWORD:
        raw_lines = body.splitlines()
        found_idx = -1
        for idx, r_line in enumerate(raw_lines):
            if r_line.strip().strip(":.,!- #*[]()\"'").lower() == NOTE_KEYWORD:
                found_idx = idx
                break
        if found_idx != -1:
            clean_body = "\n".join(raw_lines[found_idx + 1:]).strip()
            return ("note", clean_body)
        return ("note", body.strip())

    # 3. Wiadomość ogólna / uwagi biegacza
    return ("general", body.strip())


def _is_strength_workout_block(body: str) -> bool:
    """Sprawdza, czy blok wiadomości reprezentuje trening siłowy."""
    msg_type, _ = _classify_telegram_message(body)
    return msg_type == "strength"


def _parse_message_blocks(note: str) -> list[tuple[str, str]]:
    """
    Dzieli notatkę na listę bloków (nagłówek, treść_wiadomości).
    Rozpoznaje nagłówki pojedynczych wiadomości z Telegrama oraz znaczniki systemowe.
    Jeśli notatka nie zawiera nagłówków, zwraca pojedynczy blok ('', note.strip()).
    """
    if not note or not note.strip():
        return []

    # Rozdzielamy zachowując nagłówki za pomocą grupy przechwytującej w re.split
    pattern = r'(\n*---\s*Treść wiadomości z Telegrama[^\n]*---\s*|\n*\[NOWA WIADOMOŚĆ PORANNA\]:\s*|\n*\[RAPORT Z TELEGRAMA\]:\s*)'
    tokens = re.split(pattern, note)

    blocks: list[tuple[str, str]] = []

    # tokens[0] to ewentualna treść przed pierwszym nagłówkiem
    initial_text = tokens[0].strip()
    if initial_text:
        blocks.append(("", initial_text))

    # Kolejne elementy występują parami: (nagłówek, treść)
    for i in range(1, len(tokens), 2):
        header = tokens[i].strip()
        body = tokens[i + 1].strip() if i + 1 < len(tokens) else ""
        if body:
            blocks.append((header, body))

    return blocks


def separate_strength_and_user_notes(note):
    """
    Rozdziela treść notatek użytkownika z Telegrama na:
    1. Treningi siłowe: bloki, w których 1. linijka to nazwa rutyny (fbw, upper, lower, core, push, pull, legs).
    2. Uwagi biegacza: wiadomości rozpoczynające się od słowa 'note` w 1. linijce (ze stripowaniem znacznika note)
       oraz inne ogólne komentarze, z zachowaniem ich znaczników czasowych.

    Returns:
        (strength_workout, remaining_user_note)
        gdzie każda wartość to str lub None.
    """
    if not note or not note.strip():
        return None, None

    blocks = _parse_message_blocks(note)
    if not blocks:
        return None, None

    workout_blocks = []
    note_blocks = []

    for header, body in blocks:
        clean_body = re.sub(r'^\[RAPORT Z TELEGRAMA\]:\s*', '', body, flags=re.IGNORECASE).strip()
        msg_type, processed_body = _classify_telegram_message(clean_body)

        if msg_type == "strength":
            workout_blocks.append(processed_body)
        elif processed_body:
            if header:
                note_blocks.append(f"{header}\n{processed_body}")
            else:
                note_blocks.append(processed_body)

    strength_workout = "\n\n".join(workout_blocks).strip() if workout_blocks else None
    remaining_user_note = "\n\n".join(note_blocks).strip() if note_blocks else None

    return strength_workout, remaining_user_note


def prepare_user_note(note_file=None):
    """
    Wczytuje najnowsze wiadomości i uwagi od biegacza bezpośrednio z czatu Telegrama.
    Parametr note_file jest zachowany dla kompatybilności wstecznej (notatki pochodzą wyłącznie z Telegrama).
    """
    user_note = None
    new_tg_state = None

    try:
        tg_note, new_tg_state = fetch_recent_telegram_messages()
        if tg_note:
            logger.info("Odebrano nową wiadomość z czatu Telegrama.")
            print("\n" + "="*60)
            print("📲 ODEBRANO WIADOMOŚĆ Z TELEGRAMA:")
            print("="*60)
            print(tg_note)
            print("="*60 + "\n")
            user_note = tg_note
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wiadomości z Telegrama: {e}")

    if user_note:
        logger.info("Wczytano notatkę z Telegrama do promptu Trenera Gemini.")
        print(f"📄 Wiadomość dla Trenera Gemini (z Telegrama):\n   \"{user_note}\"\n")

    return user_note, new_tg_state


def _find_history_anchor_date(history_dir, all_files, ref_date):
    """Wyznacza datę bazową (anchor) dla 42-dniowego okna historii treningowej."""
    today_file = os.path.join(history_dir, f"{ref_date.isoformat()}.md")
    if os.path.exists(today_file):
        return ref_date

    # all_files jest posortowane malejąco (reverse=True), więc pierwszy pasujący element to najnowsza data przeszła
    for f in all_files:
        try:
            d = datetime.date.fromisoformat(f[:-3])
            if d <= ref_date:
                return d
        except ValueError:
            pass

    try:
        return datetime.date.fromisoformat(all_files[0][:-3])
    except (ValueError, IndexError):
        return ref_date


def _summarize_history_weeks_1_4(history_data, start_date):
    """
    Generuje podsumowanie tygodni 1–4 (Dni 1–28) historii: kilometry, biegi, siłownia.
    Odczytuje bezpośrednio linie metadanych (- Bieg: i - Siłownia:) z nagłówka każdego pliku raportu.
    """
    weeks_1_4_lines = []
    for w in range(4):
        w_start = start_date + datetime.timedelta(days=w * 7)
        w_end = w_start + datetime.timedelta(days=6)
        w_km = 0.0
        w_runs = 0
        w_strength = 0
        files_found = 0

        for d_offset in range(7):
            cur_d = w_start + datetime.timedelta(days=d_offset)
            date_str = cur_d.isoformat()
            if date_str in history_data:
                files_found += 1
                c = history_data[date_str]
                m_run = RE_RUN_META.search(c)
                m_str = RE_STR_TAK.search(c)

                if m_run:
                    w_km += float(m_run.group(1).replace(',', '.'))
                    w_runs += int(m_run.group(2))
                if m_str:
                    w_strength += 1

        if files_found == 0:
            weeks_1_4_lines.append(f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {NO_DATA}")
        else:
            weeks_1_4_lines.append(
                f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {w_km:.1f} km | Treningi biegowe: {w_runs} | Treningi siłowe: {w_strength}"
            )
    return "\n".join(weeks_1_4_lines)


def _summarize_history_week_5(history_data, start_date):
    """
    Generuje zwarty opis jednostek z tygodnia 5 (Dni 29–35) na podstawie ustandaryzowanego nagłówka metadanych.
    Uwzględnia poszczególne typy treningów, rozgrzewkę, główną serię, schłodzenie, a dla treningów siłowych
    wskaźnik zaangażowanych partii mięśniowych (góra / dół), bez zamieszczania tabel ćwiczeń.
    """
    week_5_lines = []
    w5_start = start_date + datetime.timedelta(days=28)
    for d_offset in range(7):
        cur_d = w5_start + datetime.timedelta(days=d_offset)
        date_str = cur_d.isoformat()
        if date_str not in history_data:
            week_5_lines.append(f"- {date_str} ({DAYS_PL[cur_d.weekday()]}): {NO_DATA}")
            continue

        try:
            c = history_data[date_str]
            day_name = DAYS_PL[cur_d.weekday()]

            m_day_type = RE_DAY_TYPE.search(c)
            m_run = RE_RUN_W5.search(c)
            m_run_type = RE_RUN_TYPE.search(c)
            m_run_struct = RE_RUN_STRUCT.search(c)
            m_str = RE_STR_W5.search(c)
            m_muscle = RE_MUSCLE.search(c)

            is_run = (m_run and m_run.group(1).upper() == "TAK")
            is_str = (m_str and m_str.group(1).upper() == "TAK")

            parts_desc = []

            if is_run:
                run_km_val = m_run.group(2) if m_run and m_run.group(2) else ""
                r_type = m_run_type.group(1).strip() if m_run_type else "Bieg"
                r_struct = m_run_struct.group(1).strip() if m_run_struct else ""
                run_text = f"{r_type} ({run_km_val} km)"
                if r_struct and r_struct != "Brak":
                    run_text += f" [{r_struct}]"
                parts_desc.append(run_text)

            if is_str:
                muscle_val = m_muscle.group(1).strip() if m_muscle else "GÓRA / DÓŁ"
                parts_desc.append(f"Siłownia: partie {muscle_val}")

            if not parts_desc:
                workout_desc = "Dzień wolny / Regeneracja"
            else:
                workout_desc = " + ".join(parts_desc)

            # Ekstrakcja decyzji trenera
            dec_m = RE_DECISION_CORR.search(c)
            if not dec_m:
                dec_m = RE_DECISION_ACC.search(c)
            decision_str = dec_m.group(1).strip() if dec_m else "Zgodnie z planem"

            day_entry = f"- {date_str} ({day_name}): {workout_desc} | Decyzja trenera: {decision_str}"
            week_5_lines.append(day_entry)
        except Exception:
            week_5_lines.append(f"- {date_str} ({DAYS_PL[cur_d.weekday()]}): {NO_DATA}")

    return "\n".join(week_5_lines)


def _load_history_week_6(history_data, start_date):
    """Wczytuje pełne raporty dzienne z tygodnia 6 (Dni 36–42 / ostatnie 7 dni)."""
    week_6_entries = []
    w6_start = start_date + datetime.timedelta(days=35)
    for d_offset in range(7):
        cur_d = w6_start + datetime.timedelta(days=d_offset)
        date_str = cur_d.isoformat()
        if date_str in history_data:
            week_6_entries.append(history_data[date_str])
        else:
            week_6_entries.append(f"### Dzień {date_str} ({DAYS_PL[cur_d.weekday()]}):\n{NO_DATA}")

    return ("\n\n" + "-" * 40 + "\n\n").join(week_6_entries)


def load_training_history(history_dir=HISTORY_DIR, days=42, ref_date=None):
    """
    Wczytuje historię treningów z folderu trainings_history z ostatnich 42 dni (6 tygodni)
    z wielopoziomową szczegółowością:
    - Tygodnie 1–4: podsumowanie makrocyklu (kilometry, treningi biegowe i siłowe).
    - Tydzień 5: zwarty przegląd mezocyklu z pełnymi tabelami ćwiczeń.
    - Tydzień 6: pełne szczegółowe raporty z ostatnich 7 dni.
    """
    if not os.path.exists(history_dir):
        return None

    if ref_date is None:
        ref_date = datetime.date.today()

    all_files = sorted([f for f in os.listdir(history_dir) if f.endswith(".md")], reverse=True)
    if not all_files:
        return None

    anchor_date = _find_history_anchor_date(history_dir, all_files, ref_date)
    start_date = anchor_date - datetime.timedelta(days=41)

    # Jednorazowe odpytanie systemu plików (I/O) i wczytanie danych z ostatnich 42 dni
    history_data = {}
    for d_offset in range(42):
        d_str = (start_date + datetime.timedelta(days=d_offset)).isoformat()
        f_path = os.path.join(history_dir, f"{d_str}.md")
        if os.path.exists(f_path):
            try:
                with open(f_path, "r", encoding="utf-8") as hf:
                    history_data[d_str] = hf.read()
            except Exception as e:
                logger.warning(f"Błąd ładowania pliku historii {f_path}: {e}")

    weeks_1_4 = _summarize_history_weeks_1_4(history_data, start_date)
    week_5 = _summarize_history_week_5(history_data, start_date)
    week_6 = _load_history_week_6(history_data, start_date)

    sections = [
        f"### 1. Podsumowanie makrocyklu (Tygodnie 1–4 / Dni 1–28):\n{weeks_1_4}",
        f"\n### 2. Zwarty przegląd mezocyklu (Tydzień 5 / Dni 29–35):\n{week_5}",
        f"\n### 3. Pełne szczegółowe raporty z ostatniego tygodnia (Tydzień 6 / Dni 36–42):\n{week_6}"
    ]
    return "\n\n".join(sections)


# ==============================================================================
# 2. GENEROWANIE PROMPTÓW DLA GEMINI
# ==============================================================================

def _format_activity_section(activity_stats, date_str, strength_workout=None):
    """
    Formatuje blok Markdown z listą jednostek treningowych i biomechaniką dla promptu.
    Uwzględnia aktywności biegowe oraz opcjonalny trening siłowy (np. zgłoszony przez Telegram).
    """
    parts = []
    if activity_stats:
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        run_blocks = []
        other_blocks = []

        for idx, act in enumerate(stats_list):
            is_run = act.get('is_run', True)
            time_info = f" [Start: {act.get('start_time')}]" if act.get('start_time') and act.get('start_time') != NO_DATA else ""
            prefix = f"[JEDNOSTKA {idx + 1} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")
            
            if is_run:
                splits_text = "Brak szczegółowych splitów dla tej jednostki"
                if act.get('splits'):
                    splits_text = "\n".join(act['splits'])
                
                block = f"""{prefix}{act.get('name')} | {act.get('distance')} w czasie {act.get('duration')} (Średnie tempo: {act.get('pace')})
- Warunki atmosferyczne i pogoda: {act.get('weather', NO_DATA)}
- Przewyższenia (wznios/spadek): +{act.get('elevation_gain')} / -{act.get('elevation_loss')}
- Tętno: Średnie {act.get('avg_hr')} | Maksymalne {act.get('max_hr')}
- Biomechanika kroku:
  * Kadencja: Średnia {act.get('avg_cadence')} | Maksymalna {act.get('max_cadence')}
  * Długość kroku: {act.get('stride_length')}
  * Czas kontaktu z podłożem (GCT): {act.get('ground_contact_time')}
  * Odchylenie pionowe: {act.get('vertical_oscillation')} (Vertical ratio: {act.get('vertical_ratio')})
- Efekt treningowy i moc:
  * Aerobic Training Effect: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')}
  * Średnia moc biegowa: {act.get('avg_power')}
- Splity kilometrowe / odcinki:
{splits_text}"""
                run_blocks.append(block)
            else:
                block = f"""{prefix}TRENING UZUPEŁNIAJĄCY: {act.get('name')} | {act.get('distance')} w czasie {act.get('duration')}
- Tętno: Średnie {act.get('avg_hr')} | Maksymalne {act.get('max_hr')}
- Efekt treningowy: Aerobic TE: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')}
(UWAGA: To nie jest trening biegowy, pomiń go w analizie techniki i splitów. Skup się wyłącznie na jego wpływie na zmęczenie i regenerację organizmu.)"""
                other_blocks.append(block)

        if run_blocks:
            parts.append("-" * 35 + "\n\n" + "\n\n".join(run_blocks))
        if other_blocks:
            parts.append("-" * 35 + "\n\n" + "\n\n".join(other_blocks))
    elif not strength_workout:
        parts.append(f"W dniu {date_str} nie odnotowano treningu biegowego (Dzień wolny / Regeneracja).")

    if strength_workout:
        strength_block = (
            f"[JEDNOSTKA SIŁOWA / UZUPEŁNIAJĄCA (RAPORT Z TELEGRAMA)]:\n"
            f"{strength_workout}"
        )
        parts.append(strength_block)

    return "\n\n".join(parts)


def generate_weekly_suggestions_prompt(training_context, history_context=None, user_note=None, ref_date=None):
    """
    Tworzy prompt dla Gemini w trybie 'suggest' bez przesyłania biometrii z Garmina.
    Model proponuje typy/cele treningów na podstawie profilu biegacza, historii z ostatnich 42 dni i notatki.
    """
    hist_section = history_context if history_context else "Brak zarejestrowanej historii treningów z ostatnich 42 dni."
    note_section = user_note if user_note else "Brak dodatkowych uwag od biegacza."
    profile = build_user_profile(training_context, ref_date=ref_date)

    return load_prompt_template(
        "weekly_suggestions.md",
        **profile,
        hist_section=hist_section,
        note_section=note_section
    )


def generate_weekly_plan_prompt(days_preferences, training_context, history_context=None, user_note=None, strength_routines=None, ref_date=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień.
    """
    hist_section = history_context if history_context else "Brak zarejestrowanej historii treningów z ostatnich 42 dni."
    note_section = user_note if user_note else "Brak dodatkowych uwag od biegacza."
    routines_section = strength_routines if strength_routines else "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."
    profile = build_user_profile(training_context, ref_date=ref_date)

    return load_prompt_template(
        "weekly_plan.md",
        **profile,
        hist_section=hist_section,
        strength_routines=routines_section,
        days_preferences=days_preferences,
        note_section=note_section
    )


def generate_verification_prompt(planned_workout, activity_stats, garmin_stats, weekly_plan_context,
                                 user_profile, user_note, today_date_str=None, yesterday_date_str=None,
                                 tomorrow_date_str=None, trening_z_planu=None, strength_workout=None,
                                 strength_routines=None, audit_date_str=None, target_date_str=None,
                                 history_date_str=None, target_plan_desc=None, day=None):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu oraz całodziennej/nocnej regeneracji
    oraz adaptacji planu na kolejny dzień.
    """
    audit_str = today_date_str or audit_date_str
    history_str = yesterday_date_str or history_date_str
    target_str = tomorrow_date_str or target_date_str
    plan_desc = trening_z_planu or target_plan_desc

    yesterday_section = f"Brak danych z dnia {history_str} (dzień wolny)"
    if garmin_stats.get('yesterday_training') and garmin_stats.get('yesterday_training') != "Brak aktywności (dzień wolny)":
        yesterday_section = f"""
====================
KONTEKST DNIA POPRZEDNIEGO ({history_str}):
{garmin_stats.get('yesterday_training')}
"""

    weekly_plan_section = "Brak planu tygodniowego w pliku output/weekly_plan.md"
    if weekly_plan_context:
        weekly_plan_section = f"""
====================
AKTUALNY PLAN TYGODNIOWY (I KOLEJNE ZAPLANOWANE TRENINGI):
{weekly_plan_context}
"""

    if strength_routines is None:
        try:
            strength_routines = load_strength_routines()
        except Exception:
            strength_routines = None

    routines_section = strength_routines if strength_routines else "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."

    note_content = user_note if user_note else f"Brak dodatkowych uwag od biegacza na dzień {audit_str}."
    activity_section = _format_activity_section(activity_stats, audit_str, strength_workout=strength_workout)

    profile_dict = user_profile if isinstance(user_profile, dict) else {}

    return load_prompt_template(
        "daily_verification.md",
        **profile_dict,
        today_date_str=audit_str,
        yesterday_date_str=history_str,
        tomorrow_date_str=target_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {audit_str}',
        activity_section=activity_section,
        yesterday_section=yesterday_section,
        weekly_plan_section=weekly_plan_section,
        strength_routines=routines_section,
        user_note=note_content,
        trening_z_planu=plan_desc or f"Odszukaj w planie tygodniowym jednostkę na dzień {target_str}",
        today_steps=garmin_stats.get('today_steps', NO_DATA),
        today_stress=garmin_stats.get('today_stress', NO_DATA),
        body_battery=garmin_stats.get('body_battery', NO_DATA),
        hrv_status=garmin_stats.get('hrv_status', NO_DATA),
        rhr=garmin_stats.get('rhr', NO_DATA),
        sleep_score=garmin_stats.get('sleep_score', NO_DATA),
        deep_sleep=garmin_stats.get('deep_sleep', NO_DATA),
        rem_sleep=garmin_stats.get('rem_sleep', NO_DATA),
        sleep_insights=garmin_stats.get('sleep_insights', NO_DATA)
    )


# Alias dla kompatybilności wstecznej (jedna wspólna implementacja)
build_verification_prompt = generate_verification_prompt


# ==============================================================================
# 3. FORMATOWANIE I ZAPIS RAPORTÓW / ARCHIWUM
# ==============================================================================

def _format_acts_archive_blocks(all_stats):
    """Generuje bloki jednostek treningowych do pliku archiwum markdown."""
    acts_archive_blocks = []
    for idx, act_s in enumerate(all_stats):
        is_run = act_s.get('is_run', True)
        time_info = f" [Start: {act_s.get('start_time')}]" if act_s.get('start_time') and act_s.get('start_time') != NO_DATA else ""
        
        if is_run:
            splits_formatted = "\n".join(act_s.get('splits', []))
            if not splits_formatted:
                splits_formatted = "Brak szczegółowych splitów dla tej jednostki"
            single_block = f"""### Jednostka {idx + 1}{time_info}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', NO_DATA)}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
        else:
            single_block = f"""### Trening Uzupełniający {idx + 1}{time_info}: {act_s['name']}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}"""

        acts_archive_blocks.append(single_block)
    return acts_archive_blocks


def save_daily_report(workout_date, archive_content, history_dir=HISTORY_DIR, output_dir=OUTPUT_DIR, debug=False):
    """Zapisuje wygenerowany raport trenera do pliku historii oraz do bieżącego raportu."""
    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        debug_archive_path = os.path.join(DEBUG_DIR, f"{workout_date}.md")
        debug_latest_file = os.path.join(DEBUG_DIR, "last_daily_report.md")

        with open(debug_archive_path, "w", encoding="utf-8") as hf:
            hf.write(archive_content)

        with open(debug_latest_file, "w", encoding="utf-8") as lf:
            lf.write(archive_content)
        print(f"\n✅ [DEBUG] Zapisano raport do: {debug_latest_file} oraz {debug_archive_path} (Pliki produkcyjne nie zostały zmodyfikowane)")

        try:
            debug_latest_html = os.path.join(DEBUG_DIR, "last_daily_report.html")
            html_content = markdown_to_html_doc(archive_content, title=f"Raport Coach Gemini {workout_date} (Debug)")
            with open(debug_latest_html, "w", encoding="utf-8") as hf:
                hf.write(html_content)
            print(f"📄 [DEBUG] Wygenerowano podgląd HTML: {debug_latest_html}")
        except Exception as he:
            logger.warning(f"Nie udało się wygenerować podglądu HTML: {he}")
        return

    history_file_path = os.path.join(history_dir, f"{workout_date}.md")
    latest_daily_file = os.path.join(output_dir, "last_daily_report.md")

    already_existed = os.path.exists(history_file_path)

    with open(history_file_path, "w", encoding="utf-8") as hf:
        hf.write(archive_content)

    with open(latest_daily_file, "w", encoding="utf-8") as lf:
        lf.write(archive_content)

    if already_existed:
        print(f"\n✅ Zaktualizowano (nadpisano) wcześniejszy raport w: {latest_daily_file} oraz archiwum {history_file_path}")
    else:
        print(f"\n✅ Zapisano raport do: {latest_daily_file} oraz archiwum {history_file_path}")

    try:
        latest_daily_html = os.path.join(output_dir, "last_daily_report.html")
        html_content = markdown_to_html_doc(archive_content, title=f"Raport Coach Gemini {workout_date}")
        with open(latest_daily_html, "w", encoding="utf-8") as hf:
            hf.write(html_content)
        print(f"📄 Wygenerowano podgląd HTML: {latest_daily_html}")
    except Exception as he:
        logger.warning(f"Nie udało się wygenerować podglądu HTML: {he}")


def _extract_strength_muscle_groups(strength_workout: str | None) -> tuple[str, str]:
    """
    Wyznacza nazwę treningu siłowego oraz wskaźnik zaangażowanych partii mięśniowych (góra / dół / góra + dół / brak).

    Returns:
        tuple[str, str]: (strength_line, muscle_groups)
        gdzie strength_line to np. 'TAK (UPPER)' lub 'NIE',
        a muscle_groups to np. 'GÓRA', 'DÓŁ', 'GÓRA + DÓŁ', 'BRAK'.
    """
    if not strength_workout or not strength_workout.strip():
        return ("NIE", "BRAK")

    lines = [l.strip() for l in strength_workout.splitlines() if l.strip()]
    first_line_clean = lines[0].strip(":.,!- #*[]()\"'").lower() if lines else ""

    routine_name = lines[0].strip(":.,!- #*[]()\"'").upper() if lines else "TRENING SIŁOWY"
    strength_line = f"TAK ({routine_name})"

    # Klasyfikacja partii mięśniowych
    if first_line_clean in ("upper", "push", "pull"):
        muscle_groups = "GÓRA"
    elif first_line_clean in ("lower", "legs"):
        muscle_groups = "DÓŁ"
    elif first_line_clean in ("fbw",):
        muscle_groups = "GÓRA + DÓŁ"
    elif first_line_clean in ("core",):
        muscle_groups = "CORE / STABILIZACJA"
    else:
        text_lower = strength_workout.lower()
        has_upper = any(w in text_lower for w in ["góra", "klatka", "bench", "press", "row", "pull", "bicep", "tricep", "bark"])
        has_lower = any(w in text_lower for w in ["dół", "nóg", "squat", "przysiad", "deadlift", "calf", "łydk", "thrust"])
        if has_upper and has_lower:
            muscle_groups = "GÓRA + DÓŁ"
        elif has_lower:
            muscle_groups = "DÓŁ"
        elif has_upper:
            muscle_groups = "GÓRA"
        else:
            muscle_groups = "GÓRA / DÓŁ"

    return (strength_line, muscle_groups)


def _extract_run_metadata(all_stats, response_text=None, strength_workout=None) -> tuple[str, str, str, str]:
    """
    Wyciąga ustrukturyzowane metadane biegu: linię biegu, typ treningu, strukturę (rozgrzewka, główna seria, schłodzenie)
    oraz ogólny typ dnia.

    Returns:
        tuple[str, str, str, str]: (run_line, run_type, run_structure, day_type)
    """
    stats_list = all_stats if isinstance(all_stats, list) else ([all_stats] if all_stats else [])
    
    run_stats_list = [act for act in stats_list if act.get("is_run", True)]
    other_stats_list = [act for act in stats_list if not act.get("is_run", True)]

    run_count = len(run_stats_list)
    run_km = 0.0
    for act in run_stats_list:
        d_raw = str(act.get("distance", "0"))
        m = RE_DIST_FLOAT.search(d_raw)
        if m:
            run_km += float(m.group(1).replace(",", "."))

    resp = response_text or ""

    if run_count == 0:
        run_line = "NIE (0.00 km, sesje: 0)"
        run_type = "Brak biegu"
        run_structure = "Brak"
        
        if strength_workout and other_stats_list:
            day_type = "SIŁOWNIA + TRENING UZUPEŁNIAJĄCY"
        elif strength_workout:
            day_type = "SIŁOWNIA"
        elif other_stats_list:
            day_type = "TRENING UZUPEŁNIAJĄCY"
        else:
            day_type = "REGENERACJA"
            
        return (run_line, run_type, run_structure, day_type)

    run_line = f"TAK ({run_km:.2f} km, sesje: {run_count})"
    
    if strength_workout and other_stats_list:
        day_type = "BIEG + SIŁOWNIA + TRENING UZUPEŁNIAJĄCY"
    elif strength_workout:
        day_type = "BIEG + SIŁOWNIA"
    elif other_stats_list:
        day_type = "BIEG + TRENING UZUPEŁNIAJĄCY"
    else:
        day_type = "BIEG"

    # Wykrywanie typu treningu biegowego na podstawie raportu trenera oraz danych aktywności
    run_type = None
    resp_lower = resp.lower()

    # 1. Sprawdzamy jawny profil jednostki biegowej podany przez trenera w sekcji audytu biegowego
    run_section_text = resp
    if "część biegowa" in resp_lower:
        run_section_text = resp[resp_lower.find("część biegowa"):]
        if "część siłowa" in run_section_text.lower():
            run_section_text = run_section_text[:run_section_text.lower().find("część siłowa")]

    m_profile = re.search(r'\*\s*Profil jednostki:\s*([^\n]+)', run_section_text, re.IGNORECASE)
    if m_profile:
        cand = m_profile.group(1).strip().strip("[]")
        if cand and cand.lower() not in ("brak", "n/d", "nie dotyczy", "brak danych"):
            run_type = cand

    # 2. Jeśli brak jawnego profilu w raporcie, sprawdzamy specyficzne nazwy z Garmina (act_names)
    if not run_type:
        act_names = " ".join([str(a.get("name", "")) for a in run_stats_list]).lower()
        if "półmaraton" in act_names:
            run_type = "Półmaraton / Bieg startowy"
        elif "maraton" in act_names:
            run_type = "Maraton / Bieg startowy"
        elif any(k in act_names for k in ["zawody", "bieg startowy", "parkrun", "mistrzostwa", "puchar", "start"]):
            run_type = "Zawody / Bieg startowy"
        elif any(k in act_names for k in ["interwał", "vo2max", "odcinki", "rytm", "podbieg", "intervals", "repeats"]):
            run_type = "Interwały / Próg (VO2max / Threshold)"
        elif any(k in act_names for k in ["tempo", "progowy", "threshold"]):
            run_type = "Bieg progowy / Tempo (Threshold / MP)"
        elif any(k in act_names for k in ["długie wybieganie", "long run", "wybieganie"]):
            run_type = "Długie wybieganie (Long Run)"
        elif any(k in act_names for k in ["recovery", "regenerac", "regeneracyjny"]):
            run_type = "Bieg regeneracyjny (Recovery Run)"
        elif "bieżni" in act_names or "treadmill" in act_names:
            run_type = "Bieg na bieżni mechanicznej (Treadmill)"
        elif "przełajowy" in act_names or "trail" in act_names:
            run_type = "Bieg przełajowy (Trail)"
        elif "lekkoatletyczny" in act_names or "track" in act_names:
            run_type = "Bieg na bieżni lekkoatletycznej (Track)"

    # 3. Pogłębiona analiza kontekstu raportu trenera (resp_lower), gdy brak jawnego profilu i nazwa w Garminie jest domyślna
    if not run_type:
        if any(k in resp_lower for k in ["dzień startowy", "bieg startowy", "start w zawodach", "udział w zawodach"]):
            if "maraton" in resp_lower and any(w in resp_lower for w in ["42.", "królewski", "maraton warszawski", "trasa maratonu"]):
                run_type = "Maraton / Bieg startowy"
            elif "półmaraton" in resp_lower:
                run_type = "Półmaraton / Bieg startowy"
            else:
                run_type = "Zawody / Bieg startowy"
        elif any(k in resp_lower for k in ["trening interwałowy", "interwały", "sesja vo2max", "odcinki robocze", "trening powtórzeniowy", "fartlek", "podbiegi"]):
            run_type = "Interwały / Akcent (VO2max / Threshold)"
        elif any(k in resp_lower for k in ["tempo maratońskie", "blok mp", "akcent mp", "trening progowy", "próg mleczanowy", "lthr", "strefa z4", "strefa z3", "drugi zakres", "ii zakres"]):
            run_type = "Bieg progowy / Tempo (Threshold / MP)"
        elif any(k in resp_lower for k in ["długie wybieganie", "long run", "trening objętościowy", "wybieganie"]):
            run_type = "Długie wybieganie (Long Run)"
        elif any(k in resp_lower for k in ["bieg regeneracyjny", "trucht regeneracyjny", "recovery run", "strefa z1", "regeneracja aktywna"]):
            run_type = "Bieg regeneracyjny (Recovery Run)"
        elif any(k in resp_lower for k in ["baza tlenowa", "bieg spokojny", "strefa z2", "pierwszy zakres", "i zakres", "easy run", "rozbieganie"]):
            run_type = "Bieg spokojny (Easy Run / Z2)"
        else:
            # W przypadku braku specyficznych cech nie zgadujemy "biegu spokojnego", lecz opieramy się na ogólnym charakterze z audytu
            run_type = "Bieg ciągły (według analizy trenera)"

    # Wykrywanie struktury biegu (Rozgrzewka, Główna seria, Schłodzenie)
    run_structure = None
    m_plan_struct = RE_PLAN_STRUCT.search(resp)
    if m_plan_struct:
        raw_struct = m_plan_struct.group(1).strip()
        parts = [p.strip() for p in raw_struct.split(",") if p.strip()]
        warmup_part = "Brak"
        main_part = f"{run_km:.2f} km ({run_type})"
        cool_part = "Brak"
        for p in parts:
            if "rozgrzewk" in p.lower():
                warmup_part = p
            elif "schłodzen" in p.lower():
                cool_part = p
            elif any(k in p.lower() for k in ["mp", "tempo", "część główna", "seria", "z2"]):
                main_part = p
        run_structure = f"Rozgrzewka: {warmup_part} | Główna seria: {main_part} | Schłodzenie: {cool_part}"

    if not run_structure and run_count > 1:
        unit_descs = []
        for idx, a in enumerate(run_stats_list):
            a_name = str(a.get("name", f"Jednostka {idx + 1}"))
            a_dist = str(a.get("distance", ""))
            unit_descs.append(f"{a_name} ({a_dist})")
        run_structure = " + ".join(unit_descs)

    if not run_structure:
        run_structure = f"Rozgrzewka: Brak | Główna seria: {run_km:.2f} km ({run_type}) | Schłodzenie: Brak"

    return (run_line, run_type, run_structure, day_type)


def build_daily_archive_content(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None):
    """
    Formatuje treść raportu dziennego do zapisu w archiwum trainings_history/.
    Na początku pliku zapisywane są ustandaryzowane metadane (typ dnia, bieg, typ treningu, struktura,
    siłownia, wskaźnik partii mięśniowych), a następnie biometria, aktywności, uwagi i odpowiedź trenera.
    """
    acts_title = "Zarejestrowane aktywności"
    strength_part = f"\n### Trening siłowy / uzupełniający (raport z Telegrama):\n{strength_workout}\n" if strength_workout else ""

    # Sprawdzamy czy notatka zawiera uwagi biegacza wykraczające poza sam trening siłowy
    is_only_strength = False
    if strength_workout and user_note:
        cleaned_note = re.sub(r'---\s*Treść wiadomości z Telegrama[^\n]*---\s*', '', user_note)
        cleaned_note = re.sub(r'\[(?:RAPORT Z TELEGRAMA|NOWA WIADOMOŚĆ PORANNA)\]:\s*', '', cleaned_note).strip()
        if cleaned_note == strength_workout.strip():
            is_only_strength = True

    note_part = f"\n## Uwagi biegacza (notatka z Telegrama):\n{user_note.strip()}\n" if (user_note and user_note.strip() and not is_only_strength) else ""

    # Ekstrakcja ustandaryzowanych metadanych
    run_line, run_type, run_structure, day_type = _extract_run_metadata(all_stats, response_text, strength_workout)
    strength_line, muscle_groups = _extract_strength_muscle_groups(strength_workout)

    metadata_header = f"""# AUDYT DZIENNY: {workout_date} ({date_str})
- Typ dnia: {day_type}
- Bieg: {run_line}
- Typ treningu biegowego: {run_type}
- Struktura biegu: {run_structure}
- Siłownia: {strength_line}
- Partie mięśniowe (siłownia): {muscle_groups}"""

    if all_stats and strength_workout:
        acts_part = f"\n## {acts_title}:\n{chr(10).join(_format_acts_archive_blocks(all_stats))}\n{strength_part}"
    elif all_stats:
        acts_part = f"\n## {acts_title}:\n{chr(10).join(_format_acts_archive_blocks(all_stats))}\n"
    elif strength_workout:
        acts_part = f"\n## {acts_title}:{strength_part}"
    else:
        acts_part = ""

    bio_part = f"""## Biometria regeneracyjna i bilans dnia ({date_str}):
- HRV (miniona noc przed treningiem): {garmin_stats.get('hrv_status')}
- RHR (miniona noc przed treningiem): {garmin_stats.get('rhr')}
- Sen (miniona noc przed treningiem): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery pod koniec dnia: {garmin_stats.get('body_battery')}
- Całodzienny stres: {garmin_stats.get('today_stress')}
- Kroki (cały dzień): {garmin_stats.get('today_steps')}"""

    return f"""{metadata_header}

{bio_part}
{acts_part}{note_part}
## Ocena trenera i adaptacja na dzień {next_date_str}:
{response_text}
"""


def build_and_save_daily_archive(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None, debug=False, mode="daily"):
    """
    Formatuje i zapisuje raport dzienny do pliku archiwum w trainings_history/.
    Podsumowuje audytowany dzień (date_str), biometrię snu/dnia oraz adaptację na dzień kolejny (next_date_str).
    Parametr mode jest zachowany dla pełnej kompatybilności wstecznej.
    """
    archive_content = build_daily_archive_content(
        workout_date=workout_date,
        date_str=date_str,
        next_date_str=next_date_str,
        all_stats=all_stats,
        garmin_stats=garmin_stats,
        response_text=response_text,
        strength_workout=strength_workout,
        user_note=user_note
    )
    save_daily_report(workout_date, archive_content, debug=debug)


# Alias dla pełnej kompatybilności wstecznej
_build_and_save_daily_archive = build_and_save_daily_archive

