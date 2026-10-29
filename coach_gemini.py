"""
coach_gemini.py - Asystent Treningowy Gemini.
Odpowiada za inicjalizację klienta Gemini API, obsługę zapytań z pętlą retry oraz orkiestrację trybów treningowych:
- daily: wieczorny tryb audytu bieżącego dnia (20:57), zaleceń regeneracyjnych i adaptacji na jutro
- plan: ułożenie kompletnego planu tygodniowego na podstawie struktury w weekly_workout_structure.md
"""

import os
import sys
import datetime
import logging
import argparse
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

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
    extract_day_plan,
    prepare_user_note,
    load_training_history,
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
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                ),
            )
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

def _read_and_validate_workout_structure(weekly_workout_structure_path, debug=False):
    """
    Wczytuje plik struktury tygodnia (weekly_workout_structure.md), weryfikuje jego poprawność
    i zwraca sformatowany ciąg preferencji dla modelu.
    Jeśli przy danym dniu tygodnia pole po nazwie dnia jest puste, przypisuje 'Brak preferencji',
    aby model samodzielnie dobrał optymalną jednostkę treningową.

    Args:
        weekly_workout_structure_path (str): Ścieżka do pliku weekly_workout_structure.md.
        debug (bool): Flaga trybu debug.

    Returns:
        str: Sformatowany ciąg ze strukturą dni tygodnia.
    """
    debug_structure_path = os.path.join(DEBUG_DIR_PATH, "weekly_workout_structure.md")
    active_structure_path = debug_structure_path if (debug and os.path.exists(debug_structure_path)) else weekly_workout_structure_path
    if not os.path.exists(active_structure_path):
        active_structure_path = debug_structure_path if debug else weekly_workout_structure_path
        template_lines = [
            "# Wpisz preferowany typ treningu dla poszczególnych dni tygodnia.",
            "# Pozostaw puste pole po dwukropku, jeśli model ma samodzielnie wybrać najlepszą jednostkę.",
            *[f"{day}:" for day in DAYS_PL],
        ]
        with open(active_structure_path, "w", encoding="utf-8") as structure_file:
            structure_file.write("\n".join(template_lines) + "\n")
        exit_with_error(
            f"Nie znaleziono pliku '{active_structure_path}'. "
            f"Utworzono szablon struktury tygodnia. Uzupełnij go i uruchom ponownie 'python coach_gemini.py plan'.",
            code=2
        )

    with open(active_structure_path, "r", encoding="utf-8") as structure_file:
        raw_lines = structure_file.readlines()

    formatted_day_lines, invalid_lines, defined_days = [], [], []
    for raw_line in raw_lines:
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue

        day_part, separator, preference_part = stripped_line.lstrip("0123456789.-*•) ").strip().partition(":")
        day_name = day_part.strip().capitalize()
        if day_name not in DAYS_PL:
            invalid_lines.append(stripped_line)
            continue

        defined_days.append(day_name)
        pref = preference_part.strip() if separator else ""
        formatted_day_lines.append(f"{day_name}: {'Brak preferencji' if not pref or pref.lower() == 'brak preferencji' else pref}")

    if invalid_lines:
        formatted_invalid = "\n".join(f"   - {line}" for line in invalid_lines)
        exit_with_error(
            f"W pliku '{active_structure_path}' znaleziono niepoprawne linie:\n{formatted_invalid}\n"
            "Każda linia powinna zaczynać się od dnia tygodnia, np.: 'Poniedziałek: Easy run' lub 'Wtorek:' (brak preferencji).",
            code=2
        )

    missing_days = [day for day in DAYS_PL if day not in defined_days]
    if missing_days:
        exit_with_error(
            f"W pliku '{active_structure_path}' brakuje definicji dla dni: {', '.join(missing_days)}.\n"
            "Plik musi zawierać wszystkie 7 dni tygodnia (pozostaw puste pole po dwukropku w dni bez preferencji).",
            code=2
        )

    print(f"📄 Wczytano strukturę tygodnia z pliku {active_structure_path}:\n")
    return "\n".join(formatted_day_lines)


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

    days_structure = _read_and_validate_workout_structure(weekly_workout_structure_path, debug=debug)
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
            print("🚀 [DEBUG] Raport zostanie wysłany na Telegrama (z flagą debug)" if send_tg else "📄 [DEBUG] Dane NIE zostaną wysłane na Telegrama.")
        else:
            print(f"\n✅ Zapisano plan do: {target_plan_path}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")

        if not debug or send_tg:
            try:
                send_weekly_plan(target_plan_path)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać planu na Telegram: {te}")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania planu tygodniowego.", error=e)


# ==============================================================================
# TRYB AUDYTU DZIENNEGO I ADAPTACJI (DAILY / TODAY)
# ==============================================================================

def _build_planned_workout_desc(audit_date, weekly_plan_content):
    """
    Buduje zwięzły opis założeń treningowych na audytowany dzień z planu tygodniowego.

    Args:
        audit_date (datetime.date): Data audytowanego treningu (dziś).
        weekly_plan_content (str | None): Zawartość planu tygodniowego.

    Returns:
        str: Opis zaplanowanego treningu na dany dzień.
    """
    audit_day_name = DAYS_PL[audit_date.weekday()]
    audit_date_str = f"{audit_day_name}, {audit_date.isoformat()}"
    if weekly_plan_content:
        return f"{audit_date_str}: {extract_day_plan(weekly_plan_content, audit_day_name)}"
    return f"Brak aktywnego planu tygodniowego na dzień {audit_date_str}."


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
        planned_workout_desc = _build_planned_workout_desc(todays_date, weekly_plan_content)

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
        str: Poprawna nazwa trybu ('daily' lub 'plan').
    """
    mode = (raw_mode or "daily").strip().lower()
    if mode not in ("daily", "plan"):
        exit_with_error(
            f"Nieprawidłowy tryb działania: '{raw_mode}'. "
            f"Dozwolone tryby to: daily, plan."
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
        mode (str): Tryb pracy ('daily' lub 'plan').
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

    if mode == "plan":
        run_plan_mode(client, personal_data, trainings_history, combined_note, paths["weekly_workout_structure_path"], paths["plan_path"], debug=debug, model=gemini_model, ref_date=today, send_tg=send_tg)


def main():
    """Główny punkt wejścia CLI obsługujący parsowanie argumentów i uruchomienie odpowiedniego trybu."""
    parser = argparse.ArgumentParser(description="Coach Gemini - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily (domyślny, audyt wieczorny o 20:57), plan")
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
