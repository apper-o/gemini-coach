"""
coach_prompts.py - Moduł generowania promptów dla Gemini, zarządzania historią, notatkami i raportami treningowymi.
"""

import os
import json
import datetime
import logging
import re

from send_telegram import fetch_recent_telegram_messages, save_telegram_state, markdown_to_html_doc

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
    "primary_goal", "secondary_goal", "phase", "time_left", "height", "weight", "max_hr", "lthr",
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


def build_user_profile(training_context):
    """
    Formatuje profil zawodnika (cele główne/poboczne, faza treningowa, czas do startu,
    antropometria, strefy tętna Z1-Z5 oraz rekordy życiowe PB) do postaci słownika dla promptów.
    """
    if not isinstance(training_context, dict):
        training_context = {}

    profile = dict(training_context)
    z1 = profile.get("z1", NO_DATA)
    z2 = profile.get("z2", NO_DATA)
    z3 = profile.get("z3", NO_DATA)
    z4 = profile.get("z4", NO_DATA)
    z5 = profile.get("z5", NO_DATA)

    profile["hr_zones"] = f"Z1: {z1}, Z2: {z2}, Z3: {z3}, Z4: {z4}, Z5: {z5}"
    profile["personal_records"] = format_personal_records(profile.get("personal_records"))
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


def separate_strength_and_user_notes(note: str | None) -> tuple[str | None, str | None]:
    """
    Rozdziela treść notatek użytkownika z Telegrama na:
    1. Trening(i) siłowy(e) – bloki, w których 1. linijka to nazwa rutyny (fbw, upper, lower, core, push, pull, legs).
    2. Uwagi biegacza – wiadomości rozpoczynające się od słowa 'NOTE' w 1. linijce (ze stripowaniem znacznika NOTE)
       oraz inne ogólne komentarze, z zachowaniem ich znaczników czasowych.

    Zwraca:
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


# Alias zachowany dla kompatybilności wstecznej
extract_strength_workout_from_note = separate_strength_and_user_notes





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
            print("\n" + "="*50)
            print("📲 ODEBRANO WIADOMOŚĆ Z TELEGRAMA:")
            print("="*50)
            print(tg_note)
            print("="*50 + "\n")
            user_note = tg_note
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wiadomości z Telegrama: {e}")

    if user_note:
        logger.info("Wczytano notatkę z Telegrama do promptu Trenera Gemini.")
        print(f"📝 Wiadomość dla Trenera Gemini (z Telegrama):\n   \"{user_note}\"\n")

    return user_note, new_tg_state


def _find_history_anchor_date(history_dir, all_files, ref_date):
    """Wyznacza datę bazową (anchor) dla 42-dniowego okna historii treningowej."""
    today_file = os.path.join(history_dir, f"{ref_date.isoformat()}.md")
    if os.path.exists(today_file):
        return ref_date

    past_dates = []
    for f in all_files:
        try:
            d = datetime.date.fromisoformat(f[:-3])
            if d <= ref_date:
                past_dates.append(d)
        except ValueError:
            pass

    if past_dates:
        return max(past_dates)

    try:
        return datetime.date.fromisoformat(all_files[0][:-3])
    except ValueError:
        return ref_date


def _summarize_history_weeks_1_4(history_dir, start_date):
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
            f_path = os.path.join(history_dir, f"{cur_d.isoformat()}.md")
            if os.path.exists(f_path):
                files_found += 1
                try:
                    with open(f_path, "r", encoding="utf-8") as hf:
                        c = hf.read()
                    m_run = re.search(r'^-\s*Bieg:\s*TAK\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\)', c, re.MULTILINE)
                    m_str = re.search(r'^-\s*Siłownia:\s*TAK', c, re.MULTILINE)

                    if m_run:
                        w_km += float(m_run.group(1).replace(',', '.'))
                        w_runs += int(m_run.group(2))
                    if m_str:
                        w_strength += 1
                except Exception:
                    pass

        if files_found == 0:
            weeks_1_4_lines.append(f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {NO_DATA}")
        else:
            weeks_1_4_lines.append(
                f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {w_km:.1f} km | Treningi biegowe: {w_runs} | Treningi siłowe: {w_strength}"
            )
    return "\n".join(weeks_1_4_lines)


def _summarize_history_week_5(history_dir, start_date):
    """
    Generuje zwarty opis jednostek z tygodnia 5 (Dni 29–35) na podstawie ustandaryzowanego nagłówka metadanych.
    Uwzględnia poszczególne typy treningów, rozgrzewkę, główną serię, schłodzenie, a dla treningów siłowych
    wskaźnik zaangażowanych partii mięśniowych (góra / dół), bez zamieszczania tabel ćwiczeń.
    """
    week_5_lines = []
    w5_start = start_date + datetime.timedelta(days=28)
    for d_offset in range(7):
        cur_d = w5_start + datetime.timedelta(days=d_offset)
        f_path = os.path.join(history_dir, f"{cur_d.isoformat()}.md")
        if not os.path.exists(f_path):
            week_5_lines.append(f"- {cur_d.isoformat()} ({DAYS_PL[cur_d.weekday()]}): {NO_DATA}")
            continue

        try:
            with open(f_path, "r", encoding="utf-8") as hf:
                c = hf.read()

            day_name = DAYS_PL[cur_d.weekday()]

            m_day_type = re.search(r'^-\s*Typ dnia:\s*([^\n]+)', c, re.MULTILINE)
            m_run = re.search(r'^-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([0-9.,]+)\s*km,\s*sesje:\s*([0-9]+)\))?', c, re.MULTILINE)
            m_run_type = re.search(r'^-\s*Typ treningu biegowego:\s*([^\n]+)', c, re.MULTILINE)
            m_run_struct = re.search(r'^-\s*Struktura biegu:\s*([^\n]+)', c, re.MULTILINE)
            m_str = re.search(r'^-\s*Siłownia:\s*(TAK|NIE)', c, re.MULTILINE)
            m_muscle = re.search(r'^-\s*Partie mięśniowe \(siłownia\):\s*([^\n]+)', c, re.MULTILINE)

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
            dec_m = re.search(r'\*\s*DECYZJA O KOREKCIE[^\n:]*:\s*([^\n]+)', c, re.IGNORECASE)
            if not dec_m:
                dec_m = re.search(r'\*\s*Zgodność z planem[^\n:]*:\s*([^\n]+)', c, re.IGNORECASE)
            decision_str = dec_m.group(1).strip() if dec_m else "Zgodnie z planem"

            day_entry = f"- {cur_d.isoformat()} ({day_name}): {workout_desc} | Decyzja trenera: {decision_str}"
            week_5_lines.append(day_entry)
        except Exception:
            week_5_lines.append(f"- {cur_d.isoformat()} ({DAYS_PL[cur_d.weekday()]}): {NO_DATA}")

    return "\n".join(week_5_lines)


def _load_history_week_6(history_dir, start_date):
    """Wczytuje pełne raporty dzienne z tygodnia 6 (Dni 36–42 / ostatnie 7 dni)."""
    week_6_entries = []
    w6_start = start_date + datetime.timedelta(days=35)
    for d_offset in range(7):
        cur_d = w6_start + datetime.timedelta(days=d_offset)
        f_path = os.path.join(history_dir, f"{cur_d.isoformat()}.md")
        if os.path.exists(f_path):
            try:
                with open(f_path, "r", encoding="utf-8") as hf:
                    week_6_entries.append(hf.read())
            except Exception:
                week_6_entries.append(f"### Dzień {cur_d.isoformat()} ({DAYS_PL[cur_d.weekday()]}):\n{NO_DATA}")
        else:
            week_6_entries.append(f"### Dzień {cur_d.isoformat()} ({DAYS_PL[cur_d.weekday()]}):\n{NO_DATA}")

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

    weeks_1_4 = _summarize_history_weeks_1_4(history_dir, start_date)
    week_5 = _summarize_history_week_5(history_dir, start_date)
    week_6 = _load_history_week_6(history_dir, start_date)

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
        act_blocks = []

        for idx, act in enumerate(stats_list):
            splits_text = "Brak szczegółowych splitów dla tej jednostki"
            if act.get('splits'):
                splits_text = "\n".join(act['splits'])

            time_info = f" [Start: {act['start_time']}]" if act.get('start_time') and act['start_time'] != NO_DATA else ""
            prefix = f"[JEDNOSTKA {idx + 1} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")
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
- Samoocena zawodnika (Garmin): RPE: {act.get('rpe', NO_DATA)} | Samopoczucie: {act.get('feeling', NO_DATA)}
- Splity kilometrowe / odcinki:
{splits_text}"""
            act_blocks.append(block)

        parts.append("-" * 35 + "\n\n" + "\n\n".join(act_blocks))
    elif not strength_workout:
        parts.append(f"W dniu {date_str} nie odnotowano treningu biegowego (Dzień wolny / Regeneracja).")

    if strength_workout:
        strength_block = (
            f"[JEDNOSTKA SIŁOWA / UZUPEŁNIAJĄCA (RAPORT Z TELEGRAMA)]:\n"
            f"{strength_workout}"
        )
        parts.append(strength_block)

    return "\n\n".join(parts)


def generate_weekly_suggestions_prompt(training_context, history_context=None, user_note=None):
    """
    Tworzy prompt dla Gemini w trybie 'suggest' bez przesyłania biometrii z Garmina.
    Model proponuje typy/cele treningów na podstawie profilu biegacza, historii z ostatnich 42 dni i notatki.
    """
    hist_section = history_context if history_context else "Brak zarejestrowanej historii treningów z ostatnich 42 dni."
    note_section = user_note if user_note else "Brak dodatkowych uwag od biegacza."
    profile = build_user_profile(training_context)

    return load_prompt_template(
        "weekly_suggestions.md",
        **profile,
        hist_section=hist_section,
        note_section=note_section
    )


def generate_weekly_plan_prompt(days_preferences, training_context, history_context=None, user_note=None, strength_routines=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień.
    """
    hist_section = history_context if history_context else "Brak zarejestrowanej historii treningów z ostatnich 42 dni."
    note_section = user_note if user_note else "Brak dodatkowych uwag od biegacza."
    routines_section = strength_routines if strength_routines else "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."
    profile = build_user_profile(training_context)

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
        splits_formatted = "\n".join(act_s.get('splits', []))
        if not splits_formatted:
            splits_formatted = "Brak szczegółowych splitów dla tej jednostki"
        time_info = f" [Start: {act_s['start_time']}]" if act_s.get('start_time') and act_s['start_time'] != NO_DATA else ""
        single_block = f"""### Jednostka {idx + 1}{time_info}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', NO_DATA)}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Samoocena: RPE: {act_s.get('rpe', NO_DATA)} | Samopoczucie: {act_s.get('feeling', NO_DATA)}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
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
        print(f"\n✅ [TRYB DEBUG] Zapisano raport do: {debug_latest_file} oraz {debug_archive_path} (Pliki produkcyjne nie zostały zmodyfikowane)")

        try:
            debug_latest_html = os.path.join(DEBUG_DIR, "last_daily_report.html")
            html_content = markdown_to_html_doc(archive_content, title=f"Raport Coach Gemini {workout_date} (Debug)")
            with open(debug_latest_html, "w", encoding="utf-8") as hf:
                hf.write(html_content)
            print(f"📄 [TRYB DEBUG] Wygenerowano podgląd HTML: {debug_latest_html}")
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
        print(f"\n🔄 Zaktualizowano (nadpisano) wcześniejszy raport w: {latest_daily_file} oraz archiwum {history_file_path}")
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

    run_count = len(stats_list)
    run_km = 0.0
    for act in stats_list:
        d_raw = str(act.get("distance", "0"))
        m = re.search(r'([0-9]+(?:[.,][0-9]+)?)', d_raw)
        if m:
            run_km += float(m.group(1).replace(",", "."))

    resp = response_text or ""

    if run_count == 0:
        run_line = "NIE (0.00 km, sesje: 0)"
        run_type = "Brak biegu"
        run_structure = "Brak"
        day_type = "SIŁOWNIA" if strength_workout else "REGENERACJA"
        return (run_line, run_type, run_structure, day_type)

    run_line = f"TAK ({run_km:.2f} km, sesje: {run_count})"
    day_type = "BIEG + SIŁOWNIA" if strength_workout else "BIEG"

    # Wykrywanie typu treningu biegowego
    run_type = None
    m_profile = re.search(r'\*\s*Profil jednostki:\s*([^\n]+)', resp)
    if m_profile:
        run_type = m_profile.group(1).strip()
    if not run_type:
        m_day = re.search(r'\*\s*Typ dnia:\s*BIEGOWY\s*\(([^)]+)\)', resp)
        if m_day:
            run_type = m_day.group(1).strip()

    if not run_type:
        act_names = " ".join([str(a.get("name", "")) for a in stats_list]).lower()
        if "vo2max" in resp.lower() or "interwał" in resp.lower() or any("interwał" in str(a.get("name", "")).lower() for a in stats_list):
            run_type = "Interwały / Próg (VO2max / Threshold)"
        elif "mp" in resp.lower() or "maratoński" in resp.lower() or "maraton" in resp.lower():
            run_type = "Tempo Maratońskie (MP)"
        elif run_km >= 14.0:
            run_type = "Długie wybieganie (Long Run)"
        elif any("recovery" in str(a.get("name", "")).lower() for a in stats_list) or "regenerac" in resp.lower():
            run_type = "Bieg regeneracyjny (Recovery Run)"
        else:
            run_type = "Bieg spokojny (Easy Run / Z2)"

    # Wykrywanie struktury biegu (Rozgrzewka, Główna seria, Schłodzenie)
    run_structure = None
    m_plan_struct = re.search(r'Dystans:\s*Plan:[^\n\(]*\(([^)]*(?:rozgrzewk|schłodzen|główn|mp|tempo)[^)]*)\)', resp, re.IGNORECASE)
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
        for idx, a in enumerate(stats_list):
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
- Całodzienny stres w dniu {date_str}: {garmin_stats.get('today_stress')}
- Kroki w dniu {date_str} (cały dzień): {garmin_stats.get('today_steps')}"""

    return f"""{metadata_header}

{bio_part}
{acts_part}{note_part}
## Ocena trenera i adaptacja na dzień {next_date_str}:
{response_text}
"""


def _build_and_save_daily_archive(workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None, debug=False, mode="daily"):
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


def finish_run(new_tg_state=None, debug=False, note_file=None):
    """
    Zapisuje zaktualizowany stan Telegrama po udanym wykonaniu trybu.
    W trybie debug (debug=True) operacja ta jest pomijana, aby chronić stan wiadomości.
    """
    if debug:
        logger.info("[DEBUG] Tryb debugowania aktywny: pominięto aktualizację stanu Telegrama.")
        print("\n🛡️  [TRYB DEBUG] Stan Telegrama pozostał nienaruszony.")
        return

    # Kompatybilność wsteczna na wypadek wywołania ze starej sygnatury finish_run(note_file, new_tg_state, debug)
    if isinstance(note_file, dict) and new_tg_state is None:
        new_tg_state = note_file

    if new_tg_state and save_telegram_state:
        save_telegram_state(new_tg_state)

