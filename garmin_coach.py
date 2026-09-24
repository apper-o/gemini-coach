import os
import datetime
import logging
import sys
import json
import argparse
import re
from pathlib import Path
from garminconnect import Garmin
from google import genai
from dotenv import load_dotenv

from send_telegram import fetch_recent_telegram_messages, save_telegram_state

# Załadowanie zmiennych z pliku .env.
load_dotenv()

# Inicjalizacja loggera.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Stałe globalne.
NO_DATA = "Brak danych"
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
INPUT_DIR = "input"
OUTPUT_DIR = "output"
PROMPTS_DIR = "prompts"
HISTORY_DIR = "trainings_history"

def get_gemini_models():
    """
    Wczytuje i waliduje listę modeli Gemini ze zmiennej środowiskowej GEMINI_MODELS.
    Zwraca listę nazw modeli uporządkowaną według priorytetu.
    """
    env_models = os.getenv("GEMINI_MODELS")
    if not env_models or not env_models.strip():
        logger.error(
            "Brak zdefiniowanych modeli Gemini w pliku .env! "
            "Zdefiniuj zmienną GEMINI_MODELS (np. GEMINI_MODELS=\"gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.0-flash-lite\")."
        )
        sys.exit(1)

    models = [m.strip() for m in env_models.split(",") if m.strip()]
    if not models:
        logger.error(
            "Zmienna GEMINI_MODELS w pliku .env jest pusta lub nie zawiera poprawnych nazw modeli! "
            "Zapisz nazwy w formacie: GEMINI_MODELS=\"gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.0-flash-lite\"."
        )
        sys.exit(1)

    return models


def send_gemini_prompt_with_fallback(client, prompt, models=None, debug=False):
    """
    Wysyła prompt do Gemini z automatycznym mechanizmem fallbacku (kaskada modeli).
    Jeśli dany model jest przeciążony (429, 503, high demand), automatycznie przełącza na kolejny model w kaskadzie.
    """
    if debug:
        with open("debug_log.md", "w", encoding="utf-8") as f_debug:
            f_debug.write(prompt + "\n")

    if not models:
        models = get_gemini_models()

    last_error = None
    for idx, model_name in enumerate(models, 1):
        try:
            logger.info(f"Wysyłanie zapytania do Gemini (Model [{idx}/{len(models)}]: {model_name})...")
            chat = client.chats.create(model=model_name)
            response = chat.send_message(prompt)
            logger.info(f"✅ Odpowiedź pomyślnie wygenerowana przez model: {model_name}")
            return response, model_name
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"⚠️ Model {model_name} zwrócił błąd ({err_msg}).")
            last_error = e
            if idx < len(models):
                logger.info(f"🔄 Przełączam na model zapasowy: {models[idx]}...")
                continue

    logger.error(f"❌ Wszystkie modele Gemini w kaskadzie zawiodły: {models}")
    raise last_error


def _enrich_activities(client, acts):
    """
    Uzupełnia listę aktywności o splity kilometrowe oraz dane o pogodzie.
    """
    if acts:
        for act in acts:
            act_id = act.get('activityId')
            if act_id:
                try:
                    act['splits_data'] = client.get_activity_splits(act_id)
                except Exception:
                    pass
                try:
                    act['weather_data'] = client.get_activity_weather(act_id)
                except Exception:
                    pass
    return acts


def get_garmin_client(email, password):
    """
    Inicjalizuje połączenie i loguje do Garmin Connect.
    Obsługuje bezpieczne cache'owanie tokenów sesji OAuth (tokenstore) w ~/.garminconnect.
    W przypadku błędu logowania natychmiast kończy działanie przez sys.exit(1).
    """
    tokenstore_dir = os.getenv("GARMIN_TOKENS_DIR", os.path.expanduser("~/.garminconnect"))
    os.makedirs(tokenstore_dir, exist_ok=True)

    logger.info("Inicjalizacja połączenia z Garmin Connect...")
    client = None

    # Próba wznowienia sesji z zapisanego tokena
    try:
        client = Garmin()
        client.login(tokenstore_dir)
        logger.info("Pomyślnie zalogowano do Garmina przy użyciu zapisanego tokena sesji.")
        return client
    except Exception as e_token:
        logger.info(f"Logowanie z tokena nie powiodło się ({e_token}). Próba pełnego logowania danymi...")
        try:
            client = Garmin(email, password)
            client.login(tokenstore_dir)
            logger.info("Pomyślnie zalogowano pełnymi danymi i zapisano nowe tokeny sesji.")
            return client
        except Exception as e_login:
            logger.error(f"Błąd logowania do Garmin Connect: {e_login}")
            sys.exit(1)


def fetch_garmin_data_daily(client, target_date):
    """Pobiera dane z Garmina dla trybu dziennego (daily)."""
    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()

    logger.info(f"Pobieranie danych z Garmina (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    data = {
        'today': {},
        'yesterday': {}
    }

    # ==================== DZISIAJ ====================
    try:
        data['today']['sleep'] = client.get_sleep_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać danych snu z dzisiaj: {e}")

    try:
        data['today']['rhr'] = client.get_rhr_day(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać RHR z dzisiaj: {e}")

    try:
        data['today']['rhr_history'] = client.get_heart_rates(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać tętna i średniej 7-dniowej: {e}")

    try:
        data['today']['hrv'] = client.get_hrv_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać HRV z dzisiaj: {e}")

    try:
        data['today']['body_battery'] = client.get_body_battery(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać Body Battery z dzisiaj: {e}")

    try:
        data['today']['stress'] = client.get_stress_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszego stresu: {e}")

    try:
        data['today']['stats'] = client.get_user_summary(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszego bilansu kroków: {e}")

    try:
        today_acts = client.get_activities_by_date(today_str, today_str)
        data['today']['activities'] = _enrich_activities(client, today_acts)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszych aktywności: {e}")

    # ==================== WCZORAJ (KONTEKST HISTORYCZNY) ====================
    try:
        data['yesterday']['stress'] = client.get_stress_data(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego stresu: {e}")

    try:
        data['yesterday']['stats'] = client.get_user_summary(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego bilansu kroków: {e}")

    try:
        acts = client.get_activities_by_date(yesterday_str, yesterday_str)
        data['yesterday']['activities'] = _enrich_activities(client, acts)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszych aktywności: {e}")

    return data


def fetch_garmin_data_yesterday(client, target_date):
    """Pobiera dane z Garmina dla trybu wczorajszego (yesterday)."""
    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()
    dby_date = yesterday_date - datetime.timedelta(days=1)
    dby_str = dby_date.isoformat()

    logger.info(f"Pobieranie danych z Garmina dla trybu 'yesterday' (Przedwczoraj: {dby_str}, Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    data = {
        'yesterday': {},
        'today': {},
        'overnight_recovery': {},
        'day_before_yesterday': {}
    }

    # 1. Wczoraj (Audytowany dzień): aktywności, kroki, stres, body battery pod koniec dnia
    try:
        data['yesterday']['stress'] = client.get_stress_data(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego stresu: {e}")

    try:
        data['yesterday']['stats'] = client.get_user_summary(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego bilansu kroków: {e}")

    try:
        data['yesterday']['body_battery'] = client.get_body_battery(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego Body Battery: {e}")

    try:
        yesterday_acts = client.get_activities_by_date(yesterday_str, yesterday_str)
        data['yesterday']['activities'] = _enrich_activities(client, yesterday_acts)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszych aktywności: {e}")

    # 2. Miniona noc / Dzisiaj (Odbudowa nocna i gotowość na dziś)
    try:
        data['today']['sleep'] = client.get_sleep_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać danych snu z nocy: {e}")

    try:
        data['today']['rhr'] = client.get_rhr_day(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać RHR: {e}")

    try:
        data['today']['rhr_history'] = client.get_heart_rates(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać tętna i średniej 7-dniowej: {e}")

    try:
        data['today']['hrv'] = client.get_hrv_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać HRV z nocy: {e}")

    try:
        data['today']['body_battery'] = client.get_body_battery(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać porannego Body Battery: {e}")

    data['overnight_recovery'] = data['today']

    # 3. Przedwczoraj (Tło historyczne)
    try:
        data['day_before_yesterday']['stress'] = client.get_stress_data(dby_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać stresu z dnia przedwczorajszego: {e}")

    try:
        data['day_before_yesterday']['stats'] = client.get_user_summary(dby_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać bilansu kroków z dnia przedwczorajszego: {e}")

    try:
        dby_acts = client.get_activities_by_date(dby_str, dby_str)
        data['day_before_yesterday']['activities'] = _enrich_activities(client, dby_acts)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać aktywności z dnia przedwczorajszego: {e}")

    return data


# ==================== POMOCNICZE PARSERY BIOMETRII GARMINA ====================

def _parse_hrv_summary(hrv_raw):
    """Parsuje status i średnie wartości HRV z surowych danych Garmina."""
    if not hrv_raw:
        return NO_DATA
    hrv_summary = hrv_raw.get('hrvSummary', {})
    status = hrv_summary.get('status') or NO_DATA
    last_night = hrv_summary.get('lastNightAvg')
    weekly_avg = hrv_summary.get('weeklyAvg')
    baseline_info = hrv_summary.get('baseline', {})
    b_low = baseline_info.get('balancedLow')
    b_high = baseline_info.get('balancedUpper')

    last_night_str = f"{last_night} ms" if last_night is not None else NO_DATA
    weekly_avg_str = f"{weekly_avg} ms" if weekly_avg is not None else NO_DATA
    baseline_str = f"{b_low}–{b_high} ms" if b_low and b_high else NO_DATA

    return f"{status} {last_night_str} (Średnia 7-dniowa: {weekly_avg_str}, Norma bazowa: {baseline_str})"


def _parse_rhr_and_sleep(rhr_raw, rhr_hist, sleep_raw):
    """
    Parsuje tętno spoczynkowe RHR oraz dane snu (score, fazy głęboka/REM, wnioski).
    Zwraca słownik z polami: rhr, sleep_score, deep_sleep, rem_sleep, sleep_insights.
    """
    result = {
        "rhr": NO_DATA,
        "sleep_score": NO_DATA,
        "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA,
        "sleep_insights": NO_DATA
    }

    rhr_str = NO_DATA
    if rhr_raw:
        try:
            rhr_list = rhr_raw.get('allMetrics', {}).get('metricsMap', {}).get('WELLNESS_RESTING_HEART_RATE', [])
            if rhr_list and len(rhr_list) > 0:
                today_val = rhr_list[0].get('value')
                if today_val is not None:
                    today_rhr = int(today_val)
                    avg_7d_str = ""
                    if rhr_hist:
                        avg_7d = rhr_hist.get('lastSevenDaysAvgRestingHeartRate')
                        if avg_7d is not None:
                            diff = today_rhr - int(avg_7d)
                            diff_sign = f"+{diff}" if diff > 0 else f"{diff}"
                            avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {diff_sign} bpm)"
                    rhr_str = f"{today_rhr} bpm{avg_7d_str}"
        except Exception:
            pass

    avg_night_hr = None
    if sleep_raw and 'dailySleepDTO' in sleep_raw:
        sleep_dto = sleep_raw['dailySleepDTO']
        avg_hr_val = sleep_dto.get('avgHeartRate')
        if avg_hr_val:
            avg_night_hr = f"{int(avg_hr_val)} bpm"

        score = sleep_dto.get('sleepScores', {}).get('overall', {}).get('value')
        result['sleep_score'] = f"{score}/100" if score is not None else NO_DATA

        deep_secs = sleep_dto.get('deepSleepSeconds')
        if deep_secs is not None:
            result['deep_sleep'] = f"{deep_secs // 3600}h {(deep_secs % 3600) // 60}m"

        rem_secs = sleep_dto.get('remSleepSeconds')
        if rem_secs is not None:
            result['rem_sleep'] = f"{rem_secs // 3600}h {(rem_secs % 3600) // 60}m"

        feedback = sleep_dto.get('sleepScoreFeedback')
        insight = sleep_dto.get('sleepScoreInsight')
        insights_list = [i for i in [feedback, insight] if i]
        if insights_list:
            result['sleep_insights'] = ", ".join(insights_list)

    if avg_night_hr:
        result['rhr'] = f"{rhr_str} (Średnie tętno z całej nocy: {avg_night_hr})"
    else:
        result['rhr'] = rhr_str

    return result


def _parse_body_battery_values(bb_raw):
    """Ekstrahuje wartości liczbowe z tablicy bodyBatteryValuesArray."""
    if not bb_raw:
        return []
    bb_entry = bb_raw[0] if isinstance(bb_raw, list) and bb_raw else (bb_raw if isinstance(bb_raw, dict) else None)
    if not bb_entry:
        return []
    bb_values = bb_entry.get('bodyBatteryValuesArray', [])
    return [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]


def _parse_steps_info(stats_raw, include_active_kcal=True):
    """Parsuje kroki i opcjonalnie aktywne kalorie."""
    if not stats_raw:
        return NO_DATA
    steps = stats_raw.get('totalSteps')
    if steps is None:
        return NO_DATA
    cals = stats_raw.get('activeKilocalories') if include_active_kcal else None
    cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
    return f"{steps} kroków{cals_str}"


def _parse_stress_info(stress_raw, include_qualifier=True):
    """Parsuje poziom stresu i opcjonalnie kwalifikator słowny."""
    if not stress_raw:
        return NO_DATA
    s_level = stress_raw.get('avgStressLevel')
    if s_level is None or s_level == -1:
        return NO_DATA
    qual = stress_raw.get('stressQualifier') if include_qualifier else None
    qual_str = f" ({qual})" if qual else ""
    return f"Średni poziom stresu: {s_level}/100{qual_str}"


def _format_historical_activities_text(activities_list):
    """Formatuje listę aktywności z poprzedniego dnia jako zwarty tekst poglądowy."""
    if not activities_list:
        return "Brak aktywności (dzień wolny)"

    acts_sorted = sorted(
        activities_list,
        key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
    )
    acts_texts = []
    for idx, act in enumerate(acts_sorted):
        act_details = parse_activity_biomechanics(act)
        if not act_details:
            continue
        splits_text = ""
        if act_details.get('splits'):
            splits_text = "\n    * Splity kilometrowe:\n\n" + "\n".join(act_details['splits'])

        time_info = f" [Start: {act_details['start_time']}]" if act_details.get('start_time') and act_details['start_time'] != NO_DATA else ""
        act_entry = (
            f"  [Jednostka {idx + 1}{time_info}]: {act_details['name']} ({act_details['distance']} w {act_details['duration']}, tempo {act_details['pace']})\n"
            f"    * Pogoda/Warunki: {act_details.get('weather', NO_DATA)}\n"
            f"    * Tętno: Średnie {act_details['avg_hr']} | Maksymalne {act_details['max_hr']}\n"
            f"    * Biomechanika: Średnia kadencja {act_details['avg_cadence']}, krok {act_details['stride_length']}, kontakt {act_details['ground_contact_time']}, odchylenie {act_details['vertical_oscillation']}\n"
            f"    * Obciążenie: Aerobic TE: {act_details['aerobic_te']}, Anaerobic TE: {act_details['anaerobic_te']}, Średnia moc: {act_details['avg_power']}"
            f"{splits_text}"
        )
        acts_texts.append(act_entry)

    return "\n\n".join(acts_texts) if acts_texts else "Brak aktywności (dzień wolny)"


def parse_garmin_data(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina dla trybu 'daily'.
    """
    parsed = {
        "hrv_status": NO_DATA,
        "rhr": NO_DATA,
        "sleep_score": NO_DATA,
        "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA,
        "sleep_insights": NO_DATA,
        "body_battery": NO_DATA,
        "today_steps": NO_DATA,
        "today_stress": NO_DATA,
        "yesterday_training": "Brak aktywności (dzień wolny)",
        "yesterday_steps": NO_DATA,
        "yesterday_stress": NO_DATA
    }

    if not data:
        return parsed

    today_data = data.get('today', {})
    yesterday_data = data.get('yesterday', {})

    # Poranek / miniona noc
    parsed['hrv_status'] = _parse_hrv_summary(today_data.get('hrv'))
    parsed.update(_parse_rhr_and_sleep(today_data.get('rhr'), today_data.get('rhr_history'), today_data.get('sleep')))

    # Body Battery w ciągu dnia
    bb_vals = _parse_body_battery_values(today_data.get('body_battery'))
    if bb_vals:
        current_bb = bb_vals[-1]
        max_bb = max(bb_vals)
        drain = max_bb - current_bb
        drain_str = f", spadek w ciągu dnia: -{drain}" if drain > 0 else ""
        parsed['body_battery'] = f"Aktualnie wieczorem: {current_bb}/100 (Maksymalnie po nocy: {max_bb}/100{drain_str})"

    # Koszt dzisiejszego dnia
    parsed['today_steps'] = _parse_steps_info(today_data.get('stats'), include_active_kcal=True)
    parsed['today_stress'] = _parse_stress_info(today_data.get('stress'), include_qualifier=True)

    # Wczorajsze tło historyczne
    parsed['yesterday_training'] = _format_historical_activities_text(yesterday_data.get('activities', []))
    parsed['yesterday_steps'] = _parse_steps_info(yesterday_data.get('stats'), include_active_kcal=False)
    parsed['yesterday_stress'] = _parse_stress_info(yesterday_data.get('stress'), include_qualifier=False)

    return parsed


def parse_garmin_data_yesterday(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina dla trybu 'yesterday':
    - Audytowany dzień wczorajszy: kroki, stres, Body Battery pod koniec dnia.
    - Miniona noc / dzisiejszy poranek: HRV, RHR, sen (jakość, fazy, uwagi), poranne Body Battery.
    - Kontekst dnia przedwczorajszego: aktywności, kroki, stres.
    """
    parsed = {
        "hrv_status": NO_DATA,
        "rhr": NO_DATA,
        "sleep_score": NO_DATA,
        "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA,
        "sleep_insights": NO_DATA,
        "morning_body_battery": NO_DATA,
        "yesterday_steps": NO_DATA,
        "yesterday_stress": NO_DATA,
        "yesterday_body_battery": NO_DATA,
        "day_before_yesterday_training": "Brak aktywności (dzień wolny)"
    }

    if not data:
        return parsed

    recovery_data = data.get('overnight_recovery') or data.get('today', {})
    yesterday_data = data.get('yesterday', {})
    dby_data = data.get('day_before_yesterday', {})

    # Miniona noc i poranek
    parsed['hrv_status'] = _parse_hrv_summary(recovery_data.get('hrv'))
    parsed.update(_parse_rhr_and_sleep(recovery_data.get('rhr'), recovery_data.get('rhr_history'), recovery_data.get('sleep')))

    # Poranne Body Battery
    bb_rec_vals = _parse_body_battery_values(recovery_data.get('body_battery'))
    if bb_rec_vals:
        latest_bb = bb_rec_vals[-1]
        max_bb = max(bb_rec_vals)
        parsed['morning_body_battery'] = f"{latest_bb}/100 (Szczyt poranny po nocy: {max_bb}/100)"

    # Koszt wczorajszego dnia (audyt)
    parsed['yesterday_steps'] = _parse_steps_info(yesterday_data.get('stats'), include_active_kcal=True)
    parsed['yesterday_stress'] = _parse_stress_info(yesterday_data.get('stress'), include_qualifier=True)

    bb_y_vals = _parse_body_battery_values(yesterday_data.get('body_battery'))
    if bb_y_vals:
        evening_bb = bb_y_vals[-1]
        max_bb = max(bb_y_vals)
        min_bb = min(bb_y_vals)
        drain = max_bb - evening_bb
        drain_str = f", spadek w ciągu dnia: -{drain}" if drain > 0 else ""
        parsed['yesterday_body_battery'] = f"Pod koniec dnia: {evening_bb}/100 (Max w ciągu dnia: {max_bb}/100, min: {min_bb}/100{drain_str})"

    # Kontekst dnia przedwczorajszego
    parsed['day_before_yesterday_training'] = _format_historical_activities_text(dby_data.get('activities', []))

    return parsed


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


def load_user_note(note_file=None):
    """
    Wczytuje opcjonalną notatkę użytkownika do trenera z folderu prompts/ (lub input/).
    """
    if note_file is None:
        note_file = os.path.join(PROMPTS_DIR, "user_note.md")

    if not os.path.exists(note_file):
        alt_file = os.path.join(INPUT_DIR, "user_note.md")
        if os.path.exists(alt_file):
            note_file = alt_file
        else:
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
        if not os.path.exists(note_file):
            alt_file = os.path.join(INPUT_DIR, "user_note.md")
            if os.path.exists(alt_file):
                note_file = alt_file

    try:
        if os.path.exists(note_file):
            with open(note_file, "w", encoding="utf-8") as f:
                f.write("# Notatki i uwagi do trenera Gemini (wpisz swoje uwagi poniżej, linie z # są ignorowane)\n")
            logger.info(f"Wyczyszczono plik notatki użytkownika: {note_file}")
    except Exception as e:
        logger.warning(f"Nie udało się wyczyścić pliku notatki {note_file}: {e}")


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
    Wczytuje bazę własnych zestawów siłowych biegacza (FBW, UPPER, LOWER) z pliku Markdown.
    Domyślnie szuka w input/strength_routines.md, z fallbackiem do prompts/strength_routines.md.
    """
    if file_path is None:
        file_path = os.path.join(INPUT_DIR, "strength_routines.md")

    if not os.path.exists(file_path):
        alt_path = os.path.join(PROMPTS_DIR, "strength_routines.md")
        if os.path.exists(alt_path):
            file_path = alt_path
        else:
            logger.warning(f"Nie znaleziono pliku z zestawami siłowymi: {file_path}")
            return "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content if content else "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."
    except Exception as e:
        logger.warning(f"Nie udało się odczytać pliku {file_path}: {e}")
        return "Brak zdefiniowanych zestawów siłowych w pliku input/strength_routines.md."


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


def _extract_exercise_tables(text):
    """
    Wyszukuje i wyciąga tabele Markdown zawierające ćwiczenia biegowe (serie, powtórzenia)
    oraz siłowe (zestawienie ćwiczeń, ciężary, serie, powtórzenia).
    """
    lines = text.split("\n")
    raw_tables = []
    current_table = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:]:
            current_table.append(stripped)
        else:
            if current_table:
                if len(current_table) >= 2 and any("---" in row for row in current_table):
                    raw_tables.append(current_table)
                current_table = []
    if current_table:
        if len(current_table) >= 2 and any("---" in row for row in current_table):
            raw_tables.append(current_table)

    exercise_tables = []
    for tbl in raw_tables:
        header = tbl[0].lower()
        is_strength = any(k in header for k in ["ćwiczen", "obciążen", "rpe", "łańcuch", "partia", "ruch", "exercise", "weight"])
        is_running = any(k in header for k in ["powtórzen", "seria", "akcent", "odcinek", "reps", "series", "intervals", "laps"])
        if is_strength or is_running:
            exercise_tables.append("\n".join(tbl))

    return exercise_tables


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


def generate_weekly_plan_prompt(days_preferences, training_context, history_context=None, user_note=None, strength_routines=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA TRENINGÓW (ARCHIWUM Z OSTATNICH 6 TYGODNI / 42 DNI):
{history_context}
"""

    note_section = ""
    if user_note:
        note_section = f"""
====================
DODATKOWE UWAGI I WIADOMOŚĆ OD BIEGACZA:
{user_note}
"""

    routines_section = strength_routines if strength_routines else "Brak zdefiniowanych zestawów siłowych (zawodnik nie podał rozpiski)."

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


def generate_weekly_suggestions_prompt(training_context, history_context=None, user_note=None):
    """
    Tworzy prompt dla Gemini w trybie 'suggest' bez przesyłania biometrii z Garmina.
    Model proponuje typy/cele treningów na podstawie profilu biegacza, historii z ostatnich 42 dni i notatki.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA TRENINGÓW (ARCHIWUM Z OSTATNICH 6 TYGODNI / 42 DNI):
{history_context}
"""

    note_section = ""
    if user_note:
        note_section = f"""
====================
DODATKOWE UWAGI I WIADOMOŚĆ OD BIEGACZA:
{user_note}
"""

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


def parse_activity_biomechanics(activity):
    """
    Wyciąga szczegółowe parametry biomechaniczne i fizjologiczne z konkretnego biegu.
    Oblicza średnie tempo z prędkości (m/s), jeśli Garmin nie udostępnia gotowego pola tempa.
    Jeśli parametrów brak, wstawia 'Brak danych'.
    """
    if not activity:
        return None

    raw_dist = activity.get('distance')
    dist_km = (raw_dist / 1000) if raw_dist is not None and raw_dist > 0 else 0
    dist_str = f"{dist_km:.2f} km" if dist_km > 0 else "Brak danych"

    raw_dur = activity.get('duration')
    duration_min = (raw_dur / 60) if raw_dur is not None and raw_dur > 0 else 0
    duration_str = f"{duration_min:.1f} min" if duration_min > 0 else "Brak danych"

    # Średnie tempo: sprawdzamy bezpośrednie pole lub obliczamy z averageSpeed (m/s)
    avg_speed_m_s = activity.get('averageSpeed')
    avg_pace_raw = activity.get('averagePace') or activity.get('avgPace')
    pace_str = "Brak danych"

    if avg_pace_raw:
        pace_str = str(avg_pace_raw)
    elif avg_speed_m_s and isinstance(avg_speed_m_s, (int, float)) and avg_speed_m_s > 0:
        pace_sec = 1000 / avg_speed_m_s
        p_min = int(pace_sec // 60)
        p_sec = int(pace_sec % 60)
        pace_str = f"{p_min}:{p_sec:02d} min/km"

    start_time_raw = activity.get('startTimeLocal', '')
    start_time_str = "Brak danych"
    if start_time_raw and len(start_time_raw) >= 16:
        start_time_str = start_time_raw[11:16]
    elif start_time_raw:
        start_time_str = start_time_raw

    # Tętno
    avg_hr_val = activity.get('averageHR')
    avg_hr_str = f"{int(round(avg_hr_val))} bpm" if isinstance(avg_hr_val, (int, float)) else "Brak danych"

    max_hr_val = activity.get('maxHR')
    max_hr_str = f"{int(round(max_hr_val))} bpm" if isinstance(max_hr_val, (int, float)) else "Brak danych"

    # Kadencja
    raw_cad = activity.get('averageRunningCadenceInStepsPerMinute') or activity.get('averageRunCadence')
    avg_cadence_str = f"{int(round(raw_cad))} spm" if raw_cad is not None else "Brak danych"

    raw_max_cad = activity.get('maxRunningCadenceInStepsPerMinute') or activity.get('maxRunCadence')
    max_cadence_str = f"{int(round(raw_max_cad))} spm" if raw_max_cad is not None else "Brak danych"

    # Długość kroku
    sl = activity.get('avgStrideLength')
    stride_str = f"{sl / 100:.2f} m" if sl is not None and sl > 0 else "Brak danych"

    # Czas kontaktu z podłożem i oscylacje
    gct = activity.get('avgGroundContactTime')
    gct_str = f"{gct:.1f} ms" if isinstance(gct, (int, float)) else "Brak danych"

    vo = activity.get('avgVerticalOscillation')
    vo_str = f"{vo:.2f} cm" if isinstance(vo, (int, float)) else "Brak danych"

    vr = activity.get('avgVerticalRatio')
    vr_str = f"{vr:.2f} %" if isinstance(vr, (int, float)) else "Brak danych"

    # Przewyższenia
    eg = activity.get('elevationGain')
    elevation_gain_str = f"{int(round(eg))} m" if eg is not None else "Brak danych"

    el = activity.get('elevationLoss')
    elevation_loss_str = f"{int(round(el))} m" if el is not None else "Brak danych"

    # Obciążenie treningowe
    ate = activity.get('aerobicTrainingEffect')
    label = activity.get('trainingEffectLabel', '')
    label_str = f" ({label})" if label else ""
    aerobic_te_str = f"{ate:.1f}/5.0{label_str}" if isinstance(ate, (int, float)) else "Brak danych"

    ante = activity.get('anaerobicTrainingEffect')
    anaerobic_te_str = f"{ante:.1f}/5.0" if isinstance(ante, (int, float)) else "Brak danych"

    pwr = activity.get('avgPower')
    power_str = f"{int(round(pwr))} W" if isinstance(pwr, (int, float)) else "Brak danych"

    res = {
        "name": activity.get('activityName', 'Bieg'),
        "start_time": start_time_str,
        "distance": dist_str,
        "duration": duration_str,
        "pace": pace_str,
        "avg_hr": avg_hr_str,
        "max_hr": max_hr_str,
        "avg_cadence": avg_cadence_str,
        "max_cadence": max_cadence_str,
        "stride_length": stride_str,
        "ground_contact_time": gct_str,
        "vertical_oscillation": vo_str,
        "vertical_ratio": vr_str,
        "elevation_gain": elevation_gain_str,
        "elevation_loss": elevation_loss_str,
        "aerobic_te": aerobic_te_str,
        "anaerobic_te": anaerobic_te_str,
        "avg_power": power_str,
        "splits": [],
        "weather": NO_DATA
    }

    # --- Pogoda i warunki atmosferyczne ---
    weather_info = activity.get('weather_data')
    if weather_info and isinstance(weather_info, dict):
        temp_c = weather_info.get('temperature')
        feels_c = weather_info.get('apparentTemperature')
        wind_kmh = weather_info.get('windSpeed')
        wind_dir = weather_info.get('windDirectionCompassPoint', '')
        humidity = weather_info.get('relativeHumidity')
        weather_desc = weather_info.get('weatherType', {}).get('weatherTypeKey', '') if isinstance(weather_info.get('weatherType'), dict) else ''

        parts = []
        if temp_c is not None:
            parts.append(f"Temperatura: {temp_c:.1f}°C" + (f" (odczuwalna: {feels_c:.1f}°C)" if feels_c is not None else ""))
        if wind_kmh is not None:
            parts.append(f"Wiatr: {wind_kmh:.1f} km/h {wind_dir}".strip())
        if humidity is not None:
            parts.append(f"Wilgotność: {humidity}%")
        if weather_desc:
            parts.append(f"Warunki: {weather_desc}")
        if parts:
            res["weather"] = " | ".join(parts)
    elif activity.get('minTemperature') is not None or activity.get('maxTemperature') is not None:
        min_t = activity.get('minTemperature')
        max_t = activity.get('maxTemperature')
        avg_t = round((min_t + max_t) / 2) if min_t is not None and max_t is not None else (min_t or max_t)
        res["weather"] = f"Temperatura z czujnika zegarka: śr. ok. {avg_t}°C (min: {min_t}°C, max: {max_t}°C)"

    # --- Splity kilometrowe ---
    splits_raw = activity.get('splits_data')
    parsed_splits = []
    if splits_raw and isinstance(splits_raw, dict):
        lap_list = splits_raw.get('lapDTOs', [])
        if lap_list:
            parsed_splits.append("| Km | Dystans | Czas | Tempo | GAP | Tętno (śr/max) | Kadencja | Krok | GCT | Odchylenie | Moc | Wznios/Spadek |")
            parsed_splits.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

            cumulative_time_sec = 0.0

            for idx, lap in enumerate(lap_list):
                lap_num = idx + 1
                lap_dist = lap.get('distance', 0) / 1000
                lap_dur = lap.get('duration', 0)
                cumulative_time_sec += lap_dur

                dur_m, dur_s = int(lap_dur // 60), int(lap_dur % 60)
                dur_str = f"{dur_m}:{dur_s:02d}"

                lap_speed = lap.get('averageSpeed', 0)
                lap_pace = f"{int((1000/lap_speed)//60)}:{int((1000/lap_speed)%60):02d} min/km" if lap_speed > 0 else "Brak danych"

                gap_speed = lap.get('avgGradeAdjustedSpeed', 0)
                gap_pace = f"{int((1000/gap_speed)//60)}:{int((1000/gap_speed)%60):02d} min/km" if gap_speed > 0 else "Brak danych"

                if lap.get('averageHR') is not None and lap.get('maxHR') is not None:
                    hr_str = f"{int(lap['averageHR'])} / {int(lap['maxHR'])} bpm"
                elif lap.get('averageHR') is not None:
                    hr_str = f"{int(lap['averageHR'])} bpm"
                elif lap.get('maxHR') is not None:
                    hr_str = f"max {int(lap['maxHR'])} bpm"
                else:
                    hr_str = "Brak danych"

                ascent = f"+{int(lap['elevationGain'])}m" if lap.get('elevationGain') is not None else "+0m"
                descent = f"-{int(lap['elevationLoss'])}m" if lap.get('elevationLoss') is not None else "-0m"
                elev_str = f"{ascent} / {descent}"

                avg_pwr = f"{int(lap['averagePower'])} W" if lap.get('averagePower') is not None else "Brak danych"

                raw_cad_lap = lap.get('averageRunCadence') or lap.get('averageRunningCadenceInStepsPerMinute')
                avg_cad = f"{int(round(raw_cad_lap))} spm" if raw_cad_lap is not None else "Brak danych"

                gct_lap = f"{lap['groundContactTime']:.1f} ms" if lap.get('groundContactTime') is not None else "Brak danych"
                stride_lap = f"{lap['strideLength']/100:.2f} m" if lap.get('strideLength') is not None else "Brak danych"
                vert_osc_lap = f"{lap['verticalOscillation']:.2f} cm" if lap.get('verticalOscillation') is not None else "Brak danych"

                split_row = (
                    f"| {lap_num} | {lap_dist:.2f} km | {dur_str} | {lap_pace} | {gap_pace} | "
                    f"{hr_str} | {avg_cad} | {stride_lap} | {gct_lap} | {vert_osc_lap} | "
                    f"{avg_pwr} | {elev_str} |"
                )
                parsed_splits.append(split_row)

    res["splits"] = parsed_splits
    return res


# ==================== POMOCNICZE GENERATORY I ZAPIS RAPORTÓW ====================

def _format_activity_section(activity_stats, date_str):
    """Formatuje blok Markdown z listą jednostek treningowych i biomechaniką dla promptu."""
    if not activity_stats:
        return f"W dniu {date_str} nie odnotowano treningu biegowego (Dzień wolny / Regeneracja)."

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

    return "\n\n" + "-"*35 + "\n\n".join(act_blocks)


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


def process_and_display_activities(raw_acts, date_str):
    """
    Sortuje chronologicznie pobrane aktywności, parsuje ich metryki biomechaniczne
    oraz wyświetla czytelne podsumowanie w konsoli.
    Zwraca krotkę: (posortowane_surowe_aktywności, lista_przeparsowanych_statystyk).
    """
    sorted_acts = sorted(
        raw_acts or [],
        key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
    )
    parsed_stats = []
    for act in sorted_acts:
        st = parse_activity_biomechanics(act)
        if st:
            parsed_stats.append(st)

    if parsed_stats:
        print("\n" + "="*50)
        print(f"📊 POBRANO AKTYWNOŚCI DO AUDYTU ({len(parsed_stats)} jednostek w dniu {date_str}):")
        print("="*50)
        for idx, act_st in enumerate(parsed_stats):
            time_str = f" [Start: {act_st['start_time']}]" if act_st.get('start_time') and act_st['start_time'] != NO_DATA else ""
            prefix = f"Jednostka {idx + 1}{time_str}: " if len(parsed_stats) > 1 else ""
            print(f"\n▶️ {prefix}{act_st['name']} ({act_st['distance']}, tempo: {act_st['pace']})")
            for k, v in act_st.items():
                if k not in ['splits', 'name', 'distance', 'pace', 'start_time']:
                    print(f"   - {k}: {v}")

    return sorted_acts, parsed_stats


def determine_workout_date(default_date, acts, stats):
    """
    Ustala datę wykonania treningu na podstawie pierwszej aktywności lub zwraca datę domyślną.
    """
    if stats and acts:
        first_raw_act = acts[0]
        act_start = first_raw_act.get('startTimeLocal', '')
        if len(act_start) >= 10:
            return act_start[:10]
    return default_date.isoformat()


def save_daily_report(workout_date, archive_content, history_dir=HISTORY_DIR, output_dir=OUTPUT_DIR):
    """Zapisuje wygenerowany raport trenera do pliku historii oraz do bieżącego raportu."""
    history_file_path = os.path.join(history_dir, f"{workout_date}.md")
    latest_daily_file = os.path.join(output_dir, "last_daily_report.md")

    with open(history_file_path, "w", encoding="utf-8") as hf:
        hf.write(archive_content)
    logger.info(f"Raport z dnia {workout_date} zapisano do archiwum: {history_file_path}")

    with open(latest_daily_file, "w", encoding="utf-8") as lf:
        lf.write(archive_content)
    logger.info(f"Bieżący wynik zapisano do pliku: {latest_daily_file}")
    print(f"\n✅ Zapisano raport do: {latest_daily_file} oraz archiwum {history_file_path}")


def load_or_fetch_garmin_data(target_date, dump_file, mode="daily"):
    """Wczytuje dane z pliku lokalnego lub pobiera je bezpośrednio z Garmin Connect."""
    use_local_data = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]
    if use_local_data:
        logger.info(f"Omijam logowanie. Wczytuję surowe dane z pliku lokalnego: {dump_file}...")
        try:
            with open(dump_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Nie znaleziono pliku {dump_file}. Uruchom skrypt z USE_LOCAL_DATA='False', aby go stworzyć!")
            sys.exit(1)

    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    if not garmin_email or not garmin_password:
        logger.error("Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD w pliku .env!")
        sys.exit(1)

    client = get_garmin_client(garmin_email, garmin_password)
    if mode == "yesterday":
        raw_data = fetch_garmin_data_yesterday(client, target_date)
    else:
        raw_data = fetch_garmin_data_daily(client, target_date)

    with open(dump_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=4, ensure_ascii=False)
    logger.info(f"Surowe dane zapisano pomyślnie do pliku {dump_file}.")
    return raw_data


def generate_verification_prompt(planned_workout, activity_stats, garmin_stats, weekly_plan_context,
                                 user_profile, user_note, today_date_str, yesterday_date_str,
                                 tomorrow_date_str, trening_z_planu):
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
    activity_section = _format_activity_section(activity_stats, today_date_str)

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
                                          day_before_yesterday_date_str, trening_z_planu):
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
    activity_section = _format_activity_section(activity_stats, yesterday_date_str)

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


def run_suggest_mode(client, training_context, history_context, user_note, preferences_file, debug=False, models=None):
    """Tryb 1: Generowanie sugestii typów treningów na tydzień."""
    print("\n" + "="*60)
    print("💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡")
    print("="*60)
    print("Model analizuje historię ostatnich 42 dni, fazę i cele, aby zaproponować podział jednostek.")

    suggest_prompt = generate_weekly_suggestions_prompt(
        training_context=training_context,
        history_context=history_context,
        user_note=user_note
    )

    models_info = f" (Kaskada: {', '.join(models)})" if models else ""
    print("\n" + "="*50)
    print(f"WYSYŁANIE ZAPYTANIA DO GEMINI{models_info}...")
    print("="*50)

    try:
        response, used_model = send_gemini_prompt_with_fallback(client, suggest_prompt, models=models, debug=debug)

        print("\n💡 PROPONOWANY PODZIAŁ TYPÓW TRENINGU NA TEN TYDZIEŃ 💡\n")
        print(response.text)

        with open(preferences_file, "w", encoding="utf-8") as pf:
            pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii treningowej i profilu\n")
            pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python garmin_coach.py week'\n\n")
            pf.write(response.text)

        logger.info(f"Sugestie typów treningów zapisano do pliku: {preferences_file}")
        print(f"\n✅ Zapisano propozycję do pliku: {preferences_file}")
        print(f"👉 Jeśli chcesz coś zmienić, wyedytuj '{preferences_file}', a następnie uruchom:")
        print("   python garmin_coach.py week")
    except Exception as e:
        logger.error(f"Wystąpił błąd podczas generowania sugestii: {e}")
        sys.exit(1)


def run_week_mode(client, training_context, history_context, user_note, preferences_file, weekly_plan_file, strength_routines_file, debug=False, models=None):
    """Tryb 2: Planowanie całego tygodnia treningowego."""
    print("\n" + "="*60)
    print("🗓️  TRYB PLANOWANIA TYGODNIOWEGO (GEMINI COACH) 🗓️")
    print("="*60)

    if not os.path.exists(preferences_file):
        print(f"⚠️  Nie znaleziono pliku '{preferences_file}'!")
        print("👉 Wskazówka: Możesz wygenerować sugestię za pomocą polecenia:")
        print("   python garmin_coach.py suggest")
        print("   lub utworzyć plik ręcznie, wpisując np.:\nWtorek: Easy\nCzwartek: Tempo progowe\nSobota: Long run\n")

        with open(preferences_file, "w", encoding="utf-8") as pf:
            pf.write("# Wpisz w jakie dni jaki typ treningu chcesz wykonać, np.:\n")
            pf.write("# Wtorek: Easy + przebieżki\n# Czwartek: Tempo progowe\n# Sobota: Długie wybieganie\n")
        print(f"Utworzono pusty plik '{preferences_file}'. Uzupełnij go lub uruchom 'python garmin_coach.py suggest'.")
        sys.exit(0)

    with open(preferences_file, "r", encoding="utf-8") as pf:
        raw_lines = pf.readlines()

    valid_lines = [line.strip() for line in raw_lines if line.strip() and not line.strip().startswith("#")]
    days_preferences = "\n".join(valid_lines).strip()

    if not days_preferences:
        print(f"⚠️  Plik '{preferences_file}' nie zawiera zdefiniowanych dni treningowych.")
        print("Wpisz w nim preferencje lub uruchom: python garmin_coach.py suggest")
        sys.exit(0)

    print(f"📄 Wczytano preferencje z pliku {preferences_file}:\n")
    print(days_preferences)
    print("\n" + "-"*40)

    strength_routines = load_strength_routines(strength_routines_file)
    if strength_routines:
        logger.info(f"Wczytano bazę zestawów siłowych z pliku: {strength_routines_file}")

    week_prompt = generate_weekly_plan_prompt(
        days_preferences=days_preferences,
        training_context=training_context,
        history_context=history_context,
        user_note=user_note,
        strength_routines=strength_routines
    )

    models_info = f" (Kaskada: {', '.join(models)})" if models else ""
    print("\n" + "="*50)
    print(f"WYSYŁANIE PLANU DO GEMINI{models_info}...")
    print("="*50)

    try:
        response, used_model = send_gemini_prompt_with_fallback(client, week_prompt, models=models, debug=debug)

        print("\n🏆 ROZPISKA PLANU NA CAŁY TYDZIEŃ OD TRENERA 🏆\n")
        print(response.text)

        with open(weekly_plan_file, "w", encoding="utf-8") as wf:
            wf.write(response.text)
        logger.info(f"Plan tygodniowy został zapisany do pliku: {weekly_plan_file}")
        print(f"\n✅ Zapisano plan do: {weekly_plan_file}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")
    except Exception as e:
        logger.error(f"Wystąpił błąd podczas generowania planu tygodniowego: {e}")
        sys.exit(1)


def run_daily_mode(client, today, dump_file, weekly_plan_file, user_profile, user_note, debug=False, models=None):
    """Tryb 3: Codzienna weryfikacja i adaptacja bieżącego dnia."""
    yesterday = today - datetime.timedelta(days=1)
    tomorrow = today + datetime.timedelta(days=1)

    today_date_str = f"{DAYS_PL[today.weekday()]}, {today.isoformat()}"
    yesterday_date_str = f"{DAYS_PL[yesterday.weekday()]}, {yesterday.isoformat()}"
    tomorrow_date_str = f"{DAYS_PL[tomorrow.weekday()]}, {tomorrow.isoformat()}"

    logger.info(f"Uruchomiono tryb codziennej weryfikacji dla dnia: {today_date_str}...")

    raw_data = load_or_fetch_garmin_data(today, dump_file, mode="daily")

    # 1. Parsujemy dane biometryczne z dzisiejszego dnia i minionej nocy
    garmin_stats = parse_garmin_data(raw_data)

    # 2. Wczytujemy plan tygodniowy, jeśli istnieje
    weekly_plan_content = load_weekly_plan(weekly_plan_file)

    # 3. Parsujemy i wyświetlamy dzisiejsze aktywności
    today_acts, all_today_stats = process_and_display_activities(
        raw_data.get('today', {}).get('activities', []),
        today_date_str
    )

    if all_today_stats:
        planned_workout_desc = (
            f"Założenia na dzień {today_date_str} według załączonego planu tygodniowego. "
            f"W dniu {today_date_str} zarejestrowano łącznie {len(all_today_stats)} jednostek treningowych. "
            f"Odszukaj sekcję odpowiadającą temu dniu w planie tygodniowym i sprawdź zgodność wykonania całości lub poszczególnych etapów."
        )
    else:
        print("\n" + "="*50)
        print(f"🛌 DZIEŃ BEZ BIEGU / REST DAY: {today_date_str}")
        print("="*50)
        print("Dzisiaj nie odnotowano aktywności biegowej.")
        print("Model przeprowadzi audyt regeneracji w dniu wolnym i sprawdzi gotowość na kolejny trening z planu!")

        planned_workout_desc = (
            f"W dniu {today_date_str} NIE BYŁO TRENINGU BIEGOWEGO (Dzień wolny / Rest Day). "
            f"Sprawdź w planie tygodniowym, czy dzień wolny był zaplanowany na {DAYS_PL[today.weekday()]}. "
            f"Skup się na ocenie regeneracji (sen, HRV, RHR, Body Battery, dzisiejsze kroki i stres) oraz adaptacji do treningu na dzień {tomorrow_date_str}."
        )

    trening_z_planu = f"Założenia na dzień {tomorrow_date_str} według planu tygodniowego (sekcja: {DAYS_PL[tomorrow.weekday()]})"

    verification_prompt = generate_verification_prompt(
        planned_workout=planned_workout_desc,
        activity_stats=all_today_stats,
        garmin_stats=garmin_stats,
        weekly_plan_context=weekly_plan_content,
        user_profile=user_profile,
        user_note=user_note,
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        tomorrow_date_str=tomorrow_date_str,
        trening_z_planu=trening_z_planu
    )

    models_info = f" (Kaskada: {', '.join(models)})" if models else ""
    print("\n" + "="*50)
    print(f"WYSYŁANIE RAPORTU DO GEMINI{models_info}...")
    print("="*50)

    try:
        response, used_model = send_gemini_prompt_with_fallback(client, verification_prompt, models=models, debug=debug)

        print(f"\n🏆 RAPORT TRENERSKI I ADAPTACJA NA DZIEŃ {tomorrow_date_str} 🏆\n")
        print(response.text)

        workout_date = determine_workout_date(today, today_acts, all_today_stats)

        if all_today_stats:
            header = f"# TRENING Z DNIA: {workout_date} ({today_date_str})\nLiczba zarejestrowanych jednostek: {len(all_today_stats)}"
            acts_part = f"\n## Zarejestrowane aktywności:\n{chr(10).join(_format_acts_archive_blocks(all_today_stats))}\n"
        else:
            header = f"# DZIEŃ WOLNY / REST DAY: {workout_date} ({today_date_str})\nAktywność: Brak biegu (Regeneracja / Odpoczynek)"
            acts_part = ""

        archive_content = f"""{header}

## Biometria regeneracyjna i bilans dnia ({today_date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Całodzienny stres w dniu {today_date_str}: {garmin_stats.get('today_stress')}
- Kroki w dniu {today_date_str} (cały dzień): {garmin_stats.get('today_steps')}
{acts_part}
## Ocena trenera i adaptacja na dzień {tomorrow_date_str}:
{response.text}
"""
        save_daily_report(workout_date, archive_content)
    except Exception as e:
        logger.error(f"Wystąpił błąd podczas weryfikacji i adaptacji: {e}")
        sys.exit(1)


def run_yesterday_mode(client, today, dump_file, weekly_plan_file, user_profile, user_note, debug=False, models=None):
    """Tryb 4: Zastępcza weryfikacja dnia wczorajszego i adaptacja na dziś."""
    yesterday = today - datetime.timedelta(days=1)
    day_before_yesterday = yesterday - datetime.timedelta(days=1)

    today_date_str = f"{DAYS_PL[today.weekday()]}, {today.isoformat()}"
    yesterday_date_str = f"{DAYS_PL[yesterday.weekday()]}, {yesterday.isoformat()}"
    day_before_yesterday_date_str = f"{DAYS_PL[day_before_yesterday.weekday()]}, {day_before_yesterday.isoformat()}"

    logger.info(f"Uruchomiono tryb weryfikacji wczorajszego dnia ('yesterday') dla audytu: {yesterday_date_str} oraz adaptacji na dziś: {today_date_str}...")

    raw_data = load_or_fetch_garmin_data(today, dump_file, mode="yesterday")

    # 1. Parsujemy dane biometryczne z wczorajszego dnia, minionej nocy i tła historycznego
    garmin_stats = parse_garmin_data_yesterday(raw_data)

    # 2. Wczytujemy plan tygodniowy, jeśli istnieje
    weekly_plan_content = load_weekly_plan(weekly_plan_file)

    # 3. Parsujemy i wyświetlamy wczorajsze aktywności (podlegające audytowi)
    yesterday_acts, all_yesterday_stats = process_and_display_activities(
        raw_data.get('yesterday', {}).get('activities', []),
        yesterday_date_str
    )

    if all_yesterday_stats:
        planned_workout_desc = (
            f"Założenia na dzień wczorajszy ({yesterday_date_str}) według załączonego planu tygodniowego. "
            f"W dniu {yesterday_date_str} zarejestrowano łącznie {len(all_yesterday_stats)} jednostek treningowych. "
            f"Odszukaj sekcję odpowiadającą temu dniu ({DAYS_PL[yesterday.weekday()]}) w planie tygodniowym i sprawdź zgodność wykonania całości lub poszczególnych etapów."
        )
    else:
        print("\n" + "="*50)
        print(f"🛌 DZIEŃ BEZ BIEGU / REST DAY (WCZORAJ): {yesterday_date_str}")
        print("="*50)
        print("Wczoraj nie odnotowano aktywności biegowej.")
        print("Model przeprowadzi audyt regeneracji i obciążenia wczorajszego dnia oraz snu minionej nocy!")

        planned_workout_desc = (
            f"W dniu wczorajszym ({yesterday_date_str}) NIE BYŁO TRENINGU BIEGOWEGO (Dzień wolny / Rest Day). "
            f"Sprawdź w planie tygodniowym, czy dzień wolny był zaplanowany na {DAYS_PL[yesterday.weekday()]}. "
            f"Skup się na ocenie regeneracji (wczorajsze obciążenie, sen z minionej nocy, HRV, RHR, poranne Body Battery) oraz adaptacji do treningu na dzień dzisiejszy ({today_date_str})."
        )

    trening_z_planu = f"Założenia na dzień dzisiejszy ({today_date_str}) według planu tygodniowego (sekcja: {DAYS_PL[today.weekday()]})"

    yesterday_prompt = generate_yesterday_verification_prompt(
        planned_workout=planned_workout_desc,
        activity_stats=all_yesterday_stats,
        garmin_stats=garmin_stats,
        weekly_plan_context=weekly_plan_content,
        user_profile=user_profile,
        user_note=user_note,
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        day_before_yesterday_date_str=day_before_yesterday_date_str,
        trening_z_planu=trening_z_planu
    )

    models_info = f" (Kaskada: {', '.join(models)})" if models else ""
    print("\n" + "="*50)
    print(f"WYSYŁANIE RAPORTU DO GEMINI{models_info}...")
    print("="*50)

    try:
        response, used_model = send_gemini_prompt_with_fallback(client, yesterday_prompt, models=models, debug=debug)

        print(f"\n🏆 RAPORT TRENERSKI (AUDYT DNIA WCZORAJSZEGO) I ADAPTACJA NA DZIŚ ({today_date_str}) 🏆\n")
        print(response.text)

        workout_date = determine_workout_date(yesterday, yesterday_acts, all_yesterday_stats)

        if all_yesterday_stats:
            header = f"# TRENING Z DNIA: {workout_date} ({yesterday_date_str}) [TRYB YESTERDAY]\nLiczba zarejestrowanych jednostek: {len(all_yesterday_stats)}"
            acts_part = f"\n## Zarejestrowane aktywności wczoraj:\n{chr(10).join(_format_acts_archive_blocks(all_yesterday_stats))}\n"
        else:
            header = f"# DZIEŃ WOLNY / REST DAY: {workout_date} ({yesterday_date_str}) [TRYB YESTERDAY]\nAktywność: Brak biegu (Regeneracja / Odpoczynek)"
            acts_part = ""

        archive_content = f"""{header}

## Bilans wczorajszego dnia ({yesterday_date_str}):
- Wczorajsze kroki: {garmin_stats.get('yesterday_steps')}
- Średni stres wczoraj: {garmin_stats.get('yesterday_stress')}
- Body Battery pod koniec wczorajszego dnia: {garmin_stats.get('yesterday_body_battery')}

## Biometria regeneracyjna z minionej nocy (sen przed dniem {today_date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Poranne Body Battery na start dnia {today_date_str}: {garmin_stats.get('morning_body_battery')}
{acts_part}
## Ocena trenera i adaptacja na dzień dzisiejszy ({today_date_str}):
{response.text}
"""
        save_daily_report(workout_date, archive_content)
    except Exception as e:
        logger.error(f"Wystąpił błąd podczas weryfikacji i adaptacji: {e}")
        sys.exit(1)

def check_mode_compatibility(raw_mode):
    '''
    Sprawdza czy przekazany tryb zgadza się z dostępnymi.
    '''
    mode = (raw_mode or "daily").lower()
    if mode not in ["daily", "yesterday", "week", "suggest"]:
        logger.error(
            f"Nieprawidłowy tryb działania: '{raw_mode}'. "
            f"Dozwolone tryby to: daily, yesterday, week, suggest."
        )
        sys.exit(1)
    return mode


def parse_date(date_str = None):
    '''
    Weryfikuje poprawność i zwraca datę. 
    '''
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            logger.error(f"Nieprawidłowy format daty: {date_str}. Użyj formatu YYYY-MM-DD.")
            sys.exit(1)
    else:
        return datetime.date.today()


def prepare_user_note(note_file):
    """
    Wczytuje notatkę z pliku oraz integruje opcjonalne najnowsze wiadomości z czatu Telegrama.
    """
    user_note = load_user_note(note_file)
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

            tg_payload = f"[RAPORT Z TELEGRAMA]:\n{tg_note}"
            user_note = f"{user_note}\n\n{tg_payload}" if user_note else tg_payload
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wiadomości z Telegrama: {e}")

    if user_note:
        logger.info("Wczytano notatkę do promptu Trenera Gemini.")
        print(f"📝 Wiadomość dla Trenera Gemini:\n   \"{user_note}\"\n")

    return user_note, new_tg_state


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


def finish_run(note_file, new_tg_state=None):
    """
    Zapisuje zaktualizowany stan Telegrama oraz czyści plik notatki użytkownika po udanym wykonaniu trybu.
    """
    if new_tg_state and save_telegram_state:
        save_telegram_state(new_tg_state)
    clear_user_note(note_file)


def main():
    # Inicjalizacja parsera.
    parser = argparse.ArgumentParser(description="Gemini Coach - Asystent Treningowy Gemini")
    parser.add_argument("mode", nargs="?", default="daily", help="daily, yesterday, week, suggest")
    parser.add_argument("--debug", action="store_true", help="włącz tryb debugowania (zapis promptów do debug_log.md)")
    parser.add_argument("--date", type=str, default=None, help="opcjonalna data referencyjna w formacie YYYY-MM-DD")
    
    args = parser.parse_args()
    debug = args.debug
    mode = check_mode_compatibility(args.mode)
    today = parse_date(args.date)

    # Przygotowanie stałych ścieżek.
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

    preferences_file = os.path.join(INPUT_DIR, "weekly_preferences.md")
    weekly_plan_file = os.path.join(OUTPUT_DIR, "weekly_plan.md")
    config_file = os.path.join(INPUT_DIR, "training_config.json")
    note_file = os.path.join(PROMPTS_DIR, "user_note.md")
    dump_file = os.path.join(INPUT_DIR, "garmin_dump.json")
    strength_routines_file = os.path.join(INPUT_DIR, "strength_routines.md")

    # Sprawdzenie klucza Gemini i modeli.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        logger.error("Brak klucza GEMINI_API_KEY w pliku .env!")
        sys.exit(1)

    gemini_models = get_gemini_models()
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Wczytanie konfiguracji biegacza i opcjonalnej notatki.
    training_context = load_training_config(config_file)
    user_note, new_tg_state = prepare_user_note(note_file)

    # Wczytanie historii treningów z ostatnich 42 dni.
    history_context = load_training_history(HISTORY_DIR, days=42, ref_date=today)
    if history_context:
        logger.info("Wczytano historię treningów z ostatnich 42 dni (6 tygodni).")

    # Profil tętna do prompta
    user_profile = build_user_profile(training_context)

    if mode == "suggest":
        run_suggest_mode(client, training_context, history_context, user_note, preferences_file, debug=debug, models=gemini_models)
    elif mode == "week":
        run_week_mode(client, training_context, history_context, user_note, preferences_file, weekly_plan_file, strength_routines_file, debug=debug, models=gemini_models)
    elif mode == "yesterday":
        run_yesterday_mode(client, today, dump_file, weekly_plan_file, user_profile, user_note, debug=debug, models=gemini_models)
    elif mode == "daily":
        run_daily_mode(client, today, dump_file, weekly_plan_file, user_profile, user_note, debug=debug, models=gemini_models)

    # Sprzątanie i aktualizacja stanu Telegrama
    finish_run(note_file, new_tg_state)


if __name__ == "__main__":
    main()
