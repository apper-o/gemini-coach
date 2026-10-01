"""
garmin_service.py - Moduł komunikacji z Garmin Connect oraz parserów danych biometrycznych i biegowych.
"""

import os
import sys
import json
import datetime
import logging
import re
from garminconnect import Garmin

logger = logging.getLogger(__name__)

# Stałe globalne
NO_DATA = "Brak danych"
HISTORY_DIR = "trainings_history"

# Prekompilowane wyrażenia regularne dla parsowania historii
RE_STRENGTH_KW = re.compile(r'(siłowni|siłowa|hevy|fbw|upper|lower|strength)', re.IGNORECASE)
RE_PROFILE_HEADER = re.compile(r'\*\s*Profil jednostki:\s*([^\n]+)')
RE_VARIANT_B_HEADER = re.compile(r'(WARIANT B:[^\n]+)')

def _get_or_nodata(d, key, formatter=None):
    """
    Pobiera wartość ze słownika, a jeśli jej nie ma, zwraca NO_DATA.
    
    Args:
        d (dict): Słownik, z którego pobierana jest wartość.
        key (str): Klucz do pobrania ze słownika.
        formatter (callable, optional): Funkcja formatująca pobraną wartość. Defaults to None.
        
    Returns:
        Any: Pobrana (i ewentualnie sformatowana) wartość lub NO_DATA w przypadku jej braku.
    """
    if not isinstance(d, dict):
        return NO_DATA
    val = d.get(key)
    if val is None:
        return NO_DATA
    if formatter:
        try:
            return formatter(val)
        except Exception:
            return NO_DATA
    return val

# ==============================================================================
# 1. PARSERY BIOMETRII I BIOMECHANIKI AKTYWNOŚCI
# ==============================================================================

def _speed_to_pace_str(speed_m_s):
    """
    Konwertuje prędkość w m/s na czytelne tempo w formacie M:SS min/km.
    
    Args:
        speed_m_s (float): Prędkość w metrach na sekundę.
        
    Returns:
        str: Sformatowane tempo (np. "5:30 min/km") lub NO_DATA.
    """
    if speed_m_s and isinstance(speed_m_s, (int, float)) and speed_m_s > 0:
        total_seconds = int(round(1000.0 / speed_m_s))
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d} min/km"
    return NO_DATA


def parse_activity_biomechanics(activity):
    """
    Wyciąga szczegółowe parametry biomechaniczne i fizjologiczne z konkretnego biegu.
    Oblicza średnie tempo z prędkości (m/s), jeśli Garmin nie udostępnia gotowego pola tempa.
    Jeśli parametrów brak, wstawia NO_DATA.
    
    Args:
        activity (dict): Słownik reprezentujący dane aktywności z Garmina.
        
    Returns:
        dict: Słownik zawierający przeparsowane metryki aktywności, lub None jeśli activity jest puste.
    """
    if not activity:
        return None

    dist_str = _get_or_nodata(activity, 'distance', lambda x: f"{x / 1000:.2f} km" if x > 0 else NO_DATA)
    if dist_str == NO_DATA and activity.get('distance', 0) > 0:
        dist_str = f"{activity.get('distance') / 1000:.2f} km"
        
    duration_str = _get_or_nodata(activity, 'duration', lambda x: f"{x / 60:.1f} min" if x > 0 else NO_DATA)

    # Średnie tempo
    avg_speed_m_s = activity.get('averageSpeed')
    avg_pace_raw = activity.get('averagePace') or activity.get('avgPace')
    pace_str = str(avg_pace_raw) if avg_pace_raw else _speed_to_pace_str(avg_speed_m_s)

    start_time_raw = activity.get('startTimeLocal', '')
    start_time_str = NO_DATA
    if start_time_raw and len(start_time_raw) >= 16:
        start_time_str = start_time_raw[11:16]
    elif start_time_raw:
        start_time_str = start_time_raw

    # Tętno
    avg_hr_str = _get_or_nodata(activity, 'averageHR', lambda x: f"{int(round(x))} bpm" if isinstance(x, (int, float)) else NO_DATA)
    max_hr_str = _get_or_nodata(activity, 'maxHR', lambda x: f"{int(round(x))} bpm" if isinstance(x, (int, float)) else NO_DATA)

    # Kadencja
    raw_cad = activity.get('averageRunningCadenceInStepsPerMinute') or activity.get('averageRunCadence')
    avg_cadence_str = f"{int(round(raw_cad))} spm" if raw_cad is not None else NO_DATA

    raw_max_cad = activity.get('maxRunningCadenceInStepsPerMinute') or activity.get('maxRunCadence')
    max_cadence_str = f"{int(round(raw_max_cad))} spm" if raw_max_cad is not None else NO_DATA

    # Długość kroku
    stride_str = _get_or_nodata(activity, 'avgStrideLength', lambda x: f"{x / 100:.2f} m" if x > 0 else NO_DATA)

    # Czas kontaktu z podłożem i oscylacje
    gct_str = _get_or_nodata(activity, 'avgGroundContactTime', lambda x: f"{x:.1f} ms" if isinstance(x, (int, float)) else NO_DATA)
    vo_str = _get_or_nodata(activity, 'avgVerticalOscillation', lambda x: f"{x:.2f} cm" if isinstance(x, (int, float)) else NO_DATA)
    vr_str = _get_or_nodata(activity, 'avgVerticalRatio', lambda x: f"{x:.2f} %" if isinstance(x, (int, float)) else NO_DATA)

    # Przewyższenia
    elevation_gain_str = _get_or_nodata(activity, 'elevationGain', lambda x: f"{int(round(x))} m")
    elevation_loss_str = _get_or_nodata(activity, 'elevationLoss', lambda x: f"{int(round(x))} m")

    # Obciążenie treningowe
    ate = activity.get('aerobicTrainingEffect')
    label = activity.get('trainingEffectLabel', '')
    label_str = f" ({label})" if label else ""
    aerobic_te_str = f"{ate:.1f}/5.0{label_str}" if isinstance(ate, (int, float)) else NO_DATA

    anaerobic_te_str = _get_or_nodata(activity, 'anaerobicTrainingEffect', lambda x: f"{x:.1f}/5.0" if isinstance(x, (int, float)) else NO_DATA)
    power_str = _get_or_nodata(activity, 'avgPower', lambda x: f"{int(round(x))} W" if isinstance(x, (int, float)) else NO_DATA)

    type_key = activity.get('activityType', {}).get('typeKey', '')
    is_run = 'run' in type_key.lower() if type_key else True

    res = {
        "name": activity.get('activityName', 'Aktywność'),
        "is_run": is_run,
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
                lap_pace = _speed_to_pace_str(lap_speed)

                gap_speed = lap.get('avgGradeAdjustedSpeed', 0)
                gap_pace = _speed_to_pace_str(gap_speed)

                if lap.get('averageHR') is not None and lap.get('maxHR') is not None:
                    hr_str = f"{int(lap['averageHR'])} / {int(lap['maxHR'])} bpm"
                elif lap.get('averageHR') is not None:
                    hr_str = f"{int(lap['averageHR'])} bpm"
                elif lap.get('maxHR') is not None:
                    hr_str = f"max {int(lap['maxHR'])} bpm"
                else:
                    hr_str = NO_DATA

                ascent = f"+{int(lap['elevationGain'])}m" if lap.get('elevationGain') is not None else "+0m"
                descent = f"-{int(lap['elevationLoss'])}m" if lap.get('elevationLoss') is not None else "-0m"
                elev_str = f"{ascent} / {descent}"

                avg_pwr = f"{int(lap['averagePower'])} W" if lap.get('averagePower') is not None else NO_DATA

                raw_cad_lap = lap.get('averageRunCadence') or lap.get('averageRunningCadenceInStepsPerMinute')
                avg_cad = f"{int(round(raw_cad_lap))} spm" if raw_cad_lap is not None else NO_DATA

                gct_lap = f"{lap['groundContactTime']:.1f} ms" if lap.get('groundContactTime') is not None else NO_DATA
                stride_lap = f"{lap['strideLength']/100:.2f} m" if lap.get('strideLength') is not None else NO_DATA
                vert_osc_lap = f"{lap['verticalOscillation']:.2f} cm" if lap.get('verticalOscillation') is not None else NO_DATA

                split_row = (
                    f"| {lap_num} | {lap_dist:.2f} km | {dur_str} | {lap_pace} | {gap_pace} | "
                    f"{hr_str} | {avg_cad} | {stride_lap} | {gct_lap} | {vert_osc_lap} | "
                    f"{avg_pwr} | {elev_str} |"
                )
                parsed_splits.append(split_row)

    res["splits"] = parsed_splits
    return res


def _parse_hrv_summary(hrv_raw):
    """
    Parsuje status i średnie wartości HRV z surowych danych Garmina.
    
    Args:
        hrv_raw (dict): Słownik zawierający surowe dane HRV.
        
    Returns:
        str: Sformatowany łańcuch znaków z podsumowaniem HRV lub NO_DATA.
    """
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


def _parse_rhr_and_sleep(stats_raw, sleep_raw):
    """
    Parsuje tętno spoczynkowe RHR oraz dane snu (score, fazy głęboka/REM, wnioski).
    
    Args:
        stats_raw (dict): Słownik zawierający dzienne statystyki (zawiera RHR).
        sleep_raw (dict): Dane dotyczące snu.
        
    Returns:
        dict: Słownik zawierający informacje o rhr, sleep_score, deep_sleep, rem_sleep, sleep_insights.
    """
    result = {
        "rhr": NO_DATA,
        "sleep_score": NO_DATA,
        "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA,
        "sleep_insights": NO_DATA
    }

    rhr_str = NO_DATA
    if stats_raw:
        today_val = stats_raw.get('restingHeartRate')
        if today_val is not None:
            today_rhr = int(today_val)
            avg_7d_str = ""
            avg_7d = stats_raw.get('lastSevenDaysAvgRestingHeartRate')
            if avg_7d is not None:
                diff = today_rhr - int(avg_7d)
                diff_sign = f"+{diff}" if diff > 0 else f"{diff}"
                avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {diff_sign} bpm)"
            rhr_str = f"{today_rhr} bpm{avg_7d_str}"

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
    """
    Ekstrahuje wartości liczbowe z tablicy bodyBatteryValuesArray.
    
    Args:
        bb_raw (list|dict): Surowe dane Body Battery.
        
    Returns:
        list: Lista wartości całkowitych lub zmiennoprzecinkowych reprezentujących Body Battery.
    """
    if not bb_raw:
        return []
    bb_entry = bb_raw[0] if isinstance(bb_raw, list) and bb_raw else (bb_raw if isinstance(bb_raw, dict) else None)
    if not bb_entry:
        return []
    bb_values = bb_entry.get('bodyBatteryValuesArray', [])
    return [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]


def _parse_steps_info(stats_raw, include_active_kcal=True):
    """
    Parsuje kroki i opcjonalnie aktywne kalorie.
    
    Args:
        stats_raw (dict): Słownik zawierający dzienne statystyki (kroki, kalorie).
        include_active_kcal (bool, optional): Czy włączyć aktywne kalorie do wyniku. Defaults to True.
        
    Returns:
        str: Sformatowany ciąg znaków z krokami i ew. kaloriami lub NO_DATA.
    """
    if not stats_raw:
        return NO_DATA
    steps = stats_raw.get('totalSteps')
    if steps is None:
        return NO_DATA
    cals = stats_raw.get('activeKilocalories') if include_active_kcal else None
    cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
    return f"{steps} kroków{cals_str}"


def _parse_stress_info(stress_raw, include_qualifier=True):
    """
    Parsuje poziom stresu i opcjonalnie kwalifikator słowny.
    
    Args:
        stress_raw (dict): Słownik z informacjami o stresie.
        include_qualifier (bool, optional): Czy włączyć opis słowny stresu. Defaults to True.
        
    Returns:
        str: Sformatowany opis poziomu stresu lub NO_DATA.
    """
    if not stress_raw:
        return NO_DATA
    s_level = stress_raw.get('avgStressLevel')
    if s_level is None or s_level == -1:
        return NO_DATA
    qual = stress_raw.get('stressQualifier') if include_qualifier else None
    qual_str = f" ({qual})" if qual else ""
    return f"Średni poziom stresu: {s_level}/100{qual_str}"


def _extract_exercise_tables(text):
    """
    Wyszukuje i wyciąga tabele Markdown zawierające ćwiczenia biegowe (serie, powtórzenia)
    oraz siłowe (zestawienie ćwiczeń, ciężary, serie, powtórzenia).
    
    Args:
        text (str): Tekst w formacie Markdown do przeszukania.
        
    Returns:
        list: Lista stringów, z których każdy reprezentuje pojedynczą tabelę ćwiczeń.
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


def _format_historical_activities_text(activities_list, date_str=None, history_dir=HISTORY_DIR):
    """
    Formatuje listę aktywności z poprzedniego dnia jako zwarty tekst poglądowy.
    Uwzględnia aktywności biegowe z Garmina oraz treningi siłowe.
    
    Args:
        activities_list (list): Lista aktywności do sformatowania.
        date_str (str, optional): Data z jaką powiązane są aktywności. Defaults to None.
        history_dir (str, optional): Katalog z historią treningów. Defaults to HISTORY_DIR.
        
    Returns:
        str: Sformatowany wielolinijkowy tekst reprezentujący jednostki treningowe.
    """
    acts_texts = []
    if activities_list:
        acts_sorted = sorted(
            activities_list,
            key=lambda x: str(x.get('startTimeLocal') or x.get('startTimeGMT') or x.get('beginTimestamp', 0))
        )
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

    # Sprawdzamy czy dla danej daty w historii istnieje odnotowany trening siłowy
    if date_str and os.path.exists(history_dir):
        year, month = date_str.split('-')[:2]
        hist_file = os.path.join(history_dir, year, month, f"{date_str}.md")
        if os.path.exists(hist_file):
            try:
                with open(hist_file, "r", encoding="utf-8") as hf:
                    h_content = hf.read()

                is_strength = bool(RE_STRENGTH_KW.search(h_content))
                if is_strength:
                    tables = _extract_exercise_tables(h_content)
                    strength_tables = []
                    for tbl in tables:
                        header = tbl.split("\n")[0].lower()
                        if any(k in header for k in ["ćwiczen", "obciążen", "rpe", "łańcuch", "partia", "ruch", "exercise", "weight"]):
                            strength_tables.append(tbl)

                    profile_m = RE_PROFILE_HEADER.search(h_content)
                    variant_m = RE_VARIANT_B_HEADER.search(h_content)
                    profile_str = ""
                    if profile_m:
                        profile_str = f" ({profile_m.group(1).strip()})"
                    elif variant_m:
                        profile_str = f" ({variant_m.group(1).strip()})"

                    table_text = ("\n    * Zestawienie ćwiczeń:\n" + "\n\n".join(strength_tables)) if strength_tables else ""
                    strength_entry = (
                        f"  [Trening siłowy{profile_str} - raport z {date_str}]:\n"
                        f"    * Zarejestrowano jednostkę siłową (raport z historii treningowej){table_text}"
                    )
                    acts_texts.append(strength_entry)
            except Exception as e:
                logger.warning(f"Błąd odczytu historii {hist_file}: {e}")

    return "\n\n".join(acts_texts) if acts_texts else "Brak aktywności (dzień wolny)"


def parse_garmin_data(data, target_date=None):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina dla trybu 'daily'.
    
    Args:
        data (dict): Pełne dane pobrane z Garmina.
        target_date (datetime.date, optional): Data docelowa. Defaults to None.
        
    Returns:
        dict: Przeparsowane najważniejsze metryki dnia dzisiejszego i wczorajszego.
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
    parsed.update(_parse_rhr_and_sleep(today_data.get('stats'), today_data.get('sleep')))

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
    yesterday_date_str = yesterday_data.get('date')
    if not yesterday_date_str and target_date:
        yesterday_date_str = (target_date - datetime.timedelta(days=1)).isoformat()
    parsed['yesterday_training'] = _format_historical_activities_text(
        yesterday_data.get('activities', []),
        date_str=yesterday_date_str
    )
    parsed['yesterday_steps'] = _parse_steps_info(yesterday_data.get('stats'), include_active_kcal=False)
    parsed['yesterday_stress'] = _parse_stress_info(yesterday_data.get('stress'), include_qualifier=False)

    return parsed


def process_and_display_activities(raw_acts, date_str):
    """
    Sortuje chronologicznie pobrane aktywności, parsuje ich metryki biomechaniczne
    oraz wyświetla czytelne podsumowanie w konsoli.
    
    Args:
        raw_acts (list): Surowa lista aktywności.
        date_str (str): Data powiązana z aktywnościami.
        
    Returns:
        tuple: Krotka (posortowane_surowe_aktywności, lista_przeparsowanych_statystyk).
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
            
            is_run = act_st.get('is_run', True)
            exclude_keys = ['splits', 'name', 'distance', 'pace', 'start_time', 'is_run']
            if not is_run:
                exclude_keys.extend(['avg_cadence', 'max_cadence', 'stride_length', 
                                     'ground_contact_time', 'vertical_oscillation', 'vertical_ratio'])
                                     
            for k, v in act_st.items():
                if k not in exclude_keys:
                    print(f"   - {k}: {v}")

    return sorted_acts, parsed_stats


def determine_workout_date(default_date, acts, stats):
    """
    Ustala datę wykonania treningu na podstawie pierwszej aktywności lub zwraca datę domyślną.
    
    Args:
        default_date (datetime.date): Data domyślna.
        acts (list): Lista aktywności.
        stats (list): Dodatkowe statystyki.
        
    Returns:
        str: Data w formacie ISO (YYYY-MM-DD).
    """
    if stats and acts:
        first_raw_act = acts[0]
        act_start = first_raw_act.get('startTimeLocal', '')
        if len(act_start) >= 10:
            return act_start[:10]
    return default_date.isoformat() if hasattr(default_date, 'isoformat') else str(default_date)


# ==============================================================================
# 2. KOMUNIKACJA I POBIERANIE DANYCH Z GARMIN CONNECT
# ==============================================================================

def _dump_tokens_safe(client, tokenstore_dir):
    """
    Bezpieczny zapis tokenów dla różnych wersji biblioteki garminconnect.
    
    Args:
        client (Garmin): Obiekt klienta Garmin.
        tokenstore_dir (str): Ścieżka do katalogu zapisu tokenów.
        
    Returns:
        None
    """
    try:
        if hasattr(client, "dump"):
            client.dump(tokenstore_dir)
        elif hasattr(client, "client") and hasattr(client.client, "dump"):
            client.client.dump(tokenstore_dir)
        elif hasattr(client, "garth") and hasattr(client.garth, "dump"):
            client.garth.dump(tokenstore_dir)
    except Exception as e:
        logger.debug(f"Manualny zrzut tokenów nie był wymagany lub zwrócił błąd: {e}")


def get_garmin_client(email, password):
    """
    Inicjalizuje połączenie i loguje do Garmin Connect.
    Obsługuje bezpieczne cache'owanie tokenów sesji OAuth (tokenstore) w ~/.garminconnect.
    
    Args:
        email (str): Adres e-mail konta Garmin.
        password (str): Hasło do konta Garmin.
        
    Returns:
        Garmin: Zalogowany instancja klienta Garmin.
    """
    tokenstore_dir = os.path.expanduser(os.getenv("GARMIN_TOKENS_DIR", "~/.garminconnect"))
    os.makedirs(tokenstore_dir, exist_ok=True)
    token_file = os.path.join(tokenstore_dir, "garmin_tokens.json")

    # Obsługa tokenów przekazanych bezpośrednio w zmiennych środowiskowych (np. GitHub Secret)
    tokens_base64 = os.getenv("GARMIN_TOKENS_BASE64")
    tokens_json = os.getenv("GARMIN_TOKENS_JSON")

    if tokens_base64 and tokens_base64.strip():
        try:
            import base64
            decoded_tokens = base64.b64decode(tokens_base64.strip()).decode("utf-8")
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(decoded_tokens)
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                pass
            logger.info("Zainicjalizowano plik sesji z sekretu GARMIN_TOKENS_BASE64.")
        except Exception as e:
            logger.warning(f"Nie udało się załadować tokenów z GARMIN_TOKENS_BASE64: {e}")
    elif tokens_json and tokens_json.strip():
        try:
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(tokens_json.strip())
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                pass
            logger.info("📄 Zainicjalizowano plik sesji z sekretu GARMIN_TOKENS_JSON.")
        except Exception as e:
            logger.warning(f"Nie udało się załadować tokenów z GARMIN_TOKENS_JSON: {e}")

    logger.info("🚀 Inicjalizacja połączenia z Garmin Connect...")

    # Logowanie z obsługą magazynu tokenów (garminconnect >= 0.3.0)
    try:
        client = Garmin(email, password)
        client.login(tokenstore_dir)
        _dump_tokens_safe(client, tokenstore_dir)
        logger.info("✅ Pomyślnie zalogowano do Garmin Connect.")
        return client
    except Exception as e:
        err_msg = str(e)
        logger.error(f"❌ Błąd logowania do Garmin Connect: {err_msg}")
        if "429" in err_msg or "rate limit" in err_msg.lower():
            logger.error(
                "❌ Otrzymano błąd 429 (Zbyt wiele zapytań / Rate Limited przez Garmina). "
                "Serwery Garmin tymczasowo zablokowały logowanie hasłem z tego adresu IP (częste w chmurze / GitHub Actions). "
                "Aby uniezależnić się od blokad IP, wygeneruj token lokalnie na komputerze (plik ~/.garminconnect/garmin_tokens.json) "
                "i dodaj go w GitHub Secrets jako GARMIN_TOKENS_BASE64."
            )
        sys.exit(1)


def _fetch_activity_splits_and_weather(client, acts):
    """
    Uzupełnia listę aktywności o splity kilometrowe oraz dane o pogodzie.
    
    Args:
        client (Garmin): Obiekt zalogowanego klienta Garmin.
        acts (list): Lista aktywności pobranych z Garmina.
        
    Returns:
        list: Lista aktywności z ewentualnie doklejonymi splitami i pogodą.
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


def _safe_fetch(func, log_msg, *args, **kwargs):
    """
    Pomocnicza funkcja do bezpiecznego wywoływania metod API z łapaniem wyjątków.
    
    Args:
        func (callable): Funkcja/metoda do wywołania.
        log_msg (str): Wiadomość logowania na wypadek błędu.
        *args: Argumenty pozycyjne dla funkcji.
        **kwargs: Argumenty nazwane dla funkcji.
        
    Returns:
        Any: Wynik działania funkcji lub None w przypadku błędu.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"{log_msg}: {e}")
        return None


def _fetch_night_recovery_biometrics(client, date_str):
    """
    Pobiera nocne dane regeneracyjne (sen, HRV) dla podanej daty.
    
    Args:
        client (Garmin): Obiekt zalogowanego klienta Garmin.
        date_str (str): Data, dla której mają zostać pobrane dane.
        
    Returns:
        dict: Słownik z danymi o śnie i HRV.
    """
    return {
        'sleep': _safe_fetch(client.get_sleep_data, f"Nie udało się pobrać danych snu z {date_str}", date_str),
        'hrv': _safe_fetch(client.get_hrv_data, f"Nie udało się pobrać HRV z {date_str}", date_str)
    }


def _fetch_day_activities_and_load(client, date_str, include_body_battery=False):
    """
    Pobiera dzienny stres, bilans kroków/kalorii oraz aktywności z danego dnia.
    Opcjonalnie pobiera także całodzienne Body Battery.
    
    Args:
        client (Garmin): Obiekt zalogowanego klienta Garmin.
        date_str (str): Data, dla której mają zostać pobrane dane.
        include_body_battery (bool, optional): Czy dołączyć Body Battery. Defaults to False.
        
    Returns:
        dict: Słownik zawierający dane stresu, statystyk (kroki) oraz aktywności.
    """
    day_data = {
        'stress': _safe_fetch(client.get_stress_data, f"Nie udało się pobrać stresu z {date_str}", date_str),
        'stats': _safe_fetch(client.get_user_summary, f"Nie udało się pobrać bilansu kroków z {date_str}", date_str)
    }

    if include_body_battery:
        day_data['body_battery'] = _safe_fetch(client.get_body_battery, f"Nie udało się pobrać Body Battery z {date_str}", date_str)

    acts = _safe_fetch(client.get_activities_by_date, f"Nie udało się pobrać aktywności z {date_str}", date_str, date_str)
    if acts is not None:
        day_data['activities'] = _fetch_activity_splits_and_weather(client, acts)

    return day_data


def fetch_garmin_data_daily(client, target_date):
    """
    Pobiera dane z Garmina dla trybu dziennego (daily).
    Obejmuje wskaźniki dzisiejsze oraz wczorajsze jako tło.
    
    Args:
        client (Garmin): Zalogowany obiekt klienta Garmin.
        target_date (datetime.date): Główna data analizy.
        
    Returns:
        dict: Słownik grupujący dane na klucze 'today' oraz 'yesterday'.
    """
    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()

    logger.info(f"🚀 Pobieranie danych z Garmina dla analizy dziennej (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    today_data = _fetch_night_recovery_biometrics(client, today_str)
    today_load = _fetch_day_activities_and_load(client, today_str, include_body_battery=True)
    today_data.update(today_load)
    today_data['date'] = today_str

    yesterday_data = _fetch_day_activities_and_load(client, yesterday_str, include_body_battery=False)
    yesterday_data['date'] = yesterday_str

    return {
        'today': today_data,
        'yesterday': yesterday_data
    }


def load_or_fetch_garmin_data(target_date, dump_file, mode="daily", debug=False):
    """
    Wczytuje dane z pliku lokalnego lub pobiera je bezpośrednio z Garmin Connect dla trybu 'daily'.
    
    Args:
        target_date (datetime.date): Data docelowa pobierania.
        dump_file (str): Ścieżka do zapisu/odczytu zrzutu pobranych danych.
        mode (str, optional): Tryb pobierania (domyślnie "daily"). Defaults to "daily".
        debug (bool, optional): Flaga oznaczająca tryb debug (zapis w piaskownicy). Defaults to False.
        
    Returns:
        dict: Złożone dane pobrane lub wczytane z Garmina.
    """
    use_local_data = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]
    if use_local_data:
        read_file = os.path.join("debug", "garmin_dump.json") if (debug and os.path.exists(os.path.join("debug", "garmin_dump.json"))) else dump_file
        logger.info(f"📄 Omijam logowanie. Wczytuję surowe dane z pliku lokalnego: {read_file}...")
        try:
            with open(read_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"❌ Nie znaleziono pliku {read_file}. Uruchom skrypt z USE_LOCAL_DATA='False', aby go stworzyć!")
            sys.exit(1)

    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    if not garmin_email or not garmin_password:
        logger.error("❌ Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD w pliku .env!")
        sys.exit(1)

    client = get_garmin_client(garmin_email, garmin_password)
    raw_data = fetch_garmin_data_daily(client, target_date)

    target_dump_file = os.path.join("debug", "garmin_dump.json") if debug else dump_file
    if debug:
        os.makedirs("debug", exist_ok=True)

    with open(target_dump_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=4, ensure_ascii=False)
    if debug:
        logger.info(f"📄 [DEBUG] Surowe dane zapisano w trybie piaskownicy do pliku: {target_dump_file}")
        print(f"📄 [DEBUG] Zapisano surowy zrzut Garmina do: {target_dump_file} (Plik {dump_file} pozostał nienaruszony)")
    else:
        logger.info(f"✅ Surowe dane zapisano pomyślnie do pliku {target_dump_file}.")
    return raw_data
