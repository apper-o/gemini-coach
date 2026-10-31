"""
coach_prompts.py - Moduł logiki domenowej: generowanie promptów dla Gemini, kompresja historii 42 dni,
zarządzanie bazą ćwiczeń siłowych (Hevy) oraz budowanie archiwum treningowego.
"""

import os
import json
import datetime
import logging
import re

from utils_html import markdown_to_html_doc

logger = logging.getLogger(__name__)

# Stałe globalne i ścieżki katalogów
NO_DATA = "Brak danych"
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR_PATH = os.getenv("INPUT_DIR", "input")
OUTPUT_DIR_PATH = os.getenv("OUTPUT_DIR", "output")
PROMPTS_DIR_PATH = os.getenv("PROMPTS_DIR", "prompts")
HISTORY_DIR_PATH = os.getenv("HISTORY_DIR", "trainings_history")
DEBUG_DIR_PATH = os.getenv("DEBUG_DIR", "debug")

ROUTINES_JSON_PATH = os.path.join(INPUT_DIR_PATH, "strength_routines.json")
EVENING_ROUTINE_PATH = os.path.join(INPUT_DIR_PATH, "evening_routine.md")

# Stałe domenowe (brak Magic Numbers w logice)
HISTORY_WINDOW_DAYS = 42
HISTORY_MACRO_WEEKS = 4
HISTORY_MESO_OFFSET_DAYS = 28
HISTORY_MICRO_OFFSET_DAYS = 35
HISTORY_ANCHOR_SEARCH_DAYS = 60
SESSION_GAP_MINUTES = 180

PERSONAL_DATA_KEYS = (
    "primary_goal", "secondary_goal", "phase", "last_event",
    "height", "weight", "lthr",
    "hr_zones", "pace_zones",
    "personal_records", "additional_notes",
)
ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")
UNKNOWN_VALUE_KEYWORDS = frozenset({"nieznany", "brak", "none", "null"})
DEFAULT_STRENGTH_NAMES = frozenset({
    "fbw a", "fbw b", "fbw_a", "fbw_b", "fbw",
    "upper", "lower", "push", "pull", "legs", "core",
})
ROUTINE_MUSCLE_MAP = {
    "fbw a": "GÓRA + DÓŁ", "fbw b": "GÓRA + DÓŁ",
    "fbw_a": "GÓRA + DÓŁ", "fbw_b": "GÓRA + DÓŁ", "fbw": "GÓRA + DÓŁ",
    "upper": "GÓRA", "push": "GÓRA", "pull": "GÓRA",
    "lower": "DÓŁ", "legs": "DÓŁ",
    "core": "CORE / STABILIZACJA",
}
AUX_RUN_KEYWORDS = (
    "rozgrzewk", "warmup", "warm up", "warm-up",
    "schłodzen", "cooldown", "cool down", "cool-down",
    "przebieżk", "przebiezki", "strides", "stride", "rytm", "rytmy", "drill",
)
NOTE_KEYWORD = "note"

# Prekompilowane wyrażenia regularne dla parsowania historii, metadanych i logów Hevy
RE_RUN_META = re.compile(r"^-\s*Bieg:\s*TAK(?:\s*\(([0-9.,]+)\s*km(?:,\s*sesje:\s*([0-9]+))?\))?", re.MULTILINE)
RE_STR_TAK = re.compile(r"^-\s*Siłownia:\s*TAK", re.MULTILINE)
RE_RUN_W5 = re.compile(r"^-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\))?", re.MULTILINE)
RE_RUN_TYPE = re.compile(r"^-\s*Typ treningu biegowego:\s*([^\n]+)", re.MULTILINE)
RE_RUN_STRUCT = re.compile(r"^-\s*Struktura biegu:\s*([^\n]+)", re.MULTILINE)
RE_STR_W5 = re.compile(r"^-\s*Siłownia:\s*(TAK|NIE)", re.MULTILINE)
RE_MUSCLE = re.compile(r"^-\s*Partie mięśniowe \(siłownia\):\s*([^\n]+)", re.MULTILINE)
RE_COACH_DECISION = re.compile(
    r"^[*-]?\s*\*?\*?(?:DECYZJA ADAPTACYJNA(?:\s*/\s*STOPIEŃ GOTOWOŚCI)?|DYREKTYWA WYKONAWCZA(?:\s*\([^)]*\))?|DECYZJA O KOREKCIE|STOPIEŃ GOTOWOŚCI|Decyzja trenera|Zgodność z planem)[^\n:]*:\*?\*?\s*(?:\n\s*)?([^\n|]+)",
    re.MULTILINE | re.IGNORECASE,
)
RE_PROFILE_HEADER = re.compile(r"^[*-]?\s*\*?\*?(?:Profil jednostki|Typ treningu)[^\n:]*:\*?\*?\s*([^\n\r]+)", re.MULTILINE | re.IGNORECASE)
RE_DIST_FLOAT = re.compile(r"([0-9]+(?:[.,][0-9]+)?)")
RE_PLAN_STRUCT = re.compile(r"Dystans:\s*Plan:[^\n\(]*\(([^)]*(?:rozgrzewk|schłodzen|główn|mp|tempo)[^)]*)\)", re.IGNORECASE)
RE_EX_TAG_STRIP = re.compile(r"\s*\((?:Dumbbell|Barbell|Cable|Machine|fbw_a|fbw_b|fbw a|fbw b|fbw|upper|lower|core|push|pull|legs)\)", re.IGNORECASE)

RE_SET_BODYWEIGHT = re.compile(r"^[*-]?\s*Set\s+(\d+):\s*(?:(\d+)\s*reps\b|(?:mc|bodyweight)\s*x\s*(\d+))", re.IGNORECASE)
RE_SET_PLUS_WEIGHT = re.compile(r"^[*-]?\s*Set\s+(\d+):\s*\+([0-9.,]+\s*kg)\s*x\s*(\d+)", re.IGNORECASE)
RE_SET_WEIGHT = re.compile(r"^[*-]?\s*Set\s+(\d+):\s*([0-9.,]+(?:\s*(?:kg(?:/[a-ząćęłńóśźż]+)?))?)\s*x\s*(\d+)", re.IGNORECASE)
RE_DATE_HEURISTIC = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b|"
    r"\d{4}-\d{2}-\d{2}|at\s+\d{1,2}:\d{2})",
    re.IGNORECASE,
)


def _re_first(pattern, text, default="", flags=0):
    """Zwraca pierwszą grupę dopasowania wyrażenia regularnego (po strip) lub wartość domyślną."""
    if not text:
        return default
    m = pattern.search(text) if hasattr(pattern, "search") else re.search(pattern, text, flags)
    return m.group(1).strip() if m and m.group(1) else default


def _read_file_safe(filepath, default_return=None):
    """Bezpiecznie odczytuje plik tekstowy lub zwraca default_return, jeśli plik nie istnieje."""
    if not filepath or not os.path.exists(filepath):
        return default_return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"Błąd odczytu pliku {filepath}: {e}") from e


# ==============================================================================
# 1. PROFIL ZAWODNIKA I KONFIGURACJA WEJŚCIOWA
# ==============================================================================

def _normalize_training_parameter(raw_value):
    """Czyści i normalizuje pojedynczą wartość parametru treningowego (zamienia puste/nieznane na NO_DATA)."""
    if raw_value is None:
        return NO_DATA
    if isinstance(raw_value, dict):
        return {k: _normalize_training_parameter(v) for k, v in raw_value.items()}
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        return NO_DATA if (not cleaned or cleaned.lower() in UNKNOWN_VALUE_KEYWORDS) else cleaned
    return raw_value


def load_personal_data(filepath=os.path.join(INPUT_DIR_PATH, "personal_data.json")):
    """Wczytuje, waliduje i normalizuje dane o zawodniku z pliku JSON."""
    default_zones = {z: NO_DATA for z in ZONE_KEYS}
    default_last_event = {"type": NO_DATA, "time": NO_DATA, "date": NO_DATA}
    default_records = {d: NO_DATA for d in ("400m", "800m", "1500m", "5km", "10km", "polmaraton", "maraton")}
    default_data = {
        **{field: NO_DATA for field in PERSONAL_DATA_KEYS},
        "last_event": dict(default_last_event),
        "hr_zones": dict(default_zones),
        "pace_zones": dict(default_zones),
        "personal_records": dict(default_records),
    }

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if not os.path.exists(filepath):
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(default_data, fh, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Nie udało się utworzyć pliku szablonu {filepath}: {e}")
        raise FileNotFoundError(f"Nie znaleziono pliku konfiguracji '{filepath}'. Utworzono domyślny szablon – uzupełnij go przed uruchomieniem.")

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as e:
        raise RuntimeError(f"Błąd podczas odczytu pliku konfiguracji '{filepath}': {e}") from e

    if not isinstance(cfg, dict):
        raise ValueError(f"Plik '{filepath}' musi zawierać obiekt JSON (słownik), a otrzymano: {type(cfg).__name__}")

    for goal_key in ("primary_goal", "secondary_goal"):
        goal_val = cfg.get(goal_key)
        if not isinstance(goal_val, dict) or "target" not in goal_val:
            raise ValueError(f"Klucz '{goal_key}' w '{filepath}' musi być słownikiem zawierającym pole 'target'.")

    merged = {
        **default_data,
        **cfg,
        "last_event": {**default_last_event, **cfg["last_event"]} if isinstance(cfg.get("last_event"), dict) else (cfg.get("last_event") or dict(default_last_event)),
        "hr_zones": {**default_zones, **cfg["hr_zones"]} if isinstance(cfg.get("hr_zones"), dict) else dict(default_zones),
        "pace_zones": {**default_zones, **cfg["pace_zones"]} if isinstance(cfg.get("pace_zones"), dict) else dict(default_zones),
        "personal_records": {**default_records, **cfg["personal_records"]} if isinstance(cfg.get("personal_records"), dict) else dict(default_records),
    }
    return {k: _normalize_training_parameter(v) for k, v in merged.items()}


def format_relative_time(date_str, ref_date=None):
    """Oblicza różnicę czasu między datą odniesienia a podaną datą (np. 'za 5 dni', '5 dni temu')."""
    if not date_str or date_str == NO_DATA:
        return NO_DATA
    try:
        delta = (datetime.date.fromisoformat(str(date_str).strip()) - (ref_date or datetime.date.today())).days
        return f"{abs(delta)} dni temu" if delta < 0 else (f"za {delta} dni" if delta > 0 else "dzisiaj")
    except Exception:
        return str(date_str)


def format_goal(goal_data, ref_date=None):
    """Formatuje cel biegowy wraz z czasem względnym do startu."""
    if not isinstance(goal_data, dict):
        return str(goal_data or NO_DATA).strip()
    target = str(goal_data.get("target", NO_DATA)).strip()
    date_val = goal_data.get("date")
    if date_val and date_val != NO_DATA:
        time_rel = format_relative_time(date_val, ref_date=ref_date)
        return f"{target} (Termin: {date_val}{f', {time_rel}' if time_rel and time_rel != NO_DATA else ''})"
    return f"{target} (Termin: brak)"


def format_last_event(event_data, ref_date=None):
    """Formatuje informacje o ostatnim starcie zawodnika."""
    if not event_data or event_data == NO_DATA:
        return NO_DATA
    if not isinstance(event_data, dict):
        return str(event_data).strip()
    ev_type, ev_time, ev_date = ("" if (v := str(event_data.get(k) or "").strip()) == NO_DATA else v for k in ("type", "time", "date"))
    if not (ev_type or ev_time or ev_date):
        return NO_DATA
    prefix = f"{ev_type}: {ev_time}" if (ev_type and ev_time) else (ev_type or ev_time)
    if ev_date:
        time_rel = format_relative_time(ev_date, ref_date=ref_date)
        date_parts = [f"data: {ev_date}", *([time_rel] if time_rel and time_rel != NO_DATA else [])]
        return f"{prefix} ({', '.join(date_parts)})".strip() if prefix else ", ".join(date_parts)
    return prefix or NO_DATA


def build_user_profile(personal_data, ref_date=None):
    """Czysta funkcja formatująca profil zawodnika do słownika parametrów dla szablonów promptów."""
    if not isinstance(personal_data, dict):
        raise ValueError(f"Oczekiwano słownika konfiguracji treningowej, a otrzymano: {type(personal_data).__name__}")

    profile = dict(personal_data)
    hr_zones = profile.get("hr_zones") if isinstance(profile.get("hr_zones"), dict) else {}
    pace_zones = profile.get("pace_zones") if isinstance(profile.get("pace_zones"), dict) else {}
    for z_key in ZONE_KEYS:
        profile[z_key] = hr_zones.get(z_key, profile.get(z_key, NO_DATA))
        profile[f"pace_{z_key}"] = pace_zones.get(z_key, profile.get(f"pace_{z_key}", NO_DATA))

    records = profile.get("personal_records")
    entries = [f"{d}: {v}" for d, v in (records.items() if isinstance(records, dict) else ()) if isinstance(v, str) and v and v != NO_DATA]
    profile["personal_records"] = " | ".join(entries) if entries else NO_DATA

    profile["primary_goal"] = format_goal(profile.get("primary_goal") if isinstance(profile.get("primary_goal"), dict) else {}, ref_date=ref_date)
    profile["secondary_goal"] = format_goal(profile.get("secondary_goal") if isinstance(profile.get("secondary_goal"), dict) else {}, ref_date=ref_date)

    notes = profile.get("additional_notes", [])
    if isinstance(notes, list):
        clean_notes = [str(n).strip() for n in notes if str(n).strip() and str(n).strip() != NO_DATA]
        profile["additional_notes"] = " | ".join(clean_notes) if clean_notes else "Brak stałych uwag"

    profile["last_event_info"] = profile["last_event"] = format_last_event(profile.get("last_event"), ref_date=ref_date)
    return profile


def load_weekly_plan(weekly_plan_path):
    """Wczytuje treść planu tygodniowego z pliku Markdown (lub zwraca None, jeśli nie istnieje)."""
    return _read_file_safe(weekly_plan_path, default_return=None)


def load_prompt_template(filenames, **kwargs):
    """Wczytuje jeden lub więcej szablonów z katalogu prompts/ i podstawia zmienne {klucz}."""
    if isinstance(filenames, str):
        filenames = (filenames,)
    parts = []
    for fname in filenames:
        path = os.path.join(PROMPTS_DIR_PATH, fname)
        content = _read_file_safe(path)
        if not content:
            raise FileNotFoundError(f"Nie znaleziono pliku szablonu prompta: {path}")
        parts.append(content.strip() if len(filenames) > 1 else content)
    template = "\n\n".join(parts) if len(filenames) > 1 else parts[0]
    for key, val in kwargs.items():
        template = template.replace(f"{{{key}}}", str(val) if val is not None else "")
    return template


# ==============================================================================
# 2. BAZA SIŁOWA (HEVY) I KLASYFIKACJA NOTATEK
# ==============================================================================

def load_strength_routines(filepath=ROUTINES_JSON_PATH):
    """Wczytuje zdefiniowane bazy treningów siłowych z pliku JSON."""
    if not filepath or not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Błąd odczytu pliku {filepath}: {e}")
        return {}


def save_strength_routines(data, filepath=ROUTINES_JSON_PATH):
    """Zapisuje zaktualizowane bazy treningów siłowych do pliku JSON."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Pomyślnie zapisano bazy treningów siłowych do: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Błąd zapisu pliku {filepath}: {e}")
        return False


def _get_valid_strength_names(routines_data=None):
    """Zwraca dynamiczny zbiór rozpoznawanych nazw rutyn siłowych (z pliku JSON oraz standardowych aliasów)."""
    names = set(DEFAULT_STRENGTH_NAMES)
    data = routines_data if isinstance(routines_data, dict) else load_strength_routines()
    for key, info in (data or {}).items():
        k_low = key.strip().lower()
        names.update((k_low, k_low.replace("_", " "), k_low.replace(" ", "_")))
        if isinstance(info, dict) and info.get("name"):
            n_low = str(info["name"]).strip().lower()
            names.update((n_low, n_low.replace(" ", "_")))
    return names


def _detect_strength_routine_key(first_line, routines_data=None):
    """Sprawdza, czy pierwsza linia tekstu identyfikuje trening siłowy i zwraca jego znormalizowany klucz."""
    clean = first_line.strip(":.,!- #*[]()\"'").lower()
    if not clean:
        return None
    normalized = clean.replace(" ", "_")
    first_word = clean.split()[0]
    valid_names = _get_valid_strength_names(routines_data)
    if clean in valid_names or normalized in valid_names:
        return normalized
    if first_word in valid_names:
        return first_word
    return None


def separate_strength_and_user_notes(note, routines_data=None):
    """
    Czysta funkcja rozdzielająca notatki użytkownika na raporty siłowe (Hevy) oraz uwagi biegacza (NOTE / ogólne).
    """
    if not note or not note.strip():
        return None, None

    pattern = r"(\n*---\s*Treść wiadomości z Telegrama[^\n]*---\s*|\n*\[NOWA WIADOMOŚĆ PORANNA\]:\s*|\n*\[RAPORT Z TELEGRAMA\]:\s*)"
    tokens = re.split(pattern, note)

    blocks = [("", tokens[0].strip())] if tokens[0].strip() else []
    for i in range(1, len(tokens), 2):
        header = tokens[i].strip()
        body = tokens[i + 1].strip() if i + 1 < len(tokens) else ""
        if body:
            blocks.append((header, body))

    workout_blocks, note_blocks = [], []
    for header, body in blocks:
        clean_body = re.sub(r"^\[RAPORT Z TELEGRAMA\]:\s*", "", body, flags=re.IGNORECASE).strip()
        lines = [line.strip() for line in clean_body.splitlines() if line.strip()]
        if not lines:
            continue

        first_clean = lines[0].strip(":.,!- #*[]()\"'").lower()
        if _detect_strength_routine_key(lines[0], routines_data=routines_data):
            workout_blocks.append(clean_body)
        elif first_clean == NOTE_KEYWORD:
            raw_lines = clean_body.splitlines()
            stripped_note = next(
                ("\n".join(raw_lines[idx + 1 :]).strip() for idx, r_l in enumerate(raw_lines) if r_l.strip().strip(":.,!- #*[]()\"'").lower() == NOTE_KEYWORD),
                clean_body,
            )
            if stripped_note:
                note_blocks.append(f"{header}\n{stripped_note}" if header else stripped_note)
        else:
            note_blocks.append(f"{header}\n{clean_body}" if header else clean_body)

    return (
        "\n\n".join(workout_blocks).strip() if workout_blocks else None,
        "\n\n".join(note_blocks).strip() if note_blocks else None,
    )


def parse_hevy_strength_workout(workout_text, routines_data=None):
    """Czysta funkcja parsująca raport treningu siłowego z aplikacji Hevy na klucz rutyny i słownik ćwiczeń."""
    if not workout_text or not workout_text.strip():
        return None, {}

    lines = [l.strip() for l in workout_text.splitlines() if l.strip()]
    if not lines:
        return None, {}

    routine_key = _detect_strength_routine_key(lines[0], routines_data=routines_data)
    if not routine_key:
        return None, {}

    parsed_exercises, current_exercise, current_sets = {}, None, []
    for line in lines[1:]:
        if RE_DATE_HEURISTIC.search(line):
            continue
        if m_bw := RE_SET_BODYWEIGHT.search(line):
            current_sets.append({"set": int(m_bw.group(1)), "weight": "mc", "reps": int(m_bw.group(2) or m_bw.group(3))})
        elif m_plus := RE_SET_PLUS_WEIGHT.search(line):
            current_sets.append({"set": int(m_plus.group(1)), "weight": f"+{m_plus.group(2).strip()}", "reps": int(m_plus.group(3))})
        elif m_w := RE_SET_WEIGHT.search(line):
            raw_w = m_w.group(2).strip()
            current_sets.append({"set": int(m_w.group(1)), "weight": raw_w if "kg" in raw_w.lower() else f"{raw_w} kg", "reps": int(m_w.group(3))})
        else:
            clean_name = re.sub(r"^[0-9]+[.)]\s*", "", line).strip("* -_")
            if clean_name.lower().startswith("set "):
                continue
            if current_exercise and current_sets:
                parsed_exercises[current_exercise] = current_sets
            current_exercise, current_sets = clean_name, []

    if current_exercise and current_sets:
        parsed_exercises[current_exercise] = current_sets

    return routine_key, parsed_exercises


def update_strength_routines_from_workout(workout_text, filepath=ROUTINES_JSON_PATH):
    """Aktualizuje wagi i powtórzenia w bazie JSON wyłącznie dla kanonicznych ćwiczeń danej rutyny."""
    routines_data = load_strength_routines(filepath)
    routine_key, parsed_exercises = parse_hevy_strength_workout(workout_text, routines_data=routines_data)
    if not routine_key or not parsed_exercises:
        return None

    if routine_key not in routines_data:
        alt_key = routine_key.replace("_", " ") if "_" in routine_key else routine_key.replace(" ", "_")
        if alt_key in routines_data:
            routine_key = alt_key
        else:
            logger.warning(f"Rutyna '{routine_key}' nie istnieje w pliku {filepath}.")
            return None

    canonical_dict = routines_data[routine_key].get("exercises", {})
    updated_exercises = []

    for ex_name, sets in parsed_exercises.items():
        c_norm = ex_name.strip().lower()
        c_stripped = re.sub(r"\s*\([^)]*\)", "", c_norm).strip()
        matched_canon = (
            ex_name if ex_name in canonical_dict
            else next((k for k in canonical_dict if k.strip().lower() == c_norm), None)
            or (next((k for k in canonical_dict if re.sub(r"\s*\([^)]*\)", "", k.strip().lower()).strip() == c_stripped), None) if c_stripped else None)
        )
        if matched_canon:
            canonical_dict[matched_canon]["last_sets"] = sets
            updated_exercises.append(matched_canon)
        else:
            logger.info(f"Pominięto ćwiczenie zmodyfikowane/doraźne: '{ex_name}' (brak w bazowej definicji rutyny '{routine_key}').")

    if updated_exercises:
        save_strength_routines(routines_data, filepath)
        return routine_key, updated_exercises
    return None


def format_strength_routines_for_prompt(routines_data=None, filepath=ROUTINES_JSON_PATH):
    """Formatuje bazę rutyn siłowych do postaci Markdown dla promptu modelu."""
    if routines_data is None:
        routines_data = load_strength_routines(filepath)
    elif isinstance(routines_data, (list, set, tuple)):
        all_routines = load_strength_routines(filepath)
        routines_data = {k: all_routines[k] for k in routines_data if k in all_routines}

    if not routines_data:
        return "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.json."

    def _fmt_ex_lines(ex_name, r_key, ex_data, b_pref, s_pref):
        last_sets = ex_data.get("last_sets", [])
        sets_str = (
            " | ".join(f"S{s.get('set', idx)}: {s.get('reps', '')} x {s.get('weight', 'mc')}" for idx, s in enumerate(last_sets, 1))
            if last_sets else "Brak danych w historii (ustal bezpieczną wagę startową)"
        )
        return (
            f"{b_pref}**{ex_name} ({r_key})**: {ex_data.get('target_sets', 3)} serie, {ex_data.get('target_reps', '8-10')} powtórzeń",
            f"{s_pref}Ostatnie serie i wagi: {sets_str}",
        )

    def _superset_meta(ex_data):
        sup_val = ex_data.get("superset") or ex_data.get("superset_role")
        if not sup_val:
            return None, None
        sup_str = str(sup_val).strip()
        m = re.match(r"^([A-Za-z]+)", sup_str)
        return (m.group(1).upper() if m else sup_str.upper()), sup_str

    output = [
        "# BAZA TRENINGÓW SIŁOWYCH (ROUTINES) I AKTUALNE OBCIĄŻENIA ROBOCZE",
        "* **Zasada doboru wag**: Do każdej serii planowanego treningu przypisz konkretną wagę i liczbę powtórzeń na podstawie 'Ostatnie serie i wagi' (lub zaplanuj bezpieczną progresję o max 1 parametr). Dla ćwiczeń 'mc' planuj ćwiczenie z masą ciała.",
        "",
    ]

    for routine_idx, (r_key, r_info) in enumerate(routines_data.items(), 1):
        output.append(f"## {routine_idx}. ROUTINE: {r_info.get('name', r_key.upper())}")
        if r_desc := r_info.get("description", ""):
            output.append(f"*{r_desc}*\n")

        exercises = r_info.get("exercises", {})
        if not exercises:
            output.append("*Zestaw jeszcze nie uzupełniony, pomiń go*\n")
            continue

        handled_supersets = set()
        item_counter = 1
        for ex_name, ex_data in exercises.items():
            group_key, _ = _superset_meta(ex_data)
            if group_key:
                if group_key in handled_supersets:
                    continue
                handled_supersets.add(group_key)
                output.append(f"{item_counter}. **[SUPERSET {group_key}]**:")
                for s_name, s_data in exercises.items():
                    s_key, role_tag = _superset_meta(s_data)
                    if s_key == group_key:
                        prefix = f"{role_tag}: " if role_tag else ""
                        output.extend(_fmt_ex_lines(f"{prefix}{s_name}", r_key, s_data, "   * ", "     - "))
            else:
                output.extend(_fmt_ex_lines(ex_name, r_key, ex_data, f"{item_counter}. ", "   * "))
            item_counter += 1
        output.append("")

    return "\n".join(output)


# ==============================================================================
# 3. KOMPRESJA HISTORII TRENINGOWEJ (42 DNI)
# ==============================================================================

def _extract_gym_exercises_summary(content):
    """Wyciąga zwięzłą listę zrealizowanych ćwiczeń siłowych z tabeli w raporcie dziennym."""
    m = re.search(r"\|\s*Nr\s*\|\s*Ćwiczenie[^\n]*\|\n\|(?:\s*:?-+:?\s*\|)+\n((?:\|[^\n]+\|\n?)+)", content, re.I)
    if not m:
        return _re_first(r"(?:Potwierdzenie i modyfikacje ćwiczeń|Wykonane ćwiczenia|ZESTAWIENIE ĆWICZEŃ):\s*([^\n]+)", content, flags=re.I)

    ex_list = []
    for row in m.group(1).strip().splitlines():
        cols = [col.strip() for col in row.split("|")[1:-1]]
        if len(cols) >= 3 and cols[1] and "Brak szczegółowego" not in cols[1]:
            name = RE_EX_TAG_STRIP.sub("", cols[1]).strip()
            reps = f" {cols[2]}" if cols[2] and cols[2] != "-" else ""
            weight = f" ({cols[3]})" if len(cols) > 3 and cols[3] and cols[3] != "-" else ""
            ex_list.append(f"{name}{reps}{weight}")
    return ", ".join(ex_list)


def get_historical_strength_summary(date_str, history_dir_path=HISTORY_DIR_PATH):
    """
    Wyszukuje i parsuje odnotowany trening siłowy z lokalnej historii (trainings_history/)
    do zwięzłej postaci podsumowującej jednostkę i wykonane ćwiczenia.
    """
    if not date_str:
        return ""
    try:
        year, month = date_str.split("-")[:2]
        candidates = (
            os.path.join(history_dir_path, year, month, f"{date_str}.md"),
            os.path.join(DEBUG_DIR_PATH, f"{date_str}.md"),
        )
        hist_file_path = next((p for p in candidates if os.path.exists(p)), None)
        if not hist_file_path:
            return ""

        h_content = _read_file_safe(hist_file_path, default_return="")
        m_strength = re.search(r"^\s*-\s*Siłownia:\s*([^\n\r]+)", h_content, re.MULTILINE | re.IGNORECASE)
        if m_strength and m_strength.group(1).strip().upper().startswith(("NIE", "BRAK")):
            return ""
        if not m_strength and not re.search(r"(siłowni|siłowa|hevy|fbw|upper|lower|strength)", h_content, re.IGNORECASE):
            return ""

        muscle_val = _re_first(RE_MUSCLE, h_content)
        muscle_str = f", partie: {muscle_val}" if muscle_val and muscle_val != "BRAK" else ""
        routine_label = _re_first(RE_PROFILE_HEADER, h_content) or (m_strength.group(1).strip() if m_strength else "Siłownia")
        ex_summary = _extract_gym_exercises_summary(h_content)
        return f"[Siłownia: {routine_label}{muscle_str}]{f': {ex_summary}' if ex_summary else ''}"
    except Exception as e:
        logger.warning(f"Błąd odczytu historii treningu siłowego z {date_str}: {e}")
        return ""


def _get_day_run_sessions(content, m_run):
    """Wyciąga liczbę sesji biegowych z raportu, łącząc rozgrzewkę/bieg główny/schłodzenie (< 3h) w 1 sesję."""
    if not m_run:
        return 0
    sessions = int(m_run.group(2)) if m_run.group(2) else 1
    if sessions <= 1:
        return sessions

    start_times = re.findall(r"###\s*Jednostka\s*\d+\s*\[Start:\s*(\d{1,2}):(\d{2})\]", content)
    if start_times:
        mins = sorted(int(h) * 60 + int(m) for h, m in start_times)
        if (mins[-1] - mins[0]) < SESSION_GAP_MINUTES:
            return 1
    elif any(k in content.lower() for k in AUX_RUN_KEYWORDS):
        return 1
    return sessions


def _summarize_history_weeks_1_4(history_data, start_date):
    """Generuje zagregowane podsumowanie tygodni 1–4 (Dni 1–28): kilometraż, liczba biegów i siłowni."""
    lines = []
    for w in range(HISTORY_MACRO_WEEKS):
        w_start = start_date + datetime.timedelta(days=w * 7)
        w_end = w_start + datetime.timedelta(days=6)
        w_km, w_runs, w_strength, files_found = 0.0, 0, 0, 0

        for d_offset in range(7):
            date_str = (w_start + datetime.timedelta(days=d_offset)).isoformat()
            if date_str in history_data:
                files_found += 1
                c = history_data[date_str]
                if m_run := RE_RUN_META.search(c):
                    if m_run.group(1):
                        w_km += float(m_run.group(1).replace(",", "."))
                    w_runs += _get_day_run_sessions(c, m_run)
                if RE_STR_TAK.search(c):
                    w_strength += 1

        if files_found == 0:
            lines.append(f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {NO_DATA}")
        else:
            lines.append(f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {w_km:.1f} km | Treningi biegowe: {w_runs} | Treningi siłowe: {w_strength}")
    return "\n".join(lines)


def _summarize_history_week_5(history_data, start_date):
    """Generuje zwarty opis jednostek z tygodnia 5 (Dni 29–35) na podstawie nagłówka metadanych."""
    lines = []
    w5_start = start_date + datetime.timedelta(days=HISTORY_MESO_OFFSET_DAYS)
    for d_offset in range(7):
        cur_d = w5_start + datetime.timedelta(days=d_offset)
        date_str, day_name = cur_d.isoformat(), DAYS_PL[cur_d.weekday()]
        if date_str not in history_data:
            lines.append(f"- {date_str} ({day_name}): {NO_DATA}")
            continue
        try:
            c = history_data[date_str]
            m_run, m_str = RE_RUN_W5.search(c), RE_STR_W5.search(c)
            parts_desc = []
            if m_run and m_run.group(1).upper() == "TAK":
                r_type = _re_first(RE_RUN_TYPE, c, "Bieg")
                r_struct = _re_first(RE_RUN_STRUCT, c)
                parts_desc.append(f"{r_type} ({m_run.group(2) or ''} km){f' [{r_struct}]' if r_struct and r_struct != 'Brak' else ''}")
            if m_str and m_str.group(1).upper() == "TAK":
                parts_desc.append(f"Siłownia: partie {_re_first(RE_MUSCLE, c, 'GÓRA / DÓŁ')}")

            c_lower = c.lower()
            if any(k in c_lower for k in ("typ dnia: pływanie", "typ dnia: plywanie", "trening pływania", "trening pływacki", "pool swim")):
                swim_dist = _re_first(r"(?:Trening pływania|Trening Uzupełniający|Pool Swim)[^\n]*\n-\s*Dystans:\s*([0-9.,]+\s*(?:km|m))", c, flags=re.I)
                parts_desc.append(f"Pływanie ({swim_dist})" if swim_dist else "Pływanie")
            elif "trening uzupełniający" in c_lower and not parts_desc:
                parts_desc.append("Trening uzupełniający")

            workout_desc = " + ".join(parts_desc) if parts_desc else "Dzień wolny / Regeneracja"
            decision_str = _re_first(RE_COACH_DECISION, c, "Zgodnie z planem").strip("*")
            lines.append(f"- {date_str} ({day_name}): {workout_desc} | Decyzja trenera: {decision_str}")
        except Exception:
            lines.append(f"- {date_str} ({day_name}): {NO_DATA}")
    return "\n".join(lines)


def _extract_interval_tables(content):
    """Wyciąga tabelę serii roboczych (splitów) dla treningów biegowych z akcentami."""
    pattern = r"(\|[^\n]*(?:Segment|Seria|Nr powtórzenia)[^\n]*\|\n\|(?:\s*:?-+:?\s*\|)+\n(?:\|[^\n]+\|\n?)+)"
    matched = [
        t.strip() for t in re.findall(pattern, content)
        if not (("Km" in (fl := t.splitlines()[0]) and "GAP" in fl) or "Parametr" in fl or "Plan" in fl)
        and any(k in fl for k in ("Dystans", "Tempo", "Czas", "HR", "GCT"))
    ]
    return next((t for t in matched if "Segment" in t or "Łączny Dystans" in t), matched[0] if matched else None)


def _summarize_history_day_for_planning(content, date_str, day_name):
    """Tworzy syntezę zrealizowanego dnia z ostatniego tygodnia (status ANS, jednostki, splity akcentu, ocena)."""
    if not content or content.strip() == NO_DATA:
        return f"#### {date_str} ({day_name}) – {NO_DATA}\n* Brak zarejestrowanych danych treningowych ani biometrycznych."

    day_type = _re_first(r"-\s*Typ dnia:\s*([^\n]+)", content, NO_DATA)
    m_run = re.search(r"-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([^)]+)\))?", content, re.I)
    is_run = bool(m_run and m_run.group(1).upper() == "TAK")
    run_meta = m_run.group(2) if m_run and m_run.group(2) else ""
    run_type = _re_first(RE_RUN_TYPE, content)
    run_struct = _re_first(RE_RUN_STRUCT, content)
    is_gym = bool(re.search(r"-\s*Siłownia:\s*TAK\b", content, re.I))
    muscles = _re_first(r"-\s*Partie mięśniowe[^:]*:\s*([^\n]+)", content)
    is_swim = any(k in content.lower() for k in ("typ dnia: pływanie", "typ dnia: plywanie", "pool swim", "trening pływania"))

    if is_run and run_type and run_type != "Brak biegu":
        headline_workout = f"Bieg: {run_type}"
    elif is_swim:
        headline_workout = "Pływanie"
    elif is_gym:
        headline_workout = f"Siłownia: partie {muscles}" if muscles and muscles != "BRAK" else "Siłownia"
    elif "regeneracja" in day_type.lower() or "brak" in day_type.lower():
        headline_workout = "Dzień wolny / Regeneracja"
    else:
        headline_workout = day_type

    hrv_str = _re_first(r"-\s*HRV[^:]*:\s*([^\n]+)", content, NO_DATA)
    rhr_str = _re_first(r"-\s*RHR[^:]*:\s*([^\n]+)", content, NO_DATA)
    sleep_str = _re_first(r"-\s*Sen[^:]*:\s*([^\n]+)", content, NO_DATA)
    bb_str = _re_first(r"Body Battery pod koniec dnia:\s*([^\n]+)", content) or _re_first(r"Body Battery:\s*([^\n]+)", content)
    bb_morn_str = _re_first(r"Poranne Body Battery[^:]*:\s*([^\n]+)", content)
    stress_str = (
        _re_first(r"-\s*(?:Całodzienny|Dzisiejszy całodzienny)\s*stres[^:]*:\s*(?:Średni poziom stresu:\s*)?([^\n]+)", content)
        or _re_first(r"-\s*Średni\s+(?!stres snu)stres[^:]*:\s*([^\n]+)", content)
    )
    steps_str = _re_first(r"(?:Kroki|Dzisiejsze kroki|Wczorajsze kroki)[^:]*:\s*([^\n]+)", content)

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

    workout_lines = []
    act_block = _re_first(r"##\s*Zarejestrowane aktywności[^\n]*\n(.*?)(?=\n##\s+[^\#]|\Z)", content, flags=re.DOTALL)
    if act_block:
        for u in re.split(r"\n(?=###\s+(?:Jednostka|Trening|[0-9]))", act_block):
            if not (u_clean := u.strip()):
                continue
            u_clean_base = re.split(r"\n####\s*Splity", u_clean, flags=re.I)[0].strip()
            u_title = u_clean_base.splitlines()[0].replace("###", "").strip()
            if "trening siłowy" in u_title.lower():
                continue
            if "pool swim" in u_clean.lower() or "pływanie" in u_clean.lower():
                u_title = re.sub(r"Trening Uzupełniający", "Trening pływania", u_title, flags=re.I)

            u_parts = [u_title]
            for label, pat, flg in (
                ("Dystans", r"Dystans:\s*([0-9.,]+\s*(?:km|m))", 0),
                ("Czas", r"Czas:\s*([0-9.,]+\s*(?:min|h))", 0),
                ("Śr. tempo", r"Średnie tempo:\s*([^\n|]+)", 0),
                ("HR", r"Tętno:\s*([^\n|]+(?:\s*\|\s*Max[^\n|]+)?)", 0),
                ("Kadencja", r"kadencja\s*([0-9]+\s*spm)", re.I),
                ("TE", r"Training Effect:\s*([^\n|]+(?:\s*\|\s*Beztlenowy[^\n|]+)?)", 0),
            ):
                if (val := _re_first(pat, u_clean_base, flags=flg)) and val not in ("Brak", "None", NO_DATA):
                    u_parts.append(f"{label}: {val}")
            workout_lines.append(" | ".join(u_parts))
    elif is_run:
        workout_lines.append(f"Bieg ({run_meta}) - {run_type}")

    if is_gym:
        gym_desc = f"Siłownia: partie {muscles}" if muscles and muscles != "BRAK" else "Siłownia"
        ex_summary = _extract_gym_exercises_summary(content)
        workout_lines.append(f"{gym_desc} (Ćwiczenia: {ex_summary})" if ex_summary else gym_desc)

    if not workout_lines:
        workout_lines.append("Brak aktywności treningowej (Rest Day)")

    raw_note = _re_first(r"##\s*Uwagi biegacza[^\n]*\n(.*?)(?=\n##|\Z)", content, flags=re.DOTALL)
    user_note_clean = re.sub(r"---\s*Treść wiadomości z Telegrama[^\n]*---\s*", "", raw_note, flags=re.I).replace("\\n", " ").strip()
    injury_warning = ""
    if user_note_clean:
        has_injury_kw = any(k in user_note_clean.lower() for k in ("ból", "bol", "uraz", "kontuzj", "pachwin", "ściegn", "kolan", "stop", "problem", "przeciąż"))
        injury_warning = f"⚠️ {user_note_clean}" if has_injury_kw else user_note_clean

    eval_parts = []
    if eval_v := _re_first(r"(?:Ocena(?:\s+biegu|\s+egzekucji(?:\s+planu)?|\s+treningu)?)[^\n:]*:\*?\*?\s*\[?([0-9]+/[0-9]+[^\n]*)", content):
        eval_parts.append(f"Ocena: {eval_v.rstrip(']')}")
    elif podsum_v := _re_first(r"^[*-]?\s*\*?\*?Podsumowanie[^\n:]*:\*?\*?\s*([^\n]+)", content):
        eval_parts.append(f"Podsumowanie: {podsum_v.strip('* ')}")
    if dec_v := _re_first(RE_COACH_DECISION, content).strip("* -"):
        eval_parts.append(f"Decyzja: {dec_v}")

    if phys_text := _re_first(
        r"(?:Uzasadnienie fizjologiczne|Drenaż fizjologiczny|Bodziec adaptacyjny i koszt tkankowy|Bodziec adaptacyjny i koszt metaboliczny|Bodziec fizjologiczny i szlaki energetyczne|Koszt nerwowo-mięśniowy|Dedykowana analiza fizjologiczna pływania)[^:\n]*:[ \t]*([^\n]+)",
        content,
    ):
        s_end = phys_text.find(".")
        eval_parts.append(phys_text[: s_end + 1] if s_end > 10 else phys_text)

    res = [
        f"#### {date_str} ({day_name}) – {headline_workout}",
        f"* **Status ANS i regeneracja**: {' | '.join(ans_parts)}",
        f"* **Zrealizowany trening**: {' + '.join(workout_lines)}",
    ]
    if run_struct and run_struct != "Brak" and is_run:
        res.append(f"* **Struktura biegu**: {run_struct}")
    if interval_table := _extract_interval_tables(content):
        res.append(f"* **Splity akcentu (serie robocze z audytu)**:\n\n{interval_table}\n")
    if injury_warning:
        res.append(f"* **Uwagi biegacza / urazy**: {injury_warning}")
    if eval_parts:
        res.append(f"* **Ocena trenera i adaptacja**: {' | '.join(eval_parts)}")

    return "\n".join(res)


def load_training_history(ref_date, history_dir_path=HISTORY_DIR_PATH):
    """
    Wczytuje i kompresuje 42-dniową historię treningową w 3 warstwach szczegółowości:
    Tygodnie 1–4 (makrocykl), Tydzień 5 (mezocykl) oraz Tydzień 6 (mikrocykl).
    """
    if not os.path.exists(history_dir_path):
        return None

    anchor_date = ref_date
    for i in range(HISTORY_ANCHOR_SEARCH_DAYS):
        test_date = ref_date - datetime.timedelta(days=i)
        d_str = test_date.isoformat()
        year, month = d_str.split("-")[:2]
        if os.path.exists(os.path.join(history_dir_path, year, month, f"{d_str}.md")):
            anchor_date = test_date
            break

    start_date = anchor_date - datetime.timedelta(days=HISTORY_WINDOW_DAYS - 1)
    history_data = {}
    for d_offset in range(HISTORY_WINDOW_DAYS):
        d_str = (start_date + datetime.timedelta(days=d_offset)).isoformat()
        year, month = d_str.split("-")[:2]
        if (content := _read_file_safe(os.path.join(history_dir_path, year, month, f"{d_str}.md"))) is not None:
            history_data[d_str] = content

    if not history_data:
        return None

    w6_start = start_date + datetime.timedelta(days=HISTORY_MICRO_OFFSET_DAYS)
    week_6_str = "\n\n".join(
        _summarize_history_day_for_planning(history_data.get((cur_d := w6_start + datetime.timedelta(days=i)).isoformat()), cur_d.isoformat(), DAYS_PL[cur_d.weekday()])
        for i in range(7)
    )

    return "\n\n".join([
        f"### 1. Podsumowanie makrocyklu (Tygodnie 1–4 / Dni 1–28):\n{_summarize_history_weeks_1_4(history_data, start_date)}",
        f"\n### 2. Zwarty przegląd mezocyklu (Tydzień 5 / Dni 29–35):\n{_summarize_history_week_5(history_data, start_date)}",
        f"\n### 3. Zwięzły przegląd ostatniego tygodnia (Tydzień 6 / Dni 36–42):\n{week_6_str}",
    ])


# ==============================================================================
# 4. GENEROWANIE PROMPTÓW (WEEKLY PLAN & DAILY AUDIT)
# ==============================================================================

def _format_splits_table(splits):
    """Formatuje listę splitów kilometrowych (słowników lub wierszy) do tabeli Markdown."""
    if not splits:
        return "Brak szczegółowych splitów"
    if isinstance(splits[0], str):
        return "\n".join(splits)

    lines = [
        "| Km | Dystans [km] | Czas | Tempo [/km] | GAP [/km] | HR śr/max [bpm] | Kadencja [spm] | Krok [m] | GCT [ms] | VO [cm] | Moc [W] | Wznios/Spadek [m] |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for s in splits:
        lines.append(
            f"| {s['lap']} | {s['distance']} | {s['time']} | {s['pace']} | {s['gap']} | "
            f"{s['hr']} | {s['cadence']} | {s['stride']} | {s['gct']} | {s['vo']} | "
            f"{s['power']} | {s['elevation']} |"
        )
    return "\n".join(lines)


def _format_activity_section(activity_stats, strength_workout=None):
    """Formatuje blok Markdown z listą wykonanych jednostek treningowych dla <executed_workout>."""
    parts = []
    if activity_stats:
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        for idx, act in enumerate(stats_list, 1):
            is_run, is_swim = act.get("is_run", True), act.get("is_swim", False)
            time_info = f" [Start: {act.get('start_time')}]" if act.get("start_time") and act.get("start_time") != NO_DATA else ""
            prefix = f"[JEDNOSTKA {idx} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")

            if is_run:
                splits_text = _format_splits_table(act.get("splits"))
                eg, el = act.get("elevation_gain", NO_DATA), act.get("elevation_loss", NO_DATA)
                elev_str = NO_DATA if eg == NO_DATA and el == NO_DATA else f"+{eg} / -{el}"
                parts.append(
                    f"{prefix}{act.get('name')} | Dystans: {act.get('distance')} | Czas: {act.get('duration')} | Śr. tempo: {act.get('pace')} | Przewyższenia: {elev_str}\n"
                    f"- Pogoda: {act.get('weather', NO_DATA)}\n"
                    f"- Tętno i obciążenie: HR śr. {act.get('avg_hr')} (max {act.get('max_hr')}) | Aerobic TE: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')} | Śr. moc: {act.get('avg_power')}\n"
                    f"- Biomechanika: Kadencja śr. {act.get('avg_cadence')} (max {act.get('max_cadence')}) | Krok: {act.get('stride_length')} | GCT: {act.get('ground_contact_time')} | VO: {act.get('vertical_oscillation')} (VR: {act.get('vertical_ratio')})\n"
                    f"- Splity:\n{splits_text}"
                )
            else:
                label = "TRENING PŁYWANIA" if is_swim else "TRENING UZUPEŁNIAJĄCY"
                parts.append(
                    f"{prefix}{label}: {act.get('name')} | Dystans: {act.get('distance')} | Czas: {act.get('duration')}\n"
                    f"- Tętno i obciążenie: HR śr. {act.get('avg_hr')} (max {act.get('max_hr')}) | Aerobic TE: {act.get('aerobic_te')} | Anaerobic TE: {act.get('anaerobic_te')}"
                )
    elif not strength_workout:
        parts.append("Brak zarejestrowanej aktywności w Garmin Connect ani na Telegramie (jeśli zaplanowano jednostkę, to nie została ona wykonana).")

    if strength_workout:
        parts.append(f"[JEDNOSTKA SIŁOWA (RAPORT Z TELEGRAMA)]:\n{strength_workout}")

    return "\n\n".join(parts)


def generate_weekly_plan_prompt(days_structure, personal_data, trainings_history=None, user_note=None, strength_routines=None, ref_date=None):
    """Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień."""
    if strength_routines is None:
        strength_routines = format_strength_routines_for_prompt()

    return load_prompt_template(
        "weekly_plan.md",
        **build_user_profile(personal_data, ref_date=ref_date),
        hist_section=trainings_history or "Brak zarejestrowanej historii treningów z ostatnich 42 dni.",
        weekly_preferences=days_structure,
        strength_routines=strength_routines or "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.json.",
        user_note=user_note or "Brak dodatkowych uwag od biegacza.",
    )


def _format_day_plan_section(raw_title, body_lines, day_name=None, keep_heading=False):
    """Formatuje i kompresuje pojedynczą sekcję dziennego planu treningowego."""
    clean_title = re.sub(rf"^{day_name}\s*[-–:]\s*", "", raw_title, flags=re.IGNORECASE).strip() if day_name else raw_title.strip()
    if clean_title.startswith("Siłownia:"):
        clean_title = clean_title.replace("Siłownia:", "Siłownia").strip()
    header_line = f"### {raw_title.strip()}" if keep_heading else clean_title

    expanded_lines = []
    for raw_line in body_lines:
        if m_ex_inline := re.match(r"^([*-]\s*(?:\*\*)?Ćwiczenia(?:\*\*)?:\s*)(.+)$", raw_line, flags=re.IGNORECASE):
            expanded_lines.extend(("- **Ćwiczenia**:", m_ex_inline.group(2).strip()))
        else:
            expanded_lines.append(raw_line)

    output_lines, i, in_exercises = [], 0, False
    while i < len(expanded_lines):
        line = expanded_lines[i]
        stripped_bullet = line.lstrip("*- ").strip()

        if stripped_bullet.startswith(("Wyjaśnienie decyzji:", "Decyzja:")) or line.startswith(("* **Cel", "- **Cel", "* **Uzasadnienie", "- **Uzasadnienie")):
            i += 1
            continue
        if "USUNIĘTO" in line:
            i += 1
            while i < len(expanded_lines) and expanded_lines[i].lstrip("*- ").startswith(("Seria", "S1:", "Decyzja", "Wyjaśnienie")):
                i += 1
            continue
        if "Status dolnych partii" in line:
            output_lines.append(re.sub(r"^[*-]\s*(?:\*\*)?Status dolnych partii(?:\*\*)?:\s*", "- Status dolnych partii: ", line))
            i += 1
            continue
        if "Ćwiczenia" in line and line.startswith(("* **", "-")):
            output_lines.append("- Ćwiczenia:")
            in_exercises = True
            i += 1
            continue
        if "Cardio" in line and line.startswith(("* **", "-")):
            in_exercises = False
            output_lines.append(re.sub(r"^[*-]\s*(?:\*\*)?Cardio[^:*]*(?:\*\*)?:\s*", "- Cardio: ", line))
            i += 1
            continue
        if line.startswith(("* **", "- **")) or (not in_exercises and line.startswith("- ")):
            in_exercises = False
            output_lines.append(re.sub(r"^[*-]\s*\*\*([^*]+)\*\*:\s*", r"- \1: ", line))
            i += 1
            continue

        if in_exercises:
            if re.match(r"^\[SUPERSET[^\]]*\]:?$", line.strip(), re.IGNORECASE):
                i += 1
                continue
            if inline_series_match := re.search(r"\b((?:S1|Seria\s*1)\s*:.*)$", line, flags=re.IGNORECASE):
                clean_ex_name = RE_EX_TAG_STRIP.sub("", line[: inline_series_match.start()]).strip(" *-_:.")
                output_lines.append(f"  * {clean_ex_name}: {inline_series_match.group(1).strip()}")
                i += 1
                continue

            clean_ex_name = RE_EX_TAG_STRIP.sub("", line).strip(" *-_:")
            series = []
            i += 1
            while i < len(expanded_lines):
                s_line = expanded_lines[i].lstrip("*- ").strip()
                if s_line.startswith("Seria") or re.match(r"^S\d+\s*:", s_line, flags=re.IGNORECASE):
                    series.append(s_line)
                    i += 1
                elif s_line.startswith(("Wyjaśnienie decyzji:", "Decyzja:")):
                    i += 1
                else:
                    break

            if series:
                num_sets = len(series)
                if m_s := re.search(r"(?:Seria\s*\d+|S\d+):\s*(\d+)\s*(?:x\s*([^(]+))?(?:\(([^)]+)\))?", series[0], flags=re.IGNORECASE):
                    reps = m_s.group(1)
                    weight_clean = (m_s.group(2) or "").strip().replace("na rękę", "/ręka").replace(" /", "/").strip()
                    all_rirs = [m.group(1) for s in series if (m := re.search(r"\(([^)]+)\)", s))]
                    rir_str = "RIR 2-3" if len(set(all_rirs)) > 1 else (all_rirs[-1] if all_rirs else (m_s.group(3) or "").strip())
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

    cleaned_lines = [
        line for idx, line in enumerate(output_lines)
        if not (line == "- Ćwiczenia:" and (idx + 1 >= len(output_lines) or not output_lines[idx + 1].startswith("  * ")))
    ]
    return f"{header_line}\n" + "\n".join(cleaned_lines) if cleaned_lines else header_line


def extract_day_plan(content, day_name):
    """Wyciąga skondensowane założenia treningowe dla konkretnego dnia z planu tygodniowego."""
    if not content:
        return "Brak planu"

    sections, current_section = [], None
    for line in content.split("\n"):
        if line.startswith(("### ", "## ")):
            if line.startswith("### ") and day_name in line:
                current_section = [line.replace("### ", "").strip()]
                sections.append(current_section)
            else:
                current_section = None
        elif current_section is not None and line.strip():
            current_section.append(line.strip())

    if not sections:
        return "Dzień wolny (lub brak wpisu)"

    return "\n\n".join(_format_day_plan_section(sec[0], sec[1:], day_name=day_name, keep_heading=False) for sec in sections)


def _compress_weekly_plan(content):
    """Kompresuje treść planu tygodniowego dla bloku <weekly_plan> w celu redukcji zużycia tokenów."""
    if not content:
        return content

    day_sections, summary_lines, current_day_sec, in_weekly_summary = [], [], None, False
    for line in content.split("\n"):
        if not (stripped := line.strip()):
            continue
        clean_label = stripped.strip("* -").strip().lower()

        if stripped.startswith(("### ", "## ")):
            if "podsumowanie tygodnia" in clean_label:
                in_weekly_summary, current_day_sec = True, None
                summary_lines.append(stripped)
            elif "uzasadnienie" in clean_label:
                in_weekly_summary, current_day_sec = False, None
            elif stripped.startswith("### "):
                in_weekly_summary = False
                current_day_sec = [stripped.replace("### ", "").strip()]
                day_sections.append(current_day_sec)
            else:
                current_day_sec = None
            continue

        if in_weekly_summary:
            if stripped.startswith(("*", "-")) and any(kw in clean_label for kw in ("planowan", "rozkład intensywnośc")):
                if not any(neg in clean_label for neg in ("hrv", "rhr", "poprzedni", "tętno")):
                    summary_lines.append(stripped)
        elif current_day_sec is not None:
            current_day_sec.append(stripped)

    formatted_parts = [_format_day_plan_section(sec[0], sec[1:], day_name=None, keep_heading=True) for sec in day_sections]
    if len(summary_lines) > 1:
        formatted_parts.append("\n".join(summary_lines))
    return "\n".join(formatted_parts)


def generate_daily_prompt(
    planned_workout, activity_stats, garmin_stats, weekly_plan_context,
    user_profile, user_note, strength_workout=None,
    audit_date_str=None, target_date_str=None, history_date_str=None,
    day_of_week=None, evening_routine_text=None,
):
    """Tworzy modularny prompt dla Gemini do wieczornego audytu dnia i adaptacji na jutro."""
    y_training = garmin_stats.get("yesterday_training", "Brak aktywności (dzień wolny)")
    if history_date_str and "[Siłownia:" not in y_training:
        m_iso = re.search(r"\d{4}-\d{2}-\d{2}", history_date_str)
        if m_iso and (hist_str := get_historical_strength_summary(m_iso.group(0))):
            y_training = hist_str if y_training == "Brak aktywności (dzień wolny)" else f"{y_training} + {hist_str}"

    y_steps = garmin_stats.get("yesterday_steps", NO_DATA)
    y_stress = garmin_stats.get("yesterday_stress", NO_DATA)
    yesterday_section = (
        "Brak danych (dzień wolny)"
        if (y_training == "Brak aktywności (dzień wolny)" and y_steps == NO_DATA and y_stress == NO_DATA)
        else f"Trening: {y_training} | Kroki: {y_steps} | DayStress: {y_stress}"
    )

    weekly_plan_section = _compress_weekly_plan(weekly_plan_context) if weekly_plan_context else "Brak planu tygodniowego w pliku output/weekly_plan.md"
    note_content = user_note or f"Brak dodatkowych uwag od biegacza na dzień {audit_date_str}."
    activity_section = _format_activity_section(activity_stats, strength_workout=strength_workout)
    profile_dict = user_profile if isinstance(user_profile, dict) else {}

    if evening_routine_text is None:
        evening_routine_text = _read_file_safe(EVENING_ROUTINE_PATH)
    evening_routine_section = evening_routine_text.strip() if evening_routine_text and evening_routine_text.strip() else "Brak zdefiniowanej rutyny wieczornej"

    stats_list = activity_stats if isinstance(activity_stats, list) else ([activity_stats] if activity_stats else [])
    audit_templates = [
        tpl for cond, tpl in (
            (any(act.get("is_run", True) for act in stats_list), "audit_run.md"),
            (any(not act.get("is_run", True) and act.get("is_swim", False) for act in stats_list), "audit_swim.md"),
            (bool(strength_workout), "audit_gym.md"),
            (any(not act.get("is_run", True) and not act.get("is_swim", False) for act in stats_list), "audit_other.md"),
        ) if cond
    ] or ["audit_rest.md"]

    base_text = load_prompt_template("daily_base.md")
    audit_parts = [load_prompt_template(t_name).strip() for t_name in audit_templates]
    closing_text = load_prompt_template("daily_closing.md")

    if day_of_week == "Niedziela":
        sunday_section_4 = (
            f"## 4. OCENA GOTOWOŚCI I DYREKTYWA NA DZIEŃ: {audit_date_str}\n\n"
            "* **DECYZJA ADAPTACYJNA:** [PEŁNA GOTOWOŚĆ / ZMĘCZENIE FUNKCJONALNE / GŁĘBOKI DŁUG ADAPTACYJNY / WYMAGANA REGENERACJA]\n"
            "* **Uzasadnienie fizjologiczne:** [Zwięzła diagnoza gotowości CUN, glikogenu i sztywności MTS pod kątem zamkniętego mikrocyklu; liczby wyłącznie w nawiasach]"
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
            "today_steps", "today_stress", "body_battery", "morning_body_battery",
            "hrv_last_night", "hrv_baseline_range", "rhr", "rhr_baseline",
            "sleep_score", "total_sleep_time", "deep_sleep", "rem_sleep", "sleep_stress",
        )
    }

    template_full = "\n\n".join(prompt_parts)
    all_vars = {
        **profile_dict,
        **garmin_vars,
        "today_date_str": audit_date_str,
        "yesterday_date_str": history_date_str,
        "tomorrow_date_str": target_date_str,
        "planned_workout": planned_workout or f"Brak sztywnego planu na dzień {audit_date_str}",
        "activity_section": activity_section,
        "yesterday_section": yesterday_section,
        "weekly_plan_section": weekly_plan_section,
        "evening_routine_section": evening_routine_section,
        "user_note": note_content,
    }
    for key, val in all_vars.items():
        template_full = template_full.replace(f"{{{key}}}", str(val) if val is not None else "")
    return template_full


# ==============================================================================
# 5. FORMATOWANIE I ZAPIS RAPORTÓW / ARCHIWUM
# ==============================================================================

def _format_acts_archive_blocks(all_stats):
    """Generuje bloki jednostek treningowych do pliku archiwum Markdown."""
    blocks = []
    for idx, act_s in enumerate(all_stats, 1):
        is_run, is_swim = act_s.get("is_run", True), act_s.get("is_swim", False)
        time_info = f" [Start: {act_s.get('start_time')}]" if act_s.get("start_time") and act_s.get("start_time") != NO_DATA else ""

        if is_run:
            splits_raw = act_s.get("splits", [])
            splits_formatted = _format_splits_table(splits_raw) if splits_raw else "Brak szczegółowych splitów dla tej jednostki"
            blocks.append(
                f"### Jednostka {idx}{time_info}: {act_s['name']}\n"
                f"- Warunki pogodowe: {act_s.get('weather', NO_DATA)}\n"
                f"- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}\n"
                f"- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}\n"
                f"- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}\n"
                f"- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}\n\n"
                f"#### Splity:\n{splits_formatted}"
            )
        else:
            unit_label = "Trening pływania" if is_swim else "Trening Uzupełniający"
            blocks.append(
                f"### {unit_label} {idx}{time_info}: {act_s['name']}\n"
                f"- Dystans: {act_s['distance']} | Czas: {act_s['duration']}\n"
                f"- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}\n"
                f"- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}"
            )
    return blocks


def _extract_strength_muscle_groups(strength_workout):
    """Wyznacza nazwę treningu siłowego oraz wskaźnik zaangażowanych partii mięśniowych."""
    if not strength_workout or not strength_workout.strip():
        return ("NIE", "BRAK")

    lines = [l.strip() for l in strength_workout.splitlines() if l.strip()]
    first_clean = lines[0].strip(":.,!- #*[]()\"'") if lines else ""
    first_lower = first_clean.lower()
    strength_line = f"TAK ({first_clean.upper() or 'TRENING SIŁOWY'})"

    if first_lower in ROUTINE_MUSCLE_MAP:
        return (strength_line, ROUTINE_MUSCLE_MAP[first_lower])

    text_lower = strength_workout.lower()
    has_upper = any(w in text_lower for w in ("góra", "klatka", "bench", "press", "row", "pull", "bicep", "tricep", "bark"))
    has_lower = any(w in text_lower for w in ("dół", "nóg", "squat", "przysiad", "deadlift", "calf", "łydk", "thrust"))
    muscle_groups = "GÓRA + DÓŁ" if (has_upper and has_lower) else ("DÓŁ" if has_lower else ("GÓRA" if has_upper else "GÓRA / DÓŁ"))
    return (strength_line, muscle_groups)


def _count_running_sessions(run_stats_list):
    """Zlicza liczbę odrębnych sesji biegowych w ciągu dnia (odstęp >= SESSION_GAP_MINUTES)."""
    if not run_stats_list:
        return 0
    if len(run_stats_list) == 1:
        return 1

    def _start_mins(act):
        st = act.get("start_time")
        m = re.search(r"(\d{1,2}):(\d{2})", st) if isinstance(st, str) else None
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    def _is_aux(act):
        name = str(act.get("name", "")).lower()
        return any(k in name for k in AUX_RUN_KEYWORDS)

    parsed_times = [_start_mins(act) for act in run_stats_list]
    if all(t is not None for t in parsed_times):
        sorted_acts = sorted(zip(parsed_times, run_stats_list), key=lambda x: x[0])
        sessions, last_time = 1, sorted_acts[0][0]
        for t, act in sorted_acts[1:]:
            if (t - last_time) >= SESSION_GAP_MINUTES and not _is_aux(act):
                sessions += 1
                last_time = t
            else:
                last_time = max(last_time, t)
        return sessions

    main_runs = [act for act in run_stats_list if not _is_aux(act)]
    return max(1, len(main_runs)) if main_runs else 1


def _extract_run_metadata(all_stats, response_text=None, strength_workout=None):
    """Wyciąga ustrukturyzowane metadane biegu: linię biegu, typ treningu, strukturę oraz ogólny typ dnia."""
    stats_list = all_stats if isinstance(all_stats, list) else ([all_stats] if all_stats else [])
    run_stats_list = [act for act in stats_list if act.get("is_run", True)]
    swim_stats_list = [act for act in stats_list if act.get("is_swim", False)]
    other_stats_list = [act for act in stats_list if not act.get("is_run", True) and not act.get("is_swim", False)]

    run_count = _count_running_sessions(run_stats_list)
    run_km = sum(float(m.group(1).replace(",", ".")) for act in run_stats_list if (m := RE_DIST_FLOAT.search(str(act.get("distance", "0")))))

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

    run_section_text = resp[resp_lower.find("część biegowa") :] if "część biegowa" in resp_lower else resp
    if "część siłowa" in run_section_text.lower():
        run_section_text = run_section_text[: run_section_text.lower().find("część siłowa")]

    cand = _re_first(RE_PROFILE_HEADER, run_section_text).strip("[]*")
    if cand and cand.lower() not in ("brak", "n/d", "nie dotyczy", "brak danych"):
        run_type = cand

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

    if not run_type:
        if any(k in resp_lower for k in ("dzień startowy", "bieg startowy", "start w zawodach", "udział w zawodach")):
            run_type = "Maraton / Bieg startowy" if "maraton" in resp_lower else ("Półmaraton / Bieg startowy" if "półmaraton" in resp_lower else "Zawody / Bieg startowy")
        else:
            resp_rules = (
                (("trening interwałowy", "interwały", "sesja vo2max", "odcinki robocze", "trening powtórzeniowy", "fartlek", "podbiegi"), "Interwały / Akcent (VO2max / Threshold)"),
                (("tempo maratońskie", "blok mp", "akcent mp", "trening progowy", "próg mleczanowy", "lthr", "strefa z4", "strefa z3", "drugi zakres", "ii zakres"), "Bieg progowy / Tempo (Threshold / MP)"),
                (("długie wybieganie", "long run", "trening objętościowy", "wybieganie"), "Długie wybieganie (Long Run)"),
                (("bieg regeneracyjny", "trucht regeneracyjny", "recovery run", "strefa z1", "regeneracja aktywna"), "Bieg regeneracyjny (Recovery Run)"),
                (("baza tlenowa", "bieg spokojny", "strefa z2", "pierwszy zakres", "i zakres", "easy run", "rozbieganie"), "Bieg spokojny (Easy Run / Z2)"),
            )
            run_type = next((label for kws, label in resp_rules if any(k in resp_lower for k in kws)), "Bieg ciągły (według analizy trenera)")

    if m_plan_struct := RE_PLAN_STRUCT.search(resp):
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
        run_structure = " + ".join(f"{a.get('name', f'Jednostka {idx}')} ({a.get('distance', '')})" for idx, a in enumerate(run_stats_list, 1))
    else:
        run_structure = f"Rozgrzewka: Brak | Główna seria: {run_km:.2f} km ({run_type}) | Schłodzenie: Brak"

    return (run_line, run_type, run_structure, day_type)


def build_daily_archive_content(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None):
    """Czysta funkcja formatująca treść raportu dziennego z 6-liniowym nagłówkiem metadanych do archiwum."""
    is_only_strength = False
    if strength_workout and user_note:
        cleaned_note = re.sub(r"---\s*Treść wiadomości z Telegrama[^\n]*---\s*", "", user_note)
        cleaned_note = re.sub(r"\[(?:RAPORT Z TELEGRAMA|NOWA WIADOMOŚĆ PORANNA)\]:\s*", "", cleaned_note).strip()
        is_only_strength = cleaned_note == strength_workout.strip()

    note_part = f"\n## Uwagi biegacza (notatka z Telegrama):\n{user_note.strip()}\n" if (user_note and user_note.strip() and not is_only_strength) else ""
    run_line, run_type, run_structure, day_type = _extract_run_metadata(all_stats, response_text, strength_workout)
    strength_line, muscle_groups = _extract_strength_muscle_groups(strength_workout)

    metadata_header = (
        f"# AUDYT DZIENNY: {workout_date} ({date_str})\n"
        f"- Typ dnia: {day_type}\n"
        f"- Bieg: {run_line}\n"
        f"- Typ treningu biegowego: {run_type}\n"
        f"- Struktura biegu: {run_structure}\n"
        f"- Siłownia: {strength_line}\n"
        f"- Partie mięśniowe (siłownia): {muscle_groups}"
    )

    act_sections = []
    if all_stats:
        act_sections.append("\n".join(_format_acts_archive_blocks(all_stats)))
    if strength_workout:
        act_sections.append(f"### Trening siłowy / uzupełniający (raport z Telegrama):\n{strength_workout}")
    acts_part = "\n## Zarejestrowane aktywności:\n" + "\n\n".join(act_sections) + "\n" if act_sections else ""

    rhr_archive = garmin_stats.get("rhr_status") or garmin_stats.get("rhr", NO_DATA)
    total_sleep = garmin_stats.get("total_sleep_time", NO_DATA)
    sleep_time_part = f"Czas: {total_sleep}, " if total_sleep and total_sleep != NO_DATA else ""

    bio_part = (
        f"## Biometria regeneracyjna i bilans dnia ({date_str}):\n"
        f"- HRV (miniona noc przed treningiem): {garmin_stats.get('hrv_status', NO_DATA)}\n"
        f"- RHR (miniona noc przed treningiem): {rhr_archive}\n"
        f"- Sen (miniona noc przed treningiem): {garmin_stats.get('sleep_score', NO_DATA)} ({sleep_time_part}Głęboki: {garmin_stats.get('deep_sleep', NO_DATA)}, REM: {garmin_stats.get('rem_sleep', NO_DATA)})\n"
        f"- Średni stres snu: {garmin_stats.get('sleep_stress', NO_DATA)}\n"
        f"- Poranne Body Battery (bufor startowy): {garmin_stats.get('morning_body_battery', NO_DATA)}\n"
        f"- Body Battery pod koniec dnia: {garmin_stats.get('body_battery', NO_DATA)}\n"
        f"- Całodzienny stres: {garmin_stats.get('today_stress', NO_DATA)}\n"
        f"- Kroki (cały dzień): {garmin_stats.get('today_steps', NO_DATA)}"
    )

    return f"{metadata_header}\n\n{bio_part}\n{acts_part}{note_part}\n## Ocena trenera i adaptacja na dzień {next_date_str}:\n{response_text}\n"


def save_daily_report(workout_date, archive_content, history_dir_path=HISTORY_DIR_PATH, output_dir_path=OUTPUT_DIR_PATH, debug=False):
    """Zapisuje wygenerowany raport trenera do pliku historii, bieżącego raportu oraz podglądu HTML."""
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


def build_and_save_daily_archive(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None, debug=False):
    """Formatuje i zapisuje raport dzienny do pliku archiwum w trainings_history/."""
    archive_content = build_daily_archive_content(
        workout_date, date_str, next_date_str, all_stats, garmin_stats,
        response_text, strength_workout=strength_workout, user_note=user_note,
    )
    save_daily_report(workout_date, archive_content, debug=debug)
