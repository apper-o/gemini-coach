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

def _get_or_nodata(d, keys, formatter=None):
    """
    Pobiera wartość ze słownika, sprawdzając podane klucze. Jeśli żadnego nie ma, zwraca NO_DATA.
    
    Args:
        d (dict): Słownik, z którego pobierana jest wartość.
        keys (str | list): Klucz (lub lista kluczy zapasowych) do pobrania ze słownika.
        formatter (callable, optional): Funkcja formatująca pobraną wartość. Defaults to None.
        
    Returns:
        Any: Pobrana (i ewentualnie sformatowana) wartość lub NO_DATA w przypadku jej braku.
    """
    if not isinstance(d, dict):
        return NO_DATA
        
    if isinstance(keys, str):
        keys = [keys]
        
    val = None
    for k in keys:
        if d.get(k) is not None:
            val = d.get(k)
            break
            
    if val is None:
        return NO_DATA
        
    if formatter:
        try:
            return formatter(val)
        except Exception:
            return NO_DATA
    return val

# ==============================================================================
# PARSERY BIOMETRII I BIOMECHANIKI AKTYWNOŚCI
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
        
    duration_str = _get_or_nodata(activity, 'duration', lambda x: f"{x / 60:.1f} min" if x > 0 else NO_DATA)

    # Średnie tempo
    pace_str = _get_or_nodata(activity, ['averagePace', 'avgPace'], str)
    if pace_str == NO_DATA:
        pace_str = _get_or_nodata(activity, 'averageSpeed', _speed_to_pace_str)

    start_time_str = _get_or_nodata(activity, 'startTimeLocal', lambda x: x[11:16] if isinstance(x, str) and len(x) >= 16 else x)

    # Tętno
    avg_hr_str = _get_or_nodata(activity, 'averageHR', lambda x: f"{int(round(x))} bpm" if isinstance(x, (int, float)) else NO_DATA)
    max_hr_str = _get_or_nodata(activity, 'maxHR', lambda x: f"{int(round(x))} bpm" if isinstance(x, (int, float)) else NO_DATA)

    # Kadencja
    avg_cadence_str = _get_or_nodata(activity, ['averageRunningCadenceInStepsPerMinute', 'averageRunCadence'], lambda x: f"{int(round(x))} spm")

    max_cadence_str = _get_or_nodata(activity, ['maxRunningCadenceInStepsPerMinute', 'maxRunCadence'], lambda x: f"{int(round(x))} spm")

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
    label_str = f" ({activity.get('trainingEffectLabel')})" if activity.get('trainingEffectLabel') else ""
    aerobic_te_str = _get_or_nodata(activity, 'aerobicTrainingEffect', lambda x: f"{x:.1f}/5.0{label_str}" if isinstance(x, (int, float)) else NO_DATA)

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
    status = _get_or_nodata(hrv_summary, 'status')
    baseline_info = hrv_summary.get('baseline', {})
    b_low = baseline_info.get('balancedLow')
    b_high = baseline_info.get('balancedUpper')

    last_night_str = _get_or_nodata(hrv_summary, 'lastNightAvg', lambda x: f"{x} ms")
    weekly_avg_str = _get_or_nodata(hrv_summary, 'weeklyAvg', lambda x: f"{x} ms")
    baseline_str = f"{b_low}–{b_high} ms" if b_low and b_high else NO_DATA

    return f"{status} {last_night_str} (Średnia 7-dniowa: {weekly_avg_str}, Norma bazowa: {baseline_str})"


def _parse_rhr_and_sleep(stats_raw, sleep_raw):
    """
    Parsuje tętno spoczynkowe RHR oraz dane snu (score, fazy, oddechy, stres snu).
    """
    result = {
        "rhr": NO_DATA,
        "sleep_score": NO_DATA,
        "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA,
        "sleep_stress": NO_DATA,
        "sleep_respiration": NO_DATA
    }

    rhr_str = NO_DATA
    if stats_raw:
        today_val = stats_raw.get('restingHeartRate')
        if today_val is not None:
            today_rhr = int(today_val)
            avg_7d = stats_raw.get('lastSevenDaysAvgRestingHeartRate')
            avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {'+' if today_rhr - int(avg_7d) > 0 else ''}{today_rhr - int(avg_7d)} bpm)" if avg_7d is not None else ""
            rhr_str = f"{today_rhr} bpm{avg_7d_str}"

    avg_night_hr = None
    if sleep_raw and 'dailySleepDTO' in sleep_raw:
        sleep_dto = sleep_raw['dailySleepDTO']
        avg_night_hr = _get_or_nodata(sleep_dto, 'avgHeartRate', lambda x: f"{int(x)} bpm")
        avg_night_hr = avg_night_hr if avg_night_hr != NO_DATA else None

        result['sleep_score'] = _get_or_nodata(sleep_dto.get('sleepScores', {}).get('overall', {}), 'value', lambda x: f"{x}/100")
        result['deep_sleep'] = _get_or_nodata(sleep_dto, 'deepSleepSeconds', lambda x: f"{x // 3600}h {(x % 3600) // 60}m")
        result['rem_sleep'] = _get_or_nodata(sleep_dto, 'remSleepSeconds', lambda x: f"{x // 3600}h {(x % 3600) // 60}m")



    if avg_night_hr:
        result['rhr'] = f"{rhr_str} (Średnie tętno z całej nocy: {avg_night_hr})"
    else:
        result['rhr'] = rhr_str

    return result


def _parse_body_battery_values(bb_raw):
    """
    Wyciąga wartości liczbowe z tablicy bodyBatteryValuesArray.
    
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


def _parse_steps_info(stats_raw):
    """
    Parsuje kroki oraz aktywne kalorie z danego dnia.
    
    Args:
        stats_raw (dict): Słownik zawierający dzienne statystyki (kroki, kalorie).
        
    Returns:
        str: Sformatowany ciąg znaków z krokami i kaloriami lub NO_DATA.
    """
    if not stats_raw:
        return NO_DATA
    cals = stats_raw.get('activeKilocalories')
    cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
    return _get_or_nodata(stats_raw, 'totalSteps', lambda x: f"{x} kroków{cals_str}")


def _parse_stress_info(stress_raw):
    """
    Parsuje średni poziom stresu z dnia.
    
    Args:
        stress_raw (dict): Słownik z informacjami o stresie.
        
    Returns:
        str: Sformatowany opis poziomu stresu lub NO_DATA.
    """
    if not stress_raw:
        return NO_DATA
    return _get_or_nodata(stress_raw, 'avgStressLevel', lambda x: f"Średni poziom stresu: {x}/100" if x != -1 else NO_DATA)


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


def _fetch_historical_strength_training(date_str, history_dir=HISTORY_DIR):
    """
    Wyszukuje i parsuje odnotowany trening siłowy z lokalnej historii treningów (pliki Markdown).
    
    Args:
        date_str (str): Data treningu w formacie YYYY-MM-DD.
        history_dir (str, optional): Katalog z historią. Defaults to HISTORY_DIR.
        
    Returns:
        str: Sformatowany wpis o treningu siłowym lub pusty ciąg, jeśli brak.
    """
    if not date_str or not os.path.exists(history_dir):
        return ""
        
    try:
        year, month = date_str.split('-')[:2]
        hist_file = os.path.join(history_dir, year, month, f"{date_str}.md")
        if not os.path.exists(hist_file):
            return ""
            
        with open(hist_file, "r", encoding="utf-8") as hf:
            h_content = hf.read()

        if not bool(RE_STRENGTH_KW.search(h_content)):
            return ""
            
        tables = _extract_exercise_tables(h_content)
        strength_tables = []
        for tbl in tables:
            header = tbl.split("\n")[0].lower()
            if any(k in header for k in ["ćwiczen", "obciążen", "rpe", "łańcuch", "partia", "ruch", "exercise", "weight"]):
                strength_tables.append(tbl)

        profile_m = RE_PROFILE_HEADER.search(h_content)
        variant_m = RE_VARIANT_B_HEADER.search(h_content)
        profile_str = f" ({profile_m.group(1).strip()})" if profile_m else (f" ({variant_m.group(1).strip()})" if variant_m else "")

        table_text = ("\n    * Zestawienie ćwiczeń:\n" + "\n\n".join(strength_tables)) if strength_tables else ""
        return (
            f"  [Trening siłowy{profile_str} - raport z {date_str}]:\n"
            f"    * Zarejestrowano jednostkę siłową (raport z historii treningowej){table_text}"
        )
    except Exception as e:
        logger.warning(f"Błąd odczytu historii treningu siłowego z {date_str}: {e}")
        return ""


def _format_historical_activities_text(activities_list):
    """
    Formatuje listę aktywności z poprzedniego dnia z Garmina jako zwarty tekst poglądowy.
    
    Args:
        activities_list (list): Lista aktywności do sformatowania.
        
    Returns:
        str: Sformatowany wielolinijkowy tekst reprezentujący jednostki treningowe lub pusty ciąg.
    """
    acts_texts = []
    if not activities_list:
        return ""
        
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

    return "\n\n".join(acts_texts)


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
        "sleep_stress": NO_DATA,
        "sleep_respiration": NO_DATA,
        "body_battery": NO_DATA,
        "morning_body_battery": NO_DATA,
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
        parsed['morning_body_battery'] = str(max_bb)
        parsed['body_battery'] = str(current_bb)

    # Koszt dzisiejszego dnia
    parsed['today_steps'] = _parse_steps_info(today_data.get('stats'))
    parsed['today_stress'] = _parse_stress_info(today_data.get('stress'))

    # Wczorajsze tło historyczne
    yesterday_date_str = yesterday_data.get('date')
    if not yesterday_date_str and target_date:
        yesterday_date_str = (target_date - datetime.timedelta(days=1)).isoformat()
    garmin_acts_text = _format_historical_activities_text(yesterday_data.get('activities', []))
    strength_act_text = _fetch_historical_strength_training(yesterday_date_str)
    
    combined_acts = [t for t in (garmin_acts_text, strength_act_text) if t]
    parsed['yesterday_training'] = "\n\n".join(combined_acts) if combined_acts else "Brak aktywności (dzień wolny)"
    parsed['yesterday_steps'] = _parse_steps_info(yesterday_data.get('stats'))
    parsed['yesterday_stress'] = _parse_stress_info(yesterday_data.get('stress'))

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


# ==============================================================================
# KOMUNIKACJA I POBIERANIE DANYCH Z GARMIN CONNECT
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
                act['splits_data'] = _safe_fetch(client.get_activity_splits, f"Nie udało się pobrać splitów dla aktywności {act_id}", act_id)
                act['weather_data'] = _safe_fetch(client.get_activity_weather, f"Nie udało się pobrać pogody dla aktywności {act_id}", act_id)
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


def fetch_garmin_data(target_date):
    """
    Loguje się do Garmin Connect i pobiera komplet danych dla analizy dziennej.
    Obejmuje pełne wskaźniki dzisiejsze (sen, hrv, body battery, treningi) oraz wczorajsze jako tło porównawcze.
    
    Args:
        target_date (datetime.date): Główna data analizy.
        
    Returns:
        dict: Słownik grupujący dane na klucze 'today' oraz 'yesterday'.
    """
    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    if not garmin_email or not garmin_password:
        logger.error("❌ Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD w pliku .env!")
        sys.exit(1)

    client = get_garmin_client(garmin_email, garmin_password)
    
    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()

    logger.info(f"🚀 Pobieranie danych z Garmina dla analizy dziennej (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    today_data = _fetch_night_recovery_biometrics(client, today_str)
    today_data.update(_fetch_day_activities_and_load(client, today_str, include_body_battery=True))
    today_data['date'] = today_str

    yesterday_data = _fetch_day_activities_and_load(client, yesterday_str, include_body_battery=False)
    yesterday_data['date'] = yesterday_str

    return {
        'today': today_data,
        'yesterday': yesterday_data
    }
