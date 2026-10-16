"""
coach_gemini.py - Asystent Treningowy Gemini.
Odpowiada za inicjalizację klienta Gemini API, obsługę zapytań z pętlą retry oraz orkiestrację trybów treningowych:
- daily: wieczorny tryb audytu bieżącego dnia (20:57), zaleceń regeneracyjnych i adaptacji na jutro
- plan: ułożenie kompletnego planu tygodniowego
- suggest: generowanie propozycji podziału jednostek treningowych
"""

import os
import sys
import re
import datetime
import logging
import argparse
import time
from dotenv import load_dotenv
from google import genai

from send_telegram import (
    send_daily_report,
    send_weekly_plan,
    finish_run,
)
from garmin_service import (
    fetch_garmin_data,
    parse_garmin_data,
    process_and_display_activities,
)
from coach_prompts import (
    DAYS_PL,
    INPUT_DIR_PATH,
    OUTPUT_DIR_PATH,
    PROMPTS_DIR_PATH,
    HISTORY_DIR_PATH,
    DEBUG_DIR_PATH,
    load_personal_data,
    build_user_profile,
    load_weekly_plan,
    prepare_user_note,
    load_training_history,
    generate_weekly_suggestions_prompt,
    generate_weekly_plan_prompt,
    generate_daily_prompt,
    build_and_save_daily_archive,
    separate_strength_and_user_notes,
    update_strength_routines_from_workout,
)

# Parsuje .env i zapisuje klucze do pamięci procesu (os.environ).
load_dotenv()

# Inicjalizacja loggera.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ==============================================================================
# KONFIGURACJA I KLIENT GEMINI API
# ==============================================================================

def exit_with_error(message=None, error=None, code=1):
    """
    Wyświetla komunikat o błędzie, opcjonalne szczegóły wyjątku i kończy program z odpowiednim kodem.

    Args:
        message (str, optional): Główny komunikat błędu do wyświetlenia.
        error (Exception, optional): Obiekt wyjątku dla szczegółów technicznych.
        code (int): Kod wyjścia programu (domyślnie 1).
    """
    if message:
        logger.error(message)
    if error:
        logger.error(f"🔍 Szczegóły błędu / wyjątku: {error}")
    logger.error(f"🛑 Zakończenie działania programu (kod wyjścia: {code}).")
    sys.exit(code)


def save_debug_prompt(prompt, debug=False):
    """
    Zapisuje treść wysyłanego prompta do pliku, jeśli aktywny jest tryb debugowania.

    Args:
        prompt (str): Kompletny tekst promptu wysyłanego do modelu.
        debug (bool): Flaga trybu debug.
    """
    if debug:
        debug_log_path = os.path.join(DEBUG_DIR_PATH, "debug_log.md")
        with open(debug_log_path, "w", encoding="utf-8") as f_debug:
            f_debug.write(prompt + "\n")
        logger.info(f"[DEBUG] Zapisano wysłany prompt do: {debug_log_path}")


def send_gemini_prompt_with_fallback(client, prompt, model="gemini-3.8-flash", debug=False, max_retries=10, retry_delay=10):
    """
    Wysyła prompt do wybranego modelu Gemini z automatyczną pętlą ponawiania prób.
    W przypadku nieudanej próby odczekuje retry_delay sekund
    i ponawia próbę wysłania zapytania do tego samego modelu.

    Args:
        client: Zainicjowany klient Gemini.
        prompt (str): Treść zapytania dla asystenta.
        model (str): Nazwa modelu Gemini.
        debug (bool): Flaga trybu debug.
        max_retries (int): Maksymalna liczba prób (domyślnie 10).
        retry_delay (int): Czas oczekiwania w sekundach pomiędzy kolejnymi próbami (domyślnie 10s).

    Returns:
        Odpowiedź wygenerowana przez model.
    """
    save_debug_prompt(prompt, debug=debug)
    model = (model or "gemini-3.8-flash").strip()

    print("\n" + "=" * 60)
    print("🚀 WYSYŁANIE PROMPTU DO GEMINI")
    print(f"📄 Model: {model}")
    print("=" * 60)

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Wysyłanie zapytania do Gemini (Model: {model}, próba [{attempt}/{max_retries}])...")
            response = client.models.generate_content(model=model, contents=prompt)
            logger.info(f"✅ Odpowiedź pomyślnie wygenerowana przez model: {model}")
            return response
        except Exception as e:
            last_error = e
            logger.warning(f"⚠️ Błąd podczas próby [{attempt}/{max_retries}] dla modelu {model}: {e}")

        if attempt < max_retries:
            logger.info(f"⏳ Oczekiwanie {retry_delay} sekund przed kolejną próbą połączenia...")
            time.sleep(retry_delay)

    exit_with_error(
        f"❌ Nie udało się uzyskać odpowiedzi od modelu {model} po {max_retries} próbach (odstęp: {retry_delay}s).",
        error=last_error,
        code=1
    )


# ==============================================================================
# GŁÓWNE TRYBY DZIAŁANIA
# ==============================================================================

def run_suggest_mode(client, personal_data, trainings_history, user_note, weekly_workout_structure_path, debug=False, model="gemini-3.8-flash", ref_date=None):
    """
    Generowanie sugestii typów treningów na cały nadchodzący tydzień.

    Args:
        client: Zainicjowany klient Gemini API.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        trainings_history (str): Kontekst wyników z 42 ostatnich dni.
        user_note (str): Opcjonalna notatka zawodnika z Telegrama.
        weekly_workout_structure_path (str): Ścieżka do docelowego pliku preferencji.
        debug (bool): Flaga trybu debug.
        model (str): Nazwa modelu Gemini.
        ref_date (date): Data wygenerowania układu.
    """
    print("\n" + "=" * 60 + "\n💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡" + "=" * 60)

    suggest_prompt = generate_weekly_suggestions_prompt(
        personal_data=personal_data,
        trainings_history=trainings_history,
        user_note=user_note,
        ref_date=ref_date
    )

    try:
        response = send_gemini_prompt_with_fallback(client, suggest_prompt, model=model, debug=debug)
        target_structure_path = os.path.join(DEBUG_DIR_PATH, "weekly_workout_structure.md") if debug else weekly_workout_structure_path

        with open(target_structure_path, "w", encoding="utf-8") as pf:
            pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii treningowej i profilu\n")
            pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python coach_gemini.py plan'\n\n")
            pf.write(response.text)

        if debug:
            print(f"\n✅ [DEBUG] Zapisano propozycję do pliku: {target_structure_path}")
        else:
            print(f"\n✅ Zapisano propozycję do pliku: {target_structure_path}")
            print(f"📄 Jeśli chcesz coś zmienić, edytuj '{weekly_workout_structure_path}', a następnie uruchom:")
            print("   python coach_gemini.py plan")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania sugestii.", error=e)


def _read_and_validate_preferences(weekly_workout_structure_path, debug=False):
    """
    Otwiera plik preferencji, weryfikuje jego zawartość i zwraca gotowy ciąg dni.
    Jeśli plik nie istnieje, tworzy pusty szablon i przerywa działanie z ostrzeżeniem.

    Args:
        weekly_workout_structure_path (str): Ścieżka do głównego pliku preferencji.
        debug (bool): Flaga trybu debug.

    Returns:
        str: Sformatowany ciąg ze zweryfikowanymi preferencjami treningowymi.
    """
    debug_structure_path = os.path.join(DEBUG_DIR_PATH, "weekly_workout_structure.md")
    if debug and os.path.exists(debug_structure_path):
        active_path = debug_structure_path
    elif os.path.exists(weekly_workout_structure_path):
        active_path = weekly_workout_structure_path
    else:
        active_path = debug_structure_path if debug else weekly_workout_structure_path
        with open(active_path, "w", encoding="utf-8") as pf:
            pf.write("# Wpisz w jakie dni jaki typ treningu chcesz wykonać, np.:\n")
            pf.write("# Poniedziałek: Easy + przebieżki\n# Wtorek: Tempo progowe\n# Środa: FBW\n")
        exit_with_error(
            f"Nie znaleziono pliku '{active_path}'. "
            f"Utworzono pusty szablon. Uzupełnij go lub uruchom 'python coach_gemini.py suggest'.",
            code=2
        )

    with open(active_path, "r", encoding="utf-8") as pf:
        raw_lines = pf.readlines()

    valid_lines = []
    invalid_lines = []
    for line in raw_lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "uzasadnienie" in s.lower():
            break

        clean_line = s.lstrip("0123456789.-*•) ").strip()
        first_word = clean_line.split()[0].rstrip(":").capitalize() if clean_line else ""

        if first_word in DAYS_PL:
            valid_lines.append(clean_line)
        else:
            invalid_lines.append(s)

    if invalid_lines:
        inv_Formatted = "\n".join(f"   - {inv}" for inv in invalid_lines)
        exit_with_error(
            f"W pliku '{active_path}' znaleziono niepoprawne linie:\n{inv_Formatted}\n"
            "Każda linia powinna zaczynać się od dnia tygodnia, np.: 'Poniedziałek: Easy run'.",
            code=2
        )

    days_structure = "\n".join(valid_lines).strip()
    if not days_structure:
        exit_with_error(
            f"Plik '{active_path}' nie zawiera zdefiniowanych dni treningowych.\n"
            "Wpisz w nim preferencje lub uruchom: python coach_gemini.py suggest",
            code=2
        )

    print(f"📄 Wczytano preferencje z pliku {active_path}:\n")
    return days_structure


def run_plan_mode(client, personal_data, trainings_history, user_note, weekly_workout_structure_path, weekly_plan_path, debug=False, model="gemini-3.8-flash", ref_date=None, send_tg=False):
    """
    Tryb planowania: Generuje kompletny plan na tydzień treningowy.

    Args:
        client: Zainicjowany klient Gemini.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        trainings_history (str): Kontekst historyczny (ostatnie 42 dni).
        user_note (str): Opcjonalna notatka zawodnika.
        weekly_workout_structure_path (str): Ścieżka pliku weekly_workout_structure.md.
        weekly_plan_path (str): Ścieżka zapisu dla planu (weekly_plan.md).
        debug (bool): Flaga trybu debug.
        model (str): Nazwa modelu Gemini.
        ref_date (date): Data referencyjna bieżącego układania planu.
        send_tg (bool): Czy wysłać plik na telegram (również dla debug).
    """
    print("\n" + "=" * 60)
    print("🗓️  TRYB PLANOWANIA TYGODNIOWEGO (GEMINI COACH) 🗓️")
    print("=" * 60)

    days_structure = _read_and_validate_preferences(weekly_workout_structure_path, debug=debug)
    print(days_structure)
    print("\n" + "=" * 60)

    plan_prompt = generate_weekly_plan_prompt(
        days_structure=days_structure,
        personal_data=personal_data,
        trainings_history=trainings_history,
        user_note=user_note,
        ref_date=ref_date
    )

    try:
        response = send_gemini_prompt_with_fallback(client, plan_prompt, model=model, debug=debug)
        target_plan_path = os.path.join(DEBUG_DIR_PATH, "weekly_plan.md") if debug else weekly_plan_path

        with open(target_plan_path, "w", encoding="utf-8") as wf:
            wf.write(response.text)

        if debug:
            print(f"\n📄 [DEBUG] Zapisano plan do: {target_plan_path} (Plik produkcyjny {weekly_plan_path} pozostał nienaruszony)")
            if send_tg:
                print("🚀 [DEBUG] Raport zostanie wysłany na Telegrama (z flagą debug)")
                send_weekly_plan(target_plan_path)
            else:
                print("📄 [DEBUG] Dane NIE zostaną wysłane na Telegrama.")
        else:
            print(f"\n✅ Zapisano plan do: {target_plan_path}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")
            try:
                send_weekly_plan(weekly_plan_path)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać planu na Telegram: {te}")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania planu tygodniowego.", error=e)


# ==============================================================================
# TRYB AUDYTU DZIENNEGO I ADAPTACJI (DAILY / TODAY)
# ==============================================================================

def _format_day_plan_section(raw_title, body_lines, day_name):
    """Formatuje pojedynczą sekcję dziennego planu treningowego."""
    clean_title = re.sub(rf'^{day_name}\s*[-–:]\s*', '', raw_title, flags=re.IGNORECASE).strip()
    if clean_title.startswith('Siłownia:'):
        clean_title = clean_title.replace('Siłownia:', 'Siłownia').strip()

    output_lines = []
    i = 0
    in_exercises = False

    while i < len(body_lines):
        line = body_lines[i]

        # 1. Bezwzględne odrzucanie metatekstu planistycznego i uzasadnień
        if line.startswith(('Wyjaśnienie decyzji:', 'Decyzja:', '* **Cel', '- **Cel')):
            i += 1
            continue

        # 2. Pomijanie ćwiczeń usuniętych z planu
        if 'USUNIĘTO' in line:
            i += 1
            while i < len(body_lines) and body_lines[i].startswith(('Seria', 'Decyzja', 'Wyjaśnienie')):
                i += 1
            continue

        # 3. Status dolnych partii
        if 'Status dolnych partii' in line:
            output_lines.append(re.sub(r'^\*\s*\*\*Status dolnych partii\*\*:\s*', '- Status dolnych partii: ', line))
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

        # 6. Standardowe punkty (np. rozgrzewka, część główna, schłodzenie, zalecenia regeneracyjne)
        if line.startswith(('* **', '- ')):
            in_exercises = False
            output_lines.append(re.sub(r'^\*\s*\*\*([^*]+)\*\*:\s*', r'- \1: ', line))
            i += 1
            continue

        # 7. Parsowanie ćwiczeń wewnątrz sekcji ćwiczeń
        if in_exercises:
            if re.match(r'^\[SUPERSET[^\]]*\]:?$', line.strip(), re.IGNORECASE):
                i += 1
                continue

            clean_ex_name = re.sub(
                r'\s*\((?:Dumbbell|Barbell|Cable|Machine|fbw|upper|lower|core|push|pull|legs)\)',
                '',
                line,
                flags=re.IGNORECASE
            ).strip()

            series = []
            i += 1
            while i < len(body_lines):
                s_line = body_lines[i]
                if s_line.startswith('Seria'):
                    series.append(s_line)
                    i += 1
                elif s_line.startswith(('Wyjaśnienie decyzji:', 'Decyzja:')):
                    i += 1
                else:
                    break

            if series:
                num_sets = len(series)
                m_s = re.search(r'Seria\s*\d+:\s*(\d+)\s*(?:x\s*([^(]+))?(?:\(([^)]+)\))?', series[0])
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

    return f"{clean_title}\n" + "\n".join(output_lines) if output_lines else clean_title


def _extract_day_plan(content, day_name):
    """
    Wyciąga czyste, skondensowane założenia treningowe dla konkretnego dnia z planu tygodniowego.
    Obsługuje również dni z dwiema jednostkami (np. poranek i popołudnie).
    Usuwa metatekst planistyczny (np. 'Wyjaśnienie decyzji:', 'Decyzja: Usunięcie...')
    oraz kompresuje serie ćwiczeń siłowych do zwięzłego formatu (np. 3x10 (10 kg/ręka, RIR 3)).

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
        _format_day_plan_section(sec[0], sec[1:], day_name)
        for sec in sections
    )


def _build_daily_evaluation_context(audit_date, target_date, weekly_plan_content):
    """
    Buduje opisy kontekstowe dla audytu (założenia dzisiejsze i cele na jutro).

    Args:
        audit_date (datetime.date): Data audytowanego treningu (dziś).
        target_date (datetime.date): Data adaptowanego treningu (jutro).
        weekly_plan_content (str | None): Zawartość planu tygodniowego.

    Returns:
        tuple[str, str]: Krotka zawierająca (planned_workout_desc, target_plan_desc).
    """
    audit_day_name = DAYS_PL[audit_date.weekday()]
    target_day_name = DAYS_PL[target_date.weekday()]
    audit_date_str = f"{audit_day_name}, {audit_date.isoformat()}"
    target_date_str = f"{target_day_name}, {target_date.isoformat()}"

    if weekly_plan_content:
        planned_workout_desc = f"{audit_date_str}: {_extract_day_plan(weekly_plan_content, audit_day_name)}"
    else:
        planned_workout_desc = f"Brak aktywnego planu tygodniowego na dzień {audit_date_str}."

    if audit_date.weekday() == 6:
        target_plan_desc = "Brak (koniec mikrocyklu tygodniowego; w niedzielę następuje zamknięcie mikrocyklu i nowy plan na kolejny tydzień generuje wyłącznie tryb 'plan')"
    elif weekly_plan_content:
        target_plan_desc = f"{target_date_str}: {_extract_day_plan(weekly_plan_content, target_day_name)}"
    else:
        target_plan_desc = f"Zaproponuj rekomendację treningową na dzień {target_date_str}"

    return planned_workout_desc, target_plan_desc


def run_daily_mode(client, todays_date, weekly_plan_path, user_profile, user_note, strength_workout, debug=False, model="gemini-3.8-flash", send_tg=False):
    """
    Wieczorny audyt treningu i biometrii z dnia dzisiejszego oraz adaptacja planu na jutro.

    Args:
        client: Zainicjowany klient Gemini.
        todays_date (date): Data audytowanego treningu.
        weekly_plan_path (str): Ścieżka pliku weekly_plan.md.
        user_profile (dict): Informacje o profilu i sprzęcie.
        user_note (str | None): Opcjonalna notatka zawodnika.
        strength_workout (str | None): Odseparowany tekst treningu siłowego (jeśli występuje).
        debug (bool): Flaga trybu debug.
        model (str): Nazwa modelu Gemini.
        send_tg (bool): Flaga wymuszająca wysyłkę w trybie debug.
    """
    target_date = todays_date + datetime.timedelta(days=1)
    history_date = todays_date - datetime.timedelta(days=1)

    audit_day_name = DAYS_PL[todays_date.weekday()]
    audit_date_str = f"{audit_day_name}, {todays_date.isoformat()}"
    target_date_str = f"{DAYS_PL[target_date.weekday()]}, {target_date.isoformat()}"
    history_date_str = f"{DAYS_PL[history_date.weekday()]}, {history_date.isoformat()}"

    print("\n" + "=" * 60)
    print("🏃 TRYB WIECZORNEGO AUDYTU DZIENNEGO I ADAPTACJI NA JUTRO 🏃")
    print(f"Audyt: {audit_date_str} | Adaptacja na: {target_date_str}")
    print("=" * 60)

    try:
        raw_data = fetch_garmin_data(todays_date)
        garmin_stats = parse_garmin_data(raw_data, target_date=todays_date)
        raw_activities = raw_data.get('today', {}).get('activities', [])

        # 1. Wczytujemy plan tygodniowy, jeśli istnieje (w trybie debug preferujemy plan z debug/)
        debug_weekly_plan_path = os.path.join(DEBUG_DIR_PATH, "weekly_plan.md")
        active_weekly_plan_path = debug_weekly_plan_path if (debug and os.path.exists(debug_weekly_plan_path)) else weekly_plan_path
        weekly_plan_content = load_weekly_plan(active_weekly_plan_path)
        if not weekly_plan_content:
            print(f"⚠️  Brak aktywnego planu tygodniowego ({active_weekly_plan_path}).")
            print("📄 Model przeprowadzi analizę treningu i regeneracji bez odniesienia do założeń tygodnia.")

        # 2. Parsujemy i wyświetlamy aktywności podlegające audytowi
        _, activity_stats = process_and_display_activities(raw_activities, audit_date_str)

        if strength_workout:
            print("\n" + "=" * 60)
            print(f"📲 ZAREJESTROWANO TRENING SIŁOWY (Z TELEGRAMA): {audit_date_str}")
            print("=" * 60)
            print(strength_workout)
        elif not activity_stats:
            print("\n" + "=" * 60)
            print(f"📄 DZIEŃ BEZ BIEGU / REST DAY: {audit_date_str}")
            print("=" * 60)
            print(f"W dniu {audit_date_str} nie odnotowano aktywności biegowej ani treningu siłowego.")

        # 3. Konstrukcja zwięzłego opisu założeń dla modelu
        planned_workout_desc, target_plan_desc = _build_daily_evaluation_context(
            audit_date=todays_date,
            target_date=target_date,
            weekly_plan_content=weekly_plan_content
        )

        verification_prompt = generate_daily_prompt(
            planned_workout=planned_workout_desc,
            activity_stats=activity_stats,
            garmin_stats=garmin_stats,
            weekly_plan_context=weekly_plan_content,
            user_profile=user_profile,
            user_note=user_note,
            audit_date_str=audit_date_str,
            target_date_str=target_date_str,
            history_date_str=history_date_str,
            target_plan_desc=target_plan_desc,
            strength_workout=strength_workout,
            day_of_week=audit_day_name
        )

        response = send_gemini_prompt_with_fallback(client, verification_prompt, model=model, debug=debug)

        build_and_save_daily_archive(
            workout_date=todays_date.isoformat(),
            date_str=audit_date_str,
            next_date_str=target_date_str,
            all_stats=activity_stats,
            garmin_stats=garmin_stats,
            response_text=response.text,
            strength_workout=strength_workout,
            user_note=user_note,
            debug=debug
        )

        # Wysłanie raportu dziennego na Telegram w formacie załącznika HTML
        if not debug or send_tg:
            report_dir = DEBUG_DIR_PATH if debug else OUTPUT_DIR_PATH
            report_path = os.path.join(report_dir, "last_daily_report.md")
            if debug:
                print(f"🚀 [DEBUG] Wysyłanie testowego raportu na Telegram (--send_debug): {report_path}...")
            try:
                send_daily_report(report_path)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać raportu na Telegram: {te}")

    except Exception as e:
        exit_with_error("Wystąpił błąd podczas weryfikacji i adaptacji.", error=e)


# ==============================================================================
# CLI I PUNKT WEJŚCIA PROGRAMU
# ==============================================================================

def resolve_mode(raw_mode):
    """
    Weryfikuje poprawność trybu działania wybranego przez użytkownika.
    
    Args:
        raw_mode (str): Tryb przekazany z wiersza poleceń.
        
    Returns:
        str: Poprawna nazwa trybu ('daily', 'plan' lub 'suggest').
    """
    mode = (raw_mode or "daily").strip().lower()
    if mode not in ("daily", "plan", "suggest"):
        exit_with_error(
            f"Nieprawidłowy tryb działania: '{raw_mode}'. "
            f"Dozwolone tryby to: daily, plan, suggest."
        )
    return mode


def parse_date(date_str=None):
    """
    Parsuje i weryfikuje poprawność podanej daty.
    
    Args:
        date_str (str, optional): Data w formacie YYYY-MM-DD.

    Returns:
        date: Obiekt daty lub dzisiejsza data, jeśli argument to None.
    """
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            exit_with_error(f"Nieprawidłowy format daty: {date_str}. Użyj formatu YYYY-MM-DD.")
    return datetime.date.today()


def setup_environment(debug=False):
    """
    Inicjalizuje strukturę katalogów oraz sprawdza konfigurację klucza API Gemini.
    
    Args:
        debug (bool): Flaga trybu debug.

    Returns:
        str: Pobrany z .env klucz dostępu GEMINI_API_KEY.
    """
    for directory_path in (INPUT_DIR_PATH, OUTPUT_DIR_PATH, PROMPTS_DIR_PATH, HISTORY_DIR_PATH):
        os.makedirs(directory_path, exist_ok=True)

    if debug:
        os.makedirs(DEBUG_DIR_PATH, exist_ok=True)
        logger.info("🔧 TRYB DEBUG AKTYWNY: Pliki produkcyjne nie będą modyfikowane. Wyniki trafią do katalogu 'debug/'.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        exit_with_error("Brak klucza GEMINI_API_KEY w pliku .env!")

    return api_key


def dispatch_mode(mode, client, gemini_model, today, personal_data, user_note, paths, debug=False, send_tg=False):
    """
    Kieruje wykonanie do odpowiedniego modułu na podstawie wybranego trybu działania.

    Args:
        mode (str): Tryb pracy (np. 'daily', 'plan', 'suggest').
        client: Zainicjowany klient API Gemini.
        gemini_model (str): Nazwa modelu Gemini.
        today (date): Data uruchomienia.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        user_note (str): Opcjonalna notatka zawodnika.
        paths (dict): Słownik zawierający wymagane ścieżki do plików.
        debug (bool): Flaga trybu debug.
        send_tg (bool): Czy wymusić wysyłkę raportu przy debugowaniu.
    """
    strength_workout, final_user_note = separate_strength_and_user_notes(user_note)
    combined_note = "\n\n".join(p for p in (final_user_note, strength_workout) if p) or None

    # Automatyczna aktualizacja wag w bazie rutyn siłowych po wykryciu raportu treningu
    if strength_workout:
        source_routines_path = os.path.join(INPUT_DIR_PATH, "strength_routines.json")
        routines_target = os.path.join(DEBUG_DIR_PATH, "strength_routines.json") if debug else source_routines_path
        if debug and not os.path.exists(routines_target) and os.path.exists(source_routines_path):
            import shutil
            shutil.copy(source_routines_path, routines_target)

        updated_info = update_strength_routines_from_workout(strength_workout, filepath=routines_target)
        if updated_info:
            routine_name, updated_exs = updated_info
            prefix = "🔧 [DEBUG] Zaktualizowano wagi robocze w piaskownicy debug/strength_routines.json" if debug else "💾 Zaktualizowano wagi robocze w bazie"
            print(f"{prefix} ({routine_name.upper()}): {', '.join(updated_exs)}")

    if mode == "daily":
        run_daily_mode(
            client=client,
            todays_date=today,
            weekly_plan_path=paths["plan_path"],
            user_profile=build_user_profile(personal_data, ref_date=today),
            user_note=final_user_note,
            strength_workout=strength_workout,
            debug=debug,
            model=gemini_model,
            send_tg=send_tg
        )
        return

    trainings_history = load_training_history(ref_date=today, history_dir_path=HISTORY_DIR_PATH)
    if trainings_history:
        logger.info("Wczytano historię treningów z ostatnich 42 dni (6 tygodni).")

    if mode == "suggest":
        run_suggest_mode(client, personal_data, trainings_history, combined_note, paths["weekly_workout_structure_path"], debug=debug, model=gemini_model, ref_date=today)
    elif mode == "plan":
        run_plan_mode(client, personal_data, trainings_history, combined_note, paths["weekly_workout_structure_path"], paths["plan_path"], debug=debug, model=gemini_model, ref_date=today, send_tg=send_tg)


def main():
    parser = argparse.ArgumentParser(description="Coach Gemini - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily (domyślny, audyt wieczorny o 20:57), plan, suggest")
    parser.add_argument("--debug", action="store_true", help="Włącza tryb debugowania. zapis w katalogu debug/")
    parser.add_argument("--send_debug", action="store_true", help="Włącza tryb debugowania ORAZ wysyła testowy raport na Telegram")
    parser.add_argument("--date", type=str, default=None, help="opcjonalna data referencyjna w formacie YYYY-MM-DD")

    args = parser.parse_args()
    if args.send_debug:
        args.debug = True

    mode = resolve_mode(args.mode)
    today = parse_date(args.date)

    api_key = setup_environment(debug=args.debug)
    client = genai.Client(api_key=api_key)
    gemini_model = (os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_MODELS") or "gemini-3.8-flash").strip()

    try:
        personal_data = load_personal_data(os.path.join(INPUT_DIR_PATH, "personal_data.json"))
    except Exception as e:
        exit_with_error("Nie udało się załadować konfiguracji treningowej.", error=e)

    user_note, new_tg_state = prepare_user_note()

    paths = {
        "weekly_workout_structure_path": os.path.join(INPUT_DIR_PATH, "weekly_workout_structure.md"),
        "plan_path": os.path.join(OUTPUT_DIR_PATH, "weekly_plan.md"),
    }

    dispatch_mode(mode, client, gemini_model, today, personal_data, user_note, paths, debug=args.debug, send_tg=args.send_debug)
    finish_run(new_tg_state=new_tg_state, debug=args.debug)


if __name__ == "__main__":
    main()
