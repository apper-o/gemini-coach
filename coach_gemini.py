"""
coach_gemini.py - Asystent Treningowy Gemini (Orkiestracja CLI i klient Gemini API).
Odpowiada za inicjalizację klienta Gemini API, obsługę zapytań z pętlą retry oraz orkiestrację trybów treningowych:
- daily: wieczorny tryb audytu bieżącego dnia, zaleceń regeneracyjnych i adaptacji na jutro
- plan: ułożenie kompletnego planu tygodniowego na podstawie struktury w weekly_workout_structure.md
"""

import os
import sys
import shutil
import datetime
import logging
import argparse
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

from send_telegram import (
    prepare_user_note,
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
    load_training_history,
    get_historical_strength_summary,
    generate_weekly_plan_prompt,
    generate_daily_prompt,
    build_and_save_daily_archive,
    separate_strength_and_user_notes,
    update_strength_routines_from_workout,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Konfiguracja modelu Gemini i parametrów retry ze zmiennych środowiskowych
DEFAULT_GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_MODELS") or "gemini-3.8-flash").strip()
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "10"))
GEMINI_RETRY_DELAY = int(os.getenv("GEMINI_RETRY_DELAY", "10"))


def exit_with_error(message=None, error=None, code=1):
    """Wyświetla komunikat o błędzie, opcjonalne szczegóły wyjątku i kończy program z kodem wyjścia."""
    if message:
        logger.error(message)
    if error:
        logger.error(f"🔍 Szczegóły błędu / wyjątku: {error}")
    logger.error(f"🛑 Zakończenie działania programu (kod wyjścia: {code}).")
    sys.exit(code)


def send_gemini_prompt_with_fallback(
    client,
    prompt,
    model=DEFAULT_GEMINI_MODEL,
    debug=False,
    max_retries=GEMINI_MAX_RETRIES,
    retry_delay=GEMINI_RETRY_DELAY,
):
    """Wysyła prompt do wybranego modelu Gemini z automatyczną pętlą ponawiania prób."""
    if debug:
        os.makedirs(DEBUG_DIR_PATH, exist_ok=True)
        debug_log_path = os.path.join(DEBUG_DIR_PATH, "debug_log.md")
        with open(debug_log_path, "w", encoding="utf-8") as f_debug:
            f_debug.write(prompt + "\n")
        logger.info(f"[DEBUG] Zapisano wysłany prompt do: {debug_log_path}")

    model = (model or DEFAULT_GEMINI_MODEL).strip()
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
        code=1,
    )


def _read_and_validate_workout_structure(weekly_workout_structure_path, debug=False):
    """Wczytuje plik struktury tygodnia (weekly_workout_structure.md) i weryfikuje obecność 7 dni tygodnia."""
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
            f"Nie znaleziono pliku '{active_structure_path}'. Utworzono szablon struktury tygodnia – uzupełnij go i uruchom ponownie.",
            code=2,
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
            "Każda linia powinna zaczynać się od dnia tygodnia, np.: 'Poniedziałek: Easy run' lub 'Wtorek:'.",
            code=2,
        )

    if missing_days := [day for day in DAYS_PL if day not in defined_days]:
        exit_with_error(
            f"W pliku '{active_structure_path}' brakuje definicji dla dni: {', '.join(missing_days)}.\n"
            "Plik musi zawierać wszystkie 7 dni tygodnia.",
            code=2,
        )

    print(f"📄 Wczytano strukturę tygodnia z pliku {active_structure_path}:\n")
    return "\n".join(formatted_day_lines)


def run_plan_mode(
    client,
    personal_data,
    trainings_history,
    user_note,
    weekly_workout_structure_path,
    weekly_plan_path,
    debug=False,
    model=DEFAULT_GEMINI_MODEL,
    ref_date=None,
    send_tg=False,
):
    """Tryb planowania: generuje kompletny plan na tydzień treningowy i wysyła raport HTML na Telegram."""
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
        ref_date=ref_date,
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


def run_daily_mode(
    client,
    todays_date,
    weekly_plan_path,
    user_profile,
    user_note,
    strength_workout,
    debug=False,
    model=DEFAULT_GEMINI_MODEL,
    send_tg=False,
):
    """Wieczorny audyt treningu i biometrii z dnia dzisiejszego oraz adaptacja planu na jutro."""
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
        yesterday_strength = get_historical_strength_summary(history_date.isoformat())
        garmin_stats = parse_garmin_data(raw_data, target_date=todays_date, extra_yesterday_training=yesterday_strength)
        raw_activities = raw_data.get("today", {}).get("activities", [])

        debug_weekly_plan_path = os.path.join(DEBUG_DIR_PATH, "weekly_plan.md")
        active_weekly_plan_path = debug_weekly_plan_path if (debug and os.path.exists(debug_weekly_plan_path)) else weekly_plan_path
        weekly_plan_content = load_weekly_plan(active_weekly_plan_path)
        if not weekly_plan_content:
            print(f"⚠️  Brak aktywnego planu tygodniowego ({active_weekly_plan_path}).")
            print("📄 Model przeprowadzi analizę treningu i regeneracji bez odniesienia do założeń tygodnia.")

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

        planned_workout_desc = (
            f"{audit_date_str}: {extract_day_plan(weekly_plan_content, audit_day_name)}"
            if weekly_plan_content
            else f"Brak aktywnego planu tygodniowego na dzień {audit_date_str}."
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
            strength_workout=strength_workout,
            day_of_week=audit_day_name,
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
            debug=debug,
        )

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


def setup_environment(debug=False):
    """Inicjalizuje strukturę katalogów oraz sprawdza konfigurację klucza API Gemini."""
    for directory_path in (INPUT_DIR_PATH, OUTPUT_DIR_PATH, PROMPTS_DIR_PATH, HISTORY_DIR_PATH):
        os.makedirs(directory_path, exist_ok=True)

    if debug:
        os.makedirs(DEBUG_DIR_PATH, exist_ok=True)
        logger.info("🔧 TRYB DEBUG AKTYWNY: Pliki produkcyjne nie będą modyfikowane. Wyniki trafią do katalogu 'debug/'.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        exit_with_error("Brak klucza GEMINI_API_KEY w pliku .env!")
    return api_key


def main():
    """Główny punkt wejścia CLI obsługujący parsowanie argumentów i uruchomienie odpowiedniego trybu."""
    parser = argparse.ArgumentParser(description="Coach Gemini - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily (domyślny, audyt wieczorny), plan")
    parser.add_argument("--debug", action="store_true", help="Włącza tryb debugowania (zapis w katalogu debug/)")
    parser.add_argument("--send_debug", action="store_true", help="Włącza tryb debugowania ORAZ wysyła testowy raport na Telegram")
    parser.add_argument("--date", type=str, default=None, help="Opcjonalna data referencyjna w formacie YYYY-MM-DD")

    args = parser.parse_args()
    if args.send_debug:
        args.debug = True

    mode = (args.mode or "daily").strip().lower()
    if mode not in ("daily", "plan"):
        exit_with_error(f"Nieprawidłowy tryb działania: '{args.mode}'. Dozwolone tryby to: daily, plan.")

    try:
        today = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    except ValueError:
        exit_with_error(f"Nieprawidłowy format daty: {args.date}. Użyj formatu YYYY-MM-DD.")

    api_key = setup_environment(debug=args.debug)
    client = genai.Client(api_key=api_key)

    try:
        personal_data = load_personal_data(os.path.join(INPUT_DIR_PATH, "personal_data.json"))
    except Exception as e:
        exit_with_error("Nie udało się załadować konfiguracji treningowej.", error=e)

    user_note, new_tg_state = prepare_user_note()
    strength_workout, final_user_note = separate_strength_and_user_notes(user_note)
    combined_note = "\n\n".join(p for p in (final_user_note, strength_workout) if p) or None

    if strength_workout:
        source_routines_path = os.path.join(INPUT_DIR_PATH, "strength_routines.json")
        routines_target = os.path.join(DEBUG_DIR_PATH, "strength_routines.json") if args.debug else source_routines_path
        if args.debug and not os.path.exists(routines_target) and os.path.exists(source_routines_path):
            shutil.copy(source_routines_path, routines_target)

        if updated_info := update_strength_routines_from_workout(strength_workout, filepath=routines_target):
            routine_name, updated_exs = updated_info
            prefix = "🔧 [DEBUG] Zaktualizowano wagi robocze w piaskownicy debug/strength_routines.json" if args.debug else "💾 Zaktualizowano wagi robocze w bazie"
            print(f"{prefix} ({routine_name.upper()}): {', '.join(updated_exs)}")

    plan_path = os.path.join(OUTPUT_DIR_PATH, "weekly_plan.md")
    if mode == "daily":
        run_daily_mode(
            client=client,
            todays_date=today,
            weekly_plan_path=plan_path,
            user_profile=build_user_profile(personal_data, ref_date=today),
            user_note=final_user_note,
            strength_workout=strength_workout,
            debug=args.debug,
            model=DEFAULT_GEMINI_MODEL,
            send_tg=args.send_debug,
        )
    else:
        trainings_history = load_training_history(ref_date=today, history_dir_path=HISTORY_DIR_PATH)
        if trainings_history:
            logger.info("Wczytano historię treningów z ostatnich 42 dni (6 tygodni).")
        run_plan_mode(
            client=client,
            personal_data=personal_data,
            trainings_history=trainings_history,
            user_note=combined_note,
            weekly_workout_structure_path=os.path.join(INPUT_DIR_PATH, "weekly_workout_structure.md"),
            weekly_plan_path=plan_path,
            debug=args.debug,
            model=DEFAULT_GEMINI_MODEL,
            ref_date=today,
            send_tg=args.send_debug,
        )

    finish_run(new_tg_state=new_tg_state, debug=args.debug)


if __name__ == "__main__":
    main()
