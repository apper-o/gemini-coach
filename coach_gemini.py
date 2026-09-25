"""
coach_gemini.py - Asystent Treningowy Gemini.
Odpowiada za inicjalizację klienta Gemini API, kaskadę modeli oraz orkiestrację trybów treningowych:
- daily: inteligentny tryb automatyczny (przed 12:00 -> yesterday, od 12:00 -> today)
- today: weryfikacja bieżącego dnia i adaptacja na jutro
- yesterday: audyt wczorajszego dnia i adaptacja na dziś
- plan: ułożenie kompletnego planu tygodniowego
- suggest: generowanie propozycji podziału jednostek treningowych
"""

import os
import sys
import datetime
import logging
import argparse
import time
from dotenv import load_dotenv
from google import genai

from send_telegram import send_report, markdown_to_html_doc
from garmin_service import (
    load_or_fetch_garmin_data,
    parse_garmin_data,
    parse_garmin_data_yesterday,
    parse_garmin_verification_data,
    process_and_display_activities,
    determine_workout_date,
)
from coach_prompts import (
    load_training_config,
    build_user_profile,
    load_weekly_plan,
    load_strength_routines,
    prepare_user_note,
    load_training_history,
    generate_weekly_suggestions_prompt,
    generate_weekly_plan_prompt,
    generate_verification_prompt,
    generate_yesterday_verification_prompt,
    build_verification_prompt,
    _build_and_save_daily_archive,
    finish_run,
    _extract_strength_workout_from_note,
    extract_existing_strength_workout,
    extract_existing_user_note,
)

# Parsuje .env i zapisuje klucze do pamięci procesu (os.environ).
load_dotenv()

# Inicjalizacja loggera.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Stałe globalne.
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR = "input"
OUTPUT_DIR = "output"
PROMPTS_DIR = "prompts"
HISTORY_DIR = "trainings_history"
DEBUG_DIR = "debug"

# ==============================================================================
# 1. KONFIGURACJA I KLIENT GEMINI API
# ==============================================================================

def exit_with_error(message=None, error=None, code=1):
    """Wyświetla komunikat o błędzie, opcjonalne szczegóły wyjątku i kończy program z kodem 'code'."""
    if message:
        logger.error(message)
    if error:
        logger.error(f"🔍 Szczegóły błędu / wyjątku: {error}")
    logger.error(f"🛑 Zakończenie działania programu (kod wyjścia: {code}).")
    sys.exit(code)


def get_gemini_models():
    """
    Wczytuje i sprawdza, czy lista modeli Gemini  ze zmiennej środowiskowej GEMINI_MODELS nie jest pusta.
    Zwraca listę nazw modeli uporządkowaną według wystąpienia w pliku .env.
    """
    env_models = os.getenv("GEMINI_MODELS")
    if not env_models or not env_models.strip():
        exit_with_error(
            "Brak zdefiniowanych modeli Gemini. "
            "W pliku .env zdefiniuj zmienną GEMINI_MODELS (np. GEMINI_MODELS=\"gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.0-flash-lite\")."
        )

    models = [m.strip() for m in env_models.split(",") if m.strip()]
    if not models:
        exit_with_error(
            "Zmienna GEMINI_MODELS w pliku .env nie zawiera nazw modeli! "
            "Zapisz nazwy w formacie: GEMINI_MODELS=\"gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.0-flash-lite\"."
        )

    return models


def save_debug_prompt(prompt, debug=False):
    """Zapisuje treść wysyłanego prompta do pliku "debug/debug_log.md", jeśli flaga debug jest włączona."""
    if debug:
        debug_log_path = os.path.join(DEBUG_DIR, "debug_log.md")
        with open(debug_log_path, "w", encoding="utf-8") as f_debug:
            f_debug.write(prompt + "\n")
        logger.info(f"[DEBUG] Zapisano wysłany prompt do: {debug_log_path}")


def send_gemini_prompt_with_fallback(client, prompt, models=None, debug=False):
    """
    Wysyła prompt do Gemini z automatycznym mechanizmem fallbacku.
    Jeśli dany model jest przeciążony, przełącza na kolejny model z listy.
    
    Returns:
        Odpowiedź od modelu lub error w przypadku jej braku.
    """
    save_debug_prompt(prompt, debug=debug)

    print("\n" + "="*50)
    print("WYSYŁANIE PROMPTU DO GEMINI")
    print(f"Wskazane modele: {', '.join(models)}")
    print("="*50)

    last_error = None
    for idx, model_name in enumerate(models, 1):
        try:
            logger.info(f"Wysyłanie zapytania do Gemini (Model [{idx}/{len(models)}]: {model_name})...")
            chat = client.chats.create(model=model_name)
            response = chat.send_message(prompt)
            logger.info(f"✅ Odpowiedź pomyślnie wygenerowana przez model: {model_name}")
            return response
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"⚠️ Model {model_name} zwrócił błąd ({err_msg}).")
            last_error = e
            if idx < len(models):
                logger.info(f"🔄 Przełączam na model zapasowy: {models[idx]}...")
                time.sleep(2)
                continue

    models_list_str = ', '.join(models) if models else 'Brak'
    exit_with_error(
        f"❌ Wszystkie modele Gemini w kaskadzie zawiodły ({models_list_str}).",
        error=last_error,
        code=1
    )



# ==============================================================================
# 2. GŁÓWNE TRYBY DZIAŁANIA
# ==============================================================================

def run_suggest_mode(client, training_context, history_context, user_note, preferences_file, debug=False, models=None):
    """
    Tryb suggest: Generowanie sugestii typów treningów na tydzień.
    Model analizuje historię ostatnich 42 dni, fazę i cele, aby zaproponować podział jednostek.
    """

    print("\n" + "="*60)
    print("💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡")
    print("="*60)
    print("Model analizuje historię ostatnich 42 dni, fazę i cele, aby zaproponować podział jednostek.")

    suggest_prompt = generate_weekly_suggestions_prompt(
        training_context=training_context,
        history_context=history_context,
        user_note=user_note
    )

    try:
        response = send_gemini_prompt_with_fallback(client, suggest_prompt, models=models, debug=debug)

        print("\n💡 PROPONOWANY PODZIAŁ TYPÓW TRENINGU NA TEN TYDZIEŃ 💡\n")
        print(response.text)

        target_preferences = os.path.join(DEBUG_DIR, "weekly_preferences.md") if debug else preferences_file

        with open(target_preferences, "w", encoding="utf-8") as pf:
            pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii treningowej i profilu\n")
            pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python coach_gemini.py plan'\n\n")
            pf.write(response.text)

        if debug:
            print(f"\n✅ [TRYB DEBUG] Zapisano propozycję do pliku: {target_preferences}")
        else:
            print(f"\n✅ Zapisano propozycję do pliku: {target_preferences}")
            print(f"👉 Jeśli chcesz coś zmienić, wyedytuj '{preferences_file}', a następnie uruchom:")
            print("   python coach_gemini.py plan")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania sugestii.", error=e)


def run_plan_mode(client, training_context, history_context, user_note, preferences_file, weekly_plan_file, strength_routines_file, debug=False, models=None):
    """Tryb 2: Planowanie całego tygodnia treningowego."""
    print("\n" + "="*60)
    print("🗓️  TRYB PLANOWANIA TYGODNIOWEGO (GEMINI COACH) 🗓️")
    print("="*60)

    # Sprawdzamy czy istnieje plik z debug, a jeśli nie – bierzemy produkcyjny do odczytu
    debug_preferences_file = os.path.join(DEBUG_DIR, "weekly_preferences.md")
    if debug and os.path.exists(debug_preferences_file):
        active_preferences_file = debug_preferences_file
    elif os.path.exists(preferences_file):
        active_preferences_file = preferences_file
    else:
        # Brak pliku w obu miejscach: w trybie debug tworzymy szablon w debug/, a normalnie w input/
        active_preferences_file = debug_preferences_file if debug else preferences_file
        print(f"⚠️  Nie znaleziono pliku '{active_preferences_file}'!")
        with open(active_preferences_file, "w", encoding="utf-8") as pf:
            pf.write("# Wpisz w jakie dni jaki typ treningu chcesz wykonać, np.:\n")
            pf.write("# Poniedziałek: Easy + przebieżki\n# Wtorek: Tempo progowe\n# Środa: FBW\n")
        print(f"Utworzono pusty plik '{active_preferences_file}'. Uzupełnij go lub uruchom 'python coach_gemini.py suggest'.")
        sys.exit(2)

    with open(active_preferences_file, "r", encoding="utf-8") as pf:
        raw_lines = pf.readlines()

    # Wczytuje linie zaczynające się od znaku innego niż #.
    # Pomija tekst znajdujący się za fragmentem "Uzasadnienie".
    # Weryfikuje, czy linie zaczynają się od poprawnego dnia tygodnia.
    valid_lines = []
    invalid_lines = []
    for line in raw_lines:
        s = line.strip()
        if not s:
            continue
        if "uzasadnienie" in s.lower():
            break
        if s.startswith("#"):
            continue

        clean_line = s.lstrip("0123456789.-*•) ").strip()
        first_word = clean_line.split()[0].rstrip(":").capitalize() if clean_line else ""

        if first_word in DAYS_PL:
            valid_lines.append(clean_line)
        else:
            invalid_lines.append(s)

    if invalid_lines:
        print(f"⚠️  W pliku '{active_preferences_file}' znaleziono niepoprawne linie:")
        for inv in invalid_lines:
            print(f"   ❌ {inv}")
        print("\n💡 Każda linia powinna zaczynać się od dnia tygodnia, np.: 'Poniedziałek: Easy run'")
        sys.exit(2)

    days_preferences = "\n".join(valid_lines).strip()

    if not days_preferences:
        print(f"⚠️  Plik '{active_preferences_file}' nie zawiera zdefiniowanych dni treningowych.")
        print("Wpisz w nim preferencje lub uruchom: python coach_gemini.py suggest")
        sys.exit(2)

    print(f"📄 Wczytano preferencje z pliku {active_preferences_file}:\n")
    print(days_preferences)
    print("\n" + "-"*40)

    strength_routines = load_strength_routines(strength_routines_file)

    plan_prompt = generate_weekly_plan_prompt(
        days_preferences=days_preferences,
        training_context=training_context,
        history_context=history_context,
        user_note=user_note,
        strength_routines=strength_routines
    )

    try:
        response = send_gemini_prompt_with_fallback(client, plan_prompt, models=models, debug=debug)

        print("\n🏆 ROZPISKA PLANU NA CAŁY TYDZIEŃ OD TRENERA 🏆\n")
        print(response.text)

        target_plan_file = os.path.join(DEBUG_DIR, "weekly_plan.md") if debug else weekly_plan_file

        with open(target_plan_file, "w", encoding="utf-8") as wf:
            wf.write(response.text)

        if debug:
            print(f"\n✅ [TRYB DEBUG] Zapisano plan do: {target_plan_file} (Plik produkcyjny {weekly_plan_file} pozostał nienaruszony)")

            # Wygenerowanie podglądu HTML w folderze debug/ bez wysyłki na Telegram
            try:
                html_path = os.path.join(DEBUG_DIR, "weekly_plan.html")
                html_content = markdown_to_html_doc(response.text, title="Plan Tygodniowy - Coach Gemini (Debug)")
                with open(html_path, "w", encoding="utf-8") as hf:
                    hf.write(html_content)
                print(f"📄 [TRYB DEBUG] Wygenerowano podgląd HTML: {html_path} (Wysyłka na Telegram została wstrzymana)")
            except Exception as he:
                logger.warning(f"Nie udało się wygenerować podglądu HTML: {he}")
        else:
            print(f"\n✅ Zapisano plan do: {target_plan_file}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")

            # Wysłanie planu tygodniowego na Telegram w formacie załącznika HTML
            try:
                send_report(weekly_plan_file)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać planu na Telegram: {te}")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania planu tygodniowego.", error=e)



def run_daily_mode(client, todays_date, dump_file, weekly_plan_file, user_profile, user_note, day="today", debug=False, models=None):
    """
    Weryfikacja jednostek treningowych i biometrii z adaptacją na następny trening.
    Obsługuje:
    - day="today": weryfikacja dzisiejszych aktywności i adaptacja na jutro.
    - day="yesterday": audyt wczorajszych aktywności (po nocy regeneracyjnej) i adaptacja na dziś.
    """
    if day not in ["today", "yesterday"]:
        exit_with_error(f"Nieprawidłowy parametr 'day' w run_daily_mode: '{day}'. Dozwolone wartości to: 'today', 'yesterday'.")

    is_yesterday = (day == "yesterday")

    audit_date = todays_date - datetime.timedelta(days=1) if is_yesterday else todays_date
    target_date = audit_date + datetime.timedelta(days=1)
    history_date = audit_date - datetime.timedelta(days=1)

    audit_date_str = f"{DAYS_PL[audit_date.weekday()]}, {audit_date.isoformat()}"
    target_date_str = f"{DAYS_PL[target_date.weekday()]}, {target_date.isoformat()}"
    history_date_str = f"{DAYS_PL[history_date.weekday()]}, {history_date.isoformat()}"

    mode_title = "⏪ TRYB AUDYTU WCZORAJSZEGO DNIA I ADAPTACJI NA DZIŚ ⏪" if is_yesterday else "🏃 TRYB WERYFIKACJI DZISIEJSZEGO DNIA I ADAPTACJI NA JUTRO 🏃"
    log_scope = f"audytu: {audit_date_str} oraz adaptacji na: {target_date_str}"

    print("\n" + "="*60)
    print(mode_title)
    print(f"Audyt: {audit_date_str} | Adaptacja na: {target_date_str}")
    print("="*60)

    logger.info(f"Uruchomiono tryb weryfikacji ('{day}') dla {log_scope}...")

    try:
        raw_data = load_or_fetch_garmin_data(todays_date, dump_file, mode=day, debug=debug)
        garmin_stats = parse_garmin_verification_data(raw_data, day=day, target_date=todays_date)
        raw_activities = raw_data.get(day, {}).get('activities', [])

        # 1. Wczytujemy plan tygodniowy, jeśli istnieje (w trybie debug preferujemy plan z debug/)
        debug_weekly_plan_file = os.path.join(DEBUG_DIR, "weekly_plan.md")
        active_weekly_plan_file = debug_weekly_plan_file if (debug and os.path.exists(debug_weekly_plan_file)) else weekly_plan_file
        weekly_plan_content = load_weekly_plan(active_weekly_plan_file)
        if not weekly_plan_content:
            print(f"ℹ️  Brak aktywnego planu tygodniowego ({active_weekly_plan_file}).")
            print("   Model przeprowadzi analizę treningu i regeneracji bez odniesienia do założeń tygodnia.")

        # 2. Sprawdzamy istnienie wcześniejszej analizy oraz zachowujemy jej notatki
        existing_history_file = os.path.join(HISTORY_DIR, f"{audit_date.isoformat()}.md")
        has_existing_analysis = os.path.exists(existing_history_file)

        if has_existing_analysis:
            logger.info(f"ℹ️  Wykryto wcześniejszą analizę dla dnia {audit_date.isoformat()} ({existing_history_file}). Zostanie ona zaktualizowana i nadpisana.")
            print(f"ℹ️  Wykryto wcześniejszą analizę z dnia {audit_date_str}. Nowy raport zaktualizuje i nadpisze dotychczasowe podsumowanie.")

            # Odzyskujemy wcześniejsze uwagi biegacza, jeśli nie ma nowej porannej notatki
            recovered_note = extract_existing_user_note(existing_history_file)
            if recovered_note:
                if user_note and recovered_note not in user_note:
                    user_note = f"{recovered_note}\n\n[NOWA WIADOMOŚĆ PORANNA]:\n{user_note}"
                    logger.info("📝 Połączono wcześniejszą notatkę z nową wiadomością poranną.")
                elif not user_note:
                    user_note = recovered_note
                    logger.info(f"📝 Zachowano zarejestrowaną we wcześniejszej analizie notatkę biegacza z: {existing_history_file}")

        strength_workout = _extract_strength_workout_from_note(user_note)
        if not strength_workout and has_existing_analysis:
            strength_workout = extract_existing_strength_workout(existing_history_file)
            if strength_workout:
                logger.info(f"🏋️ Zachowano zarejestrowany we wcześniejszej analizie trening siłowy z: {existing_history_file}")

        # 3. Parsujemy i wyświetlamy aktywności podlegające audytowi
        sorted_activities, activity_stats = process_and_display_activities(
            raw_activities,
            audit_date_str
        )

        audit_day_name = DAYS_PL[audit_date.weekday()]
        target_day_name = DAYS_PL[target_date.weekday()]
        day_label = "WCZORAJ: " if is_yesterday else ""

        # Wyświetlenie informacji o siłowni lub dniu wolnym w konsoli
        if strength_workout:
            print("\n" + "="*50)
            print(f"🏋️ ZAREJESTROWANO TRENING SIŁOWY (Z TELEGRAMA) {day_label}{audit_date_str}")
            print("="*50)
            print(strength_workout)
        elif not activity_stats:
            rest_label = " (WCZORAJ)" if is_yesterday else ""
            print("\n" + "="*50)
            print(f"🛌 DZIEŃ BEZ BIEGU / REST DAY{rest_label}: {audit_date_str}")
            print("="*50)
            print(f"W dniu {audit_date_str} nie odnotowano aktywności biegowej ani treningu siłowego.")

        # 4. Konstrukcja zwięzłego opisu założeń dla modelu
        if activity_stats and strength_workout:
            workout_summary = f"zarejestrowano {len(activity_stats)} jednostek biegowych oraz trening siłowy zgłoszony w notatce"
        elif activity_stats:
            workout_summary = f"zarejestrowano {len(activity_stats)} jednostek biegowych"
        elif strength_workout:
            workout_summary = "nie było treningu biegowego, ale zrealizowano trening siłowy (zgłoszony w notatce)"
        else:
            workout_summary = "nie było treningu biegowego ani siłowego (Dzień wolny / Rest Day)"

        variant_note = " (WARIANT A i B)" if is_yesterday else ""
        if weekly_plan_content:
            if activity_stats and strength_workout:
                plan_action = f"Odszukaj sekcję ({audit_day_name}) w planie tygodniowym, sprawdź zgodność wykonania biegu oraz audytuj jednostkę siłową{variant_note}."
            elif activity_stats:
                plan_action = f"Odszukaj sekcję ({audit_day_name}) w planie tygodniowym i sprawdź zgodność wykonania całości lub poszczególnych etapów."
            elif strength_workout:
                plan_action = f"Sprawdź w planie tygodniowym, czy siłownia była zaplanowana na {audit_day_name}. Przeprowadź audyt wykonanych ćwiczeń, oceń regenerację i zaadaptuj trening na dzień {target_date_str}{variant_note}."
            else:
                plan_action = f"Sprawdź w planie tygodniowym, czy dzień wolny był zaplanowany na {audit_day_name}. Skup się na ocenie regeneracji oraz adaptacji do treningu na dzień {target_date_str}."

            planned_workout_desc = f"Założenia na dzień {audit_date_str} według planu tygodniowego. W tym dniu {workout_summary}. {plan_action}"
        else:
            planned_workout_desc = (
                f"Brak aktywnego planu tygodniowego. W dniu {audit_date_str} {workout_summary}. "
                f"Dokonaj autonomicznej oceny treningu i wskaźników regeneracji oraz zaproponuj plan działania na dzień {target_date_str}."
            )

        target_plan_desc = f"Założenia na dzień {target_date_str} według planu tygodniowego (sekcja: {target_day_name})" if weekly_plan_content else f"Zaproponuj rekomendację treningową na dzień {target_date_str}"

        verification_prompt = build_verification_prompt(
            day=day,
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
            strength_workout=strength_workout
        )

        response = send_gemini_prompt_with_fallback(client, verification_prompt, models=models, debug=debug)

        report_title = "AUDYT DNIA WCZORAJSZEGO" if is_yesterday else "RAPORT TRENERSKI"
        print(f"\n🏆 {report_title} I ADAPTACJA NA {target_date_str} 🏆\n")
        print(response.text)

        workout_date = determine_workout_date(audit_date, sorted_activities, activity_stats)
        _build_and_save_daily_archive(
            mode=day,
            workout_date=workout_date,
            date_str=audit_date_str,
            next_date_str=target_date_str,
            all_stats=activity_stats,
            garmin_stats=garmin_stats,
            response_text=response.text,
            strength_workout=strength_workout,
            user_note=user_note,
            debug=debug
        )

        # Wysłanie raportu dziennego na Telegram w formacie załącznika HTML (pomijane w trybie debug)
        if not debug:
            try:
                latest_report_file = os.path.join(OUTPUT_DIR, "last_daily_report.md")
                send_report(latest_report_file)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać raportu na Telegram: {te}")

    except Exception as e:
        exit_with_error("Wystąpił błąd podczas weryfikacji i adaptacji.", error=e)


# ==============================================================================
# 3. CLI I PUNKT WEJŚCIA PROGRAMU
# ==============================================================================

def check_mode_compatibility(raw_mode):
    """
    Sprawdza czy przekazany tryb zgadza się z dostępnymi.
    """
    mode = (raw_mode or "daily").lower()
    if mode == "week":
        mode = "plan"
    if mode not in ["daily", "today", "yesterday", "plan", "suggest"]:
        exit_with_error(
            f"Nieprawidłowy tryb działania: '{raw_mode}'. "
            f"Dozwolone tryby to: daily, today, yesterday, plan, suggest."
        )
    return mode


def parse_date(date_str=None):
    """
    Weryfikuje poprawność i zwraca datę.
    """
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            exit_with_error(f"Nieprawidłowy format daty: {date_str}. Użyj formatu YYYY-MM-DD.")
    else:
        return datetime.date.today()


def main():
    # Inicjalizacja parsera.
    parser = argparse.ArgumentParser(description="Coach Gemini - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily (inteligentny auto-wybór), today, yesterday, plan, suggest")
    parser.add_argument("--debug", action="store_true", help="włącz tryb debugowania (bezpieczna piaskownica w katalogu debug/)")
    parser.add_argument("--date", type=str, default=None, help="opcjonalna data referencyjna w formacie YYYY-MM-DD")
    
    args = parser.parse_args()
    debug = args.debug
    mode = check_mode_compatibility(args.mode)
    today = parse_date(args.date)

    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        logger.info("🔧 TRYB DEBUG AKTYWNY: Pliki produkcyjne nie będą modyfikowane. Wyniki trafią do katalogu 'debug/'.")

    # Przygotowanie stałych ścieżek.
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

    preferences_file = os.path.join(INPUT_DIR, "weekly_preferences.md")
    weekly_plan_file = os.path.join(OUTPUT_DIR, "weekly_plan.md")
    config_file = os.path.join(INPUT_DIR, "training_config.json")
    dump_file = os.path.join(INPUT_DIR, "garmin_dump.json")
    strength_routines_file = os.path.join(INPUT_DIR, "strength_routines.md")

    # Sprawdzenie klucza Gemini i modeli.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        exit_with_error("Brak klucza GEMINI_API_KEY w pliku .env!")

    gemini_models = get_gemini_models()
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Wczytanie konfiguracji biegacza i opcjonalnej notatki z Telegrama.
    training_context = load_training_config(config_file)
    user_note, new_tg_state = prepare_user_note()

    # Profil tętna do prompta
    user_profile = build_user_profile(training_context)

    if mode in ["suggest", "plan"]:
        # Wczytanie historii treningów z ostatnich 42 dni (wymagane tylko do planowania i sugestii).
        history_context = load_training_history(HISTORY_DIR, days=42, ref_date=today)
        if history_context:
            logger.info("Wczytano historię treningów z ostatnich 42 dni (6 tygodni).")

        if mode == "suggest":
            run_suggest_mode(client, training_context, history_context, user_note, preferences_file, debug=debug, models=gemini_models)
        else:
            run_plan_mode(client, training_context, history_context, user_note, preferences_file, weekly_plan_file, strength_routines_file, debug=debug, models=gemini_models)

    elif mode in ["daily", "today", "yesterday"]:
        if mode == "daily":
            current_hour = datetime.datetime.now().hour
            if current_hour < 12:
                resolved_day = "yesterday"
                logger.info(f"⏰ [TRYB DAILY] Godzina {datetime.datetime.now().strftime('%H:%M')} (przed południem) -> automatycznie wybrano audyt wczorajszego dnia ('yesterday').")
            else:
                resolved_day = "today"
                logger.info(f"⏰ [TRYB DAILY] Godzina {datetime.datetime.now().strftime('%H:%M')} (po południu) -> automatycznie wybrano weryfikację dzisiejszego dnia ('today').")
        else:
            resolved_day = mode

        run_daily_mode(client, today, dump_file, weekly_plan_file, user_profile, user_note, day=resolved_day, debug=debug, models=gemini_models)

    # Sprzątanie i aktualizacja stanu Telegrama
    finish_run(new_tg_state, debug=debug)



if __name__ == "__main__":
    main()
