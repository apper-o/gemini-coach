import os
import datetime
import logging
import sys
import json
from pathlib import Path
from garminconnect import Garmin
from google import genai
from dotenv import load_dotenv

# Załadowanie zmiennych z pliku .env
load_dotenv()
debug = os.getenv("DEBUG", "True").lower() in ["true", "1"]

# Stałe ścieżki do katalogów
INPUT_DIR = "input"
OUTPUT_DIR = "output"
PROMPTS_DIR = "prompts"
HISTORY_DIR = "trainings_history"

# Konfiguracja modelu Gemini z .env (domyślnie gemini-3.5-flash-lite)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Dni tygodnia w języku polskim
DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

# Inicjalizacja loggera
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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


def fetch_garmin_data(email, password, target_date, mode="daily"):
    """
    Łączy się z Garmin Connect w celu pobrania surowych danych z zegarka.
    Obsługuje bezpieczne cache'owanie tokenów sesji OAuth (tokenstore),
    aby uniknąć blokad konta, wymuszania captcha oraz limitów zapytań logowania.
    Wspiera tryb standardowy 'daily' oraz tryb 'yesterday' (obejmujący wczorajszy audyt,
    sen z minionej nocy oraz kontekst dnia przedwczorajszego).
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
    except Exception as e_token:
        logger.info(f"Logowanie z tokena nie powiodło się ({e_token}). Próba pełnego logowania danymi...")
        try:
            client = Garmin(email, password)
            client.login(tokenstore_dir)
            logger.info("Pomyślnie zalogowano pełnymi danymi i zapisano nowe tokeny sesji.")
        except Exception as e_login:
            logger.error(f"Błąd logowania do Garmin Connect: {e_login}")
            return None

    if mode == "yesterday":
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


def parse_garmin_data(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina.
    Jeśli jakiegoś parametru brakuje, wpisuje 'Brak danych' (bez sztucznych fallbacków z innego dnia).
    """
    parsed = {
        "hrv_status": "Brak danych o HRV",
        "rhr": "Brak danych o RHR",
        "sleep_score": "Brak danych o śnie",
        "deep_sleep": "Brak danych",
        "rem_sleep": "Brak danych",
        "sleep_insights": "Brak uwag",
        "body_battery": "Brak danych",
        "today_steps": "Brak danych o krokach",
        "today_stress": "Brak danych o stresie",
        "yesterday_training": "Brak aktywności (dzień wolny)",
        "yesterday_steps": "Brak danych o krokach",
        "yesterday_stress": "Brak danych o stresie"
    }

    if not data:
        return parsed

    today_data = data.get('today', {})
    yesterday_data = data.get('yesterday', {})

    # ==================== STAN NA START DNIA (MINIONA NOC / PORANEK) ====================
    # --- HRV ---
    if today_data.get('hrv'):
        hrv_raw = today_data['hrv']
        hrv_summary = hrv_raw.get('hrvSummary', {})

        status = hrv_summary.get('status') or 'Brak statusu'
        last_night = hrv_summary.get('lastNightAvg')
        weekly_avg = hrv_summary.get('weeklyAvg')

        baseline_info = hrv_summary.get('baseline', {})
        b_low = baseline_info.get('balancedLow')
        b_high = baseline_info.get('balancedUpper')

        last_night_str = f"{last_night} ms" if last_night is not None else "Brak danych"
        weekly_avg_str = f"{weekly_avg} ms" if weekly_avg is not None else "Brak danych"
        baseline_str = f"{b_low}–{b_high} ms" if b_low and b_high else "Brak danych bazowych"

        parsed['hrv_status'] = f"{status} {last_night_str} (Średnia 7-dniowa: {weekly_avg_str}, Norma bazowa: {baseline_str})"

    # --- RHR (Tętno spoczynkowe) ---
    rhr_str = "Brak danych o RHR"
    if today_data.get('rhr'):
        rhr_raw = today_data['rhr']
        try:
            rhr_list = rhr_raw.get('allMetrics', {}).get('metricsMap', {}).get('WELLNESS_RESTING_HEART_RATE', [])
            if rhr_list and len(rhr_list) > 0:
                today_val = rhr_list[0].get('value')
                if today_val is not None:
                    today_rhr = int(today_val)

                    avg_7d_str = ""
                    rhr_hist = today_data.get('rhr_history')
                    if rhr_hist:
                        avg_7d = rhr_hist.get('lastSevenDaysAvgRestingHeartRate')
                        if avg_7d is not None:
                            diff = today_rhr - int(avg_7d)
                            diff_sign = f"+{diff}" if diff > 0 else f"{diff}"
                            avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {diff_sign} bpm)"

                    rhr_str = f"{today_rhr} bpm{avg_7d_str}"
        except Exception:
            pass

    # --- Sen (dailySleepDTO) ---
    avg_night_hr = None
    if today_data.get('sleep') and 'dailySleepDTO' in today_data['sleep']:
        sleep_dto = today_data['sleep']['dailySleepDTO']

        avg_hr_val = sleep_dto.get('avgHeartRate')
        if avg_hr_val:
            avg_night_hr = f"{int(avg_hr_val)} bpm"

        score = sleep_dto.get('sleepScores', {}).get('overall', {}).get('value')
        parsed['sleep_score'] = f"{score}/100" if score is not None else "Brak danych"

        deep_secs = sleep_dto.get('deepSleepSeconds')
        if deep_secs is not None:
            parsed['deep_sleep'] = f"{deep_secs // 3600}h {(deep_secs % 3600) // 60}m"

        rem_secs = sleep_dto.get('remSleepSeconds')
        if rem_secs is not None:
            parsed['rem_sleep'] = f"{rem_secs // 3600}h {(rem_secs % 3600) // 60}m"

        feedback = sleep_dto.get('sleepScoreFeedback')
        insight = sleep_dto.get('sleepScoreInsight')
        insights_list = [i for i in [feedback, insight] if i]
        if insights_list:
            parsed['sleep_insights'] = ", ".join(insights_list)

    if avg_night_hr:
        parsed['rhr'] = f"{rhr_str} (Średnie tętno z całej nocy: {avg_night_hr})"
    else:
        parsed['rhr'] = rhr_str

    # --- Body Battery ---
    if today_data.get('body_battery') and len(today_data['body_battery']) > 0:
        bb_entry = today_data['body_battery'][0]
        bb_values = bb_entry.get('bodyBatteryValuesArray', [])
        valid_values = [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]

        if valid_values:
            current_bb = valid_values[-1]
            max_bb = max(valid_values)
            drain = max_bb - current_bb
            drain_str = f", spadek w ciągu dnia: -{drain}" if drain > 0 else ""
            parsed['body_battery'] = f"Aktualnie wieczorem: {current_bb}/100 (Maksymalnie po nocy: {max_bb}/100{drain_str})"

    # ==================== KOSZT DZISIEJSZEGO DNIA ====================
    if today_data.get('stats'):
        t_steps = today_data['stats'].get('totalSteps')
        if t_steps is not None:
            cals = today_data['stats'].get('activeKilocalories')
            cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
            parsed['today_steps'] = f"{t_steps} kroków{cals_str}"

    if today_data.get('stress'):
        t_stress = today_data['stress'].get('avgStressLevel')
        stress_qual = today_data['stress'].get('stressQualifier')
        if t_stress is not None and t_stress != -1:
            qual_str = f" ({stress_qual})" if stress_qual else ""
            parsed['today_stress'] = f"Średni poziom stresu: {t_stress}/100{qual_str}"

    # ==================== WCZORAJSZY DZIEŃ (TŁO HISTORYCZNE) ====================
    if yesterday_data.get('activities') and len(yesterday_data['activities']) > 0:
        yesterday_acts = sorted(
            yesterday_data['activities'],
            key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
        )
        yesterday_acts_texts = []
        for idx, act in enumerate(yesterday_acts):
            act_details = parse_activity_biomechanics(act)
            if act_details:
                splits_text = ""
                if act_details.get('splits'):
                    splits_text = "\n    * Splity kilometrowe:\n\n" + "\n".join(act_details['splits'])

                time_info = f" [Start: {act_details['start_time']}]" if act_details.get('start_time') and act_details['start_time'] != "Brak danych" else ""
                act_entry = (
                    f"  [Jednostka {idx + 1}{time_info}]: {act_details['name']} ({act_details['distance']} w {act_details['duration']}, tempo {act_details['pace']})\n"
                    f"    * Pogoda/Warunki: {act_details.get('weather', 'Brak danych o pogodzie')}\n"
                    f"    * Tętno: Średnie {act_details['avg_hr']} | Maksymalne {act_details['max_hr']}\n"
                    f"    * Biomechanika: Średnia kadencja {act_details['avg_cadence']}, krok {act_details['stride_length']}, kontakt {act_details['ground_contact_time']}, odchylenie {act_details['vertical_oscillation']}\n"
                    f"    * Obciążenie: Aerobic TE: {act_details['aerobic_te']}, Anaerobic TE: {act_details['anaerobic_te']}, Średnia moc: {act_details['avg_power']}"
                    f"{splits_text}"
                )
                yesterday_acts_texts.append(act_entry)

        if yesterday_acts_texts:
            parsed['yesterday_training'] = "\n\n".join(yesterday_acts_texts)

    if yesterday_data.get('stats'):
        y_steps = yesterday_data['stats'].get('totalSteps')
        if y_steps is not None:
            parsed['yesterday_steps'] = f"{y_steps} kroków"

    if yesterday_data.get('stress'):
        y_stress = yesterday_data['stress'].get('avgStressLevel')
        if y_stress is not None and y_stress != -1:
            parsed['yesterday_stress'] = f"Średni poziom stresu: {y_stress}/100"

    return parsed


def parse_garmin_data_yesterday(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina dla trybu 'yesterday':
    - Audytowany dzień wczorajszy: kroki, stres, Body Battery pod koniec dnia.
    - Miniona noc / dzisiejszy poranek: HRV, RHR, sen (jakość, fazy, uwagi), poranne Body Battery.
    - Kontekst dnia przedwczorajszego: aktywności, kroki, stres.
    """
    parsed = {
        "hrv_status": "Brak danych o HRV",
        "rhr": "Brak danych o RHR",
        "sleep_score": "Brak danych o śnie",
        "deep_sleep": "Brak danych",
        "rem_sleep": "Brak danych",
        "sleep_insights": "Brak uwag",
        "morning_body_battery": "Brak danych",
        "yesterday_steps": "Brak danych o krokach",
        "yesterday_stress": "Brak danych o stresie",
        "yesterday_body_battery": "Brak danych",
        "day_before_yesterday_training": "Brak aktywności (dzień wolny)"
    }

    if not data:
        return parsed

    recovery_data = data.get('overnight_recovery') or data.get('today', {})
    yesterday_data = data.get('yesterday', {})
    dby_data = data.get('day_before_yesterday', {})

    # ==================== MINIONA NOC I PORANEK (REGENERACJA WCZORAJ -> DZIŚ) ====================
    # --- HRV ---
    if recovery_data.get('hrv'):
        hrv_raw = recovery_data['hrv']
        hrv_summary = hrv_raw.get('hrvSummary', {})

        status = hrv_summary.get('status') or 'Brak statusu'
        last_night = hrv_summary.get('lastNightAvg')
        weekly_avg = hrv_summary.get('weeklyAvg')

        baseline_info = hrv_summary.get('baseline', {})
        b_low = baseline_info.get('balancedLow')
        b_high = baseline_info.get('balancedUpper')

        last_night_str = f"{last_night} ms" if last_night is not None else "Brak danych"
        weekly_avg_str = f"{weekly_avg} ms" if weekly_avg is not None else "Brak danych"
        baseline_str = f"{b_low}–{b_high} ms" if b_low and b_high else "Brak danych bazowych"

        parsed['hrv_status'] = f"{status} {last_night_str} (Średnia 7-dniowa: {weekly_avg_str}, Norma bazowa: {baseline_str})"

    # --- RHR (Tętno spoczynkowe) ---
    rhr_str = "Brak danych o RHR"
    if recovery_data.get('rhr'):
        rhr_raw = recovery_data['rhr']
        try:
            rhr_list = rhr_raw.get('allMetrics', {}).get('metricsMap', {}).get('WELLNESS_RESTING_HEART_RATE', [])
            if rhr_list and len(rhr_list) > 0:
                today_val = rhr_list[0].get('value')
                if today_val is not None:
                    today_rhr = int(today_val)

                    avg_7d_str = ""
                    rhr_hist = recovery_data.get('rhr_history')
                    if rhr_hist:
                        avg_7d = rhr_hist.get('lastSevenDaysAvgRestingHeartRate')
                        if avg_7d is not None:
                            diff = today_rhr - int(avg_7d)
                            diff_sign = f"+{diff}" if diff > 0 else f"{diff}"
                            avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {diff_sign} bpm)"

                    rhr_str = f"{today_rhr} bpm{avg_7d_str}"
        except Exception:
            pass

    # --- Sen (dailySleepDTO) ---
    avg_night_hr = None
    if recovery_data.get('sleep') and 'dailySleepDTO' in recovery_data['sleep']:
        sleep_dto = recovery_data['sleep']['dailySleepDTO']

        avg_hr_val = sleep_dto.get('avgHeartRate')
        if avg_hr_val:
            avg_night_hr = f"{int(avg_hr_val)} bpm"

        score = sleep_dto.get('sleepScores', {}).get('overall', {}).get('value')
        parsed['sleep_score'] = f"{score}/100" if score is not None else "Brak danych"

        deep_secs = sleep_dto.get('deepSleepSeconds')
        if deep_secs is not None:
            parsed['deep_sleep'] = f"{deep_secs // 3600}h {(deep_secs % 3600) // 60}m"

        rem_secs = sleep_dto.get('remSleepSeconds')
        if rem_secs is not None:
            parsed['rem_sleep'] = f"{rem_secs // 3600}h {(rem_secs % 3600) // 60}m"

        feedback = sleep_dto.get('sleepScoreFeedback')
        insight = sleep_dto.get('sleepScoreInsight')
        insights_list = [i for i in [feedback, insight] if i]
        if insights_list:
            parsed['sleep_insights'] = ", ".join(insights_list)

    if avg_night_hr:
        parsed['rhr'] = f"{rhr_str} (Średnie tętno z całej nocy: {avg_night_hr})"
    else:
        parsed['rhr'] = rhr_str

    # --- Poranne Body Battery ---
    bb_rec = recovery_data.get('body_battery')
    bb_entry = None
    if isinstance(bb_rec, list) and len(bb_rec) > 0:
        bb_entry = bb_rec[0]
    elif isinstance(bb_rec, dict):
        bb_entry = bb_rec

    if bb_entry:
        bb_values = bb_entry.get('bodyBatteryValuesArray', [])
        valid_values = [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]
        if valid_values:
            latest_bb = valid_values[-1]
            max_bb = max(valid_values)
            parsed['morning_body_battery'] = f"{latest_bb}/100 (Szczyt poranny po nocy: {max_bb}/100)"

    # ==================== KOSZT WCZORAJSZEGO DNIA (AUDYT) ====================
    if yesterday_data.get('stats'):
        y_steps = yesterday_data['stats'].get('totalSteps')
        if y_steps is not None:
            cals = yesterday_data['stats'].get('activeKilocalories')
            cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
            parsed['yesterday_steps'] = f"{y_steps} kroków{cals_str}"

    if yesterday_data.get('stress'):
        y_stress = yesterday_data['stress'].get('avgStressLevel')
        stress_qual = yesterday_data['stress'].get('stressQualifier')
        if y_stress is not None and y_stress != -1:
            qual_str = f" ({stress_qual})" if stress_qual else ""
            parsed['yesterday_stress'] = f"Średni poziom stresu: {y_stress}/100{qual_str}"

    bb_y = yesterday_data.get('body_battery')
    bb_y_entry = None
    if isinstance(bb_y, list) and len(bb_y) > 0:
        bb_y_entry = bb_y[0]
    elif isinstance(bb_y, dict):
        bb_y_entry = bb_y

    if bb_y_entry:
        bb_values = bb_y_entry.get('bodyBatteryValuesArray', [])
        valid_values = [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]
        if valid_values:
            evening_bb = valid_values[-1]
            max_bb = max(valid_values)
            min_bb = min(valid_values)
            drain = max_bb - evening_bb
            drain_str = f", spadek w ciągu dnia: -{drain}" if drain > 0 else ""
            parsed['yesterday_body_battery'] = f"Pod koniec dnia: {evening_bb}/100 (Max w ciągu dnia: {max_bb}/100, min: {min_bb}/100{drain_str})"

    # ==================== KONTEKST DNIA PRZEDWCZORAJSZEGO ====================
    if dby_data.get('activities') and len(dby_data['activities']) > 0:
        dby_acts = sorted(
            dby_data['activities'],
            key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
        )
        dby_acts_texts = []
        for idx, act in enumerate(dby_acts):
            act_details = parse_activity_biomechanics(act)
            if act_details:
                splits_text = ""
                if act_details.get('splits'):
                    splits_text = "\n    * Splity kilometrowe:\n\n" + "\n".join(act_details['splits'])

                time_info = f" [Start: {act_details['start_time']}]" if act_details.get('start_time') and act_details['start_time'] != "Brak danych" else ""
                act_entry = (
                    f"  [Jednostka {idx + 1}{time_info}]: {act_details['name']} ({act_details['distance']} w {act_details['duration']}, tempo {act_details['pace']})\n"
                    f"    * Pogoda/Warunki: {act_details.get('weather', 'Brak danych o pogodzie')}\n"
                    f"    * Tętno: Średnie {act_details['avg_hr']} | Maksymalne {act_details['max_hr']}\n"
                    f"    * Biomechanika: Średnia kadencja {act_details['avg_cadence']}, krok {act_details['stride_length']}, kontakt {act_details['ground_contact_time']}, odchylenie {act_details['vertical_oscillation']}\n"
                    f"    * Obciążenie: Aerobic TE: {act_details['aerobic_te']}, Anaerobic TE: {act_details['anaerobic_te']}, Średnia moc: {act_details['avg_power']}"
                    f"{splits_text}"
                )
                dby_acts_texts.append(act_entry)

        if dby_acts_texts:
            parsed['day_before_yesterday_training'] = "\n\n".join(dby_acts_texts)

    return parsed


def load_training_config(config_file=os.path.join(INPUT_DIR, "training_config.json")):
    """
    Wczytuje kontekst treningowy, strefy tętna i cele biegacza z pliku JSON w folderze input/.
    Jeśli jakiejś wartości brakuje, przyjmuje 'Brak danych' bez wpisywania fikcyjnych danych domyślnych.
    """
    keys = ["goal", "phase", "time_left", "max_hr", "lthr", "z1", "z2", "z3", "z4", "z5"]
    default_config = {k: "Brak danych" for k in keys}

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
                    merged[k] = "Brak danych"
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
                    f.write("# Twoja wiadomość/uwagi do Trenera Gemini\n"
                            "# Możesz tu wpisać dowolne bieżące informacje, np.:\n"
                            "# - 'Czuję lekkie zmęczenie w czwórgłowych po wczorajszych schodach'\n"
                            "# - 'W czwartek mam czas tylko rano na max 45 minut'\n"
                            "# - 'W sobotę chcę biegać w terenie krosowym'\n"
                            "# Trener uwzględni te uwagi w prompcie. Linie zaczynające się od '#' są ignorowane.\n")
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


def load_training_history(history_dir=HISTORY_DIR, days=7, ref_date=None):
    """
    Wczytuje historię treningów z folderu trainings_history z ostatnich `days` dni (domyślnie 7 dni).
    """
    if not os.path.exists(history_dir):
        return None

    if ref_date is None:
        ref_date = datetime.date.today()

    cutoff_date = ref_date - datetime.timedelta(days=days)
    entries = []

    history_files = sorted(os.listdir(history_dir), reverse=True)
    for fname in history_files:
        if fname.endswith(".md"):
            date_part = fname[:-3]
            try:
                f_date = datetime.date.fromisoformat(date_part)
                if cutoff_date <= f_date <= ref_date:
                    with open(os.path.join(history_dir, fname), "r", encoding="utf-8") as hf:
                        entries.append(hf.read())
            except ValueError:
                continue

    # Fallback: jeśli w zadanym oknie czasowym nie ma wpisów (np. testy na starszych danych), weź do `days` najnowszych plików
    if not entries and history_files:
        for fname in history_files[:days]:
            if fname.endswith(".md"):
                with open(os.path.join(history_dir, fname), "r", encoding="utf-8") as hf:
                    entries.append(hf.read())

    return "\n\n" + "-"*40 + "\n\n".join(entries) if entries else None


def generate_weekly_plan_prompt(days_preferences, training_context, history_context=None, user_note=None, strength_routines=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA POPRZEDNICH TRENINGÓW (ARCHIWUM Z OSTATNIEGO TYGODNIA):
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
        goal=training_context.get('goal', 'Brak danych'),
        phase=training_context.get('phase', 'Brak danych'),
        time_left=training_context.get('time_left', 'Brak danych'),
        max_hr=training_context.get('max_hr', 'Brak danych'),
        lthr=training_context.get('lthr', 'Brak danych'),
        z1=training_context.get('z1', 'Brak danych'),
        z2=training_context.get('z2', 'Brak danych'),
        z3=training_context.get('z3', 'Brak danych'),
        z4=training_context.get('z4', 'Brak danych'),
        z5=training_context.get('z5', 'Brak danych'),
        hist_section=hist_section,
        strength_routines=routines_section,
        days_preferences=days_preferences,
        note_section=note_section
    )


def generate_weekly_suggestions_prompt(training_context, history_context=None, user_note=None):
    """
    Tworzy prompt dla Gemini w trybie 'suggest' bez przesyłania biometrii z Garmina.
    Model proponuje typy/cele treningów na podstawie profilu biegacza, historii z 7 dni i notatki.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA POPRZEDNICH TRENINGÓW (ARCHIWUM Z OSTATNIEGO TYGODNIA):
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
        goal=training_context.get('goal', 'Brak danych'),
        phase=training_context.get('phase', 'Brak danych'),
        time_left=training_context.get('time_left', 'Brak danych'),
        max_hr=training_context.get('max_hr', 'Brak danych'),
        lthr=training_context.get('lthr', 'Brak danych'),
        z1=training_context.get('z1', 'Brak danych'),
        z2=training_context.get('z2', 'Brak danych'),
        z3=training_context.get('z3', 'Brak danych'),
        z4=training_context.get('z4', 'Brak danych'),
        z5=training_context.get('z5', 'Brak danych'),
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
        "weather": "Brak danych o pogodzie"
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


def generate_verification_prompt(planned_workout, activity_stats, garmin_stats=None, weekly_plan_context=None,
                                 user_profile=None, user_note=None, today_date_str="", yesterday_date_str="",
                                 tomorrow_date_str="", trening_z_planu=""):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu oraz całodziennej/nocnej regeneracji
    oraz adaptacji planu na kolejny dzień.
    """
    if user_profile is None:
        user_profile = {
            "max_hr": "Brak danych",
            "lthr": "Brak danych",
            "hr_zones": "Brak danych"
        }

    yesterday_section = f"Brak danych o treningu z dnia {yesterday_date_str} (dzień wolny)"
    if garmin_stats and garmin_stats.get('yesterday_training') and garmin_stats.get('yesterday_training') != "Brak aktywności (dzień wolny)":
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

    activity_section = f"W dniu {today_date_str} nie odnotowano treningu biegowego (Dzień wolny / Regeneracja)."
    if activity_stats:
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        act_blocks = []

        for idx, act in enumerate(stats_list):
            splits_text = "Brak szczegółowych splitów dla tej jednostki"
            if act.get('splits'):
                splits_text = "\n".join(act['splits'])

            time_info = f" [Start: {act['start_time']}]" if act.get('start_time') and act['start_time'] != "Brak danych" else ""
            prefix = f"[JEDNOSTKA {idx + 1} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")
            block = f"""{prefix}{act.get('name')} | {act.get('distance')} w czasie {act.get('duration')} (Średnie tempo: {act.get('pace')})
- Warunki atmosferyczne i pogoda: {act.get('weather', 'Brak danych o pogodzie')}
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

        activity_section = "\n\n" + "-"*35 + "\n\n".join(act_blocks)

    g_stats = garmin_stats or {}

    return load_prompt_template(
        "daily_verification.md",
        max_hr=user_profile.get('max_hr', 'Brak danych'),
        lthr=user_profile.get('lthr', 'Brak danych'),
        hr_zones=user_profile.get('hr_zones', 'Brak danych'),
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        tomorrow_date_str=tomorrow_date_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {today_date_str}',
        activity_section=activity_section,
        yesterday_section=yesterday_section,
        weekly_plan_section=weekly_plan_section,
        user_note=note_content,
        trening_z_planu=trening_z_planu or f"Odszukaj w planie tygodniowym jednostkę na dzień {tomorrow_date_str}",
        today_steps=g_stats.get('today_steps', 'Brak danych o krokach'),
        today_stress=g_stats.get('today_stress', 'Brak danych o stresie'),
        body_battery=g_stats.get('body_battery', 'Brak danych'),
        hrv_status=g_stats.get('hrv_status', 'Brak danych o HRV'),
        rhr=g_stats.get('rhr', 'Brak danych o RHR'),
        sleep_score=g_stats.get('sleep_score', 'Brak danych o śnie'),
        deep_sleep=g_stats.get('deep_sleep', 'Brak danych'),
        rem_sleep=g_stats.get('rem_sleep', 'Brak danych'),
        sleep_insights=g_stats.get('sleep_insights', 'Brak uwag')
    )


def generate_yesterday_verification_prompt(planned_workout, activity_stats, garmin_stats=None, weekly_plan_context=None,
                                          user_profile=None, user_note=None, today_date_str="", yesterday_date_str="",
                                          day_before_yesterday_date_str="", trening_z_planu=""):
    """
    Tworzy prompt dla Gemini w trybie 'yesterday' do audytu wczorajszego treningu,
    oceny regeneracji z minionej nocy (sen wczoraj->dziś) oraz natychmiastowej adaptacji planu na dzień dzisiejszy.
    """
    if user_profile is None:
        user_profile = {
            "max_hr": "Brak danych",
            "lthr": "Brak danych",
            "hr_zones": "Brak danych"
        }

    day_before_yesterday_section = f"Brak danych o treningu z dnia {day_before_yesterday_date_str} (dzień wolny)"
    if garmin_stats and garmin_stats.get('day_before_yesterday_training') and garmin_stats.get('day_before_yesterday_training') != "Brak aktywności (dzień wolny)":
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

    activity_section = f"W dniu wczorajszym ({yesterday_date_str}) nie odnotowano treningu biegowego (Dzień wolny / Regeneracja)."
    if activity_stats:
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        act_blocks = []

        for idx, act in enumerate(stats_list):
            splits_text = "Brak szczegółowych splitów dla tej jednostki"
            if act.get('splits'):
                splits_text = "\n".join(act['splits'])

            time_info = f" [Start: {act['start_time']}]" if act.get('start_time') and act['start_time'] != "Brak danych" else ""
            prefix = f"[JEDNOSTKA {idx + 1} z {len(stats_list)}{time_info}]: " if len(stats_list) > 1 else (f"[JEDNOSTKA 1{time_info}]: " if time_info else "")
            block = f"""{prefix}{act.get('name')} | {act.get('distance')} w czasie {act.get('duration')} (Średnie tempo: {act.get('pace')})
- Warunki atmosferyczne i pogoda: {act.get('weather', 'Brak danych o pogodzie')}
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

        activity_section = "\n\n" + "-"*35 + "\n\n".join(act_blocks)

    g_stats = garmin_stats or {}

    return load_prompt_template(
        "yesterday_verification.md",
        max_hr=user_profile.get('max_hr', 'Brak danych'),
        lthr=user_profile.get('lthr', 'Brak danych'),
        hr_zones=user_profile.get('hr_zones', 'Brak danych'),
        today_date_str=today_date_str,
        yesterday_date_str=yesterday_date_str,
        day_before_yesterday_date_str=day_before_yesterday_date_str,
        planned_workout=planned_workout or f'Brak sztywnego planu na dzień {yesterday_date_str}',
        activity_section=activity_section,
        yesterday_steps=g_stats.get('yesterday_steps', 'Brak danych o krokach'),
        yesterday_stress=g_stats.get('yesterday_stress', 'Brak danych o stresie'),
        yesterday_body_battery=g_stats.get('yesterday_body_battery', 'Brak danych'),
        hrv_status=g_stats.get('hrv_status', 'Brak danych o HRV'),
        rhr=g_stats.get('rhr', 'Brak danych o RHR'),
        sleep_score=g_stats.get('sleep_score', 'Brak danych o śnie'),
        deep_sleep=g_stats.get('deep_sleep', 'Brak danych'),
        rem_sleep=g_stats.get('rem_sleep', 'Brak danych'),
        sleep_insights=g_stats.get('sleep_insights', 'Brak uwag'),
        morning_body_battery=g_stats.get('morning_body_battery', 'Brak danych'),
        day_before_yesterday_section=day_before_yesterday_section,
        weekly_plan_section=weekly_plan_section,
        user_note=note_content,
        trening_z_planu=trening_z_planu or f"Odszukaj w planie tygodniowym jednostkę na dzień dzisiejszy ({today_date_str})"
    )


def main():
    # 1. Określenie trybu działania na samym początku (Punkt 1 wytycznych)
    mode = "daily"
    if len(sys.argv) > 1:
        arg_mode = sys.argv[1].lower()
        if arg_mode in ["suggest", "sugestia", "sugeruj", "propozycja"]:
            mode = "suggest"
        elif arg_mode in ["week", "tydzien", "plan-tygodnia", "weekly"]:
            mode = "week"
        elif arg_mode == "yesterday":
            mode = "yesterday"

    # 2. Precyzyjne wyliczenie dat kalendarzowych (Punkt 6 wytycznych)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    tomorrow = today + datetime.timedelta(days=1)
    day_before_yesterday = yesterday - datetime.timedelta(days=1)

    today_date_str = f"{DAYS_PL[today.weekday()]}, {today.isoformat()}"
    yesterday_date_str = f"{DAYS_PL[yesterday.weekday()]}, {yesterday.isoformat()}"
    tomorrow_date_str = f"{DAYS_PL[tomorrow.weekday()]}, {tomorrow.isoformat()}"
    day_before_yesterday_date_str = f"{DAYS_PL[day_before_yesterday.weekday()]}, {day_before_yesterday.isoformat()}"

    # 3. Przygotowanie stałych ścieżek
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

    # 4. Sprawdzenie klucza Gemini
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        logger.error("Brak klucza GEMINI_API_KEY w pliku .env!")
        sys.exit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)

    # 5. Wczytanie konfiguracji biegacza i opcjonalnej notatki
    training_context = load_training_config(config_file)
    user_note = load_user_note(note_file)
    if user_note:
        logger.info(f"Wczytano notatkę użytkownika z pliku {note_file}.")
        print(f"📝 Wczytano Twoją wiadomość z {note_file}:\n   \"{user_note}\"\n")

    # 6. Wczytanie historii treningów z ostatnich 7 dni (Punkt 1 i 4 wytycznych)
    history_context = load_training_history(HISTORY_DIR, days=7, ref_date=today)
    if history_context:
        logger.info("Wczytano historię treningów z ostatnich 7 dni.")

    # Profil tętna do prompta
    user_profile = {
        "max_hr": training_context.get("max_hr", "Brak danych"),
        "lthr": training_context.get("lthr", "Brak danych"),
        "hr_zones": f"Z1: {training_context.get('z1', 'Brak danych')}, Z2: {training_context.get('z2', 'Brak danych')}, Z3: {training_context.get('z3', 'Brak danych')}, Z4: {training_context.get('z4', 'Brak danych')}, Z5: {training_context.get('z5', 'Brak danych')}"
    }

    # ==================== TRYB 1: SUGESTIE TYPÓW TRENINGÓW (SUGGEST) ====================
    # Omijamy łączenie z Garminem – używamy profilu, historii z 7 dni i notatki
    if mode == "suggest":
        print("\n" + "="*60)
        print("💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡")
        print("="*60)
        print("Model analizuje historię ostatnich 7 dni, fazę i cele, aby zaproponować podział jednostek.")

        suggest_prompt = generate_weekly_suggestions_prompt(
            training_context=training_context,
            history_context=history_context,
            user_note=user_note
        )

        print("\n" + "="*50)
        print(f"WYSYŁANIE ZAPYTANIA DO GEMINI (Model: {GEMINI_MODEL})...")
        print("="*50)

        try:
            chat = client.chats.create(model=GEMINI_MODEL)
            response = chat.send_message(suggest_prompt)

            print("\n💡 PROPONOWANY PODZIAŁ TYPÓW TRENINGU NA TEN TYDZIEŃ 💡\n")
            print(response.text)

            with open(preferences_file, "w", encoding="utf-8") as pf:
                pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii treningowej i profilu\n")
                pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python garmin_coach.py week'\n\n")
                pf.write(response.text)

            logger.info(f"Sugestie typów treningów zapisano do pliku: {preferences_file}")
            print(f"\n✅ Zapisano propozycję do pliku: {preferences_file}")
            print(f"👉 Jeśli chcesz coś zmienić, wyedytuj '{preferences_file}', a następnie uruchom:")
            print(f"   python garmin_coach.py week")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas generowania sugestii: {e}")
            sys.exit(1)

    # ==================== TRYB 2: PLANOWANIE TYGODNIOWE (WEEK) ====================
    # Omijamy łączenie z Garminem – używamy preferencji, profilu, historii z 7 dni i notatki
    elif mode == "week":
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

        if debug:
            with open("debug_log.md", "w", encoding="utf-8") as f_debug:
                f_debug.write(week_prompt + "\n")
        

        print("\n" + "="*50)
        print(f"WYSYŁANIE PLANU DO GEMINI (Model: {GEMINI_MODEL})...")
        print("="*50)

        try:
            chat = client.chats.create(model=GEMINI_MODEL)
            response = chat.send_message(week_prompt)

            print("\n🏆 ROZPISKA PLANU NA CAŁY TYDZIEŃ OD TRENERA 🏆\n")
            print(response.text)

            with open(weekly_plan_file, "w", encoding="utf-8") as wf:
                wf.write(response.text)
            logger.info(f"Plan tygodniowy został zapisany do pliku: {weekly_plan_file}")
            print(f"\n✅ Zapisano plan do: {weekly_plan_file}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas generowania planu tygodniowego: {e}")
            sys.exit(1)

    # ==================== TRYB 3: CODZIENNA WERYFIKACJA I ADAPTACJA (DAILY) ====================
    # Pobieranie danych z zegarka Garmin następuje TYLKO w tym trybie!
    elif mode == "daily":
        logger.info(f"Uruchomiono tryb codziennej weryfikacji dla dnia: {today_date_str}...")

        USE_LOCAL_DATA = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]

        if USE_LOCAL_DATA:
            logger.info(f"Omijam logowanie. Wczytuję surowe dane z pliku lokalnego: {dump_file}...")
            try:
                with open(dump_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except FileNotFoundError:
                logger.error(f"Nie znaleziono pliku {dump_file}. Uruchom skrypt z USE_LOCAL_DATA='False', aby go stworzyć!")
                sys.exit(1)
        else:
            GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
            GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")
            if not GARMIN_EMAIL or not GARMIN_PASSWORD:
                logger.error("Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD w pliku .env!")
                sys.exit(1)

            raw_data = fetch_garmin_data(GARMIN_EMAIL, GARMIN_PASSWORD, today)
            if raw_data is None:
                logger.error("Nie udało się pobrać danych z serwerów Garmina.")
                sys.exit(1)

            with open(dump_file, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Surowe dane zapisano pomyślnie do pliku {dump_file}.")

        # 1. Parsujemy dane biometryczne z dzisiejszego dnia i minionej nocy
        garmin_stats = parse_garmin_data(raw_data)

        # 2. Wczytujemy plan tygodniowy, jeśli istnieje
        weekly_plan_content = None
        if os.path.exists(weekly_plan_file):
            try:
                with open(weekly_plan_file, "r", encoding="utf-8") as wf:
                    weekly_plan_content = wf.read()
            except Exception:
                pass

        # 3. Parsujemy dzisiejsze aktywności
        today_acts = raw_data.get('today', {}).get('activities', [])
        today_acts = sorted(
            today_acts,
            key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
        )
        all_today_stats = []
        for act in today_acts:
            st = parse_activity_biomechanics(act)
            if st:
                all_today_stats.append(st)

        if all_today_stats:
            print("\n" + "="*50)
            print(f"📊 POBRANO AKTYWNOŚCI DO AUDYTU ({len(all_today_stats)} jednostek w dniu {today_date_str}):")
            print("="*50)
            for idx, act_st in enumerate(all_today_stats):
                time_str = f" [Start: {act_st['start_time']}]" if act_st.get('start_time') and act_st['start_time'] != "Brak danych" else ""
                prefix = f"Jednostka {idx + 1}{time_str}: " if len(all_today_stats) > 1 else ""
                print(f"\n▶️ {prefix}{act_st['name']} ({act_st['distance']}, tempo: {act_st['pace']})")
                for k, v in act_st.items():
                    if k not in ['splits', 'name', 'distance', 'pace', 'start_time']:
                        print(f"   - {k}: {v}")

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
            activity_stats=all_today_stats if all_today_stats else None,
            garmin_stats=garmin_stats,
            weekly_plan_context=weekly_plan_content,
            user_profile=user_profile,
            user_note=user_note,
            today_date_str=today_date_str,
            yesterday_date_str=yesterday_date_str,
            tomorrow_date_str=tomorrow_date_str,
            trening_z_planu=trening_z_planu
        )

        if debug:
            with open("debug_log.md", "w", encoding="utf-8") as f_debug:
                f_debug.write(verification_prompt + "\n")

        print("\n" + "="*50)
        print(f"WYSYŁANIE RAPORTU DO GEMINI (Model: {GEMINI_MODEL})...")
        print("="*50)

        try:
            chat = client.chats.create(model=GEMINI_MODEL)
            response = chat.send_message(verification_prompt)

            print(f"\n🏆 RAPORT TRENERSKI I ADAPTACJA NA DZIEŃ {tomorrow_date_str} 🏆\n")
            print(response.text)

            # Określenie daty do archiwum
            workout_date = today.isoformat()
            if all_today_stats and today_acts:
                first_raw_act = today_acts[0]
                act_start = first_raw_act.get('startTimeLocal', '')
                if len(act_start) >= 10:
                    workout_date = act_start[:10]

            history_file_path = os.path.join(HISTORY_DIR, f"{workout_date}.md")

            if all_today_stats:
                acts_archive_blocks = []
                for idx, act_s in enumerate(all_today_stats):
                    splits_formatted = "\n".join(act_s.get('splits', []))
                    if not splits_formatted:
                        splits_formatted = "Brak szczegółowych splitów dla tej jednostki"
                    time_info = f" [Start: {act_s['start_time']}]" if act_s.get('start_time') and act_s['start_time'] != "Brak danych" else ""
                    single_block = f"""### Jednostka {idx + 1}{time_info}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', 'Brak danych o pogodzie')}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
                    acts_archive_blocks.append(single_block)

                archive_content = f"""# TRENING Z DNIA: {workout_date} ({today_date_str})
Liczba zarejestrowanych jednostek: {len(all_today_stats)}

## Biometria regeneracyjna i bilans dnia ({today_date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Całodzienny stres w dniu {today_date_str}: {garmin_stats.get('today_stress')}
- Kroki w dniu {today_date_str} (cały dzień): {garmin_stats.get('today_steps')}

## Zarejestrowane aktywności:
{chr(10).join(acts_archive_blocks)}

## Ocena trenera i adaptacja na dzień {tomorrow_date_str}:
{response.text}
"""
            else:
                archive_content = f"""# DZIEŃ WOLNY / REST DAY: {workout_date} ({today_date_str})
Aktywność: Brak biegu (Regeneracja / Odpoczynek)

## Biometria regeneracyjna i bilans dnia ({today_date_str}):
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Całodzienny stres w dniu {today_date_str}: {garmin_stats.get('today_stress')}
- Kroki w dniu {today_date_str} (cały dzień): {garmin_stats.get('today_steps')}

## Ocena trenera i adaptacja na dzień {tomorrow_date_str}:
{response.text}
"""
            with open(history_file_path, "w", encoding="utf-8") as hf:
                hf.write(archive_content)
            logger.info(f"Raport z dnia {workout_date} zapisano do archiwum: {history_file_path}")

            latest_daily_file = os.path.join(OUTPUT_DIR, "last_daily_report.md")
            with open(latest_daily_file, "w", encoding="utf-8") as lf:
                lf.write(archive_content)
            logger.info(f"Bieżący wynik zapisano do pliku: {latest_daily_file}")
            print(f"\n✅ Zapisano raport do: {latest_daily_file} oraz archiwum {history_file_path}")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas weryfikacji i adaptacji: {e}")
            sys.exit(1)

    # ==================== TRYB 4: ZASTĘPCZA WERYFIKACJA DNIA WCZORAJSZEGO (YESTERDAY) ====================
    elif mode == "yesterday":
        logger.info(f"Uruchomiono tryb weryfikacji wczorajszego dnia ('yesterday') dla audytu: {yesterday_date_str} oraz adaptacji na dziś: {today_date_str}...")

        USE_LOCAL_DATA = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]

        if USE_LOCAL_DATA:
            logger.info(f"Omijam logowanie. Wczytuję surowe dane z pliku lokalnego: {dump_file}...")
            try:
                with open(dump_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except FileNotFoundError:
                logger.error(f"Nie znaleziono pliku {dump_file}. Uruchom skrypt z USE_LOCAL_DATA='False', aby go stworzyć!")
                sys.exit(1)
        else:
            GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
            GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")
            if not GARMIN_EMAIL or not GARMIN_PASSWORD:
                logger.error("Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD w pliku .env!")
                sys.exit(1)

            raw_data = fetch_garmin_data(GARMIN_EMAIL, GARMIN_PASSWORD, today, mode="yesterday")
            if raw_data is None:
                logger.error("Nie udało się pobrać danych z serwerów Garmina.")
                sys.exit(1)

            with open(dump_file, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Surowe dane zapisano pomyślnie do pliku {dump_file}.")

        # 1. Parsujemy dane biometryczne z wczorajszego dnia, minionej nocy i tła historycznego
        garmin_stats = parse_garmin_data_yesterday(raw_data)

        # 2. Wczytujemy plan tygodniowy, jeśli istnieje
        weekly_plan_content = None
        if os.path.exists(weekly_plan_file):
            try:
                with open(weekly_plan_file, "r", encoding="utf-8") as wf:
                    weekly_plan_content = wf.read()
            except Exception:
                pass

        # 3. Parsujemy wczorajsze aktywności (podlegające audytowi)
        yesterday_acts = raw_data.get('yesterday', {}).get('activities', [])
        yesterday_acts = sorted(
            yesterday_acts,
            key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
        )
        all_yesterday_stats = []
        for act in yesterday_acts:
            st = parse_activity_biomechanics(act)
            if st:
                all_yesterday_stats.append(st)

        if all_yesterday_stats:
            print("\n" + "="*50)
            print(f"📊 POBRANO AKTYWNOŚCI DO AUDYTU ({len(all_yesterday_stats)} jednostek w dniu {yesterday_date_str}):")
            print("="*50)
            for idx, act_st in enumerate(all_yesterday_stats):
                time_str = f" [Start: {act_st['start_time']}]" if act_st.get('start_time') and act_st['start_time'] != "Brak danych" else ""
                prefix = f"Jednostka {idx + 1}{time_str}: " if len(all_yesterday_stats) > 1 else ""
                print(f"\n▶️ {prefix}{act_st['name']} ({act_st['distance']}, tempo: {act_st['pace']})")
                for k, v in act_st.items():
                    if k not in ['splits', 'name', 'distance', 'pace', 'start_time']:
                        print(f"   - {k}: {v}")

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
            activity_stats=all_yesterday_stats if all_yesterday_stats else None,
            garmin_stats=garmin_stats,
            weekly_plan_context=weekly_plan_content,
            user_profile=user_profile,
            user_note=user_note,
            today_date_str=today_date_str,
            yesterday_date_str=yesterday_date_str,
            day_before_yesterday_date_str=day_before_yesterday_date_str,
            trening_z_planu=trening_z_planu
        )

        if debug:
            with open("debug_log.md", "w", encoding="utf-8") as f_debug:
                f_debug.write(yesterday_prompt + "\n")

        print("\n" + "="*50)
        print(f"WYSYŁANIE RAPORTU DO GEMINI (Model: {GEMINI_MODEL})...")
        print("="*50)

        try:
            chat = client.chats.create(model=GEMINI_MODEL)
            response = chat.send_message(yesterday_prompt)

            print(f"\n🏆 RAPORT TRENERSKI (AUDYT DNIA WCZORAJSZEGO) I ADAPTACJA NA DZIŚ ({today_date_str}) 🏆\n")
            print(response.text)

            # Określenie daty audytowanego treningu do archiwum (wczorajszy dzień)
            workout_date = yesterday.isoformat()
            if all_yesterday_stats and yesterday_acts:
                first_raw_act = yesterday_acts[0]
                act_start = first_raw_act.get('startTimeLocal', '')
                if len(act_start) >= 10:
                    workout_date = act_start[:10]

            history_file_path = os.path.join(HISTORY_DIR, f"{workout_date}.md")

            if all_yesterday_stats:
                acts_archive_blocks = []
                for idx, act_s in enumerate(all_yesterday_stats):
                    splits_formatted = "\n".join(act_s.get('splits', []))
                    if not splits_formatted:
                        splits_formatted = "Brak szczegółowych splitów dla tej jednostki"
                    time_info = f" [Start: {act_s['start_time']}]" if act_s.get('start_time') and act_s['start_time'] != "Brak danych" else ""
                    single_block = f"""### Jednostka {idx + 1}{time_info}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', 'Brak danych o pogodzie')}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
                    acts_archive_blocks.append(single_block)

                archive_content = f"""# TRENING Z DNIA: {workout_date} ({yesterday_date_str}) [TRYB YESTERDAY]
Liczba zarejestrowanych jednostek: {len(all_yesterday_stats)}

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

## Zarejestrowane aktywności wczoraj:
{chr(10).join(acts_archive_blocks)}

## Ocena trenera i adaptacja na dzień dzisiejszy ({today_date_str}):
{response.text}
"""
            else:
                archive_content = f"""# DZIEŃ WOLNY / REST DAY: {workout_date} ({yesterday_date_str}) [TRYB YESTERDAY]
Aktywność: Brak biegu (Regeneracja / Odpoczynek)

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

## Ocena trenera i adaptacja na dzień dzisiejszy ({today_date_str}):
{response.text}
"""
            with open(history_file_path, "w", encoding="utf-8") as hf:
                hf.write(archive_content)
            logger.info(f"Raport z dnia {workout_date} zapisano do archiwum: {history_file_path}")

            latest_daily_file = os.path.join(OUTPUT_DIR, "last_daily_report.md")
            with open(latest_daily_file, "w", encoding="utf-8") as lf:
                lf.write(archive_content)
            logger.info(f"Bieżący wynik zapisano do pliku: {latest_daily_file}")
            print(f"\n✅ Zapisano raport do: {latest_daily_file} oraz archiwum {history_file_path}")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas weryfikacji i adaptacji: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
