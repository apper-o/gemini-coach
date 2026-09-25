"""
coach_prompts.py - Moduł generowania promptów dla Gemini, zarządzania historią, notatkami i raportami treningowymi.
"""

import os
import sys
import json
import datetime
import logging
import re

from send_telegram import fetch_recent_telegram_messages, save_telegram_state, markdown_to_html_doc
from garmin_service import _extract_exercise_tables

logger = logging.getLogger(__name__)

# Stałe globalne
NO_DATA = "Brak danych"
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR = "input"
OUTPUT_DIR = "output"
PROMPTS_DIR = "prompts"
HISTORY_DIR = "trainings_history"
DEBUG_DIR = "debug"


# ==============================================================================
# 1. PLIKI WEJŚCIOWE, NOTATKA BIEGACZA I HISTORIA 42 DNI
# ==============================================================================

def load_training_config(config_file=os.path.join(INPUT_DIR, "training_config.json")):
    """
    Wczytuje kontekst treningowy, strefy tętna i cele biegacza z pliku JSON w folderze input/.
    Jeśli jakiejś wartości brakuje, przyjmuje 'Brak danych' bez wpisywania fikcyjnych danych domyślnych.
    """
    keys = ["goal", "phase", "time_left", "max_hr", "lthr", "z1", "z2", "z3", "z4", "z5"]
    default_config = {k: NO_DATA for k in keys}

    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    if not os.path.exists(config_file):
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"Utworzono pusty szablon konfiguracji treningowej: {config_file}")
        except Exception as e:
            logger.warning(f"Nie udało się utworzyć pliku {config_file}: {e}")
        return default_config

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            merged = default_config.copy()
            merged.update(user_config)
            for k, v in merged.items():
                if v is None or (isinstance(v, str) and (not v.strip() or v.strip().lower() in ["nieznany", "brak"])):
                    merged[k] = NO_DATA
            return merged
    except Exception as e:
        logger.warning(f"Błąd odczytu {config_file}: {e}. Używam pustej konfiguracji.")
        return default_config


def build_user_profile(training_context):
    """
    Formatuje profil stref tętna zawodnika do promptu.
    """
    return {
        "max_hr": training_context.get("max_hr", NO_DATA),
        "lthr": training_context.get("lthr", NO_DATA),
        "hr_zones": (
            f"Z1: {training_context.get('z1', NO_DATA)}, "
            f"Z2: {training_context.get('z2', NO_DATA)}, "
            f"Z3: {training_context.get('z3', NO_DATA)}, "
            f"Z4: {training_context.get('z4', NO_DATA)}, "
            f"Z5: {training_context.get('z5', NO_DATA)}"
        )
    }


def load_weekly_plan(weekly_plan_file):
    """
    Wczytuje treść planu tygodniowego, jeśli plik istnieje.
    """
    if os.path.exists(weekly_plan_file):
        try:
            with open(weekly_plan_file, "r", encoding="utf-8") as wf:
                return wf.read()
        except Exception as e:
            logger.warning(f"Nie udało się odczytać planu tygodniowego z {weekly_plan_file}: {e}")
    return None


def load_strength_routines(file_path=None):
    """
    Wczytuje bazę własnych zestawów siłowych biegacza (FBW, UPPER, LOWER) z pliku input/strength_routines.md.
    """
    if file_path is None:
        file_path = os.path.join(INPUT_DIR, "strength_routines.md")

    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            logger.info(f"Wczytano bazę zestawów siłowych z pliku: {file_path}")
            return content
        return None
    except Exception as e:
        logger.warning(f"Nie udało się odczytać pliku {file_path}: {e}")
        return None


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


def load_user_note(note_file=None):
    """
    Wczytuje opcjonalną notatkę użytkownika do trenera z folderu prompts/user_note.md.
    """
    if note_file is None:
        note_file = os.path.join(PROMPTS_DIR, "user_note.md")

    if not os.path.exists(note_file):
        os.makedirs(os.path.dirname(note_file), exist_ok=True)
        try:
            with open(note_file, "w", encoding="utf-8") as f:
                f.write("# Notatki i uwagi do trenera Gemini (wpisz swoje uwagi poniżej, linie z # są ignorowane)\n")
        except Exception:
            pass
        return None

    try:
        with open(note_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        valid_lines = [l for l in lines if not l.strip().startswith("#")]
        content = "".join(valid_lines).strip()
        return content if content else None
    except Exception as e:
        logger.warning(f"Nie udało się odczytać pliku {note_file}: {e}")
        return None


def clear_user_note(note_file=None):
    """
    Czyści plik notatki użytkownika po uruchomieniu, pozostawiając jedynie nagłówek z komentarzem.
    """
    if note_file is None:
        note_file = os.path.join(PROMPTS_DIR, "user_note.md")

    try:
        if os.path.exists(note_file):
            with open(note_file, "w", encoding="utf-8") as f:
                f.write("# Notatki i uwagi do trenera Gemini (wpisz swoje uwagi poniżej, linie z # są ignorowane)\n")
            logger.info(f"Wyczyszczono plik notatki użytkownika: {note_file}")
    except Exception as e:
        logger.warning(f"Nie udało się wyczyścić pliku notatki {note_file}: {e}")


def _extract_strength_workout_from_note(note):
    """
    Wykrywa i wyodrębnia raport z treningu siłowego z notatki użytkownika (np. przesłanej przez Telegram).
    Sprawdza, czy w pierwszej linijce notatki (lub wiadomości) występuje pojedyncze słowo
    będące nazwą treningu siłowego: 'upper', 'fbw' lub 'lower'.
    Zwraca wyczyszczony tekst treningu siłowego lub None, jeśli notatka nie jest treningiem siłowym.
    """
    if not note or not note.strip():
        return None

    # Sprawdzamy poszczególne bloki wiadomości (jeśli wiadomość pochodzi z Telegrama) lub całość notatki
    blocks = re.split(r'---\s*Treść wiadomości z Telegrama[^\n]*---\s*', note)
    for block in blocks:
        cleaned = re.sub(r'\[RAPORT Z TELEGRAMA\]:\s*', '', block).strip()
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines:
            continue
        first_line = lines[0].strip(":.,!- #*").lower()
        if first_line in ["upper", "fbw", "lower"]:
            return cleaned

    return None


def extract_existing_strength_workout(history_file_path):
    """
    Jeśli dla danej daty w trainings_history/ istnieje już raport z treningiem siłowym,
    odzyskuje jego treść, aby poranne nadpisanie raportu nie utraciło danych o siłowni.
    """
    if not os.path.exists(history_file_path):
        return None
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r"### Trening siłowy / uzupełniający \(raport z Telegrama\):\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            if extracted:
                return extracted
    except Exception as e:
        logger.warning(f"Nie udało się odczytać wcześniejszego treningu siłowego z {history_file_path}: {e}")
    return None


def extract_existing_user_note(history_file_path):
    """
    Jeśli dla danej daty w trainings_history/ istnieje już raport z uwagami biegacza,
    odzyskuje treść notatki, aby poranny audyt wczorajszego dnia nie utracił komentarza z wieczora.
    """
    if not os.path.exists(history_file_path):
        return None
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r"## Uwagi biegacza \(notatka z Telegrama\):\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            if extracted:
                return extracted
    except Exception as e:
        logger.warning(f"Nie udało się odczytać wcześniejszej notatki z {history_file_path}: {e}")
    return None


def prepare_user_note(note_file=None):
    """
    Wczytuje najnowsze wiadomości i uwagi od biegacza bezpośrednio z czatu Telegrama.
    Wszelkie notatki do trenera pochodzą wyłącznie z Telegrama.
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


def load_training_history(history_dir=HISTORY_DIR, days=42, ref_date=None):
    """
    Wczytuje historię treningów z folderu trainings_history z ostatnich 42 dni (6 tygodni)
    z wielopoziomową szczegółowością:
    - Tygodnie 1–4 (Dni 1–28): podsumowanie tygodniowe (kilometry, treningi biegowe, siłowe).
    - Tydzień 5 (Dni 29–35 / 8–14 dni wstecz): zwarty opis wykonanych jednostek wraz z pełnymi tabelami ćwiczeń biegowych i siłowych (bez ucinania serii, powtórzeń i ciężarów).
    - Tydzień 6 (Dni 36–42 / ostatnie 7 dni): pełne szczegółowe analizy dzienne.
    Dla brakujących dni lub tygodni wstawia 'Brak danych'.
    """
    if not os.path.exists(history_dir):
        return None

    if ref_date is None:
        ref_date = datetime.date.today()

    all_files = sorted([f for f in os.listdir(history_dir) if f.endswith(".md")], reverse=True)
    if not all_files:
        return None

    # Sprawdzamy czy istnieje raport na dzień dzisiejszy (ref_date)
    today_file = os.path.join(history_dir, f"{ref_date.isoformat()}.md")
    if os.path.exists(today_file):
        anchor_date = ref_date
    else:
        past_dates = []
        for f in all_files:
            try:
                d = datetime.date.fromisoformat(f[:-3])
                if d <= ref_date:
                    past_dates.append(d)
            except ValueError:
                pass
        if past_dates:
            anchor_date = max(past_dates)
        else:
            try:
                anchor_date = datetime.date.fromisoformat(all_files[0][:-3])
            except ValueError:
                anchor_date = ref_date

    # Wyznaczamy 42 dni (6 tygodni) licząc wstecz od anchor_date (anchor_date to dzień 42)
    start_date = anchor_date - datetime.timedelta(days=41)

    # 1. Tygodnie 1–4 (Dni 1–28)
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
                    dists = [float(x) for x in re.findall(r'-\s*Dystans:\s*([0-9.]+)\s*km', c)]
                    if dists:
                        w_km += sum(dists)
                        w_runs += len(dists)
                    elif "Aktywność: Brak biegu" not in c and "Bieg" in c:
                        w_runs += 1

                    if re.search(r'(siłowni|siłowa|hevy|fbw|upper|lower|strength)', c, re.IGNORECASE):
                        w_strength += 1
                except Exception:
                    pass

        if files_found == 0:
            weeks_1_4_lines.append(f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {NO_DATA}")
        else:
            weeks_1_4_lines.append(
                f"- Tydzień {w + 1} ({w_start.isoformat()} – {w_end.isoformat()}): {w_km:.1f} km | Treningi biegowe: {w_runs} | Treningi siłowe: {w_strength}"
            )

    # 2. Tydzień 5 (Dni 29–35)
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
            is_rest_day = "Aktywność: Brak biegu" in c or "DZIEŃ WOLNY" in c
            is_strength = bool(re.search(r'(siłowni|siłowa|hevy|fbw|upper|lower|strength)', c, re.IGNORECASE))

            units = re.findall(
                r'###\s*(Jednostka[^\n]+)\n(?:-\s*Warunki[^\n]*\n)?-\s*Dystans:\s*([0-9.]+\s*km)[^|\n]*\|\s*Czas:\s*([^|\n]+)\|\s*Średnie tempo:\s*([^\n]+)\n-\s*Tętno:\s*([^\n]+)',
                c
            )
            act_summaries = []
            for u in units:
                act_summaries.append(f"{u[0].strip()}: {u[1].strip()}, tempo {u[3].strip()}, tętno {u[4].strip()}")

            if not act_summaries and not is_rest_day:
                dists = re.findall(r'-\s*Dystans:\s*([0-9.]+\s*km)', c)
                paces = re.findall(r'Średnie tempo:\s*([^|\n]+)', c)
                hrs = re.findall(r'-\s*Tętno:\s*([^\n]+)', c)
                for i in range(len(dists)):
                    p = paces[i].strip() if i < len(paces) else NO_DATA
                    h = hrs[i].strip() if i < len(hrs) else NO_DATA
                    act_summaries.append(f"Bieg: {dists[i]}, tempo {p}, tętno {h}")

            workout_desc = ", ".join(act_summaries) if act_summaries else ("Dzień wolny / Regeneracja" if is_rest_day else "Aktywność zarejestrowana")
            if is_strength and "siłowni" not in workout_desc.lower():
                workout_desc += " + Trening siłowy"

            dec_m = re.search(r'\*\s*DECYZJA O KOREKCIE:\s*([^\n]+)', c)
            if not dec_m:
                dec_m = re.search(r'\*\s*Zgodność z planem:\s*([^\n]+)', c)
            decision_str = dec_m.group(1).strip() if dec_m else "Zgodnie z planem"

            day_entry = f"- {cur_d.isoformat()} ({day_name}): {workout_desc} | Decyzja trenera: {decision_str}"
            ex_tables = _extract_exercise_tables(c)
            if ex_tables:
                tables_formatted = "\n\n".join(ex_tables)
                day_entry += f"\n\n  * Tabele ćwiczeń i serii ({cur_d.isoformat()}):\n{tables_formatted}\n"
            elif is_strength:
                wb_match = re.search(r'(WARIANT B:[^\n]+\n(?:[^\n]+\n){1,10})', c)
                if wb_match:
                    day_entry += f"\n\n  * Realizacja siłowa ({cur_d.isoformat()}):\n{wb_match.group(1).strip()}\n"

            week_5_lines.append(day_entry)
        except Exception as e:
            week_5_lines.append(f"- {cur_d.isoformat()} ({DAYS_PL[cur_d.weekday()]}): {NO_DATA}")

    # 3. Tydzień 6 (Dni 36–42, ostatnie 7 dni)
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

    sections = [
        "### 1. Podsumowanie makrocyklu (Tygodnie 1–4 / Dni 1–28):\n" + "\n".join(weeks_1_4_lines),
        "\n### 2. Zwarty przegląd mezocyklu (Tydzień 5 / Dni 29–35):\n" + "\n".join(week_5_lines),
        "\n### 3. Pełne szczegółowe raporty z ostatniego tygodnia (Tydzień 6 / Dni 36–42):\n" + ("\n\n" + "-"*40 + "\n\n").join(week_6_entries)
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

    return load_prompt_template(
        "weekly_suggestions.md",
        goal=training_context.get('goal', NO_DATA),
        phase=training_context.get('phase', NO_DATA),
        time_left=training_context.get('time_left', NO_DATA),
        max_hr=training_context.get('max_hr', NO_DATA),
        lthr=training_context.get('lthr', NO_DATA),
        z1=training_context.get('z1', NO_DATA),
        z2=training_context.get('z2', NO_DATA),
        z3=training_context.get('z3', NO_DATA),
        z4=training_context.get('z4', NO_DATA),
        z5=training_context.get('z5', NO_DATA),
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

    return load_prompt_template(
        "weekly_plan.md",
        goal=training_context.get('goal', NO_DATA),
        phase=training_context.get('phase', NO_DATA),
        time_left=training_context.get('time_left', NO_DATA),
        max_hr=training_context.get('max_hr', NO_DATA),
        lthr=training_context.get('lthr', NO_DATA),
        z1=training_context.get('z1', NO_DATA),
        z2=training_context.get('z2', NO_DATA),
        z3=training_context.get('z3', NO_DATA),
        z4=training_context.get('z4', NO_DATA),
        z5=training_context.get('z5', NO_DATA),
        hist_section=hist_section,
        strength_routines=routines_section,
        days_preferences=days_preferences,
        note_section=note_section
    )


def generate_verification_prompt(planned_workout, activity_stats, garmin_stats, weekly_plan_context,
                                 user_profile, user_note, today_date_str, yesterday_date_str,
                                 tomorrow_date_str, trening_z_planu, strength_workout=None):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu oraz całodziennej/nocnej regeneracji
    oraz adaptacji planu na kolejny dzień.
    """
    yesterday_section = f"Brak danych z dnia {yesterday_date_str} (dzień wolny)"
    if garmin_stats.get('yesterday_training') and garmin_stats.get('yesterday_training') != "Brak aktywności (dzień wolny)":
        yesterday_section = f"""
====================
KONTEKST DNIA POPRZEDNIEGO ({yesterday_date_str}):
{garmin_stats.get('yesterday_training')}
"""

    weekly_plan_section = "Brak planu tygodniowego w pliku output/weekly_plan.md"
    if weekly_plan_context:
        weekly_plan_section = f"""
====================
AKTUALNY PLAN TYGODNIOWY (I KOLEJNE ZAPLANOWANE TRENINGI):
{weekly_plan_context}
"""

    note_content = user_note if user_note else f"Brak dodatkowych uwag od biegacza na dzień {today_date_str}."
    activity_section = _format_activity_section(activity_stats, today_date_str, strength_workout=strength_workout)

    return load_prompt_template(
        "daily_verification.md",
        max_hr=user_profile.get('max_hr', NO_DATA),
        lthr=user_profile.get('lthr', NO_DATA),
        hr_zones=user_profile.get('hr_zones', NO_DATA),
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        tomorrow_date_str=tomorrow_date_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {today_date_str}',
        activity_section=activity_section,
        yesterday_section=yesterday_section,
        weekly_plan_section=weekly_plan_section,
        user_note=note_content,
        trening_z_planu=trening_z_planu or f"Odszukaj w planie tygodniowym jednostkę na dzień {tomorrow_date_str}",
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


def generate_yesterday_verification_prompt(planned_workout, activity_stats, garmin_stats, weekly_plan_context,
                                          user_profile, user_note, today_date_str, yesterday_date_str,
                                          day_before_yesterday_date_str, trening_z_planu, strength_workout=None):
    """
    Tworzy prompt dla Gemini w trybie 'yesterday' do audytu wczorajszego treningu,
    oceny regeneracji z minionej nocy (sen wczoraj->dziś) oraz natychmiastowej adaptacji planu na dzień dzisiejszy.
    """
    day_before_yesterday_section = f"Brak danych z dnia {day_before_yesterday_date_str} (dzień wolny)"
    if garmin_stats.get('day_before_yesterday_training') and garmin_stats.get('day_before_yesterday_training') != "Brak aktywności (dzień wolny)":
        day_before_yesterday_section = f"""
====================
KONTEKST DNIA PRZEDWCZORAJSZEGO ({day_before_yesterday_date_str}):
{garmin_stats.get('day_before_yesterday_training')}
"""

    weekly_plan_section = "Brak planu tygodniowego w pliku output/weekly_plan.md"
    if weekly_plan_context:
        weekly_plan_section = f"""
====================
AKTUALNY PLAN TYGODNIOWY (I KOLEJNE ZAPLANOWANE TRENINGI):
{weekly_plan_context}
"""

    note_content = user_note if user_note else f"Brak dodatkowych uwag od biegacza na dzień dzisiejszy ({today_date_str}) ani odnośnie wczorajszych jednostek."
    activity_section = _format_activity_section(activity_stats, yesterday_date_str, strength_workout=strength_workout)

    return load_prompt_template(
        "yesterday_verification.md",
        max_hr=user_profile.get('max_hr', NO_DATA),
        lthr=user_profile.get('lthr', NO_DATA),
        hr_zones=user_profile.get('hr_zones', NO_DATA),
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        day_before_yesterday_date_str=day_before_yesterday_date_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {yesterday_date_str}',
        activity_section=activity_section,
        yesterday_steps=garmin_stats.get('yesterday_steps', NO_DATA),
        yesterday_stress=garmin_stats.get('yesterday_stress', NO_DATA),
        yesterday_body_battery=garmin_stats.get('yesterday_body_battery', NO_DATA),
        hrv_status=garmin_stats.get('hrv_status', NO_DATA),
        rhr=garmin_stats.get('rhr', NO_DATA),
        sleep_score=garmin_stats.get('sleep_score', NO_DATA),
        deep_sleep=garmin_stats.get('deep_sleep', NO_DATA),
        rem_sleep=garmin_stats.get('rem_sleep', NO_DATA),
        sleep_insights=garmin_stats.get('sleep_insights', NO_DATA),
        morning_body_battery=garmin_stats.get('morning_body_battery', NO_DATA),
        day_before_yesterday_section=day_before_yesterday_section,
        weekly_plan_section=weekly_plan_section,
        user_note=note_content,
        trening_z_planu=trening_z_planu or f"Odszukaj w planie tygodniowym jednostkę na dzień dzisiejszy ({today_date_str})"
    )


def build_verification_prompt(day, planned_workout, activity_stats, garmin_stats, weekly_plan_context,
                              user_profile, user_note, audit_date_str, target_date_str,
                              history_date_str, target_plan_desc=None, strength_workout=None, trening_z_planu=None):
    """
    Zunifikowana fasada generowania promptu weryfikacyjnego.
    Hermetyzuje przypisanie ról dat do parametrów generatorów promptów:
    - Dla day == 'yesterday':
        today_date_str (dzień adaptacji / cel) = target_date_str
        yesterday_date_str (dzień audytowany) = audit_date_str
        day_before_yesterday_date_str (tło historyczne) = history_date_str
    - Dla day in ['today', 'daily']:
        today_date_str (dzień weryfikowany) = audit_date_str
        yesterday_date_str (tło historyczne) = history_date_str
        tomorrow_date_str (dzień adaptacji / cel) = target_date_str
    """
    target_plan = target_plan_desc or trening_z_planu

    if day == "yesterday":
        return generate_yesterday_verification_prompt(
            planned_workout=planned_workout,
            activity_stats=activity_stats,
            garmin_stats=garmin_stats,
            weekly_plan_context=weekly_plan_context,
            user_profile=user_profile,
            user_note=user_note,
            today_date_str=target_date_str,
            yesterday_date_str=audit_date_str,
            day_before_yesterday_date_str=history_date_str,
            trening_z_planu=target_plan,
            strength_workout=strength_workout
        )
    return generate_verification_prompt(
        planned_workout=planned_workout,
        activity_stats=activity_stats,
        garmin_stats=garmin_stats,
        weekly_plan_context=weekly_plan_context,
        user_profile=user_profile,
        user_note=user_note,
        today_date_str=audit_date_str,
        yesterday_date_str=history_date_str,
        tomorrow_date_str=target_date_str,
        trening_z_planu=target_plan,
        strength_workout=strength_workout
    )


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


def _build_and_save_daily_archive(mode, workout_date, date_str, next_date_str, all_stats, garmin_stats, response_text, strength_workout=None, user_note=None, debug=False):
    """
    Formatuje i zapisuje raport dzienny do pliku archiwum w trainings_history/.
    Obsługuje zarówno tryb 'today'/'daily' (bieżący dzień) jak i 'yesterday' (audyt wczorajszego dnia),
    z uwzględnieniem treningów siłowych oraz uwag biegacza zgłoszonych przez Telegram.
    """
    is_today = mode in ["today", "daily"]
    tag = "" if is_today else " [TRYB YESTERDAY]"
    acts_title = "Zarejestrowane aktywności" if is_today else "Zarejestrowane aktywności wczoraj"
    strength_part = f"\n### Trening siłowy / uzupełniający (raport z Telegrama):\n{strength_workout}\n" if strength_workout else ""
    note_part = f"\n## Uwagi biegacza (notatka z Telegrama):\n{user_note}\n" if (user_note and not strength_workout) else ""

    if all_stats and strength_workout:
        header = f"# TRENING BIEGOWY + SIŁOWNIA: {workout_date} ({date_str}){tag}\nLiczba zarejestrowanych jednostek biegowych: {len(all_stats)} + Trening siłowy"
        acts_part = f"\n## {acts_title}:\n{chr(10).join(_format_acts_archive_blocks(all_stats))}\n{strength_part}"
    elif all_stats:
        header = f"# TRENING Z DNIA: {workout_date} ({date_str}){tag}\nLiczba zarejestrowanych jednostek: {len(all_stats)}"
        acts_part = f"\n## {acts_title}:\n{chr(10).join(_format_acts_archive_blocks(all_stats))}\n"
    elif strength_workout:
        header = f"# TRENING SIŁOWY: {workout_date} ({date_str}){tag}\nAktywność: Trening siłowy / uzupełniający (zgłoszony przez Telegram)"
        acts_part = f"\n## {acts_title}:{strength_part}"
    else:
        header = f"# DZIEŃ WOLNY / REST DAY: {workout_date} ({date_str}){tag}\nAktywność: Brak biegu (Regeneracja / Odpoczynek)"
        acts_part = ""

    if is_today:
        bio_part = f"""## Biometria regeneracyjna i bilans dnia ({date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Całodzienny stres w dniu {date_str}: {garmin_stats.get('today_stress')}
- Kroki w dniu {date_str} (cały dzień): {garmin_stats.get('today_steps')}"""
    else:
        bio_part = f"""## Bilans wczorajszego dnia ({date_str}):
- Wczorajsze kroki: {garmin_stats.get('yesterday_steps')}
- Średni stres wczoraj: {garmin_stats.get('yesterday_stress')}
- Body Battery pod koniec wczorajszego dnia: {garmin_stats.get('yesterday_body_battery')}

## Biometria regeneracyjna z minionej nocy (sen przed dniem {next_date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Poranne Body Battery na start dnia {next_date_str}: {garmin_stats.get('morning_body_battery')}"""

    archive_content = f"""{header}

{bio_part}
{acts_part}{note_part}
## Ocena trenera i adaptacja na dzień {next_date_str}:
{response_text}
"""
    save_daily_report(workout_date, archive_content, debug=debug)


def finish_run(note_file=None, new_tg_state=None, debug=False):
    """
    Zapisuje zaktualizowany stan Telegrama po udanym wykonaniu trybu.
    W trybie debug (debug=True) operacja ta jest pomijana, aby chronić stan wiadomości.
    """
    if debug:
        logger.info("[DEBUG] Tryb debugowania aktywny: pominięto aktualizację stanu Telegrama.")
        print("\n🛡️  [TRYB DEBUG] Stan Telegrama pozostał nienaruszony.")
        return

    # Obsługa wywołania z dwoma argumentami: finish_run(new_tg_state, debug=debug)
    if isinstance(note_file, dict) and new_tg_state is None:
        new_tg_state = note_file

    if new_tg_state and save_telegram_state:
        save_telegram_state(new_tg_state)

