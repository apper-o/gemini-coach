"""
coach_prompts.py - Moduł generowania promptów dla Gemini, zarządzania historią, notatkami i raportami treningowymi.
"""

import os
import json
import datetime
import logging
import re

from utils_html import markdown_to_html_doc
from send_telegram import (
    fetch_recent_telegram_messages,
)

logger = logging.getLogger(__name__)

# Stałe globalne
NO_DATA = "Brak danych"
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR_PATH = "input"
OUTPUT_DIR_PATH = "output"
PROMPTS_DIR_PATH = "prompts"
HISTORY_DIR_PATH = "trainings_history"
DEBUG_DIR_PATH = "debug"

PERSONAL_DATA_KEYS = (
    "primary_goal", "secondary_goal", "phase", "last_event",
    "height", "weight", "lthr",
    "hr_zones", "pace_zones",
    "personal_records", "additional_notes"
)
ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")
UNKNOWN_VALUE_KEYWORDS = frozenset({"nieznany", "brak", "none", "null"})

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
RE_RUN_META = re.compile(r'^-\s*Bieg:\s*TAK(?:\s*\(([0-9.,]+)\s*km(?:,\s*sesje:\s*([0-9]+))?\))?', re.MULTILINE)
RE_STR_TAK = re.compile(r'^-\s*Siłownia:\s*TAK', re.MULTILINE)
RE_RUN_W5 = re.compile(r'^-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\))?', re.MULTILINE)
RE_RUN_TYPE = re.compile(r'^-\s*Typ treningu biegowego:\s*([^\n]+)', re.MULTILINE)
RE_RUN_STRUCT = re.compile(r'^-\s*Struktura biegu:\s*([^\n]+)', re.MULTILINE)
RE_STR_W5 = re.compile(r'^-\s*Siłownia:\s*(TAK|NIE)', re.MULTILINE)
RE_MUSCLE = re.compile(r'^-\s*Partie mięśniowe \(siłownia\):\s*([^\n]+)', re.MULTILINE)
RE_COACH_DECISION = re.compile(
    r'^[*-]?\s*\*?\*?(?:DECYZJA ADAPTACYJNA(?:\s*/\s*STOPIEŃ GOTOWOŚCI)?|DECYZJA O KOREKCIE|STOPIEŃ GOTOWOŚCI|Decyzja trenera|Zgodność z planem)[^\n:]*:\s*(?:\n\s*)?([^\n|]+)',
    re.MULTILINE | re.IGNORECASE
)
RE_PROFILE_HEADER = re.compile(r'^[*-]?\s*\*?\*?Profil jednostki\*?\*?:\s*([^\n\r]+)', re.MULTILINE | re.IGNORECASE)

RE_DIST_FLOAT = re.compile(r'([0-9]+(?:[.,][0-9]+)?)')
RE_PLAN_STRUCT = re.compile(r'Dystans:\s*Plan:[^\n\(]*\(([^)]*(?:rozgrzewk|schłodzen|główn|mp|tempo)[^)]*)\)', re.IGNORECASE)

# Wyrażenia regularne do parsowania notatek z aplikacji Hevy (trening siłowy)
RE_SET_BODYWEIGHT = re.compile(r'^[*-]?\s*Set\s+(\d+):\s*(?:(\d+)\s*reps\b|(?:mc|bodyweight)\s*x\s*(\d+))', re.IGNORECASE)
RE_SET_PLUS_WEIGHT = re.compile(r'^[*-]?\s*Set\s+(\d+):\s*\+([0-9.,]+\s*kg)\s*x\s*(\d+)', re.IGNORECASE)
RE_SET_WEIGHT = re.compile(r'^[*-]?\s*Set\s+(\d+):\s*([0-9.,]+(?:\s*(?:kg(?:/[a-ząćęłńóśźż]+)?))?)\s*x\s*(\d+)', re.IGNORECASE)
RE_DATE_HEURISTIC = re.compile(
    r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|'
    r'Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela|'
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b|'
    r'\d{4}-\d{2}-\d{2}|at\s+\d{1,2}:\d{2})',
    re.IGNORECASE
)
ROUTINES_JSON_PATH = os.path.join(INPUT_DIR_PATH, "strength_routines.json")
EVENING_ROUTINE_PATH = os.path.join(INPUT_DIR_PATH, "evening_routine.md")


# ==============================================================================
# PLIKI WEJŚCIOWE, NOTATKA BIEGACZA I HISTORIA 42 DNI
# ==============================================================================

def _re_first(pattern, text, default="", flags=0):
    """Zwraca pierwszą grupę dopasowania wyrażenia regularnego (po strip) lub wartość domyślną."""
    if not text:
        return default
    m = pattern.search(text) if hasattr(pattern, "search") else re.search(pattern, text, flags)
    return m.group(1).strip() if m and m.group(1) else default


def _read_file_safe(filepath, default_return=None):
    """
    Bezpiecznie odczytuje plik tekstowy.

    Args:
        filepath (str): Ścieżka do pliku.
        default_return (any, optional): Wartość do zwrotu w przypadku błędu. Defaults to None.

    Returns:
        str: Zawartość pliku, lub default_return jeśli plik nie istnieje.
    """
    if not filepath or not os.path.exists(filepath):
        return default_return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"Błąd odczytu pliku {filepath}: {e}") from e


def _normalize_training_parameter(raw_value):
    """
    Czyści i normalizuje pojedynczą wartość parametru treningowego.

    Zasada działania:
    - zamienia None, pusty ciąg oraz słowa kluczowe ('brak', 'nieznany') na NO_DATA ('Brak danych'),
    - dla słowników rekursywnie normalizuje klucze i wartości,
    - dla poprawnych ciągów znaków usuwa zbędne spacje brzegowe (strip).

    Args:
        raw_value: Surowa wartość do znormalizowania.

    Returns:
        Znormalizowana wartość lub znormalizowany słownik.
    """
    if raw_value is None:
        return NO_DATA
    if isinstance(raw_value, dict):
        return {k: _normalize_training_parameter(v) for k, v in raw_value.items()}
    if isinstance(raw_value, str):
        cleaned_text = raw_value.strip()
        if not cleaned_text or cleaned_text.lower() in UNKNOWN_VALUE_KEYWORDS:
            return NO_DATA
        return cleaned_text
    return raw_value


def load_personal_data(filepath=os.path.join(INPUT_DIR_PATH, "personal_data.json")):
    """
    Wczytuje dane o zawodniku z pliku JSON.

    Zasada działania:
    1. Jeśli plik nie istnieje: automatycznie tworzy katalog oraz wypełnia plik domyślnym
       szablonem ze stałymi 'Brak danych', po czym zgłasza FileNotFoundError, aby
       użytkownik uzupełnił go przed pierwszym uruchomieniem.
    2. Jeśli plik istnieje: parsuje zawartość JSON i weryfikuje, czy główną strukturą jest słownik.
       W przypadku błędu odczytu I/O lub składni JSON rzuca RuntimeError.
    3. Scala wczytaną konfigurację z kompletem kluczy domyślnych oraz zamienia puste pola na 'Brak danych'.

    Args:
        filepath (str): Ścieżka do pliku konfiguracji.

    Returns:
        dict: Znormalizowany słownik parametrów treningowych.
    """
    default_zones = {z: NO_DATA for z in ZONE_KEYS}
    default_last_event = {"type": NO_DATA, "time": NO_DATA, "date": NO_DATA}
    default_personal_records = {
        dist: NO_DATA
        for dist in ("400m", "800m", "1500m", "5km", "10km", "polmaraton", "maraton")
    }
    default_personal_data = {
        **{field: NO_DATA for field in PERSONAL_DATA_KEYS},
        "last_event": dict(default_last_event),
        "hr_zones": dict(default_zones),
        "pace_zones": dict(default_zones),
        "personal_records": dict(default_personal_records),
    }

    # 1. Sprawdzenie istnienia pliku i utworzenie szablonu startowego w razie potrzeby
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if not os.path.exists(filepath):
        try:
            with open(filepath, "w", encoding="utf-8") as file_handle:
                json.dump(default_personal_data, file_handle, indent=4, ensure_ascii=False)
            logger.info(f"Utworzono pusty szablon danych o zawodniku: {filepath}")
        except Exception as write_error:
            logger.error(f"Nie udało się utworzyć pliku szablonu {filepath}: {write_error}")

        raise FileNotFoundError(
            f"Nie znaleziono pliku konfiguracji '{filepath}'. "
            f"Utworzono domyślny szablon – uzupełnij go przed uruchomieniem."
        )

    # 2. Odczyt i parsowanie pliku JSON
    try:
        with open(filepath, "r", encoding="utf-8") as file_handle:
            runner_config = json.load(file_handle)
    except Exception as read_error:
        raise RuntimeError(f"Błąd podczas otwierania lub odczytu pliku konfiguracji '{filepath}': {read_error}") from read_error

    # 3. Walidacja typu głównej struktury JSON (wymagany słownik)
    if not isinstance(runner_config, dict):
        raise ValueError(
            f"Plik '{filepath}' musi zawierać obiekt JSON (słownik), a otrzymano: {type(runner_config).__name__}"
        )

    for goal_key in ("primary_goal", "secondary_goal"):
        goal_val = runner_config.get(goal_key)
        if not isinstance(goal_val, dict):
            raise ValueError(
                f"Klucz '{goal_key}' w '{filepath}' musi być obiektem JSON (słownikiem) z polami 'target', 'date'. Otrzymano: {type(goal_val).__name__}"
            )
        if "target" not in goal_val:
            raise ValueError(f"Obiekt '{goal_key}' w '{filepath}' musi zawierać pole 'target'.")

    # 4. Scalenie z szablonem bazowym (gwarancja obecności wszystkich wymaganych kluczy)
    runner_last_event = runner_config.get("last_event")
    merged_last_event = (
        {**default_last_event, **runner_last_event}
        if isinstance(runner_last_event, dict)
        else (runner_last_event or dict(default_last_event))
    )
    runner_hr_zones = runner_config.get("hr_zones")
    merged_hr_zones = {**default_zones, **runner_hr_zones} if isinstance(runner_hr_zones, dict) else dict(default_zones)

    runner_pace_zones = runner_config.get("pace_zones")
    merged_pace_zones = {**default_zones, **runner_pace_zones} if isinstance(runner_pace_zones, dict) else dict(default_zones)

    runner_records = runner_config.get("personal_records")
    merged_records = {**default_personal_records, **runner_records} if isinstance(runner_records, dict) else dict(default_personal_records)

    complete_personal_data = {
        **default_personal_data,
        **runner_config,
        "last_event": merged_last_event,
        "hr_zones": merged_hr_zones,
        "pace_zones": merged_pace_zones,
        "personal_records": merged_records,
    }

    # 5. Sanityzacja i normalizacja wszystkich pól do jednolitego formatu
    return {
        param_name: _normalize_training_parameter(param_value)
        for param_name, param_value in complete_personal_data.items()
    }


def format_personal_records(records):
    """
    Formatuje rekordy życiowe zawodnika do zwięzłego, jednoliniowego zapisu dla promptu
    (pomija dystanse bez zarejestrowanego wyniku).

    Args:
        records (dict): Słownik zawierający rekordy życiowe.

    Returns:
        str: Sformatowany tekst z rekordami życiowymi.
    """
    if not records or not isinstance(records, dict):
        return NO_DATA

    entries = [
        f"{distance}: {val}"
        for distance, val in records.items()
        if isinstance(val, str) and val and val != NO_DATA
    ]
    return " | ".join(entries) if entries else NO_DATA


def format_goal(goal_data, ref_date=None):
    """
    Formatuje cel biegowy z obiektu słownika, uwzględniając czas względny do startu.

    Args:
        goal_data (dict): Słownik zawierający dane celu (target, date).
        ref_date (datetime.date, optional): Data odniesienia do wyliczenia relacji czasowej.

    Returns:
        str: Sformatowany opis celu biegowego.
    """
    if not isinstance(goal_data, dict):
        return str(goal_data or NO_DATA).strip()

    target = str(goal_data.get("target", NO_DATA)).strip()
    date_val = goal_data.get("date")
    if date_val and date_val != NO_DATA:
        time_rel = format_relative_time(date_val, ref_date=ref_date)
        time_str = f", {time_rel}" if time_rel and time_rel != NO_DATA else ""
        return f"{target} (Termin: {date_val}{time_str})"

    return f"{target} (Termin: brak)"


def format_relative_time(date_str, ref_date=None):
    """
    Oblicza różnicę czasu między datą odniesienia a podaną datą i zwraca sformatowany tekst.

    Args:
        date_str (str): Data wydarzenia/celu.
        ref_date (datetime.date, optional): Data odniesienia, domyślnie dzisiaj.

    Returns:
        str: Sformatowany tekst z informacją o czasie (np. 'za 5 dni' lub '5 dni temu').
    """
    if not date_str or date_str == NO_DATA:
        return NO_DATA

    try:
        ref_d = ref_date or datetime.date.today()
        ev_d = datetime.date.fromisoformat(str(date_str).strip())
        delta = (ev_d - ref_d).days
        return f"{abs(delta)} dni temu" if delta < 0 else (f"za {delta} dni" if delta > 0 else "dzisiaj")
    except Exception as e:
        logger.debug(f"Nie udało się obliczyć czasu dla daty {date_str}: {e}")
        return str(date_str)


def format_last_event(event_data, ref_date=None):
    """
    Formatuje informacje o ostatnim starcie zawodnika z obiektu słownika lub tekstu.

    Args:
        event_data (dict | str): Słownik zawierający dane startu (type, time, date) lub tekst.
        ref_date (datetime.date, optional): Data odniesienia do wyliczenia relacji czasowej.

    Returns:
        str: Sformatowany opis ostatniego startu lub NO_DATA.
    """
    if not event_data or event_data == NO_DATA:
        return NO_DATA
    if not isinstance(event_data, dict):
        return str(event_data).strip()

    ev_type, ev_time, ev_date = (
        "" if (v := str(event_data.get(k) or "").strip()) == NO_DATA else v
        for k in ("type", "time", "date")
    )
    if not (ev_type or ev_time or ev_date):
        return NO_DATA

    prefix = f"{ev_type}: {ev_time}" if (ev_type and ev_time) else (ev_type or ev_time)
    if ev_date:
        time_rel = format_relative_time(ev_date, ref_date=ref_date)
        date_parts = [f"data: {ev_date}", *([time_rel] if time_rel and time_rel != NO_DATA else [])]
        return f"{prefix} ({', '.join(date_parts)})".strip() if prefix else ", ".join(date_parts)
    return prefix or NO_DATA


def build_user_profile(personal_data, ref_date=None):
    """
    Formatuje profil zawodnika do postaci słownika parametrów dla szablonów promptów.

    Args:
        personal_data (dict): Dane zawodnika (strefy tętna i tempa, cele, rekordy PB, antropometria).
        ref_date (datetime.date, optional): Data odniesienia do wyznaczania relacji czasowych.

    Returns:
        dict: Sformatowany słownik profilu użytkownika.
    """
    if not isinstance(personal_data, dict):
        raise ValueError(f"Oczekiwano słownika konfiguracji treningowej, a otrzymano: {type(personal_data).__name__}")

    profile = dict(personal_data)

    # 1. Strefy tętna (hr_zones -> z1..z5) i strefy tempa (pace_zones -> pace_z1..pace_z5)
    hr_zones = profile.get("hr_zones") if isinstance(profile.get("hr_zones"), dict) else {}
    pace_zones = profile.get("pace_zones") if isinstance(profile.get("pace_zones"), dict) else {}
    for z_key in ZONE_KEYS:
        profile[z_key] = hr_zones.get(z_key, profile.get(z_key, NO_DATA))
        profile[f"pace_{z_key}"] = pace_zones.get(z_key, profile.get(f"pace_{z_key}", NO_DATA))

    # 2. Rekordy życiowe (PB) oraz cele biegowe (główny i poboczny)
    profile["personal_records"] = format_personal_records(profile.get("personal_records"))
    profile["primary_goal"] = format_goal(profile.get("primary_goal") if isinstance(profile.get("primary_goal"), dict) else {}, ref_date=ref_date)
    profile["secondary_goal"] = format_goal(profile.get("secondary_goal") if isinstance(profile.get("secondary_goal"), dict) else {}, ref_date=ref_date)

    # 3. Dodatkowe notatki zawodnika (zwięzły zapis liniowy pasujący do <athlete_profile>)
    notes = profile.get("additional_notes", [])
    if isinstance(notes, list):
        clean_notes = [str(n).strip() for n in notes if str(n).strip() and str(n).strip() != NO_DATA]
        profile["additional_notes"] = " | ".join(clean_notes) if clean_notes else "Brak stałych uwag"

    # 4. Informacje o ostatnim starcie
    last_event_formatted = format_last_event(profile.get("last_event"), ref_date=ref_date)
    profile["last_event_info"] = profile["last_event"] = last_event_formatted

    return profile


def load_weekly_plan(weekly_plan_path):
    """
    Wczytuje treść planu tygodniowego z pliku Markdown.

    Jeśli plik nie istnieje, zwraca None (plan tygodniowy jest opcjonalny).
    W przypadku błędu otwarcia lub odczytu istniejącego pliku zgłasza RuntimeError.

    Args:
        weekly_plan_path (str): Ścieżka do pliku planu tygodniowego.

    Returns:
        str | None: Zawartość planu tygodniowego lub None, gdy plik nie istnieje.
    """
    return _read_file_safe(weekly_plan_path, default_return=None)


def _substitute_template_variables(template, **kwargs):
    """
    Podstawia wartości zmiennych {nazwa_zmiennej} w szablonie tekstowym.

    Args:
        template (str): Szablon tekstowy ze znacznikami {klucz}.
        **kwargs: Zmienne do podstawienia w szablonie.

    Returns:
        str: Tekst z podstawionymi wartościami.
    """
    for key, val in kwargs.items():
        template = template.replace(f"{{{key}}}", str(val) if val is not None else "")
    return template


def _load_raw_prompt_file(filename):
    """
    Wczytuje surową zawartość pojedynczego pliku szablonu z katalogu prompts/.

    Args:
        filename (str): Nazwa pliku szablonu (np. 'daily_base.md').

    Returns:
        str: Treść pliku szablonu.
    """
    prompt_path = os.path.join(PROMPTS_DIR_PATH, filename)
    content = _read_file_safe(prompt_path)
    if not content:
        raise FileNotFoundError(f"Nie znaleziono pliku szablonu prompta: {prompt_path}")
    return content


def load_prompt_template(filenames, **kwargs):
    """
    Wczytuje szablon prompta z folderu prompts/ i podstawia przekazane zmienne {nazwa_zmiennej}.
    Jeśli filenames jest listą, ładuje po kolei i łączy znakiem nowej linii.

    Args:
        filenames (str | list): Nazwa pliku z szablonem lub lista plików.
        **kwargs: Zmienne do podstawienia w szablonie.

    Returns:
        str: Szablon z uzupełnionymi wartościami.
    """
    if isinstance(filenames, str):
        filenames = [filenames]

    template = "\n".join(_load_raw_prompt_file(filename) for filename in filenames)
    return _substitute_template_variables(template, **kwargs)


def _classify_telegram_message(body):
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

    Args:
        body (str): Treść wiadomości.

    Returns:
        tuple[str, str]: (typ_wiadomości, przetworzona_treść)
    """
    if not body or not body.strip():
        return ("empty", "")

    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ("empty", "")

    first_line_clean = lines[0].strip(":.,!- #*[]()\"'").lower()
    first_word = first_line_clean.split()[0] if first_line_clean else ""

    # 1. Kwalifikacja jako trening siłowy
    if first_word in STRENGTH_WORKOUT_NAMES:
        return ("strength", body.strip())

    # 2. Kwalifikacja jako notatka biegacza ze znacznikiem NOTE
    if first_line_clean == NOTE_KEYWORD:
        raw_lines = body.splitlines()
        for idx, r_line in enumerate(raw_lines):
            if r_line.strip().strip(":.,!- #*[]()\"'").lower() == NOTE_KEYWORD:
                return ("note", "\n".join(raw_lines[idx + 1:]).strip())
        return ("note", body.strip())

    # 3. Wiadomość ogólna / uwagi biegacza
    return ("general", body.strip())


def _parse_message_blocks(note):
    """
    Dzieli notatkę na listę bloków (nagłówek, treść_wiadomości).
    Rozpoznaje nagłówki pojedynczych wiadomości z Telegrama oraz znaczniki systemowe.
    Jeśli notatka nie zawiera nagłówków, zwraca pojedynczy blok ('', note.strip()).

    Args:
        note (str): Notatka do podzielenia.

    Returns:
        list[tuple[str, str]]: Lista bloków (nagłówek, treść_wiadomości).
    """
    if not note or not note.strip():
        return []

    # Rozdzielamy zachowując nagłówki za pomocą grupy przechwytującej w re.split
    pattern = r'(\n*---\s*Treść wiadomości z Telegrama[^\n]*---\s*|\n*\[NOWA WIADOMOŚĆ PORANNA\]:\s*|\n*\[RAPORT Z TELEGRAMA\]:\s*)'
    tokens = re.split(pattern, note)

    blocks = []
    if tokens[0].strip():
        blocks.append(("", tokens[0].strip()))

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

    Args:
        note (str): Notatka z Telegrama.

    Returns:
        tuple[str | None, str | None]: (strength_workout, remaining_user_note)
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
            note_blocks.append(f"{header}\n{processed_body}" if header else processed_body)

    strength_workout = "\n\n".join(workout_blocks).strip() if workout_blocks else None
    remaining_user_note = "\n\n".join(note_blocks).strip() if note_blocks else None

    return strength_workout, remaining_user_note


def prepare_user_note():
    """
    Wczytuje najnowsze wiadomości i uwagi od biegacza bezpośrednio z czatu Telegrama.

    Returns:
        tuple[str | None, any]: Wczytana notatka użytkownika oraz nowy stan telegrama.
    """
    user_note = None
    new_tg_state = None

    try:
        tg_note, new_tg_state = fetch_recent_telegram_messages()
        if tg_note:
            print("\n" + "=" * 60)
            print("📲 ODEBRANO WIADOMOŚĆ Z TELEGRAMA:")
            print("=" * 60)
            print(tg_note)
            print("=" * 60 + "\n")
            print(f"📄 Wiadomość dla Trenera Gemini (z Telegrama):\n   \"{tg_note}\"\n")
            user_note = tg_note
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wiadomości z Telegrama: {e}")

    return user_note, new_tg_state


def _find_history_anchor_date(history_dir_path, ref_date):
    """Wyznacza datę bazową (anchor) dla 42-dniowego okna historii treningowej.

    Args:
        history_dir_path (str): Ścieżka do katalogu historii.
        ref_date (datetime.date): Data odniesienia.

    Returns:
        datetime.date: Data bazowa.
    """
    for i in range(60):
        test_date = ref_date - datetime.timedelta(days=i)
        d_str = test_date.isoformat()
        year, month = d_str.split('-')[:2]
        if os.path.exists(os.path.join(history_dir_path, year, month, f"{d_str}.md")):
            return test_date

    return ref_date


def _get_day_run_sessions(content, m_run):
    """
    Wyciąga liczbę jednostek biegowych z treści raportu dziennego, zabezpieczając przed rozbijaniem
    części składowych jednego treningu (rozgrzewki, schłodzenia, przebieżek) na osobne jednostki w historii.

    Args:
        content (str): Zawartość pliku raportu dziennego.
        m_run (re.Match): Dopasowanie wyrażenia RE_RUN_META.

    Returns:
        int: Liczba jednostek biegowych dla danego dnia.
    """
    if not m_run:
        return 0
    sessions = int(m_run.group(2)) if m_run.group(2) else 1
    if sessions <= 1:
        return sessions

    # Jeśli w nagłówku zapisano sesje > 1, sprawdzamy czy to nie były fragmenty jednej jednostki
    c_lower = content.lower()
    has_aux = any(k in c_lower for k in (
        "rozgrzewka:", "rozgrzewka", "warmup", "schłodzenie:", "schłodzenie",
        "cooldown", "przebieżki", "przebiezki", "strides"
    ))

    start_times = re.findall(r'###\s*Jednostka\s*\d+\s*\[Start:\s*(\d{1,2}):(\d{2})\]', content)
    if start_times:
        mins = sorted(int(h) * 60 + int(m) for h, m in start_times)
        # Jeśli wszystkie aktywności zmieściły się w oknie < 3h (180 min)
        if (mins[-1] - mins[0]) < 180:
            return 1
    elif has_aux:
        return 1

    return sessions


def _summarize_history_weeks_1_4(history_data, start_date):
    """
    Generuje podsumowanie tygodni 1–4 (Dni 1–28) historii: kilometry, biegi, siłownia.
    Odczytuje bezpośrednio linie metadanych (- Bieg: i - Siłownia:) z nagłówka każdego pliku raportu.

    Args:
        history_data (dict): Słownik z historią treningów.
        start_date (datetime.date): Data początkowa historii.

    Returns:
        str: Podsumowanie z 4 tygodni.
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
            date_str = (w_start + datetime.timedelta(days=d_offset)).isoformat()
            if date_str in history_data:
                files_found += 1
                c = history_data[date_str]
                m_run = RE_RUN_META.search(c)
                if m_run:
                    if m_run.group(1):
                        w_km += float(m_run.group(1).replace(',', '.'))
                    w_runs += _get_day_run_sessions(c, m_run)
                if RE_STR_TAK.search(c):
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

    Args:
        history_data (dict): Słownik z historią treningów.
        start_date (datetime.date): Data początkowa historii.

    Returns:
        str: Opis jednostek z 5. tygodnia.
    """
    week_5_lines = []
    w5_start = start_date + datetime.timedelta(days=28)
    for d_offset in range(7):
        cur_d = w5_start + datetime.timedelta(days=d_offset)
        date_str = cur_d.isoformat()
        day_name = DAYS_PL[cur_d.weekday()]
        if date_str not in history_data:
            week_5_lines.append(f"- {date_str} ({day_name}): {NO_DATA}")
            continue

        try:
            c = history_data[date_str]
            m_run = RE_RUN_W5.search(c)
            m_str = RE_STR_W5.search(c)

            parts_desc = []
            if m_run and m_run.group(1).upper() == "TAK":
                r_type = _re_first(RE_RUN_TYPE, c, "Bieg")
                r_struct = _re_first(RE_RUN_STRUCT, c)
                struct_suffix = f" [{r_struct}]" if r_struct and r_struct != "Brak" else ""
                parts_desc.append(f"{r_type} ({m_run.group(2) or ''} km){struct_suffix}")

            if m_str and m_str.group(1).upper() == "TAK":
                parts_desc.append(f"Siłownia: partie {_re_first(RE_MUSCLE, c, 'GÓRA / DÓŁ')}")

            c_lower = c.lower()
            if any(k in c_lower for k in ("typ dnia: pływanie", "typ dnia: plywanie", "trening pływania", "trening pływacki", "pool swim")):
                swim_dist = _re_first(r'(?:Trening pływania|Trening Uzupełniający|Pool Swim)[^\n]*\n-\s*Dystans:\s*([0-9.,]+\s*(?:km|m))', c, flags=re.IGNORECASE)
                parts_desc.append(f"Pływanie ({swim_dist})" if swim_dist else "Pływanie")
            elif ("typ dnia: trening uzupełniający" in c_lower or "trening uzupełniający" in c_lower) and not parts_desc:
                parts_desc.append("Trening uzupełniający")

            workout_desc = " + ".join(parts_desc) if parts_desc else "Dzień wolny / Regeneracja"
            decision_str = _re_first(RE_COACH_DECISION, c, "Zgodnie z planem").strip("*")
            week_5_lines.append(f"- {date_str} ({day_name}): {workout_desc} | Decyzja trenera: {decision_str}")
        except Exception:
            week_5_lines.append(f"- {date_str} ({day_name}): {NO_DATA}")

    return "\n".join(week_5_lines)


def _extract_gym_exercises_summary(content):
    """
    Wyciąga zwięzłą listę zrealizowanych ćwiczeń siłowych (serie x powtórzenia, obciążenie)
    z tabeli ćwiczeń lub podsumowania w raporcie dziennym.

    Args:
        content (str): Zawartość raportu dziennego.

    Returns:
        str: Sformatowana linia z listą ćwiczeń lub pusty ciąg.
    """
    m = re.search(r'\|\s*Nr\s*\|\s*Ćwiczenie[^\n]*\|\n\|(?:\s*:?-+:?\s*\|)+\n((?:\|[^\n]+\|\n?)+)', content, re.I)
    if not m:
        return _re_first(r'(?:Potwierdzenie i modyfikacje ćwiczeń|Wykonane ćwiczenia|ZESTAWIENIE ĆWICZEŃ):\s*([^\n]+)', content, flags=re.I)

    ex_list = []
    for row in m.group(1).strip().splitlines():
        cols = [col.strip() for col in row.split('|')[1:-1]]
        if len(cols) >= 3 and cols[1] and 'Brak szczegółowego' not in cols[1]:
            name = re.sub(r'\s*\((?:Barbell|Dumbbell|Cable|Machine|fbw|upper|lower|core|push|pull|legs)\)', '', cols[1], flags=re.I).strip()
            reps = f" {cols[2]}" if cols[2] and cols[2] != '-' else ""
            weight = f" ({cols[3]})" if len(cols) > 3 and cols[3] and cols[3] != '-' else ""
            ex_list.append(f"{name}{reps}{weight}")
    return ", ".join(ex_list)


def _extract_interval_tables(content):
    """
    Wyciąga zwięzłą tabelę serii roboczych (splitów) dla treningów biegowych z akcentami
    (interwały, tempo progowe, powtórzenia) wygenerowaną pierwotnie w trybie daily (audit_run.md).

    Args:
        content (str): Zawartość raportu dziennego.

    Returns:
        str | None: Wyciągnięta tabela Markdown ze splitami serii lub None.
    """
    pattern = r'(\|[^\n]*(?:Segment|Seria|Nr powtórzenia)[^\n]*\|\n\|(?:\s*:?-+:?\s*\|)+\n(?:\|[^\n]+\|\n?)+)'
    matched = []
    for t in re.findall(pattern, content):
        first_line = t.splitlines()[0]
        if ('Km' in first_line and 'GAP' in first_line) or 'Parametr' in first_line or 'Plan' in first_line:
            continue
        if any(k in first_line for k in ('Dystans', 'Tempo', 'Czas', 'HR', 'GCT')):
            matched.append(t.strip())

    return next((t for t in matched if 'Segment' in t or 'Łączny Dystans' in t), matched[0] if matched else None)


def _summarize_history_day_for_planning(content, date_str, day_name):
    """
    Tworzy zwięzłą i wysoce informatywną syntezę zrealizowanego dnia dla promptu planowania tygodniowego.
    Dostarcza modelowi wyłącznie kluczowe metryki:
    - Status ANS i regeneracji (HRV, RHR, jakość snu, Body Battery, stres, kroki),
    - Podsumowanie zrealizowanych jednostek (typ, dystans, czas, tempo, tętno, kadencja, TE),
    - Strukturę serii i splity akcentu (tabela z audit_run.md przy interwałach/tempie),
    - Zgłoszone uwagi biegacza i ostrzeżenia o przeciążeniach/bólach (oznaczone ⚠️),
    - Ocenę egzekucji oraz syntetyczny wniosek adaptacyjny trenera.

    Args:
        content (str): Zawartość pliku raportu dziennego.
        date_str (str): Data w formacie ISO (YYYY-MM-DD).
        day_name (str): Nazwa dnia tygodnia (np. Poniedziałek).

    Returns:
        str: Zwięzły blok informacyjny dla danego dnia.
    """
    if not content or content.strip() == NO_DATA:
        return f"#### {date_str} ({day_name}) – {NO_DATA}\n* Brak zarejestrowanych danych treningowych ani biometrycznych."

    # 1. Nagłówek i identyfikacja aktywności
    day_type = _re_first(r'-\s*Typ dnia:\s*([^\n]+)', content, NO_DATA)
    m_run = re.search(r'-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([^)]+)\))?', content, re.I)
    is_run = bool(m_run and m_run.group(1).upper() == 'TAK')
    run_meta = m_run.group(2) if m_run and m_run.group(2) else ''
    run_type = _re_first(RE_RUN_TYPE, content)
    run_struct = _re_first(RE_RUN_STRUCT, content)
    is_gym = bool(re.search(r'-\s*Siłownia:\s*TAK\b', content, re.I))
    muscles = _re_first(r'-\s*Partie mięśniowe[^:]*:\s*([^\n]+)', content)
    is_swim = any(k in content.lower() for k in ('typ dnia: pływanie', 'typ dnia: plywanie', 'pool swim', 'trening pływania'))

    if is_run and run_type and run_type != 'Brak biegu':
        headline_workout = f"Bieg: {run_type}"
    elif is_swim:
        headline_workout = "Pływanie"
    elif is_gym:
        headline_workout = f"Siłownia: partie {muscles}" if muscles and muscles != 'BRAK' else "Siłownia"
    elif 'regeneracja' in day_type.lower() or 'brak' in day_type.lower():
        headline_workout = "Dzień wolny / Regeneracja"
    else:
        headline_workout = day_type

    # 2. Status autonomiczny ANS i biometria regeneracyjna
    hrv_str = _re_first(r'-\s*HRV[^:]*:\s*([^\n]+)', content, NO_DATA)
    rhr_str = _re_first(r'-\s*RHR[^:]*:\s*([^\n]+)', content, NO_DATA)
    sleep_str = _re_first(r'-\s*Sen[^:]*:\s*([^\n]+)', content, NO_DATA)
    bb_str = _re_first(r'Body Battery pod koniec dnia:\s*([^\n]+)', content) or _re_first(r'Body Battery:\s*([^\n]+)', content)
    bb_morn_str = _re_first(r'Poranne Body Battery[^:]*:\s*([^\n]+)', content)
    stress_str = (
        _re_first(r'-\s*(?:Całodzienny|Dzisiejszy całodzienny)\s*stres[^:]*:\s*(?:Średni poziom stresu:\s*)?([^\n]+)', content)
        or _re_first(r'-\s*Średni\s+(?!stres snu)stres[^:]*:\s*([^\n]+)', content)
    )
    steps_str = _re_first(r'(?:Kroki|Dzisiejsze kroki|Wczorajsze kroki)[^:]*:\s*([^\n]+)', content)

    ans_parts = [f"HRV: {hrv_str}", f"RHR: {rhr_str}"]
    if sleep_str and sleep_str != NO_DATA:
        ans_parts.append(f"Sen: {sleep_str}")
    if bb_str:
        ans_parts.append(f"Body Battery: {bb_str}")
    elif bb_morn_str:
        ans_parts.append(f"Body Battery (start): {bb_morn_str}")
    if stress_str:
        ans_parts.append(f"Stres: {stress_str}")
    if steps_str:
        ans_parts.append(f"Kroki: {steps_str}")
    ans_line = " | ".join(ans_parts)

    # 3. Zrealizowane jednostki treningowe
    workout_lines = []
    act_block = _re_first(r'##\s*Zarejestrowane aktywności[^\n]*\n(.*?)(?=\n##\s+[^\#]|\Z)', content, flags=re.DOTALL)
    if act_block:
        for u in re.split(r'\n(?=###\s+(?:Jednostka|Trening|[0-9]))', act_block):
            u_clean = u.strip()
            if not u_clean:
                continue
            u_clean_base = re.split(r'\n####\s*Splity', u_clean, flags=re.I)[0].strip()
            u_title = u_clean_base.splitlines()[0].replace('###', '').strip()
            if 'trening siłowy' in u_title.lower():
                continue
            if 'pool swim' in u_clean.lower() or 'pływanie' in u_clean.lower():
                u_title = re.sub(r'Trening Uzupełniający', 'Trening pływania', u_title, flags=re.I)

            dist_v = _re_first(r'Dystans:\s*([0-9.,]+\s*(?:km|m))', u_clean_base)
            time_v = _re_first(r'Czas:\s*([0-9.,]+\s*(?:min|h))', u_clean_base)
            pace_v = _re_first(r'Średnie tempo:\s*([^\n|]+)', u_clean_base)
            hr_v = _re_first(r'Tętno:\s*([^\n|]+(?:\s*\|\s*Max[^\n|]+)?)', u_clean_base)
            te_v = _re_first(r'Training Effect:\s*([^\n|]+(?:\s*\|\s*Beztlenowy[^\n|]+)?)', u_clean_base)
            cad_v = _re_first(r'kadencja\s*([0-9]+)\s*spm', u_clean_base, flags=re.I)

            u_parts = [u_title]
            if dist_v:
                u_parts.append(f"Dystans: {dist_v}")
            if time_v:
                u_parts.append(f"Czas: {time_v}")
            if pace_v and pace_v not in ('Brak', 'None', NO_DATA):
                u_parts.append(f"Śr. tempo: {pace_v}")
            if hr_v:
                u_parts.append(f"HR: {hr_v}")
            if cad_v:
                u_parts.append(f"Kadencja: {cad_v} spm")
            if te_v:
                u_parts.append(f"TE: {te_v}")
            workout_lines.append(" | ".join(u_parts))
    elif is_run:
        workout_lines.append(f"Bieg ({run_meta}) - {run_type}")

    if is_gym:
        gym_desc = f"Siłownia: partie {muscles}" if muscles and muscles != "BRAK" else "Siłownia"
        ex_summary = _extract_gym_exercises_summary(content)
        workout_lines.append(f"{gym_desc} (Ćwiczenia: {ex_summary})" if ex_summary else gym_desc)

    if not workout_lines:
        workout_lines.append("Brak aktywności treningowej (Rest Day)")

    interval_table = _extract_interval_tables(content)

    # 4. Uwagi biegacza i raporty przeciążeniowe / urazowe
    raw_note = _re_first(r'##\s*Uwagi biegacza[^\n]*\n(.*?)(?=\n##|\Z)', content, flags=re.DOTALL)
    user_note_clean = re.sub(r'---\s*Treść wiadomości z Telegrama[^\n]*---\s*', '', raw_note, flags=re.I).replace('\\n', ' ').strip()
    injury_warning = ''
    if user_note_clean:
        has_injury_kw = any(k in user_note_clean.lower() for k in ('ból', 'bol', 'uraz', 'kontuzj', 'pachwin', 'ściegn', 'kolan', 'stop', 'problem', 'przeciąż'))
        injury_warning = f"⚠️ {user_note_clean}" if has_injury_kw else user_note_clean

    # 5. Ocena trenera, decyzja adaptacyjna i kluczowe wnioski
    eval_parts = []
    if (eval_v := _re_first(r'(?:Ocena|Ocena egzekucji planu|Ocena treningu)\*?\*?:\s*([0-9]+/[0-9]+[^\n]*)', content)):
        eval_parts.append(f"Ocena: {eval_v}")
    if (dec_v := _re_first(RE_COACH_DECISION, content).strip('*')):
        eval_parts.append(f"Decyzja: {dec_v}")

    phys_text = _re_first(
        r'(?:Uzasadnienie fizjologiczne|Bodziec adaptacyjny i koszt tkankowy|Bodziec adaptacyjny i koszt metaboliczny|Bodziec fizjologiczny i szlaki energetyczne|Koszt nerwowo-mięśniowy|Dedykowana analiza fizjologiczna pływania)[^:\n]*:[ \t]*([^\n]+)',
        content
    )
    if phys_text:
        s_end = phys_text.find('.')
        eval_parts.append(phys_text[:s_end + 1] if s_end > 10 else phys_text)

    res = [
        f"#### {date_str} ({day_name}) – {headline_workout}",
        f"* **Status ANS i regeneracja**: {ans_line}",
        f"* **Zrealizowany trening**: {' + '.join(workout_lines)}"
    ]
    if run_struct and run_struct != 'Brak' and is_run:
        res.append(f"* **Struktura biegu**: {run_struct}")
    if interval_table:
        res.append(f"* **Splity akcentu (serie robocze z audytu)**:\n\n{interval_table}\n")
    if injury_warning:
        res.append(f"* **Uwagi biegacza / urazy**: {injury_warning}")
    if eval_parts:
        res.append(f"* **Ocena trenera i adaptacja**: {' | '.join(eval_parts)}")

    return "\n".join(res)


def _load_history_week_6(history_data, start_date):
    """
    Wczytuje i syntetyzuje raporty dzienne z tygodnia 6 (Dni 36–42 / ostatnie 7 dni)
    do zwartej postaci: zrealizowane jednostki, splity akcentów oraz status ANS.

    Args:
        history_data (dict): Słownik z historią.
        start_date (datetime.date): Data początkowa.

    Returns:
        str: Raporty z ostatnich 7 dni w zwięzłej formie.
    """
    week_6_entries = []
    w6_start = start_date + datetime.timedelta(days=35)
    for d_offset in range(7):
        cur_d = w6_start + datetime.timedelta(days=d_offset)
        date_str = cur_d.isoformat()
        day_name = DAYS_PL[cur_d.weekday()]
        week_6_entries.append(_summarize_history_day_for_planning(history_data.get(date_str), date_str, day_name))

    return "\n\n".join(week_6_entries)


def load_training_history(ref_date, history_dir_path=HISTORY_DIR_PATH):
    """
    Wczytuje historię treningów z folderu trainings_history z ostatnich 42 dni (6 tygodni)
    z wielopoziomową szczegółowością:
    - Tygodnie 1–4: podsumowanie makrocyklu (kilometry, treningi biegowe i siłowe).
    - Tydzień 5: zwarty przegląd mezocyklu z pełnymi tabelami ćwiczeń.
    - Tydzień 6: zwięzły przegląd zrealizowanych jednostek i statusu ANS.

    Args:
        ref_date (datetime.date): Data odniesienia.
        history_dir_path (str, optional): Ścieżka do katalogu z historią.

    Returns:
        str | None: Sformatowana historia treningów z ostatnich 42 dni.
    """
    if not os.path.exists(history_dir_path):
        return None

    anchor_date = _find_history_anchor_date(history_dir_path, ref_date)
    start_date = anchor_date - datetime.timedelta(days=41)

    history_data = {}
    for d_offset in range(42):
        d_str = (start_date + datetime.timedelta(days=d_offset)).isoformat()
        year, month = d_str.split('-')[:2]
        content = _read_file_safe(os.path.join(history_dir_path, year, month, f"{d_str}.md"))
        if content is not None:
            history_data[d_str] = content

    if not history_data:
        return None

    return "\n\n".join([
        f"### 1. Podsumowanie makrocyklu (Tygodnie 1–4 / Dni 1–28):\n{_summarize_history_weeks_1_4(history_data, start_date)}",
        f"\n### 2. Zwarty przegląd mezocyklu (Tydzień 5 / Dni 29–35):\n{_summarize_history_week_5(history_data, start_date)}",
        f"\n### 3. Zwięzły przegląd ostatniego tygodnia (Tydzień 6 / Dni 36–42):\n{_load_history_week_6(history_data, start_date)}"
    ])



# ==============================================================================
# 2. GENEROWANIE PROMPTÓW DLA GEMINI
# ==============================================================================

def _format_activity_section(activity_stats, strength_workout=None):
    """
    Formatuje zwięzły blok Markdown z listą jednostek treningowych i biomechaniką dla <executed_workout>.
    Uwzględnia aktywności z Garmina oraz opcjonalny trening siłowy z Telegrama.

    Args:
        activity_stats (dict | list): Statystyki aktywności.
        strength_workout (str, optional): Opis treningu siłowego.

    Returns:
        str: Sformatowany blok jednostek treningowych.
    """
    parts = []
    if activity_stats:
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        for idx, act in enumerate(stats_list, 1):
            is_run = act.get('is_run', True)
            is_swim = act.get('is_swim', False)
            time_info = f" [Start: {act.get('start_time')}]" if act.get('start_time') and act.get('start_time') != NO_DATA else ""
            prefix = f"[JEDNOSTKA {idx} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")

            if is_run:
                splits_text = "\n".join(act['splits']) if act.get('splits') else "Brak szczegółowych splitów"
                eg, el = act.get('elevation_gain', NO_DATA), act.get('elevation_loss', NO_DATA)
                elev_str = NO_DATA if eg == NO_DATA and el == NO_DATA else f"+{eg} / -{el}"

                parts.append(
                    f"{prefix}{act.get('name')} | Dystans: {act.get('distance')} | Czas: {act.get('duration')} | Śr. tempo: {act.get('pace')} | Przewyższenia: {elev_str}\n"
                    f"- Pogoda: {act.get('weather', NO_DATA)}\n"
                    f"- Tętno i obciążenie: HR śr. {act.get('avg_hr')} (max {act.get('max_hr')}) | Aerobic TE: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')} | Śr. moc: {act.get('avg_power')}\n"
                    f"- Biomechanika: Kadencja śr. {act.get('avg_cadence')} (max {act.get('max_cadence')}) | Krok: {act.get('stride_length')} | GCT: {act.get('ground_contact_time')} | VO: {act.get('vertical_oscillation')} (VR: {act.get('vertical_ratio')})\n"
                    f"- Splity:\n{splits_text}"
                )
            else:
                header_str = (
                    f"TRENING PŁYWANIA: {act.get('name')} | Dystans: {act.get('distance')} | Czas: {act.get('duration')}"
                    if is_swim else
                    f"TRENING UZUPEŁNIAJĄCY: {act.get('name')} | Dystans: {act.get('distance')} | Czas: {act.get('duration')}"
                )
                parts.append(
                    f"{prefix}{header_str}\n"
                    f"- Tętno i obciążenie: HR śr. {act.get('avg_hr')} (max {act.get('max_hr')}) | Aerobic TE: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')}"
                )
    elif not strength_workout:
        parts.append("Brak zarejestrowanej aktywności w Garmin Connect ani na Telegramie (jeśli zaplanowano jednostkę, to nie została ona wykonana).")

    if strength_workout:
        parts.append(f"[JEDNOSTKA SIŁOWA (RAPORT Z TELEGRAMA)]:\n{strength_workout}")

    return "\n\n".join(parts)


def load_strength_routines(filepath=ROUTINES_JSON_PATH):
    """
    Wczytuje zdefiniowane bazy treningów siłowych z pliku JSON.

    Args:
        filepath (str, optional): Ścieżka do pliku JSON z rutynami siłowymi.

    Returns:
        dict: Słownik z definicjami rutyn siłowych lub pusty słownik w razie błędu.
    """
    if not filepath or not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Błąd odczytu pliku {filepath}: {e}")
        return {}


def save_strength_routines(data, filepath=ROUTINES_JSON_PATH):
    """
    Zapisuje zaktualizowane bazy treningów siłowych do pliku JSON.

    Args:
        data (dict): Słownik z definicjami i obciążeniami rutyn siłowych.
        filepath (str, optional): Ścieżka docelowego pliku JSON.

    Returns:
        bool: True w przypadku pomyślnego zapisu, False w razie błędu.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Pomyślnie zapisano bazy treningów siłowych do: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Błąd zapisu pliku {filepath}: {e}")
        return False


def parse_hevy_strength_workout(workout_text):
    """
    Parsuje raport z treningu siłowego z aplikacji Hevy (przesłany przez Telegram).

    Wyciąga klucz rutyny (np. 'fbw', 'upper') oraz listę wykonanych ćwiczeń
    wraz z przypisanymi seriami, wagami roboczymi (lub 'mc' dla ćwiczeń z masą ciała)
    i liczbą powtórzeń.

    Args:
        workout_text (str): Surowy tekst raportu treningu siłowego z Telegrama.

    Returns:
        tuple: Krotka (routine_key, exercises_dict) lub (None, {}) w przypadku braku dopasowania.
    """
    if not workout_text or not workout_text.strip():
        return None, {}

    lines = [l.strip() for l in workout_text.splitlines() if l.strip()]
    if not lines:
        return None, {}

    first_clean = lines[0].strip(":.,!- #*[]()\"'").lower()
    routine_key = first_clean.split()[0] if first_clean else ""
    if routine_key not in STRENGTH_WORKOUT_NAMES:
        return None, {}

    parsed_exercises = {}
    current_exercise = None
    current_sets = []

    for line in lines[1:]:
        if RE_DATE_HEURISTIC.search(line):
            continue

        m_bw = RE_SET_BODYWEIGHT.search(line)
        if m_bw:
            current_sets.append({
                "set": int(m_bw.group(1)),
                "weight": "mc",
                "reps": int(m_bw.group(2) or m_bw.group(3))
            })
            continue

        m_plus = RE_SET_PLUS_WEIGHT.search(line)
        if m_plus:
            current_sets.append({
                "set": int(m_plus.group(1)),
                "weight": f"+{m_plus.group(2).strip()}",
                "reps": int(m_plus.group(3))
            })
            continue

        m_w = RE_SET_WEIGHT.search(line)
        if m_w:
            raw_w = m_w.group(2).strip()
            if "kg" not in raw_w.lower():
                raw_w += " kg"
            current_sets.append({
                "set": int(m_w.group(1)),
                "weight": raw_w,
                "reps": int(m_w.group(3))
            })
            continue

        clean_name = re.sub(r"^[0-9]+[.)]\s*", "", line).strip("* -_")
        if clean_name.lower().startswith("set "):
            continue

        if current_exercise and current_sets:
            parsed_exercises[current_exercise] = current_sets

        current_exercise = clean_name
        current_sets = []

    if current_exercise and current_sets:
        parsed_exercises[current_exercise] = current_sets

    return routine_key, parsed_exercises


def _find_canonical_exercise_key(exercise_candidate, canonical_exercises):
    """
    Dopasowuje nazwę ćwiczenia z notatki Hevy do klucza w rutynie.
    Obsługuje dopasowanie dokładne (1:1), bez uwzględniania wielkości liter oraz
    po usunięciu dopisków sprzętu w nawiasach (np. '(Barbell)', '(Dumbbell)', '(Cable)').

    Args:
        exercise_candidate (str): Nazwa ćwiczenia wyodrębniona z notatki Hevy.
        canonical_exercises (dict): Słownik kanonicznych ćwiczeń przypisanych do danej rutyny.

    Returns:
        str | None: Dopasowany klucz kanoniczny ćwiczenia lub None.
    """
    if exercise_candidate in canonical_exercises:
        return exercise_candidate

    c_norm = exercise_candidate.strip().lower()
    c_stripped = re.sub(r'\s*\([^)]*\)', '', c_norm).strip()
    return (
        next((k for k in canonical_exercises if k.strip().lower() == c_norm), None)
        or (next((k for k in canonical_exercises if re.sub(r'\s*\([^)]*\)', '', k.strip().lower()).strip() == c_stripped), None) if c_stripped else None)
    )


def update_strength_routines_from_workout(workout_text, filepath=ROUTINES_JSON_PATH):
    """
    Aktualizuje wagi i powtórzenia w bazie rutyn siłowych po zrealizowanym treningu.

    Rygor kanoniczności (ochrona bazy przed zanieczyszczeniem):
    Zapisuje wyłącznie ćwiczenia należące do oficjalnej definicji danej rutyny w JSON.
    Wszelkie modyfikacje, zamienniki i ćwiczenia doraźne są celowo pomijane i NIE trafiają do JSON.

    Args:
        workout_text (str): Surowy tekst raportu siłowego z Telegrama.
        filepath (str, optional): Ścieżka do pliku JSON z bazą rutyn siłowych.

    Returns:
        tuple | None: Krotka (nazwa_rutyny, lista_zaktualizowanych_ćwiczeń) lub None.
    """
    routine_key, parsed_exercises = parse_hevy_strength_workout(workout_text)
    if not routine_key or not parsed_exercises:
        return None

    routines_data = load_strength_routines(filepath)
    if routine_key not in routines_data:
        logger.warning(f"Rutyna '{routine_key}' nie istnieje w pliku {filepath}.")
        return None

    canonical_dict = routines_data[routine_key].get("exercises", {})
    updated_exercises = []

    for ex_name, sets in parsed_exercises.items():
        matched_canon = _find_canonical_exercise_key(ex_name, canonical_dict)
        if matched_canon:
            canonical_dict[matched_canon]["last_sets"] = sets
            updated_exercises.append(matched_canon)
        else:
            logger.info(
                f"Pominięto ćwiczenie zmodyfikowane/doraźne: '{ex_name}' "
                f"(brak w bazowej definicji rutyny '{routine_key}')."
            )

    if updated_exercises:
        save_strength_routines(routines_data, filepath)
        return routine_key, updated_exercises

    return None


def _format_last_sets_str(last_sets):
    """
    Formatuje listę ostatnich serii i wag ćwiczenia do postaci czytelnej dla modelu.

    Args:
        last_sets (list): Lista słowników reprezentujących serie ćwiczenia.

    Returns:
        str: Sformatowany ciąg serii (np. 'S1: 8 x 60 kg | S2: 8 x 60 kg') lub komunikat o braku danych.
    """
    if not last_sets:
        return "Brak danych w historii (ustal bezpieczną wagę startową)"
    return " | ".join(
        f"S{s.get('set', idx)}: {s.get('reps', '')} x {s.get('weight', 'mc')}"
        for idx, s in enumerate(last_sets, 1)
    )


def _parse_superset_meta(ex_data):
    """
    Wyodrębnia metadane superserii ze słownika ćwiczenia.

    Args:
        ex_data (dict): Słownik z parametrami ćwiczenia.

    Returns:
        tuple: Krotka (group_key, group_header, role_tag) lub (None, None, None) jeśli ćwiczenie nie należy do superserii.
    """
    superset_val = ex_data.get("superset") or ex_data.get("superset_role")
    if superset_val:
        sup_str = str(superset_val).strip()
        match = re.match(r"^([A-Za-z]+)", sup_str)
        group_key = match.group(1).upper() if match else sup_str.upper()
        return group_key, f"[SUPERSET {group_key}]", sup_str
    return None, None, None


def _format_routine_exercise_lines(ex_name, r_key, ex_data, bullet_prefix, sub_prefix):
    """
    Formatuje dwie linie opisu pojedynczego ćwiczenia w bazie rutyn siłowych.

    Args:
        ex_name (str): Nazwa ćwiczenia.
        r_key (str): Klucz rutyny (np. 'fbw', 'upper').
        ex_data (dict): Słownik parametrów ćwiczenia (serie, powtórzenia, tempo, historia).
        bullet_prefix (str): Prefiks linii głównej ćwiczenia.
        sub_prefix (str): Prefiks linii podrzędnej z historią ciężarów.

    Returns:
        tuple: Dwulementowa krotka linii tekstu (linia_główna, linia_historii_serii).
    """
    t_sets = ex_data.get("target_sets", 3)
    t_reps = ex_data.get("target_reps", "8-10")
    tempo_val = ex_data.get("tempo")
    tempo_str = f", tempo {tempo_val}" if tempo_val else ""
    sets_str = _format_last_sets_str(ex_data.get("last_sets", []))
    return (
        f"{bullet_prefix}**{ex_name} ({r_key})**: {t_sets} serie, {t_reps} powtórzeń{tempo_str}",
        f"{sub_prefix}Ostatnie serie i wagi: {sets_str}"
    )


def format_strength_routines_for_prompt(routines_data=None, filepath=ROUTINES_JSON_PATH):
    """
    Formatuje bazę rutyn siłowych z pliku JSON do postaci Markdown dla promptu modelu.
    Wstrzykuje do każdego ćwiczenia jego docelowe parametry, tempo oraz ostatnie
    serie i wagi robocze (lub informację o braku danych).

    Args:
        routines_data (dict | list | None, optional): Słownik rutyn lub kolekcja kluczy do przefiltrowania.
        filepath (str, optional): Ścieżka do pliku JSON z bazą rutyn siłowych.

    Returns:
        str: Sformatowany blok Markdown z bazą treningów siłowych.
    """
    if routines_data is None:
        routines_data = load_strength_routines(filepath)
    elif isinstance(routines_data, (list, set, tuple)):
        all_routines = load_strength_routines(filepath)
        routines_data = {k: all_routines[k] for k in routines_data if k in all_routines}

    if not routines_data:
        return "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.json."

    output = [
        "# BAZA TRENINGÓW SIŁOWYCH (ROUTINES) I AKTUALNE OBCIĄŻENIA ROBOCZE",
        "* **Zapis tempa**: Cztery cyfry oznaczają kolejno: faza ekscentryczna (opuszczanie) - pauza w rozciągnięciu - faza koncentryczna (unoszenie/skurcz) - pauza w skurczu.",
        "* **Zasada doboru wag**: Do każdej serii planowanego treningu przypisz konkretną wagę i liczbę powtórzeń na podstawie 'Ostatnie serie i wagi' (lub zaplanuj bezpieczną progresję o max 1 parametr). Dla ćwiczeń 'mc' planuj ćwiczenie z masą ciała.",
        ""
    ]

    for routine_idx, (r_key, r_info) in enumerate(routines_data.items(), 1):
        r_name = r_info.get("name", r_key.upper())
        r_desc = r_info.get("description", "")
        exercises = r_info.get("exercises", {})

        output.append(f"## {routine_idx}. ROUTINE: {r_name}")
        if r_desc:
            output.append(f"*{r_desc}*\n")

        if not exercises:
            output.append("*Zestaw jeszcze nie uzupełniony, pomiń go*\n")
            continue

        handled_supersets = set()
        item_counter = 1

        for ex_name, ex_data in exercises.items():
            group_key, group_header, _ = _parse_superset_meta(ex_data)

            if group_key:
                if group_key in handled_supersets:
                    continue
                handled_supersets.add(group_key)
                output.append(f"{item_counter}. **{group_header}**:")

                for s_name, s_data in exercises.items():
                    s_key, _, role_or_tag = _parse_superset_meta(s_data)
                    if s_key == group_key:
                        tag_prefix = f"{role_or_tag}: " if role_or_tag else ""
                        output.extend(_format_routine_exercise_lines(
                            f"{tag_prefix}{s_name}", r_key, s_data, "   * ", "     - "
                        ))
                item_counter += 1
            else:
                output.extend(_format_routine_exercise_lines(
                    ex_name, r_key, ex_data, f"{item_counter}. ", "   * "
                ))
                item_counter += 1

        output.append("")

    return "\n".join(output)


def generate_weekly_plan_prompt(days_structure, personal_data, trainings_history=None, user_note=None, strength_routines=None, ref_date=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień.

    Args:
        days_structure (str): Struktura dni tygodnia (z pliku weekly_workout_structure.md).
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        trainings_history (str, optional): Historia treningów.
        user_note (str): Opcjonalna notatka zawodnika.
        strength_routines (str, optional): Baza ćwiczeń siłowych.
        ref_date (datetime.date, optional): Data odniesienia.

    Returns:
        str: Wygenerowany prompt planu tygodniowego.
    """
    if strength_routines is None:
        strength_routines = format_strength_routines_for_prompt()

    return load_prompt_template(
        "weekly_plan.md",
        **build_user_profile(personal_data, ref_date=ref_date),
        hist_section=trainings_history or "Brak zarejestrowanej historii treningów z ostatnich 42 dni.",
        weekly_preferences=days_structure,
        strength_routines=strength_routines or "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.json.",
        user_note=user_note or "Brak dodatkowych uwag od biegacza."
    )


def _strip_exercise_tags(exercise_name):
    """
    Usuwa pomocnicze tagi sprzętu i rutyny z nazwy ćwiczenia siłowego.

    Args:
        exercise_name (str): Surowa nazwa ćwiczenia z planu lub historii.

    Returns:
        str: Oczyszczona nazwa ćwiczenia.
    """
    return re.sub(
        r'\s*\((?:Dumbbell|Barbell|Cable|Machine|fbw|upper|lower|core|push|pull|legs)\)',
        '',
        exercise_name,
        flags=re.IGNORECASE
    ).strip(" *-_:")


def _format_day_plan_section(raw_title, body_lines, day_name=None, keep_heading=False):
    """
    Formatuje i kompresuje pojedynczą sekcję dziennego planu treningowego:
    odrzuca metatekst planistyczny ('Wyjaśnienie decyzji:', 'Decyzja:', '* **Cel')
    oraz formatuje ćwiczenia siłowe do zwięzłego zapisu jednoliniowego.

    Args:
        raw_title (str): Tytuł sekcji dnia z planu tygodniowego.
        body_lines (list): Lista linii należących do danej sekcji.
        day_name (str, optional): Nazwa dnia tygodnia do usunięcia z nagłówka.
        keep_heading (bool, optional): Czy zachować nagłówek Markdown '### '. Domyślnie False.

    Returns:
        str: Skompresowany tekst sekcji planu.
    """
    clean_title = re.sub(rf'^{day_name}\s*[-–:]\s*', '', raw_title, flags=re.IGNORECASE).strip() if day_name else raw_title.strip()
    if clean_title.startswith('Siłownia:'):
        clean_title = clean_title.replace('Siłownia:', 'Siłownia').strip()
    header_line = f"### {raw_title.strip()}" if keep_heading else clean_title

    expanded_lines = []
    for raw_line in body_lines:
        # Jeśli nagłówek '* **Ćwiczenia**:' zawiera w tej samej linii pierwsze ćwiczenie, rozdzielamy je
        m_ex_inline = re.match(r'^([*-]\s*(?:\*\*)?Ćwiczenia(?:\*\*)?:\s*)(.+)$', raw_line, flags=re.IGNORECASE)
        if m_ex_inline:
            expanded_lines.append('- **Ćwiczenia**:')
            expanded_lines.append(m_ex_inline.group(2).strip())
        else:
            expanded_lines.append(raw_line)

    output_lines = []
    i = 0
    in_exercises = False

    while i < len(expanded_lines):
        line = expanded_lines[i]
        stripped_bullet = line.lstrip("*- ").strip()

        # 1. Bezwzględne odrzucanie metatekstu planistycznego i uzasadnień
        if stripped_bullet.startswith(('Wyjaśnienie decyzji:', 'Decyzja:')) or line.startswith(('* **Cel', '- **Cel', '* **Uzasadnienie', '- **Uzasadnienie')):
            i += 1
            continue

        # 2. Pomijanie ćwiczeń usuniętych z planu
        if 'USUNIĘTO' in line:
            i += 1
            while i < len(expanded_lines) and expanded_lines[i].lstrip("*- ").startswith(('Seria', 'S1:', 'Decyzja', 'Wyjaśnienie')):
                i += 1
            continue

        # 3. Status dolnych partii
        if 'Status dolnych partii' in line:
            output_lines.append(re.sub(r'^[*-]\s*(?:\*\*)?Status dolnych partii(?:\*\*)?:\s*', '- Status dolnych partii: ', line))
            i += 1
            continue

        # 4. Sekcja ćwiczeń
        if 'Ćwiczenia' in line and line.startswith(('* **', '-')):
            output_lines.append('- Ćwiczenia:')
            in_exercises = True
            i += 1
            continue

        # 5. Cardio
        if 'Cardio' in line and line.startswith(('* **', '-')):
            in_exercises = False
            output_lines.append(re.sub(r'^[*-]\s*(?:\*\*)?Cardio[^:*]*(?:\*\*)?:\s*', '- Cardio: ', line))
            i += 1
            continue

        # 6. Standardowe punkty z pogrubioną etykietą (np. rozgrzewka, część główna, schłodzenie, zalecenia regeneracyjne)
        if line.startswith(('* **', '- **')) or (not in_exercises and line.startswith('- ')):
            in_exercises = False
            output_lines.append(re.sub(r'^[*-]\s*\*\*([^*]+)\*\*:\s*', r'- \1: ', line))
            i += 1
            continue

        # 7. Parsowanie ćwiczeń wewnątrz sekcji ćwiczeń
        if in_exercises:
            if re.match(r'^\[SUPERSET[^\]]*\]:?$', line.strip(), re.IGNORECASE):
                i += 1
                continue

            # Sprawdzenie nowego formatu jednoliniowego: [Nazwa] S1: ... | S2: ...
            inline_series_match = re.search(r'\b((?:S1|Seria\s*1)\s*:.*)$', line, flags=re.IGNORECASE)
            if inline_series_match:
                clean_ex_name = _strip_exercise_tags(line[:inline_series_match.start()])
                series_text = inline_series_match.group(1).strip()
                output_lines.append(f"  * {clean_ex_name}: {series_text}")
                i += 1
                continue

            clean_ex_name = _strip_exercise_tags(line)
            series = []
            i += 1
            while i < len(expanded_lines):
                s_line = expanded_lines[i].lstrip("*- ").strip()
                if s_line.startswith('Seria') or re.match(r'^S\d+\s*:', s_line, flags=re.IGNORECASE):
                    series.append(s_line)
                    i += 1
                elif s_line.startswith(('Wyjaśnienie decyzji:', 'Decyzja:')):
                    i += 1
                else:
                    break

            if series:
                num_sets = len(series)
                m_s = re.search(r'(?:Seria\s*\d+|S\d+):\s*(\d+)\s*(?:x\s*([^(]+))?(?:\(([^)]+)\))?', series[0], flags=re.IGNORECASE)
                if m_s:
                    reps = m_s.group(1)
                    weight_clean = (m_s.group(2) or '').strip().replace('na rękę', '/ręka').replace(' /', '/').strip()
                    rir = (m_s.group(3) or '').strip()

                    all_rirs = [m.group(1) for s in series if (m := re.search(r'\(([^)]+)\)', s))]
                    rir_str = 'RIR 2-3' if len(set(all_rirs)) > 1 else (all_rirs[-1] if all_rirs else rir)

                    details_parts = [p for p in (weight_clean, rir_str) if p]
                    det_str = f" ({', '.join(details_parts)})" if details_parts else ""
                    output_lines.append(f"  * {clean_ex_name}: {num_sets}x{reps}{det_str}")
                else:
                    output_lines.append(f"  * {clean_ex_name}: {num_sets} serie")
            else:
                output_lines.append(f"  * {clean_ex_name}")
        else:
            output_lines.append(line)
            i += 1

    # Odfiltrowanie pustej etykiety '- Ćwiczenia:', jeśli nie ma po niej żadnych ćwiczeń
    cleaned_lines = [
        line for idx, line in enumerate(output_lines)
        if not (line == '- Ćwiczenia:' and (idx + 1 >= len(output_lines) or not output_lines[idx + 1].startswith('  * ')))
    ]
    return f"{header_line}\n" + "\n".join(cleaned_lines) if cleaned_lines else header_line


def extract_day_plan(content, day_name):
    """
    Wyciąga czyste, skondensowane założenia treningowe dla konkretnego dnia z planu tygodniowego.
    Obsługuje również dni z dwiema jednostkami (np. poranek i popołudnie).

    Args:
        content (str): Surowa treść planu tygodniowego w Markdown.
        day_name (str): Nazwa dnia tygodnia po polsku (np. 'Niedziela').

    Returns:
        str: Sformatowany, przejrzysty opis założeń lub informacja o braku wpisu.
    """
    if not content:
        return "Brak planu"

    sections = []
    current_section = None

    for line in content.split('\n'):
        if line.startswith(('### ', '## ')):
            if line.startswith('### ') and day_name in line:
                current_section = [line.replace('### ', '').strip()]
                sections.append(current_section)
            elif current_section is not None:
                current_section = None
        elif current_section is not None and line.strip():
            current_section.append(line.strip())

    if not sections:
        return "Dzień wolny (lub brak wpisu)"

    return "\n\n".join(
        _format_day_plan_section(sec[0], sec[1:], day_name=day_name, keep_heading=False)
        for sec in sections
    )


def _compress_weekly_plan(content):
    """
    Kompresuje treść planu tygodniowego dla bloku <weekly_plan>, aby zminimalizować zużycie tokenów
    przy zachowaniu pełnej informacji o strukturze mikrocyklu i skompresowanych ćwiczeniach siłowych (1 linia/ćwiczenie).
    Dla sekcji '### Podsumowanie tygodnia' pozostawia wyłącznie wskaźniki planowanej objętości i intensywności.

    Args:
        content (str): Surowa treść planu tygodniowego w formacie Markdown.

    Returns:
        str: Skompresowana treść planu tygodniowego.
    """
    if not content:
        return content

    day_sections = []
    summary_lines = []
    current_day_sec = None
    in_weekly_summary = False

    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        clean_label = stripped.strip("* -").strip().lower()

        if stripped.startswith(('### ', '## ')):
            if 'podsumowanie tygodnia' in clean_label:
                in_weekly_summary = True
                current_day_sec = None
                summary_lines.append(stripped)
            elif 'uzasadnienie' in clean_label:
                in_weekly_summary = False
                current_day_sec = None
            elif stripped.startswith('### '):
                in_weekly_summary = False
                current_day_sec = [stripped.replace('### ', '').strip()]
                day_sections.append(current_day_sec)
            else:
                current_day_sec = None
            continue

        if in_weekly_summary:
            if stripped.startswith(('*', '-')) and any(kw in clean_label for kw in ('planowan', 'rozkład intensywnośc')):
                if not any(neg in clean_label for neg in ('hrv', 'rhr', 'poprzedni', 'tętno')):
                    summary_lines.append(stripped)
        elif current_day_sec is not None:
            current_day_sec.append(stripped)

    formatted_parts = [
        _format_day_plan_section(sec[0], sec[1:], day_name=None, keep_heading=True)
        for sec in day_sections
    ]
    if len(summary_lines) > 1:
        formatted_parts.append("\n".join(summary_lines))

    return "\n".join(formatted_parts)


def generate_daily_prompt(
    planned_workout, activity_stats, garmin_stats, weekly_plan_context,
    user_profile, user_note, strength_workout=None,
    audit_date_str=None, target_date_str=None, history_date_str=None,
    day_of_week=None):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu oraz całodziennej/nocnej regeneracji
    oraz adaptacji planu na kolejny dzień.

    Args:
        planned_workout (str): Zaplanowany trening na audytowany dzień.
        activity_stats (dict | list): Statystyki aktywności.
        garmin_stats (dict): Statystyki garmina.
        weekly_plan_context (str): Kontekst planu tygodniowego.
        user_profile (dict): Profil użytkownika.
        user_note (str): Opcjonalna notatka zawodnika.
        strength_workout (str, optional): Trening siłowy.
        audit_date_str (str, optional): Data audytu.
        target_date_str (str, optional): Data kolejnego dnia (adaptacji).
        history_date_str (str, optional): Data dnia poprzedniego (kontekstu).
        day_of_week (str, optional): Nazwa dnia tygodnia.

    Returns:
        str: Prompt weryfikacyjny.
    """
    y_training = garmin_stats.get('yesterday_training', 'Brak aktywności (dzień wolny)')
    y_steps = garmin_stats.get('yesterday_steps', NO_DATA)
    y_stress = garmin_stats.get('yesterday_stress', NO_DATA)

    if y_training == "Brak aktywności (dzień wolny)" and y_steps == NO_DATA and y_stress == NO_DATA:
        yesterday_section = "Brak danych (dzień wolny)"
    else:
        yesterday_section = f"Trening: {y_training} | Kroki: {y_steps} | DayStress: {y_stress}"

    if weekly_plan_context:
        weekly_plan_context = _compress_weekly_plan(weekly_plan_context)

    weekly_plan_section = weekly_plan_context or "Brak planu tygodniowego w pliku output/weekly_plan.md"
    note_content = user_note or f"Brak dodatkowych uwag od biegacza na dzień {audit_date_str}."
    activity_section = _format_activity_section(activity_stats, strength_workout=strength_workout)
    profile_dict = user_profile if isinstance(user_profile, dict) else {}

    evening_routine_raw = _read_file_safe(EVENING_ROUTINE_PATH)
    evening_routine_section = (
        evening_routine_raw.strip()
        if evening_routine_raw and evening_routine_raw.strip()
        else "Brak zdefiniowanej rutyny wieczornej"
    )

    # Wybór odpowiednich szablonów audytu
    stats_list = activity_stats if isinstance(activity_stats, list) else ([activity_stats] if activity_stats else [])
    audit_templates = [
        tpl for cond, tpl in (
            (any(act.get('is_run', True) for act in stats_list), "audit_run.md"),
            (any(not act.get('is_run', True) and act.get('is_swim', False) for act in stats_list), "audit_swim.md"),
            (bool(strength_workout), "audit_gym.md"),
            (any(not act.get('is_run', True) and not act.get('is_swim', False) for act in stats_list), "audit_other.md"),
        ) if cond
    ] or ["audit_rest.md"]

    base_text = _load_raw_prompt_file("daily_base.md")
    audit_parts = [_load_raw_prompt_file(t_name).strip() for t_name in audit_templates]
    closing_text = _load_raw_prompt_file("daily_closing.md")

    # Protokół niedzielny w sekcji 4 (zamknięcie mikrocyklu)
    if day_of_week == "Niedziela":
        sunday_section_4 = (
            f"## 4. OCENA GOTOWOŚCI I DYREKTYWA NA DZIEŃ: {audit_date_str}\n\n"
            "- **DECYZJA ADAPTACYJNA / STOPIEŃ GOTOWOŚCI**: [PEŁNA GOTOWOŚĆ / ZMĘCZENIE FUNKCJONALNE / GŁĘBOKI DŁUG ADAPTACYJNY / WYMAGANA REGENERACJA]\n"
            "- **Uzasadnienie fizjologiczne**: [Zwięzła diagnoza gotowości CUN, glikogenu i sztywności MTS pod kątem zamkniętego mikrocyklu; liczby wyłącznie w nawiasach]"
        )
        closing_text = re.sub(r"## 4\. OCENA GOTOWOŚCI.*", sunday_section_4, closing_text, flags=re.DOTALL)

    prompt_parts = [base_text.strip(), *audit_parts]
    if len(audit_templates) > 1:
        prompt_parts.append(
            "[ZAREJESTROWANO WIELE TYPÓW TRENINGÓW (NP. BIEG + SIŁOWNIA). ZINTEGRUJ WYTYCZNE Z POSZCZEGÓLNYCH SZABLONÓW PUNKTU 5 W JEDEN WSPÓLNY, SPÓJNY RAPORT. POŁĄCZ AUDYTY DO JEDNEJ SEKCJI NR 1 I NIE DUBLUJ SEKCJI 2, 3 ANI 4!]"
        )
    prompt_parts.append(closing_text.strip())

    garmin_vars = {
        k: garmin_stats.get(k, NO_DATA)
        for k in (
            'today_steps', 'today_stress', 'body_battery', 'morning_body_battery',
            'hrv_last_night', 'hrv_baseline_range', 'rhr', 'rhr_baseline',
            'sleep_score', 'total_sleep_time', 'deep_sleep', 'rem_sleep', 'sleep_stress',
        )
    }

    return _substitute_template_variables(
        "\n\n".join(prompt_parts),
        **profile_dict,
        **garmin_vars,
        today_date_str=audit_date_str,
        yesterday_date_str=history_date_str,
        tomorrow_date_str=target_date_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {audit_date_str}',
        activity_section=activity_section,
        yesterday_section=yesterday_section,
        weekly_plan_section=weekly_plan_section,
        evening_routine_section=evening_routine_section,
        user_note=note_content,
    )


# ==============================================================================
# 3. FORMATOWANIE I ZAPIS RAPORTÓW / ARCHIWUM
# ==============================================================================

def _format_acts_archive_blocks(all_stats):
    """Generuje bloki jednostek treningowych do pliku archiwum markdown.

    Args:
        all_stats (list): Statystyki wszystkich aktywności.

    Returns:
        list[str]: Lista wygenerowanych bloków.
    """
    acts_archive_blocks = []
    for idx, act_s in enumerate(all_stats, 1):
        is_run = act_s.get('is_run', True)
        is_swim = act_s.get('is_swim', False)
        time_info = f" [Start: {act_s.get('start_time')}]" if act_s.get('start_time') and act_s.get('start_time') != NO_DATA else ""

        if is_run:
            splits_formatted = "\n".join(act_s.get('splits', [])) or "Brak szczegółowych splitów dla tej jednostki"
            single_block = f"""### Jednostka {idx}{time_info}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', NO_DATA)}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
        else:
            unit_label = "Trening pływania" if is_swim else "Trening Uzupełniający"
            single_block = f"""### {unit_label} {idx}{time_info}: {act_s['name']}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}"""

        acts_archive_blocks.append(single_block)
    return acts_archive_blocks


def save_daily_report(workout_date, archive_content, history_dir_path=HISTORY_DIR_PATH, output_dir_path=OUTPUT_DIR_PATH, debug=False):
    """Zapisuje wygenerowany raport trenera do pliku historii oraz do bieżącego raportu.

    Args:
        workout_date (str): Data treningu.
        archive_content (str): Treść do zapisania.
        history_dir_path (str, optional): Katalog historii.
        output_dir_path (str, optional): Katalog wyjściowy.
        debug (bool): Flaga trybu debug.
    """
    target_dir = DEBUG_DIR_PATH if debug else output_dir_path
    os.makedirs(target_dir, exist_ok=True)
    if debug:
        archive_file_path = os.path.join(DEBUG_DIR_PATH, f"{workout_date}.md")
        already_existed = False
    else:
        year, month = workout_date.split("-")[:2]
        target_history_dir_path = os.path.join(history_dir_path, year, month)
        os.makedirs(target_history_dir_path, exist_ok=True)
        archive_file_path = os.path.join(target_history_dir_path, f"{workout_date}.md")
        already_existed = os.path.exists(archive_file_path)

    latest_file_path = os.path.join(target_dir, "last_daily_report.md")
    latest_html_path = os.path.join(target_dir, "last_daily_report.html")
    html_title = f"Raport Coach Gemini {workout_date}{' (Debug)' if debug else ''}"

    for path in (archive_file_path, latest_file_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(archive_content)

    if debug:
        print(f"\n✅ [DEBUG] Zapisano raport do: {latest_file_path} oraz {archive_file_path} (Pliki produkcyjne nie zostały zmodyfikowane)")
    elif already_existed:
        print(f"\n✅ Zaktualizowano (nadpisano) wcześniejszy raport w: {latest_file_path} oraz archiwum {archive_file_path}")
    else:
        print(f"\n✅ Zapisano raport do: {latest_file_path} oraz archiwum {archive_file_path}")

    try:
        html_content = markdown_to_html_doc(archive_content, title=html_title)
        with open(latest_html_path, "w", encoding="utf-8") as hf:
            hf.write(html_content)
        print(f"{'📄 [DEBUG]' if debug else '📄'} Wygenerowano podgląd HTML: {latest_html_path}")
    except Exception as he:
        logger.warning(f"Nie udało się wygenerować podglądu HTML: {he}")


def _extract_strength_muscle_groups(strength_workout):
    """
    Wyznacza nazwę treningu siłowego oraz wskaźnik zaangażowanych partii mięśniowych (góra / dół / góra + dół / brak).

    Args:
        strength_workout (str | None): Opis treningu siłowego.

    Returns:
        tuple[str, str]: (strength_line, muscle_groups)
        gdzie strength_line to np. 'TAK (UPPER)' lub 'NIE',
        a muscle_groups to np. 'GÓRA', 'DÓŁ', 'GÓRA + DÓŁ', 'BRAK'.
    """
    if not strength_workout or not strength_workout.strip():
        return ("NIE", "BRAK")

    lines = [l.strip() for l in strength_workout.splitlines() if l.strip()]
    first_clean = lines[0].strip(":.,!- #*[]()\"'") if lines else ""
    first_line_lower = first_clean.lower()
    strength_line = f"TAK ({first_clean.upper() or 'TRENING SIŁOWY'})"

    routine_muscle_map = {
        "upper": "GÓRA", "push": "GÓRA", "pull": "GÓRA",
        "lower": "DÓŁ", "legs": "DÓŁ",
        "fbw": "GÓRA + DÓŁ",
        "core": "CORE / STABILIZACJA",
    }
    if first_line_lower in routine_muscle_map:
        return (strength_line, routine_muscle_map[first_line_lower])

    text_lower = strength_workout.lower()
    has_upper = any(w in text_lower for w in ("góra", "klatka", "bench", "press", "row", "pull", "bicep", "tricep", "bark"))
    has_lower = any(w in text_lower for w in ("dół", "nóg", "squat", "przysiad", "deadlift", "calf", "łydk", "thrust"))
    muscle_groups = "GÓRA + DÓŁ" if (has_upper and has_lower) else ("DÓŁ" if has_lower else ("GÓRA" if has_upper else "GÓRA / DÓŁ"))
    return (strength_line, muscle_groups)


def _count_running_sessions(run_stats_list):
    """
    Zlicza liczbę odrębnych jednostek (sesji) biegowych w ciągu dnia.
    Części składowe tego samego treningu (rozgrzewka, bieg główny, schłodzenie,
    przebieżki) wykonywane w ramach jednej sesji są traktowane jako 1 trening.
    Odrębne sesje są zliczane tylko w przypadku wyraźnego odstępu czasowego
    (np. trening poranny i wieczorny, odstęp >= 3 godziny).

    Args:
        run_stats_list (list): Lista słowników ze statystykami aktywności biegowych.

    Returns:
        int: Liczba jednostek/sesji biegowych.
    """
    if not run_stats_list:
        return 0
    if len(run_stats_list) == 1:
        return 1

    def _parse_start_minutes(act):
        st = act.get('start_time')
        m = re.search(r'(\d{1,2}):(\d{2})', st) if isinstance(st, str) else None
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    def _is_auxiliary(act):
        name = str(act.get('name', '')).lower()
        return any(k in name for k in (
            'rozgrzewk', 'warmup', 'warm up', 'warm-up',
            'schłodzen', 'cooldown', 'cool down', 'cool-down',
            'przebieżk', 'strides', 'stride', 'rytm', 'rytmy', 'drill'
        ))

    parsed_times = [_parse_start_minutes(act) for act in run_stats_list]
    if all(t is not None for t in parsed_times):
        sorted_acts = sorted(zip(parsed_times, run_stats_list), key=lambda x: x[0])
        sessions, last_time = 1, sorted_acts[0][0]
        for t, act in sorted_acts[1:]:
            if (t - last_time) >= 180 and not _is_auxiliary(act):
                sessions += 1
                last_time = t
            else:
                last_time = max(last_time, t)
        return sessions

    main_runs = [act for act in run_stats_list if not _is_auxiliary(act)]
    return max(1, len(main_runs)) if main_runs else 1


def _extract_run_metadata(all_stats, response_text=None, strength_workout=None):
    """
    Wyciąga ustrukturyzowane metadane biegu: linię biegu, typ treningu, strukturę (rozgrzewka, główna seria, schłodzenie)
    oraz ogólny typ dnia.

    Args:
        all_stats (list | dict): Statystyki aktywności.
        response_text (str, optional): Treść odpowiedzi trenera.
        strength_workout (str, optional): Opis treningu siłowego.

    Returns:
        tuple[str, str, str, str]: (run_line, run_type, run_structure, day_type)
    """
    stats_list = all_stats if isinstance(all_stats, list) else ([all_stats] if all_stats else [])

    run_stats_list = [act for act in stats_list if act.get("is_run", True)]
    swim_stats_list = [act for act in stats_list if act.get("is_swim", False)]
    other_stats_list = [act for act in stats_list if not act.get("is_run", True) and not act.get("is_swim", False)]

    run_count = _count_running_sessions(run_stats_list)
    run_km = sum(
        float(m.group(1).replace(",", "."))
        for act in run_stats_list
        if (m := RE_DIST_FLOAT.search(str(act.get("distance", "0"))))
    )

    activity_parts = [
        label for cond, label in (
            (run_count > 0, "BIEG"),
            (bool(strength_workout), "SIŁOWNIA"),
            (bool(swim_stats_list), "PŁYWANIE"),
            (bool(other_stats_list), "TRENING UZUPEŁNIAJĄCY"),
        ) if cond
    ]
    day_type = " + ".join(activity_parts) if activity_parts else "REGENERACJA"

    if run_count == 0:
        return ("NIE (0.00 km, sesje: 0)", "Brak biegu", "Brak", day_type)

    run_line = f"TAK ({run_km:.2f} km, sesje: {run_count})"
    resp = response_text or ""
    resp_lower = resp.lower()
    run_type = None

    # 1. Sprawdzamy jawny profil jednostki biegowej podany przez trenera w sekcji audytu biegowego
    run_section_text = resp[resp_lower.find("część biegowa"):] if "część biegowa" in resp_lower else resp
    if "część siłowa" in run_section_text.lower():
        run_section_text = run_section_text[:run_section_text.lower().find("część siłowa")]

    cand = _re_first(RE_PROFILE_HEADER, run_section_text).strip("[]*")
    if cand and cand.lower() not in ("brak", "n/d", "nie dotyczy", "brak danych"):
        run_type = cand

    # 2. Jeśli brak jawnego profilu w raporcie, sprawdzamy specyficzne nazwy z Garmina (act_names)
    if not run_type:
        act_names = " ".join(str(a.get("name", "")) for a in run_stats_list).lower()
        name_rules = (
            (("półmaraton",), "Półmaraton / Bieg startowy"),
            (("maraton",), "Maraton / Bieg startowy"),
            (("zawody", "bieg startowy", "parkrun", "mistrzostwa", "puchar", "start"), "Zawody / Bieg startowy"),
            (("interwał", "vo2max", "odcinki", "rytm", "podbieg", "intervals", "repeats"), "Interwały / Próg (VO2max / Threshold)"),
            (("tempo", "progowy", "threshold"), "Bieg progowy / Tempo (Threshold / MP)"),
            (("długie wybieganie", "long run", "wybieganie"), "Długie wybieganie (Long Run)"),
            (("recovery", "regenerac", "regeneracyjny"), "Bieg regeneracyjny (Recovery Run)"),
            (("bieżni", "treadmill"), "Bieg na bieżni mechanicznej (Treadmill)"),
            (("przełajowy", "trail"), "Bieg przełajowy (Trail)"),
            (("lekkoatletyczny", "track"), "Bieg na bieżni lekkoatletycznej (Track)"),
        )
        run_type = next((label for kws, label in name_rules if any(k in act_names for k in kws)), None)

    # 3. Pogłębiona analiza kontekstu raportu trenera (resp_lower), gdy brak jawnego profilu i nazwa w Garminie jest domyślna
    if not run_type:
        if any(k in resp_lower for k in ("dzień startowy", "bieg startowy", "start w zawodach", "udział w zawodach")):
            if "maraton" in resp_lower and any(w in resp_lower for w in ("42.", "królewski", "maraton warszawski", "trasa maratonu")):
                run_type = "Maraton / Bieg startowy"
            elif "półmaraton" in resp_lower:
                run_type = "Półmaraton / Bieg startowy"
            else:
                run_type = "Zawody / Bieg startowy"
        else:
            resp_rules = (
                (("trening interwałowy", "interwały", "sesja vo2max", "odcinki robocze", "trening powtórzeniowy", "fartlek", "podbiegi"), "Interwały / Akcent (VO2max / Threshold)"),
                (("tempo maratońskie", "blok mp", "akcent mp", "trening progowy", "próg mleczanowy", "lthr", "strefa z4", "strefa z3", "drugi zakres", "ii zakres"), "Bieg progowy / Tempo (Threshold / MP)"),
                (("długie wybieganie", "long run", "trening objętościowy", "wybieganie"), "Długie wybieganie (Long Run)"),
                (("bieg regeneracyjny", "trucht regeneracyjny", "recovery run", "strefa z1", "regeneracja aktywna"), "Bieg regeneracyjny (Recovery Run)"),
                (("baza tlenowa", "bieg spokojny", "strefa z2", "pierwszy zakres", "i zakres", "easy run", "rozbieganie"), "Bieg spokojny (Easy Run / Z2)"),
            )
            run_type = next((label for kws, label in resp_rules if any(k in resp_lower for k in kws)), "Bieg ciągły (według analizy trenera)")

    # Wykrywanie struktury biegu (Rozgrzewka, Główna seria, Schłodzenie)
    m_plan_struct = RE_PLAN_STRUCT.search(resp)
    if m_plan_struct:
        warmup_part, main_part, cool_part = "Brak", f"{run_km:.2f} km ({run_type})", "Brak"
        for p in (part.strip() for part in m_plan_struct.group(1).strip().split(",") if part.strip()):
            p_low = p.lower()
            if "rozgrzewk" in p_low:
                warmup_part = p
            elif "schłodzen" in p_low:
                cool_part = p
            elif any(k in p_low for k in ("mp", "tempo", "część główna", "seria", "z2")):
                main_part = p
        run_structure = f"Rozgrzewka: {warmup_part} | Główna seria: {main_part} | Schłodzenie: {cool_part}"
    elif len(run_stats_list) > 1:
        run_structure = " + ".join(
            f"{a.get('name', f'Jednostka {idx}')} ({a.get('distance', '')})"
            for idx, a in enumerate(run_stats_list, 1)
        )
    else:
        run_structure = f"Rozgrzewka: Brak | Główna seria: {run_km:.2f} km ({run_type}) | Schłodzenie: Brak"

    return (run_line, run_type, run_structure, day_type)


def build_daily_archive_content(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None):
    """
    Formatuje treść raportu dziennego do zapisu w archiwum trainings_history/.
    Na początku pliku zapisywane są ustandaryzowane metadane (typ dnia, bieg, typ treningu, struktura,
    siłownia, wskaźnik partii mięśniowych), a następnie biometria, aktywności, uwagi i odpowiedź trenera.

    Args:
        workout_date (str): Data treningu.
        date_str (str): Data string.
        next_date_str (str): Kolejna data string.
        all_stats (list): Statystyki aktywności.
        garmin_stats (dict): Statystyki garmin.
        response_text (str): Odpowiedź trenera.
        strength_workout (str, optional): Trening siłowy.
        user_note (str): Opcjonalna notatka zawodnika.

    Returns:
        str: Zawartość archiwum dziennego.
    """
    # Sprawdzamy czy notatka zawiera uwagi biegacza wykraczające poza sam trening siłowy
    is_only_strength = False
    if strength_workout and user_note:
        cleaned_note = re.sub(r'---\s*Treść wiadomości z Telegrama[^\n]*---\s*', '', user_note)
        cleaned_note = re.sub(r'\[(?:RAPORT Z TELEGRAMA|NOWA WIADOMOŚĆ PORANNA)\]:\s*', '', cleaned_note).strip()
        is_only_strength = (cleaned_note == strength_workout.strip())

    note_part = f"\n## Uwagi biegacza (notatka z Telegrama):\n{user_note.strip()}\n" if (user_note and user_note.strip() and not is_only_strength) else ""

    run_line, run_type, run_structure, day_type = _extract_run_metadata(all_stats, response_text, strength_workout)
    strength_line, muscle_groups = _extract_strength_muscle_groups(strength_workout)

    metadata_header = f"""# AUDYT DZIENNY: {workout_date} ({date_str})
- Typ dnia: {day_type}
- Bieg: {run_line}
- Typ treningu biegowego: {run_type}
- Struktura biegu: {run_structure}
- Siłownia: {strength_line}
- Partie mięśniowe (siłownia): {muscle_groups}"""

    act_sections = []
    if all_stats:
        act_sections.append("\n".join(_format_acts_archive_blocks(all_stats)))
    if strength_workout:
        act_sections.append(f"### Trening siłowy / uzupełniający (raport z Telegrama):\n{strength_workout}")
    acts_part = f"\n## Zarejestrowane aktywności:\n" + "\n\n".join(act_sections) + "\n" if act_sections else ""

    rhr_archive = garmin_stats.get('rhr_status') or garmin_stats.get('rhr', NO_DATA)
    total_sleep = garmin_stats.get('total_sleep_time', NO_DATA)
    sleep_time_part = f"Czas: {total_sleep}, " if total_sleep and total_sleep != NO_DATA else ""

    bio_part = f"""## Biometria regeneracyjna i bilans dnia ({date_str}):
- HRV (miniona noc przed treningiem): {garmin_stats.get('hrv_status', NO_DATA)}
- RHR (miniona noc przed treningiem): {rhr_archive}
- Sen (miniona noc przed treningiem): {garmin_stats.get('sleep_score', NO_DATA)} ({sleep_time_part}Głęboki: {garmin_stats.get('deep_sleep', NO_DATA)}, REM: {garmin_stats.get('rem_sleep', NO_DATA)})
- Średni stres snu: {garmin_stats.get('sleep_stress', NO_DATA)}
- Poranne Body Battery (bufor startowy): {garmin_stats.get('morning_body_battery', NO_DATA)}
- Body Battery pod koniec dnia: {garmin_stats.get('body_battery', NO_DATA)}
- Całodzienny stres: {garmin_stats.get('today_stress', NO_DATA)}
- Kroki (cały dzień): {garmin_stats.get('today_steps', NO_DATA)}"""

    return f"""{metadata_header}

{bio_part}
{acts_part}{note_part}
## Ocena trenera i adaptacja na dzień {next_date_str}:
{response_text}
"""


def build_and_save_daily_archive(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None, debug=False):
    """
    Formatuje i zapisuje raport dzienny do pliku archiwum w trainings_history/.
    Podsumowuje audytowany dzień (date_str), biometrię snu/dnia oraz adaptację na dzień kolejny (next_date_str).

    Args:
        workout_date (str): Data treningu.
        date_str (str): Sformatowana data.
        next_date_str (str): Sformatowana kolejna data.
        all_stats (list): Statystyki.
        garmin_stats (dict): Statystyki garmina.
        response_text (str): Odpowiedź trenera.
        strength_workout (str, optional): Trening siłowy.
        user_note (str): Opcjonalna notatka zawodnika.
        debug (bool): Flaga trybu debug.
    """
    archive_content = build_daily_archive_content(
        workout_date, date_str, next_date_str, all_stats, garmin_stats,
        response_text, strength_workout=strength_workout, user_note=user_note
    )
    save_daily_report(workout_date, archive_content, debug=debug)



