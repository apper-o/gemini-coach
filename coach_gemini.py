"""
coach_gemini.py - Asystent Treningowy Gemini.
Odpowiada za inicjalizację klienta Gemini API, kaskadę modeli oraz orkiestrację trybów treningowych:
- daily: wieczorny tryb audytu bieżącego dnia (20:57), zaleceń regeneracyjnych i adaptacji na jutro (alias: today)
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
    load_personal_data,
    build_user_profile,
    load_weekly_plan,
    load_strength_routines,
    prepare_user_note,
    load_training_history,
    generate_weekly_suggestions_prompt,
    generate_weekly_plan_prompt,
    generate_verification_prompt,
    build_and_save_daily_archive,
    separate_strength_and_user_notes,
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


def get_gemini_models():
    """
    Wczytuje i sprawdza dostępność modeli Gemini w konfiguracji.

    Returns:
        list: Uporządkowana lista nazw modeli gotowych do kaskady.
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
    """
    Zapisuje treść wysyłanego prompta do pliku, jeśli aktywny jest tryb debugowania.

    Args:
        prompt (str): Kompletny tekst promptu wysyłanego do modelu.
        debug (bool): Flaga trybu debug.
    """
    if debug:
        debug_log_path = os.path.join(DEBUG_DIR, "debug_log.md")
        with open(debug_log_path, "w", encoding="utf-8") as f_debug:
            f_debug.write(prompt + "\n")
        logger.info(f"[DEBUG] Zapisano wysłany prompt do: {debug_log_path}")


def send_gemini_prompt_with_fallback(client, prompt, models=None, debug=False):
    """
    Wysyła prompt do Gemini z automatycznym mechanizmem fallbacku.
    Jeśli dany model jest przeciążony lub zawiedzie, próbuje kolejnego z listy modeli.
    
    Args:
        client: Zainicjowany klient Gemini.
        prompt (str): Treść zapytania dla asystenta.
        models (list): Lista modeli w kaskadzie.
        debug (bool): Flaga trybu debug.

    Returns:
        Odpowiedzi wygenerowana przez model.
    """
    save_debug_prompt(prompt, debug=debug)

    print("\n" + "="*60)
    print("🚀 WYSYŁANIE PROMPTU DO GEMINI")
    print(f"📄 Wskazane modele: {', '.join(models)}")
    print("="*60)

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
            last_error = e
            logger.warning(f"⚠️ Model {model_name} zwrócił błąd ({err_msg}).")

        if idx < len(models):
            time.sleep(5)
            continue

    models_list_str = ', '.join(models) if models else 'Brak'
    exit_with_error(
        f"❌ Wszystkie modele Gemini w kaskadzie zawiodły ({models_list_str}).",
        error=last_error,
        code=1
    )



# ==============================================================================
# GŁÓWNE TRYBY DZIAŁANIA
# ==============================================================================

def run_suggest_mode(client, personal_data, trainings_history, user_note, weekly_workout_structure, debug=False, models=None, ref_date=None):
    """
    Generowanie sugestii typów treningów na cały nadchodzący tydzień.

    Args:
        client: Zainicjowany klient Gemini API.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        trainings_history (str): Kontekst wyników z 42 ostatnich dni.
        user_note (str): Opcjonalna notatka zawodnika.
        weekly_workout_structure (str): Ścieżka do docelowego pliku preferencji.
        debug (bool): Flaga trybu debug.
        models (list): Dostępne modele Gemini.
        ref_date (date): Data wygenerowania układu.
    """

    print("\n" + "="*60)
    print("💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡")
    print("="*60)

    suggest_prompt = generate_weekly_suggestions_prompt(
        personal_data=personal_data,
        trainings_history=trainings_history,
        user_note=user_note,
        ref_date=ref_date
    )

    try:
        response = send_gemini_prompt_with_fallback(client, suggest_prompt, models=models, debug=debug)

        target_structure = os.path.join(DEBUG_DIR, "weekly_workout_structure.md") if debug else weekly_workout_structure

        with open(target_structure, "w", encoding="utf-8") as pf:
            pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii treningowej i profilu\n")
            pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python coach_gemini.py plan'\n\n")
            pf.write(response.text)

        if debug:
            print(f"\n✅ [DEBUG] Zapisano propozycję do pliku: {target_structure}")
        else:
            print(f"\n✅ Zapisano propozycję do pliku: {target_structure}")
            print(f"📄 Jeśli chcesz coś zmienić, wyedytuj '{weekly_workout_structure}', a następnie uruchom:")
            print("   python coach_gemini.py plan")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania sugestii.", error=e)


def _read_and_validate_preferences(weekly_workout_structure, debug=False):
    """
    Otwiera plik preferencji, weryfikuje jego zawartość i zwraca gotowy ciąg dni.
    Jeśli plik nie istnieje, tworzy pusty szablon i przerywa działanie z ostrzeżeniem.

    Args:
        weekly_workout_structure (str): Ścieżka do głównego pliku preferencji.
        debug (bool): Flaga trybu debug.

    Returns:
        tuple: Sformatowany string z preferencjami (str) oraz ścieżka do załadowanego pliku (str).
    """
    debug_weekly_workout_structure = os.path.join(DEBUG_DIR, "weekly_workout_structure.md")
    if debug and os.path.exists(debug_weekly_workout_structure):
        active_weekly_workout_structure = debug_weekly_workout_structure
    elif os.path.exists(weekly_workout_structure):
        active_weekly_workout_structure = weekly_workout_structure
    else:
        active_weekly_workout_structure = debug_weekly_workout_structure if debug else weekly_workout_structure
        with open(active_weekly_workout_structure, "w", encoding="utf-8") as pf:
            pf.write("# Wpisz w jakie dni jaki typ treningu chcesz wykonać, np.:\n")
            pf.write("# Poniedziałek: Easy + przebieżki\n# Wtorek: Tempo progowe\n# Środa: FBW\n")
        exit_with_error(
            f"Nie znaleziono pliku '{active_weekly_workout_structure}'. "
            f"Utworzono pusty szablon. Uzupełnij go lub uruchom 'python coach_gemini.py suggest'.",
            code=2
        )

    with open(active_weekly_workout_structure, "r", encoding="utf-8") as pf:
        raw_lines = pf.readlines()

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
        msg = f"W pliku '{active_weekly_workout_structure}' znaleziono niepoprawne linie:\n"
        for inv in invalid_lines:
            msg += f"   - {inv}\n"
        msg += "Każda linia powinna zaczynać się od dnia tygodnia, np.: 'Poniedziałek: Easy run'."
        exit_with_error(msg, code=2)

    days_structure = "\n".join(valid_lines).strip()

    if not days_structure:
        exit_with_error(
            f"Plik '{active_weekly_workout_structure}' nie zawiera zdefiniowanych dni treningowych.\n"
            "Wpisz w nim preferencje lub uruchom: python coach_gemini.py suggest",
            code=2
        )

    return days_structure, active_weekly_workout_structure


def run_plan_mode(client, personal_data, trainings_history, user_note, weekly_workout_structure, weekly_plan_file, strength_routines_file, debug=False, models=None, ref_date=None, send_tg=False):
    """
    Tryb planowania: Generuje kompletny plan na tydzień treningowy.

    Args:
        client: Zainicjowany klient Gemini.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        trainings_history (str): Kontekst historyczny (ostatnie 42 dni).
        user_note (str): Opcjonalna notatka zawodnika.
        weekly_workout_structure (str): Ścieżka pliku weekly_workout_structure.md.
        weekly_plan_file (str): Ścieżka zapisu dla planu (weekly_plan.md).
        strength_routines_file (str): Ścieżka pliku siłowego (strength_routines.md).
        debug (bool): Flaga trybu debug.
        models (list): Lista dostępnych modeli Gemini.
        ref_date (date): Data referencyjna bieżącego układania planu.
        send_tg (bool): Czy wysłać plik na telegram (również dla debug).
    """
    print("\n" + "="*60)
    print("🗓️  TRYB PLANOWANIA TYGODNIOWEGO (GEMINI COACH) 🗓️")
    print("="*60)

    days_structure, active_weekly_workout_structure = _read_and_validate_preferences(weekly_workout_structure, debug=debug)

    print(f"📄 Wczytano preferencje z pliku {active_weekly_workout_structure}:\n")
    print(days_structure)
    print("\n" + "="*60)

    strength_routines = load_strength_routines(strength_routines_file)

    plan_prompt = generate_weekly_plan_prompt(
        days_structure=days_structure,
        personal_data=personal_data,
        trainings_history=trainings_history,
        user_note=user_note,
        strength_routines=strength_routines,
        ref_date=ref_date
    )

    try:
        response = send_gemini_prompt_with_fallback(client, plan_prompt, models=models, debug=debug)

        target_plan_file = os.path.join(DEBUG_DIR, "weekly_plan.md") if debug else weekly_plan_file

        with open(target_plan_file, "w", encoding="utf-8") as wf:
            wf.write(response.text)

        if debug:
            print(f"\n📄 [DEBUG] Zapisano plan do: {target_plan_file} (Plik produkcyjny {weekly_plan_file} pozostał nienaruszony)")

            if send_tg:
                print(f"🚀 [DEBUG] Raport zostanie wysłany na Telegrama (z flagą debug)")
                send_weekly_plan(target_plan_file)
            else:
                print(f"📄 [DEBUG] Dane NIE zostaną wysłane na Telegrama.")
        else:
            print(f"\n✅ Zapisano plan do: {target_plan_file}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")

            # Wysłanie planu tygodniowego na Telegram w formacie załącznika HTML
            try:
                send_weekly_plan(weekly_plan_file)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać planu na Telegram: {te}")
    except Exception as e:
        exit_with_error("Wystąpił błąd podczas generowania planu tygodniowego.", error=e)



def _build_daily_evaluation_context(audit_date, target_date, run_stats, other_stats, strength_workout, weekly_plan_content):
    """
    Buduje opisy kontekstowe dla audytu (założenia dzisiejsze i cele na jutro).

    Args:
        audit_date (date): Data audytowanego treningu (dziś).
        target_date (date): Data adaptowanego treningu (jutro).
        run_stats (list): Zestawienie aktywności biegowych.
        other_stats (list): Zestawienie pozostałych aktywności (rower, basen).
        strength_workout (str): Zgłoszony trening siłowy.
        weekly_plan_content (str): Zawartość planu tygodniowego.

    Returns:
        tuple: Krotka (planned_workout_desc, target_plan_desc).
    """
    audit_date_str = f"{DAYS_PL[audit_date.weekday()]}, {audit_date.isoformat()}"
    target_date_str = f"{DAYS_PL[target_date.weekday()]}, {target_date.isoformat()}"
    audit_day_name = DAYS_PL[audit_date.weekday()]
    target_day_name = DAYS_PL[target_date.weekday()]
    is_sunday = (audit_date.weekday() == 6)

    workout_summary_parts = []
    if run_stats:
        workout_summary_parts.append(f"zarejestrowano {len(run_stats)} jednostek biegowych")
    if other_stats:
        other_names = ", ".join([s['name'] for s in other_stats])
        workout_summary_parts.append(f"wykonano trening uzupełniający: {other_names}")
    if strength_workout:
        workout_summary_parts.append("zrealizowano trening siłowy (notatka z Telegrama)")

    if workout_summary_parts:
        workout_summary = " oraz ".join(workout_summary_parts)
    else:
        workout_summary = "nie było treningu biegowego ani siłowego (Dzień wolny / Rest Day)"

    if weekly_plan_content:
        if is_sunday:
            plan_action = f"Odszukaj sekcję ({audit_day_name}) w planie tygodniowym i sprawdź zgodność wykonania treningu kończącego mikrocykl."
        elif run_stats:
            plan_action = f"Odszukaj sekcję ({audit_day_name}) w planie tygodniowym i sprawdź zgodność wykonania biegu."
        elif other_stats or strength_workout:
            plan_action = f"Sprawdź w planie tygodniowym, czy siłownia/trening uzupełniający były zaplanowane na {audit_day_name}. Przeprowadź audyt wykonanych ćwiczeń, oceń regenerację i zaadaptuj trening na dzień {target_date_str}."
        else:
            plan_action = f"Sprawdź w planie tygodniowym, czy dzień wolny był zaplanowany na {audit_day_name}. Skup się na ocenie regeneracji oraz adaptacji do treningu na dzień {target_date_str}."

        planned_workout_desc = f"Założenia na dzień {audit_date_str} według planu tygodniowego. W tym dniu {workout_summary}. {plan_action}"
    else:
        planned_workout_desc = (
            f"Brak aktywnego planu tygodniowego. W dniu {audit_date_str} {workout_summary}. "
            f"Dokonaj autonomicznej oceny treningu i wskaźników regeneracji oraz zaproponuj plan działania na dzień {target_date_str}."
        )

    if is_sunday:
        target_plan_desc = "Brak (koniec mikrocyklu tygodniowego; nowy plan generuje tryb 'plan')"
    elif weekly_plan_content:
        target_plan_desc = f"Założenia na dzień {target_date_str} według planu tygodniowego (sekcja: {target_day_name})"
    else:
        target_plan_desc = f"Zaproponuj rekomendację treningową na dzień {target_date_str}"

    return planned_workout_desc, target_plan_desc


def run_daily_mode(client, todays_date, weekly_plan_file, user_profile, user_note, strength_workout, strength_routines_file=None, debug=False, models=None, day="daily", send_tg=False):
    """
    Wieczorny audyt treningu i biometrii z dnia dzisiejszego oraz adaptacja planu na jutro.

    Args:
        client: Zainicjowany klient Gemini.
        todays_date (date): Data audytowanego treningu.
        weekly_plan_file (str): Ścieżka pliku weekly_plan.md.
        user_profile (str): Informacje o profilu i sprzęcie.
        user_note (str): Opcjonalna notatka zawodnika.
        strength_workout (str): Odseparowany tekst treningu siłowego (jeśli występuje).
        strength_routines_file (str, optional): Ścieżka pliku siłowego (strength_routines.md).
        debug (bool): Flaga trybu debug.
        models (list): Lista dostępnych modeli Gemini.
        day (str): Rodzaj dnia, domyślnie "daily".
        send_tg (bool): Flaga wymuszająca wysyłkę w trybie debug.
    """
    audit_date = todays_date
    target_date = audit_date + datetime.timedelta(days=1)
    history_date = audit_date - datetime.timedelta(days=1)

    audit_date_str = f"{DAYS_PL[audit_date.weekday()]}, {audit_date.isoformat()}"
    target_date_str = f"{DAYS_PL[target_date.weekday()]}, {target_date.isoformat()}"
    history_date_str = f"{DAYS_PL[history_date.weekday()]}, {history_date.isoformat()}"

    print("\n" + "="*60)
    print("🏃 TRYB WIECZORNEGO AUDYTU DZIENNEGO I ADAPTACJI NA JUTRO 🏃")
    print(f"Audyt: {audit_date_str} | Adaptacja na: {target_date_str}")
    print("="*60)

    try:
        raw_data = fetch_garmin_data(todays_date)
        garmin_stats = parse_garmin_data(raw_data, target_date=todays_date)
        raw_activities = raw_data.get('today', {}).get('activities', [])

        # 1. Wczytujemy plan tygodniowy, jeśli istnieje (w trybie debug preferujemy plan z debug/)
        debug_weekly_plan_file = os.path.join(DEBUG_DIR, "weekly_plan.md")
        active_weekly_plan_file = debug_weekly_plan_file if (debug and os.path.exists(debug_weekly_plan_file)) else weekly_plan_file
        weekly_plan_content = load_weekly_plan(active_weekly_plan_file)
        if not weekly_plan_content:
            print(f"⚠️  Brak aktywnego planu tygodniowego ({active_weekly_plan_file}).")
            print("📄 Model przeprowadzi analizę treningu i regeneracji bez odniesienia do założeń tygodnia.")

        # 2. Wczytujemy bazę własnych zestawów siłowych biegacza
        strength_routines_content = None
        if strength_routines_file:
            try:
                strength_routines_content = load_strength_routines(strength_routines_file)
            except Exception as se:
                logger.warning(f"Nie udało się załadować zestawów siłowych ({strength_routines_file}): {se}")



        # 4. Parsujemy i wyświetlamy aktywności podlegające audytowi
        sorted_activities, activity_stats = process_and_display_activities(
            raw_activities,
            audit_date_str
        )

        run_stats = [act for act in activity_stats if act.get("is_run", True)]
        other_stats = [act for act in activity_stats if not act.get("is_run", True)]

        # Wyświetlenie informacji o siłowni lub dniu wolnym w konsoli
        if strength_workout:
            print("\n" + "="*60)
            print(f"📲 ZAREJESTROWANO TRENING SIŁOWY (Z TELEGRAMA): {audit_date_str}")
            print("="*60)
            print(strength_workout)
        elif not activity_stats:
            print("\n" + "="*60)
            print(f"📄 DZIEŃ BEZ BIEGU / REST DAY: {audit_date_str}")
            print("="*60)
            print(f"W dniu {audit_date_str} nie odnotowano aktywności biegowej ani treningu siłowego.")

        # 5. Konstrukcja zwięzłego opisu założeń dla modelu
        planned_workout_desc, target_plan_desc = _build_daily_evaluation_context(
            audit_date=audit_date,
            target_date=target_date,
            run_stats=run_stats,
            other_stats=other_stats,
            strength_workout=strength_workout,
            weekly_plan_content=weekly_plan_content
        )

        verification_prompt = generate_verification_prompt(
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
            strength_routines=strength_routines_content
        )

        response = send_gemini_prompt_with_fallback(client, verification_prompt, models=models, debug=debug)

        

        build_and_save_daily_archive(
            workout_date=audit_date.isoformat(),
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
        if not debug:
            try:
                latest_report_file = os.path.join(OUTPUT_DIR, "last_daily_report.md")
                send_daily_report(latest_report_file)
            except Exception as te:
                logger.warning(f"Nie udało się wysłać raportu na Telegram: {te}")
        elif send_tg:
            try:
                debug_report_file = os.path.join(DEBUG_DIR, "last_daily_report.md")
                print(f"🚀 [DEBUG] Wysyłanie testowego raportu na Telegram (--send_debug): {debug_report_file}...")
                send_daily_report(debug_report_file)
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
        str: Sformatowana, poprawna nazwa trybu ('daily', 'plan' lub 'suggest').
    """
    mode = (raw_mode or "daily").lower()
    if mode == "week":
        mode = "plan"
    elif mode == "today":
        mode = "daily"

    if mode == "yesterday":
        exit_with_error(
            "Tryb 'yesterday' został wycofany. "
            "Coach Gemini działa w trybie wieczornym 'daily' (uruchamianym o 20:57), "
            "który audytuje bieżący dzień i adaptuje jutrzejszy trening."
        )

    if mode not in ["daily", "plan", "suggest"]:
        exit_with_error(
            f"Nieprawidłowy tryb działania: '{raw_mode}'. "
            f"Dozwolone tryby to: daily, plan, suggest."
        )

    return mode


def parse_date(date_str=None):
    """
    Parsuje i weryfikuje poprawność podanej daty.
    
    Args:
        date_str (str, optional): Data w formacie ISO (YYYY-MM-DD).

    Returns:
        date: Obiekt daty (dzisiejsza data, jeśli argument to None).
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
    for directory in [INPUT_DIR, OUTPUT_DIR, PROMPTS_DIR, HISTORY_DIR]:
        os.makedirs(directory, exist_ok=True)

    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        logger.info("🔧 TRYB DEBUG AKTYWNY: Pliki produkcyjne nie będą modyfikowane. Wyniki trafią do katalogu 'debug/'.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        exit_with_error("Brak klucza GEMINI_API_KEY w pliku .env!")

    return api_key


def dispatch_mode(mode, client, gemini_models, today, personal_data, user_note, paths, debug=False, send_tg=False):
    """
    Kieruje wykonanie do odpowiedniego modułu na podstawie wybranego trybu działania.

    Args:
        mode (str): Tryb pracy (np. 'daily', 'plan', 'suggest').
        client: Zainicjowany klient API Gemini.
        gemini_models (list): Dostępne nazwy modeli (kaskada).
        today (date): Data uruchomienia.
        personal_data (dict): Dane zawodnika (HR Zones, PB, ...).
        user_note (str): Opcjonalna notatka zawodnika.
        paths (dict): Słownik zawierający wymagane ścieżki do plików.
        debug (bool): Flaga trybu debug.
        send_tg (bool): Czy wymusić wysyłkę raportu przy debugowaniu.
    """
    strength_workout, final_user_note = separate_strength_and_user_notes(user_note)
    
    parts = [p for p in (final_user_note, strength_workout) if p]
    combined_note = "\n\n".join(parts) if parts else None

    if mode == "daily":
        user_profile = build_user_profile(personal_data, ref_date=today)
        run_daily_mode(
            client=client,
            todays_date=today,
            weekly_plan_file=paths["plan"],
            user_profile=user_profile,
            user_note=final_user_note,
            strength_workout=strength_workout,
            strength_routines_file=paths["strength"],
            debug=debug,
            models=gemini_models,
            send_tg=send_tg
        )
        return

    trainings_history = load_training_history(ref_date=today, history_dir=HISTORY_DIR)
    if trainings_history:
        logger.info("Wczytano historię treningów z ostatnich 42 dni (6 tygodni).")

    if mode == "suggest":
        run_suggest_mode(client, personal_data, trainings_history, combined_note, paths["weekly_workout_structure"], debug=debug, models=gemini_models, ref_date=today)
    elif mode == "plan":
        run_plan_mode(client, personal_data, trainings_history, combined_note, paths["weekly_workout_structure"], paths["plan"], paths["strength"], debug=debug, models=gemini_models, ref_date=today, send_tg=send_tg)


def main():
    parser = argparse.ArgumentParser(description="Coach Gemini - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily (domyślny, audyt wieczorny o 20:57), plan, suggest")
    parser.add_argument("--debug", action="store_true", help="włącz tryb debugowania (bezpieczna piaskownica w katalogu debug/)")
    parser.add_argument("--send_debug", action="store_true", help="włącz tryb debugowania ORAZ wyślij testowy raport na Telegram")
    parser.add_argument("--date", type=str, default=None, help="opcjonalna data referencyjna w formacie YYYY-MM-DD")

    args = parser.parse_args()
    
    # Użycie send_debug implikuje włączenie trybu debug
    if args.send_debug:
        args.debug = True

    mode = resolve_mode(args.mode)
    today = parse_date(args.date)

    api_key = setup_environment(debug=args.debug)
    client = genai.Client(api_key=api_key)
    gemini_models = get_gemini_models()

    try:
        personal_data = load_personal_data(os.path.join(INPUT_DIR, "personal_data.json"))
    except Exception as e:
        exit_with_error("Nie udało się załadować konfiguracji treningowej.", error=e)
    user_note, new_tg_state = prepare_user_note()

    paths = {
        "weekly_workout_structure": os.path.join(INPUT_DIR, "weekly_workout_structure.md"),
        "plan": os.path.join(OUTPUT_DIR, "weekly_plan.md"),
        "strength": os.path.join(INPUT_DIR, "strength_routines.md"),
    }

    dispatch_mode(mode, client, gemini_models, today, personal_data, user_note, paths, debug=args.debug, send_tg=args.send_debug)
    finish_run(new_tg_state=new_tg_state, debug=args.debug)


if __name__ == "__main__":
    main()
