"""
garmin_service.py - Moduł komunikacji z Garmin Connect oraz czystych parserów danych biometrycznych i biegowych.
"""

import os
import json
import base64
import datetime
import logging
from garminconnect import Garmin

logger = logging.getLogger(__name__)

# Stałe globalne i progi filtrowania telemetrii
NO_DATA = "Brak danych"
GARMIN_CACHE_DIR_PATH = os.getenv("GARMIN_CACHE_DIR", "garmin_data")
MIN_LAP_DISTANCE_KM = 0.10
MIN_LAP_DURATION_SEC = 20

WEATHER_DESC_PL = {
    "Clear": "Bezchmurnie",
    "Fair": "Pogodnie",
    "Cloudy": "Pochmurno",
    "Mostly Cloudy": "Duże zachmurzenie",
    "Partly Cloudy": "Umiarkowane zachmurzenie",
    "Overcast": "Całkowite zachmurzenie",
    "Rain": "Deszcz",
    "Light Rain": "Lekki deszcz",
    "Heavy Rain": "Mocny deszcz",
    "Snow": "Śnieg",
    "Fog": "Mgła",
    "Windy": "Wietrznie",
}


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
        keys = (keys,)
    val = next((d[k] for k in keys if d.get(k) is not None), None)
    if val is None:
        return NO_DATA
    if formatter:
        try:
            return formatter(val)
        except Exception:
            return NO_DATA
    return val


def _activity_sort_key(act):
    """Zwraca klucz sortowania chronologicznego dla słownika aktywności z Garmina."""
    return str(act.get("startTimeLocal") or act.get("startTimeGMT") or act.get("beginTimestamp", 0))


# ==============================================================================
# CZYSTE PARSERY BIOMETRII I BIOMECHANIKI AKTYWNOŚCI (PURE FUNCTIONS)
# ==============================================================================

def _speed_to_pace_short(speed_m_s):
    """Konwertuje prędkość w m/s na zwięzłe tempo w formacie M:SS (bez jednostki)."""
    if speed_m_s and isinstance(speed_m_s, (int, float)) and speed_m_s > 0:
        total_seconds = int(round(1000.0 / speed_m_s))
        return f"{total_seconds // 60}:{total_seconds % 60:02d}"
    return "-"


def _fmt_sleep_duration(seconds):
    """Formatuje czas trwania snu w sekundach do postaci Xh Ym."""
    return f"{int(seconds) // 3600}h {(int(seconds) % 3600) // 60}m"


def _parse_activity_weather(activity):
    """Wyciąga i tłumaczy warunki pogodowe z danych aktywności Garmina lub czujnika zegarka."""
    weather_info = activity.get("weather_data")
    parts = []
    temp_c = None

    if isinstance(weather_info, dict):
        raw_temp = weather_info.get("temp") if weather_info.get("temp") is not None else weather_info.get("temperature")
        raw_feels = weather_info.get("apparentTemp") if weather_info.get("apparentTemp") is not None else weather_info.get("apparentTemperature")

        # Garmin Connect API weather endpoint zwraca temperaturę w stopniach Fahrenheita
        temp_c = (float(raw_temp) - 32.0) * 5.0 / 9.0 if raw_temp is not None else None
        feels_c = (float(raw_feels) - 32.0) * 5.0 / 9.0 if raw_feels is not None else None

        w_dto, w_type = weather_info.get("weatherTypeDTO"), weather_info.get("weatherType")
        raw_desc = w_dto.get("desc", "") if isinstance(w_dto, dict) else (w_type.get("weatherTypeKey", "") if isinstance(w_type, dict) else "")
        weather_desc = WEATHER_DESC_PL.get(raw_desc, raw_desc)

        if temp_c is not None:
            feels_str = f" (odczuwalna: {feels_c:.1f}°C)" if feels_c is not None and abs(feels_c - temp_c) >= 1.0 else ""
            parts.append(f"Temperatura: {temp_c:.1f}°C{feels_str}")
        if (wind_speed := weather_info.get("windSpeed")) is not None:
            parts.append(f"Wiatr: {wind_speed:.1f} km/h {weather_info.get('windDirectionCompassPoint', '')}".strip())
        if (humidity := weather_info.get("relativeHumidity")) is not None:
            parts.append(f"Wilgotność: {humidity}%")
        if weather_desc:
            parts.append(f"Warunki: {weather_desc}")

    # Fallback na czujnik temperatury zegarka, gdy stacja pogodowa nie zwróciła temperatury
    if temp_c is None:
        min_t, max_t = activity.get("minTemperature"), activity.get("maxTemperature")
        if min_t is not None and max_t is not None:
            parts.append(f"Temperatura (czujnik zegarka): {round((min_t + max_t) / 2, 1):.1f}°C (min: {min_t:.1f}°C, max: {max_t:.1f}°C)")
        elif min_t is not None or max_t is not None:
            parts.append(f"Temperatura (czujnik zegarka): {(min_t if min_t is not None else max_t):.1f}°C")

    return " | ".join(parts) if parts else NO_DATA


def _parse_activity_splits(splits_raw):
    """
    Parsuje surowe dane splitów (lapDTOs) do ustrukturyzowanej listy słowników,
    odrzucając szczątkowy ostatni autolap powstały przy zatrzymaniu zegarka.
    """
    if not isinstance(splits_raw, dict):
        return []

    lap_list = list(splits_raw.get("lapDTOs", []))
    while len(lap_list) > 1 and (
        (lap_list[-1].get("distance") or 0) / 1000 < MIN_LAP_DISTANCE_KM
        or (lap_list[-1].get("duration") or 0) < MIN_LAP_DURATION_SEC
    ):
        lap_list.pop()

    parsed_laps = []
    for idx, lap in enumerate(lap_list, 1):
        lap_dur = lap.get("duration", 0)
        avg_hr, max_hr = lap.get("averageHR"), lap.get("maxHR")
        hr_str = (
            f"{int(avg_hr)}/{int(max_hr)}" if avg_hr is not None and max_hr is not None
            else (str(int(avg_hr)) if avg_hr is not None else (f"max {int(max_hr)}" if max_hr is not None else "-"))
        )
        ascent = int(lap["elevationGain"]) if lap.get("elevationGain") is not None else 0
        descent = int(lap["elevationLoss"]) if lap.get("elevationLoss") is not None else 0
        raw_cad = lap.get("averageRunCadence") or lap.get("averageRunningCadenceInStepsPerMinute")

        parsed_laps.append({
            "lap": idx,
            "distance": f"{lap.get('distance', 0) / 1000:.2f}",
            "time": f"{int(lap_dur // 60)}:{int(lap_dur % 60):02d}",
            "pace": _speed_to_pace_short(lap.get("averageSpeed", 0)),
            "gap": _speed_to_pace_short(lap.get("avgGradeAdjustedSpeed", 0)),
            "hr": hr_str,
            "cadence": str(int(round(raw_cad))) if raw_cad is not None else "-",
            "stride": f"{lap['strideLength'] / 100:.2f}" if lap.get("strideLength") is not None else "-",
            "gct": f"{lap['groundContactTime']:.1f}" if lap.get("groundContactTime") is not None else "-",
            "vo": f"{lap['verticalOscillation']:.2f}" if lap.get("verticalOscillation") is not None else "-",
            "power": str(int(lap["averagePower"])) if lap.get("averagePower") is not None else "-",
            "elevation": f"+{ascent}/-{descent}",
        })
    return parsed_laps


def parse_activity_biomechanics(activity, include_splits=True):
    """
    Czysta funkcja wyciągająca parametry biomechaniczne i fizjologiczne z pojedynczej aktywności.

    Args:
        activity (dict): Słownik reprezentujący dane aktywności z Garmina.
        include_splits (bool, optional): Czy parsować splity kilometrowe. Defaults to True.

    Returns:
        dict | None: Słownik zawierający przeparsowane metryki aktywności lub None.
    """
    if not activity:
        return None

    pace_str = _get_or_nodata(activity, ("averagePace", "avgPace"), str)
    if pace_str == NO_DATA:
        short_pace = _speed_to_pace_short(activity.get("averageSpeed"))
        pace_str = f"{short_pace} min/km" if short_pace != "-" else NO_DATA

    label_str = f" ({activity.get('trainingEffectLabel')})" if activity.get("trainingEffectLabel") else ""
    type_key = (activity.get("activityType") or {}).get("typeKey", "").lower()

    return {
        "name": activity.get("activityName", "Aktywność"),
        "is_run": "run" in type_key if type_key else True,
        "is_swim": "swim" in type_key if type_key else False,
        "start_time": _get_or_nodata(activity, "startTimeLocal", lambda x: x[11:16] if isinstance(x, str) and len(x) >= 16 else x),
        "distance": _get_or_nodata(activity, "distance", lambda x: f"{x / 1000:.2f} km" if x > 0 else NO_DATA),
        "duration": _get_or_nodata(activity, "duration", lambda x: f"{x / 60:.1f} min" if x > 0 else NO_DATA),
        "pace": pace_str,
        "avg_hr": _get_or_nodata(activity, "averageHR", lambda x: f"{int(round(x))} bpm"),
        "max_hr": _get_or_nodata(activity, "maxHR", lambda x: f"{int(round(x))} bpm"),
        "avg_cadence": _get_or_nodata(activity, ("averageRunningCadenceInStepsPerMinute", "averageRunCadence"), lambda x: f"{int(round(x))} spm"),
        "max_cadence": _get_or_nodata(activity, ("maxRunningCadenceInStepsPerMinute", "maxRunCadence"), lambda x: f"{int(round(x))} spm"),
        "stride_length": _get_or_nodata(activity, "avgStrideLength", lambda x: f"{x / 100:.2f} m" if x > 0 else NO_DATA),
        "ground_contact_time": _get_or_nodata(activity, "avgGroundContactTime", lambda x: f"{x:.1f} ms"),
        "vertical_oscillation": _get_or_nodata(activity, "avgVerticalOscillation", lambda x: f"{x:.2f} cm"),
        "vertical_ratio": _get_or_nodata(activity, "avgVerticalRatio", lambda x: f"{x:.2f} %"),
        "elevation_gain": _get_or_nodata(activity, "elevationGain", lambda x: f"{int(round(x))} m"),
        "elevation_loss": _get_or_nodata(activity, "elevationLoss", lambda x: f"{int(round(x))} m"),
        "aerobic_te": _get_or_nodata(activity, "aerobicTrainingEffect", lambda x: f"{x:.1f}/5.0{label_str}"),
        "anaerobic_te": _get_or_nodata(activity, "anaerobicTrainingEffect", lambda x: f"{x:.1f}/5.0"),
        "avg_power": _get_or_nodata(activity, "avgPower", lambda x: f"{int(round(x))} W"),
        "splits": _parse_activity_splits(activity.get("splits_data")) if include_splits else [],
        "weather": _parse_activity_weather(activity),
    }


def _parse_hrv_data(hrv_raw):
    """Parsuje metryki HRV z surowych danych Garmina."""
    result = {"hrv_last_night": NO_DATA, "hrv_baseline_range": NO_DATA, "hrv_status": NO_DATA}
    if not isinstance(hrv_raw, dict):
        return result

    hrv_summary = hrv_raw.get("hrvSummary") or {}
    baseline_info = hrv_summary.get("baseline") or {}
    b_low, b_high = baseline_info.get("balancedLow"), baseline_info.get("balancedUpper")

    last_night_val = _get_or_nodata(hrv_summary, "lastNightAvg", lambda x: f"{int(round(x))} ms")
    weekly_avg_str = _get_or_nodata(hrv_summary, "weeklyAvg", lambda x: f"{int(round(x))} ms")
    baseline_str = f"{int(round(b_low))}–{int(round(b_high))} ms" if b_low is not None and b_high is not None else NO_DATA

    result["hrv_last_night"] = last_night_val
    result["hrv_baseline_range"] = baseline_str
    if any(v != NO_DATA for v in (last_night_val, weekly_avg_str, baseline_str)):
        result["hrv_status"] = f"{last_night_val} (Średnia 7-dniowa: {weekly_avg_str}, Norma bazowa: {baseline_str})"
    return result


def _parse_rhr_and_sleep(stats_raw, sleep_raw):
    """Parsuje tętno spoczynkowe RHR oraz dane architektury snu."""
    result = {
        "rhr": NO_DATA, "rhr_baseline": NO_DATA, "rhr_status": NO_DATA,
        "sleep_score": NO_DATA, "total_sleep_time": NO_DATA,
        "deep_sleep": NO_DATA, "rem_sleep": NO_DATA, "sleep_stress": NO_DATA,
    }

    if isinstance(stats_raw, dict) and stats_raw.get("restingHeartRate") is not None:
        today_rhr = int(round(stats_raw["restingHeartRate"]))
        result["rhr"] = f"{today_rhr} bpm"
        avg_7d = stats_raw.get("lastSevenDaysAvgRestingHeartRate")
        if avg_7d is not None:
            avg_7d_int = int(round(avg_7d))
            result["rhr_baseline"] = f"{avg_7d_int} bpm"
            diff = today_rhr - avg_7d_int
            avg_7d_str = f" (Średnia 7-dniowa: {avg_7d_int} bpm, odchylenie: {'+' if diff > 0 else ''}{diff} bpm)"
        else:
            avg_7d_str = ""
        result["rhr_status"] = f"{today_rhr} bpm{avg_7d_str}"

    if isinstance(sleep_raw, dict) and isinstance(sleep_raw.get("dailySleepDTO"), dict):
        sleep_dto = sleep_raw["dailySleepDTO"]
        result["sleep_score"] = _get_or_nodata((sleep_dto.get("sleepScores") or {}).get("overall") or {}, "value", lambda x: f"{x}/100")
        result["deep_sleep"] = _get_or_nodata(sleep_dto, "deepSleepSeconds", _fmt_sleep_duration)
        result["rem_sleep"] = _get_or_nodata(sleep_dto, "remSleepSeconds", _fmt_sleep_duration)
        result["sleep_stress"] = _get_or_nodata(sleep_dto, "avgSleepStress", lambda x: str(int(round(x))))

        total_sec = sleep_dto.get("sleepTimeSeconds")
        if total_sec is None:
            phase_secs = [sleep_dto.get(k) for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")]
            if any(isinstance(s, (int, float)) for s in phase_secs):
                total_sec = sum(s for s in phase_secs if isinstance(s, (int, float)))
        if isinstance(total_sec, (int, float)) and total_sec > 0:
            result["total_sleep_time"] = _fmt_sleep_duration(total_sec)

    return result


def _format_historical_activities_text(activities_list):
    """Formatuje listę aktywności z poprzedniego dnia z Garmina jako zwięzły opis jednoliniowy."""
    if not activities_list:
        return ""

    acts_texts = []
    for idx, act in enumerate(sorted(activities_list, key=_activity_sort_key), 1):
        act_details = parse_activity_biomechanics(act, include_splits=False)
        if not act_details:
            continue
        time_info = f" [Start: {act_details['start_time']}]" if act_details.get("start_time") and act_details["start_time"] != NO_DATA else ""
        metrics = [
            f"{act_details['distance']} w {act_details['duration']}",
            f"tempo {act_details['pace']}",
            f"HR śr. {act_details['avg_hr']} (max {act_details['max_hr']})",
            f"TE {act_details['aerobic_te']} / {act_details['anaerobic_te']}",
        ]
        if act_details.get("avg_power") and act_details["avg_power"] != NO_DATA:
            metrics.append(f"moc {act_details['avg_power']}")
        if act_details.get("is_run", True) and act_details.get("avg_cadence") != NO_DATA:
            metrics.append(f"kadencja {act_details['avg_cadence']}, GCT {act_details['ground_contact_time']}")
        acts_texts.append(f"[Jednostka {idx}{time_info}] {act_details['name']} ({', '.join(metrics)})")

    return " + ".join(acts_texts)


def parse_garmin_data(data, target_date=None, extra_yesterday_training=None):
    """
    Czysta funkcja (Pure Function) wyciągająca metryki z JSON-ów API Garmina dla trybu 'daily'.
    Nie wykonuje żadnych operacji dyskowych ani sieciowych.

    Args:
        data (dict): Pełne dane pobrane z Garmina.
        target_date (datetime.date, optional): Data docelowa (zachowana dla kompatybilności).
        extra_yesterday_training (str, optional): Dodatkowy opis treningu z poprzedniego dnia (np. siłownia z archiwum).

    Returns:
        dict: Przeparsowane najważniejsze metryki dnia dzisiejszego i wczorajszego.
    """
    parsed = {
        "hrv_last_night": NO_DATA, "hrv_baseline_range": NO_DATA, "hrv_status": NO_DATA,
        "rhr": NO_DATA, "rhr_baseline": NO_DATA, "rhr_status": NO_DATA,
        "sleep_score": NO_DATA, "total_sleep_time": NO_DATA, "deep_sleep": NO_DATA,
        "rem_sleep": NO_DATA, "sleep_stress": NO_DATA,
        "body_battery": NO_DATA, "morning_body_battery": NO_DATA,
        "today_steps": NO_DATA, "today_stress": NO_DATA,
        "yesterday_training": "Brak aktywności (dzień wolny)",
        "yesterday_steps": NO_DATA, "yesterday_stress": NO_DATA,
    }
    if not data:
        return parsed

    def _fmt_steps(stats):
        if not stats:
            return NO_DATA
        cals = stats.get("activeKilocalories")
        cals_str = f" (aktywne: {int(round(cals))} kcal)" if cals else ""
        return _get_or_nodata(stats, "totalSteps", lambda x: f"{x}{cals_str}")

    def _fmt_stress(stress):
        return _get_or_nodata(stress, "avgStressLevel", lambda x: f"{x}/100" if x != -1 else NO_DATA)

    today_data = data.get("today") or {}
    yesterday_data = data.get("yesterday") or {}

    parsed.update(_parse_hrv_data(today_data.get("hrv")))
    parsed.update(_parse_rhr_and_sleep(today_data.get("stats"), today_data.get("sleep")))

    bb_raw = today_data.get("body_battery")
    bb_entry = bb_raw[0] if isinstance(bb_raw, list) and bb_raw else (bb_raw if isinstance(bb_raw, dict) else {})
    bb_vals = [v[1] for v in bb_entry.get("bodyBatteryValuesArray", []) if len(v) >= 2 and isinstance(v[1], (int, float))]
    if bb_vals:
        parsed["morning_body_battery"] = f"{max(bb_vals)}/100"
        parsed["body_battery"] = f"{bb_vals[-1]}/100"

    parsed["today_steps"] = _fmt_steps(today_data.get("stats"))
    parsed["today_stress"] = _fmt_stress(today_data.get("stress"))

    combined_acts = [
        t for t in (
            _format_historical_activities_text(yesterday_data.get("activities", [])),
            extra_yesterday_training,
        ) if t
    ]
    parsed["yesterday_training"] = " + ".join(combined_acts) if combined_acts else "Brak aktywności (dzień wolny)"
    parsed["yesterday_steps"] = _fmt_steps(yesterday_data.get("stats"))
    parsed["yesterday_stress"] = _fmt_stress(yesterday_data.get("stress"))

    return parsed


def parse_activities(raw_acts):
    """
    Czysta funkcja sortująca chronologicznie surowe aktywności i parsująca ich biomechanikę.

    Args:
        raw_acts (list): Surowa lista aktywności z Garmina.

    Returns:
        tuple: Krotka (posortowane_surowe_aktywności, lista_przeparsowanych_statystyk).
    """
    sorted_acts = sorted(raw_acts or [], key=_activity_sort_key)
    parsed_stats = [st for act in sorted_acts if (st := parse_activity_biomechanics(act))]
    return sorted_acts, parsed_stats


def display_activities(parsed_stats, date_str):
    """Wyświetla czytelne podsumowanie przeparsowanych aktywności w konsoli."""
    if not parsed_stats:
        return
    print("\n" + "=" * 50)
    print(f"📊 POBRANO AKTYWNOŚCI DO AUDYTU ({len(parsed_stats)} jednostek w dniu {date_str}):")
    print("=" * 50)
    base_exclude = {"splits", "name", "distance", "pace", "start_time", "is_run", "is_swim"}
    run_only_keys = {"avg_cadence", "max_cadence", "stride_length", "ground_contact_time", "vertical_oscillation", "vertical_ratio"}

    for idx, act_st in enumerate(parsed_stats, 1):
        time_str = f" [Start: {act_st['start_time']}]" if act_st.get("start_time") and act_st["start_time"] != NO_DATA else ""
        prefix = f"Jednostka {idx}{time_str}: " if len(parsed_stats) > 1 else ""
        print(f"\n▶️ {prefix}{act_st['name']} ({act_st['distance']}, tempo: {act_st['pace']})")

        exclude_keys = base_exclude if act_st.get("is_run", True) else (base_exclude | run_only_keys)
        for k, v in act_st.items():
            if k not in exclude_keys:
                print(f"   - {k}: {v}")


def process_and_display_activities(raw_acts, date_str):
    """Sortuje, parsuje i wyświetla podsumowanie aktywności z danego dnia."""
    sorted_acts, parsed_stats = parse_activities(raw_acts)
    display_activities(parsed_stats, date_str)
    return sorted_acts, parsed_stats


# ==============================================================================
# KOMUNIKACJA I ZARZĄDZANIE SESJĄ OAUTH GARMIN CONNECT
# ==============================================================================

def _write_env_token_to_store(token_file_path):
    """Zapisuje token z GARMIN_TOKENS_BASE64 lub GARMIN_TOKENS_JSON do pliku sesji."""
    tokens_base64 = (os.getenv("GARMIN_TOKENS_BASE64") or "").strip()
    tokens_json = (os.getenv("GARMIN_TOKENS_JSON") or "").strip()
    if not (tokens_base64 or tokens_json):
        return False

    source_name = "GARMIN_TOKENS_BASE64" if tokens_base64 else "GARMIN_TOKENS_JSON"
    try:
        payload = base64.b64decode(tokens_base64).decode("utf-8") if tokens_base64 else tokens_json
        with open(token_file_path, "w", encoding="utf-8") as f:
            f.write(payload)
        try:
            os.chmod(token_file_path, 0o600)
        except OSError:
            pass
        logger.info(f"📄 Zainicjalizowano plik sesji z sekretu {source_name}.")
        return True
    except Exception as e:
        logger.warning(f"Nie udało się załadować tokenów z {source_name}: {e}")
        return False


def _persist_session_tokens(client, tokenstore_dir_path):
    """Zapisuje odświeżone tokeny sesyjne OAuth do magazynu na dysku."""
    try:
        for obj in (getattr(client, "client", None), client, getattr(client, "garth", None)):
            if obj is not None and hasattr(obj, "dump"):
                obj.dump(tokenstore_dir_path)
                break
    except Exception as e:
        logger.debug(f"Zrzut tokenów nie był wymagany lub zwrócił błąd: {e}")


def get_garmin_client(email=None, password=None):
    """
    Inicjalizuje połączenie i loguje do Garmin Connect z bezpiecznym zarządzaniem sesją OAuth:
    1. Korzysta z istniejącego tokenstore (~/.garminconnect), nie nadpisując świeżych tokenów z cache'u.
    2. Jeśli brak lokalnego pliku sesji, inicjalizuje go z GARMIN_TOKENS_BASE64 / GARMIN_TOKENS_JSON.
    3. Jeśli sesja z cache'u wygasła, ponawia próbę z tokenem z sekretu lub pełnym logowaniem email/password.
    4. Po udanym logowaniu serializuje odświeżone tokeny z powrotem na dysk.
    """
    tokenstore_dir_path = os.path.expanduser(os.getenv("GARMIN_TOKENS_DIR", "~/.garminconnect"))
    os.makedirs(tokenstore_dir_path, exist_ok=True)
    token_file_path = os.path.join(tokenstore_dir_path, "garmin_tokens.json")

    had_cached_file = os.path.exists(token_file_path)
    if not had_cached_file:
        _write_env_token_to_store(token_file_path)

    logger.info("🚀 Inicjalizacja połączenia z Garmin Connect...")

    try:
        client = Garmin(email, password)
        client.login(tokenstore_dir_path)
        _persist_session_tokens(client, tokenstore_dir_path)
        logger.info("✅ Pomyślnie zalogowano do Garmin Connect.")
        return client
    except Exception as first_err:
        # Jeśli użyto starszego pliku z cache, a w środowisku jest GARMIN_TOKENS_BASE64, spróbuj go użyć
        if had_cached_file and _write_env_token_to_store(token_file_path):
            try:
                client = Garmin(email, password)
                client.login(tokenstore_dir_path)
                _persist_session_tokens(client, tokenstore_dir_path)
                logger.info("✅ Pomyślnie zalogowano do Garmin Connect (po odświeżeniu z sekretu).")
                return client
            except Exception as second_err:
                first_err = second_err

        err_msg = str(first_err)
        if "429" in err_msg or "rate limit" in err_msg.lower():
            logger.error(
                "❌ Otrzymano błąd 429 (Rate Limited przez Garmina). "
                "Wygeneruj token lokalnie (~/.garminconnect/garmin_tokens.json) "
                "i dodaj go w GitHub Secrets jako GARMIN_TOKENS_BASE64."
            )
        raise RuntimeError(f"Błąd logowania do Garmin Connect: {err_msg}") from first_err


def _safe_fetch(func, log_msg, *args, **kwargs):
    """Bezpiecznie wywołuje metodę API Garmina, zwracając None i logując ostrzeżenie w razie błędu."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"{log_msg}: {e}")
        return None


def _fetch_day_telemetry(client, date_str, is_today=True):
    """Pobiera komplet danych dziennych (oraz nocnych i szczegółów aktywności dla dnia bieżącego)."""
    day_data = {"date": date_str}
    if is_today:
        day_data["sleep"] = _safe_fetch(client.get_sleep_data, f"Nie udało się pobrać danych snu z {date_str}", date_str)
        day_data["hrv"] = _safe_fetch(client.get_hrv_data, f"Nie udało się pobrać HRV z {date_str}", date_str)

    day_data["stress"] = _safe_fetch(client.get_stress_data, f"Nie udało się pobrać stresu z {date_str}", date_str)
    day_data["stats"] = _safe_fetch(client.get_user_summary, f"Nie udało się pobrać bilansu kroków z {date_str}", date_str)

    if is_today:
        day_data["body_battery"] = _safe_fetch(client.get_body_battery, f"Nie udało się pobrać Body Battery z {date_str}", date_str)

    acts = _safe_fetch(client.get_activities_by_date, f"Nie udało się pobrać aktywności z {date_str}", date_str, date_str)
    if acts is not None:
        if is_today:
            enriched_acts = []
            for act in acts:
                act_copy = dict(act)
                if act_id := act_copy.get("activityId"):
                    act_copy["splits_data"] = _safe_fetch(client.get_activity_splits, f"Nie udało się pobrać splitów dla aktywności {act_id}", act_id)
                    act_copy["weather_data"] = _safe_fetch(client.get_activity_weather, f"Nie udało się pobrać pogody dla aktywności {act_id}", act_id)
                enriched_acts.append(act_copy)
            day_data["activities"] = enriched_acts
        else:
            day_data["activities"] = list(acts)

    return day_data


def fetch_garmin_data(target_date, force_refresh=False):
    """
    Pobiera komplet danych z Garmin Connect dla analizy dziennej (dziś + wczoraj)
    z obsługą lokalnej pamięci podręcznej (garmin_data/YYYY-MM-DD.json).
    """
    today_str = target_date.isoformat()
    yesterday_str = (target_date - datetime.timedelta(days=1)).isoformat()

    cache_file_path = os.path.join(GARMIN_CACHE_DIR_PATH, f"{today_str}.json")
    if not force_refresh and os.path.exists(cache_file_path):
        try:
            with open(cache_file_path, "r", encoding="utf-8") as cf:
                cached_data = json.load(cf)
            if cached_data and "today" in cached_data and "yesterday" in cached_data:
                logger.info(f"💾 Wczytano dane telemetryczne Garmina z lokalnej pamięci podręcznej ({cache_file_path}).")
                return cached_data
        except Exception as e:
            logger.warning(f"Błąd odczytu pamięci podręcznej Garmina ({cache_file_path}): {e}. Pobieranie z API...")

    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    has_token_env = bool((os.getenv("GARMIN_TOKENS_BASE64") or os.getenv("GARMIN_TOKENS_JSON") or "").strip())
    token_file_exists = os.path.exists(os.path.expanduser(os.path.join(os.getenv("GARMIN_TOKENS_DIR", "~/.garminconnect"), "garmin_tokens.json")))

    if not (garmin_email and garmin_password) and not (has_token_env or token_file_exists):
        raise RuntimeError("Brak danych logowania GARMIN_EMAIL / GARMIN_PASSWORD oraz brak tokenów sesji OAuth!")

    client = get_garmin_client(garmin_email, garmin_password)
    logger.info(f"🚀 Pobieranie danych z Garmina dla analizy dziennej (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    result = {
        "today": _fetch_day_telemetry(client, today_str, is_today=True),
        "yesterday": _fetch_day_telemetry(client, yesterday_str, is_today=False),
    }

    try:
        os.makedirs(GARMIN_CACHE_DIR_PATH, exist_ok=True)
        with open(cache_file_path, "w", encoding="utf-8") as cf:
            json.dump(result, cf, ensure_ascii=False, indent=2)
        logger.info(f"💾 Zapisano pobrane dane telemetryczne Garmina do pamięci podręcznej: {cache_file_path}")
    except Exception as e:
        logger.warning(f"Nie udało się zapisać danych Garmina do pamięci podręcznej ({cache_file_path}): {e}")

    return result
