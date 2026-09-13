import os
import datetime
import logging
import sys
from garminconnect import Garmin
from google import genai
from dotenv import load_dotenv # type: ignore
import json

# Załadowanie zmiennych z pliku .env
load_dotenv()


# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def fetch_garmin_data(email, password, target_date):
    """
    Pobiera dane biometryczne z dwóch dni:
    - WCZORAJ: całodzienny stres, kroki, aktywności treningowe
    - DZISIAJ: sen z minionej nocy, HRV, RHR, poranne Body Battery
    """
    logger.info("Logowanie do Garmin Connect...")
    try:
        client = Garmin(email, password)
        client.login()
        logger.info("Pomyślnie zalogowano do Garmina.")
    except Exception as e:
        logger.error(f"Błąd logowania do Garmin Connect: {e}")
        return None

    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()
    
    logger.info(f"Pobieranie danych (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

    data = {
        'today': {},
        'yesterday': {}
    }

    # ==================== DZISIAJ (OCENA NOCY I PORANKA) ====================
    try:
        data['today']['sleep'] = client.get_sleep_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać danych snu z dzisiaj: {e}")

    try:
        # Pobieramy RHR na dzień dzisiejszy
        data['today']['rhr'] = client.get_rhr_day(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać RHR z dzisiaj: {e}")

    try:
        # Pobieramy tętno z dzisiaj (zawiera m.in. lastSevenDaysAvgRestingHeartRate)
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
        # Dzisiejsze aktywności (np. świeży bieg do weryfikacji)
        today_acts = client.get_activities_by_date(today_str, today_str)
        if today_acts:
            for act in today_acts:
                act_id = act.get('activityId')
                if act_id:
                    try:
                        act['splits_data'] = client.get_activity_splits(act_id)
                    except Exception:
                        pass
        data['today']['activities'] = today_acts
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszych aktywności: {e}")

    # ==================== WCZORAJ (CAŁODZIENNY KOSZT DNIA) ====================
    try:
        # Całodzienny stres z wczoraj
        data['yesterday']['stress'] = client.get_stress_data(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego stresu: {e}")

    try:
        # Kroki i podsumowanie wczorajszego ruchu poza treningiem
        data['yesterday']['stats'] = client.get_user_summary(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego bilansu kroków: {e}")

    try:
        # Wczorajsze aktywności treningowe (wszystkie, nie tylko bieg)
        acts = client.get_activities_by_date(yesterday_str, yesterday_str)
        if acts:
            # Dla każdej aktywności próbujemy dociągnąć szczegółowe splity kilometrowe
            for act in acts:
                act_id = act.get('activityId')
                if act_id:
                    try:
                        act['splits_data'] = client.get_activity_splits(act_id)
                    except Exception:
                        pass
        data['yesterday']['activities'] = acts
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszych aktywności: {e}")

    return data

def parse_garmin_data(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina:
    - z wczoraj: trening, kroki poza treningiem, stres
    - z dzisiaj: sen (w sekundach), REM, HRV, tętno spoczynkowe, Body Battery
    """
    parsed = {
        # Dzisiaj (poranek / noc)
        "hrv_status": "Brak danych o HRV",
        "rhr": "Brak danych o RHR",
        "sleep_score": "Brak danych o śnie",
        "deep_sleep": "Brak danych",
        "rem_sleep": "Brak danych",
        "body_battery": "Brak danych",
        # Wczoraj (koszt dnia)
        "yesterday_training": "Brak aktywności (dzień wolny)",
        "yesterday_steps": "Brak danych o krokach",
        "yesterday_stress": "Brak danych o stresie"
    }
    
    if not data:
        return parsed

    today_data = data.get('today', {})
    yesterday_data = data.get('yesterday', {})

    # ==================== DZISIEJSZY PORANEK ====================
    # --- HRV ---
    if today_data.get('hrv'):
        hrv_raw = today_data['hrv']
        hrv_summary = hrv_raw.get('hrvSummary', {})
        
        status = hrv_summary.get('status', 'Brak statusu')
        last_night = hrv_summary.get('lastNightAvg', 'Brak')
        weekly_avg = hrv_summary.get('weeklyAvg', 'Brak')
        
        baseline_info = hrv_summary.get('baseline', {})
        b_low = baseline_info.get('balancedLow')
        b_high = baseline_info.get('balancedUpper')
        
        baseline_str = f"{b_low}–{b_high} ms" if b_low and b_high else "Brak danych bazowych"
        
        parsed['hrv_status'] = f"{status} {last_night} ms (Średnia 7-dniowa: {weekly_avg} ms, Norma bazowa: {baseline_str})"
    
    # --- RHR (Tętno spoczynkowe) i Tętno nocne ---
    rhr_str = "Brak danych"
    if today_data.get('rhr'):
        rhr_raw = today_data['rhr']
        try:
            rhr_list = rhr_raw.get('allMetrics', {}).get('metricsMap', {}).get('WELLNESS_RESTING_HEART_RATE', [])
            if rhr_list and len(rhr_list) > 0:
                today_val = rhr_list[0].get('value')
                if today_val is not None:
                    today_rhr = int(today_val)
                    
                    # Sprawdzamy czy mamy średnią 7-dniową z Garmina
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

    # --- Sen (Pobierane bezpośrednio z dailySleepDTO) ---
    avg_night_hr = None
    if today_data.get('sleep') and 'dailySleepDTO' in today_data['sleep']:
        sleep_dto = today_data['sleep']['dailySleepDTO']
        
        # Średnie tętno ze snu
        avg_hr_val = sleep_dto.get('avgHeartRate')
        if avg_hr_val:
            avg_night_hr = f"{int(avg_hr_val)} bpm"

        # Ocena snu
        score = sleep_dto.get('sleepScores', {}).get('overall', {}).get('value', 'Brak')
        parsed['sleep_score'] = f"{score}/100"
        
        # Faza głęboka (zamiana sekund na godziny i minuty)
        deep_secs = sleep_dto.get('deepSleepSeconds', 0)
        parsed['deep_sleep'] = f"{deep_secs // 3600}h {(deep_secs % 3600) // 60}m"
        
        # Faza REM
        rem_secs = sleep_dto.get('remSleepSeconds', 0)
        parsed['rem_sleep'] = f"{rem_secs // 3600}h {(rem_secs % 3600) // 60}m"

        # Wnioski i spostrzeżenia Garmina o śnie
        feedback = sleep_dto.get('sleepScoreFeedback')
        insight = sleep_dto.get('sleepScoreInsight')
        insights_list = [i for i in [feedback, insight] if i]
        if insights_list:
            parsed['sleep_insights'] = ", ".join(insights_list)
        else:
            parsed['sleep_insights'] = "Brak specyficznych uwag"

    # Łączymy RHR ze średnim tętnem nocnym
    if avg_night_hr:
        parsed['rhr'] = f"{rhr_str} (Średnie tętno z całej nocy: {avg_night_hr})"
    else:
        parsed['rhr'] = rhr_str

    # --- Body Battery ---
    if today_data.get('body_battery') and len(today_data['body_battery']) > 0:
        bb_values = today_data['body_battery'][0].get('bodyBatteryValuesArray', [])
        valid_values = [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]
        
        if valid_values:
            current_bb = valid_values[-1] # Aktualny stan
            max_bb = max(valid_values)    # Maksimum po śnie
            parsed['body_battery'] = f"Aktualnie {current_bb} (Maksymalnie po nocy: {max_bb})"

    # ==================== WCZORAJSZY DZIEŃ ====================
    # --- Wczorajsze aktywności (Pełna biomechanika i fizjologia) ---
    if yesterday_data.get('activities') and len(yesterday_data['activities']) > 0:
        act = yesterday_data['activities'][0]
        act_details = parse_activity_biomechanics(act)
        if act_details:
            splits_text = ""
            if act_details.get('splits'):
                splits_text = "\n  * Splity kilometrowe:\n" + "\n".join(act_details['splits'])

            parsed['yesterday_training'] = (
                f"{act_details['name']} ({act_details['distance']} w {act_details['duration']}, tempo {act_details['pace']})\n"
                f"  * Tętno: Średnie {act_details['avg_hr']} | Maksymalne {act_details['max_hr']}\n"
                f"  * Biomechanika: Średnia kadencja {act_details['avg_cadence']}, krok {act_details['stride_length']}, kontakt {act_details['ground_contact_time']}, odchylenie {act_details['vertical_oscillation']}\n"
                f"  * Obciążenie: Aerobic TE: {act_details['aerobic_te']}, Anaerobic TE: {act_details['anaerobic_te']}, Średnia moc: {act_details['avg_power']}"
                f"{splits_text}"
            )

    # --- Wczorajsze kroki i ruch poza treningiem ---
    if yesterday_data.get('stats'):
        total_steps = yesterday_data['stats'].get('totalSteps', 'Brak')
        parsed['yesterday_steps'] = f"{total_steps} kroków"

    # --- Wczorajszy stres ---
    if yesterday_data.get('stress'):
        avg_stress = yesterday_data['stress'].get('avgStressLevel', 'Brak')
        parsed['yesterday_stress'] = f"Średni poziom stresu: {avg_stress}/100"

    return parsed

def generate_prompt(garmin_stats, training_context, last_verification=None):
    """
    Tworzy końcowy prompt dla modelu Gemini, łącząc wytyczne analityczne,
    dane biometryczne oraz ewentualną weryfikację ostatniego treningu.
    """
    verification_context = ""
    if last_verification:
        verification_context = f"""
====================
RAPORT Z OSTATNIEJ WERYFIKACJI TRENINGU (JAK POSZEDŁ OSTATNI BIEG):
{last_verification}
"""

    prompt = f"""Działasz jako doświadczony trener biegania długodystansowego i fizjolog sportowy. 
Twoim zadaniem jest zaplanowanie dzisiejszej jednostki treningowej na podstawie mojego aktualnego celu biegowego, 
parametrów biometrycznych z zegarka Garmin Forerunner oraz analizy i weryfikacji ostatnio wykonanego biegu.

Zanim zaproponujesz trening, dokonaj krótkiej, precyzyjnej analizy wg poniższych kategorii, 
biorąc pod uwagę zasady fizjologii (jeśli jakichś danych brakuje, pomiń daną kategorię lub opisz możliwe ryzyka bazując na reszcie):

1. Regeneracja i układ autonomiczny: 
   - Analiza HRV, tętna spoczynkowego (RHR) i architektury snu (faza głęboka - mięśnie, faza REM - układ nerwowy). 
   - Wskazówka: krótki sen głęboki (<20%) to gorsza regeneracja mięśniowa; spadek HRV to sygnał przeciążenia.
2. Obciążenie treningowe i bilans wczorajszego dnia: 
   - Oceniasz wpływ wczorajszego treningu, kroków oraz poziomu stresu w ciągu dnia na dzisiejsze zasoby.
3. Zarządzanie energią i planowanie dnia:
   - Na podstawie Body Battery i jakości nocy, zaplanuj ułożenie energii na dzisiejsze zadania i wskaż najlepsze okno na trening.

====================
KONTEKST TRENINGOWY:
- Główny cel: {training_context.get('goal', 'Budowanie bazy tlenowej')}
- Dzień tygodnia i faza: {training_context.get('phase', 'Faza podstawowa')}
- Docelowe strefy / tempa bazowe:
  * Regeneracja (Z1): {training_context.get('z1', '<135 bpm')}
  * Bieg spokojny (Z2): {training_context.get('z2', '135–150 bpm')}
  * Tempo maratońskie / Z3: {training_context.get('z3', '155–165 bpm')}
  * Próg mleczanowy (Z4): {training_context.get('z4', '168–176 bpm')}
{verification_context}
====================
DANE BIOMETRYCZNE:
[WCZORAJSZY DZIEŃ]:
- Trening: {garmin_stats.get('yesterday_training')}
- Ruch poza treningiem: {garmin_stats.get('yesterday_steps')}
- Poziom stresu w ciągu dnia: {garmin_stats.get('yesterday_stress')}

[DZISIEJSZA NOC I PORANEK]:
- Status HRV: {garmin_stats.get('hrv_status')}
- Tętno spoczynkowe (RHR): {garmin_stats.get('rhr')}
- Sleep Score: {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski Garmina o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}

====================
LOGIKA DECYZYJNA:
1. Jeśli HRV jest drastycznie obniżone lub RHR mocno wzrosło (albo wczorajszy stres był skrajnie wysoki): bezwzględnie zredukuj intensywność (zamień planowany akcent na lekki bieg regeneracyjny Z1/Z2 lub zaleć dzień wolny/rolowanie).
2. Weź pod uwagę realizację ostatniego biegu (czy zrealizowano założenia, czy tempo nie dryfowało, czy kadencja była prawidłowa).
3. Jeśli regeneracja jest optymalna: dobierz właściwy dla cyklu bodziec (np. interwały progowe, bieg zmienny, bieg z narastającą prędkością BNP lub długie wybieganie).

====================
ZWRÓĆ ODPOWIEDŹ DOKŁADNIE W TYM FORMACIE:
1. KWALIFIKACJA DNIA: (1 zdanie oceniające gotowość układu nerwowego do przyjęcia obciążenia).
2. ANALIZA FIZJOLOGICZNA:
   - Regeneracja i układ autonomiczny: [Twój wniosek]
   - Obciążenie treningowe: [Twój wniosek]
   - Zarządzanie energią: [Twój wniosek]
3. TYP TRENINGU I CEL FIZJOLOGICZNY: (np. Bieg progowy – stymulacja utylizacji mleczanu).
4. STRUKTURA JEDNOSTKI KROK PO KROKU:
   - Rozgrzewka (czas/dystans, strefa, ćwiczenia)
   - Część główna (serie, tempo/strefa tętna, kadencja, przerwy)
   - Schłodzenie (czas wyciszenia tętna)
5. WARUNEK KOREKTY W BIEGU: (np. kryterium dryfu tętna, przy którym należy natychmiast skrócić trening).
"""
    return prompt

def parse_activity_biomechanics(activity):
    """
    Wyciąga szczegółowe parametry biomechaniczne i fizjologiczne z konkretnego biegu.
    """
    if not activity:
        return None

    dist_km = activity.get('distance', 0) / 1000
    duration_min = activity.get('duration', 0) / 60
    
    # Obliczanie tempa min/km
    avg_speed_m_s = activity.get('averageSpeed', 0)
    pace_str = "Brak"
    if avg_speed_m_s > 0:
        pace_sec = 1000 / avg_speed_m_s
        pace_str = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d} min/km"

    res = {
        "name": activity.get('activityName', 'Bieg'),
        "distance": f"{dist_km:.2f} km",
        "duration": f"{duration_min:.1f} min",
        "pace": pace_str,
        "avg_hr": f"{activity.get('averageHR', 'Brak')} bpm",
        "max_hr": f"{activity.get('maxHR', 'Brak')} bpm",
        # Biomechanika (z nadgarstka Forerunner 165)
        "avg_cadence": f"{activity.get('averageRunningCadenceInStepsPerMinute', 'Brak')} spm",
        "max_cadence": f"{activity.get('maxRunningCadenceInStepsPerMinute', 'Brak')} spm",
        "stride_length": f"{activity.get('avgStrideLength', 0) / 100:.2f} m" if activity.get('avgStrideLength') else "Brak",
        "ground_contact_time": f"{activity.get('avgGroundContactTime', 'Brak')} ms",
        "vertical_oscillation": f"{activity.get('avgVerticalOscillation', 'Brak')} cm",
        "vertical_ratio": f"{activity.get('avgVerticalRatio', 'Brak')} %",
        # Obciążenie treningowe
        "aerobic_te": f"{activity.get('aerobicTrainingEffect', 'Brak')}/5.0 ({activity.get('trainingEffectLabel', '')})",
        "anaerobic_te": f"{activity.get('anaerobicTrainingEffect', 'Brak')}/5.0",
        "avg_power": f"{activity.get('avgPower', 'Brak')} W",
        "splits": []
    }

    # --- Ekstrakcja splitów kilometrowych ---
    splits_raw = activity.get('splits_data')
    parsed_splits = []
    if splits_raw and isinstance(splits_raw, dict):
        lap_list = splits_raw.get('lapDTOs', [])
        for idx, lap in enumerate(lap_list):
            lap_dist = lap.get('distance', 0) / 1000
            lap_dur = lap.get('duration', 0)
            lap_speed = lap.get('averageSpeed', 0)
            lap_pace = "Brak"
            if lap_speed > 0:
                p_sec = 1000 / lap_speed
                lap_pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} min/km"
            
            lap_hr = lap.get('averageHR', 'Brak')
            lap_cad = lap.get('averageRunningCadenceInStepsPerMinute', 'Brak')
            lap_stride = f"{lap.get('strideLength', 0) / 100:.2f} m" if lap.get('strideLength') else "Brak"
            
            parsed_splits.append(
                f"  * Km {idx + 1} ({lap_dist:.2f} km): tempo {lap_pace}, tętno {lap_hr} bpm, kadencja {lap_cad} spm, krok {lap_stride}"
            )

    res["splits"] = parsed_splits
    return res

def generate_verification_prompt(planned_workout, activity_stats):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu względem założeń.
    """
    splits_section = "Brak szczegółowych splitów"
    if activity_stats.get('splits'):
        splits_section = "\n".join(activity_stats['splits'])

    prompt = f"""Działasz jako rygorystyczny, ale wspierający trener biegania i fizjolog sportowy.
Twoim zadaniem jest ocena wykonanej jednostki biegowej na podstawie danych z zegarka Garmin oraz weryfikacja, 
czy zrealizowałem dzisiejsze założenia treningowe.

====================
ZAŁOŻENIA TRENINGU (CO MIAŁO BYĆ ZROBIONE):
{planned_workout}

====================
RZECZYWISTE DANE Z ZEGARKA GARMIN (CO ZOSTAŁO ZROBIONE):
- Nazwa i dystans: {activity_stats.get('name')} | {activity_stats.get('distance')} w czasie {activity_stats.get('duration')} (Średnie tempo: {activity_stats.get('pace')})
- Tętno: Średnie {activity_stats.get('avg_hr')} | Maksymalne {activity_stats.get('max_hr')}
- Biomechanika kroku:
  * Średnia kadencja: {activity_stats.get('avg_cadence')} (Maksymalna: {activity_stats.get('max_cadence')})
  * Długość kroku: {activity_stats.get('stride_length')}
  * Czas kontaktu z podłożem: {activity_stats.get('ground_contact_time')}
  * Odchylenie pionowe: {activity_stats.get('vertical_oscillation')} (Współczynnik odchylenia: {activity_stats.get('vertical_ratio')})
- Efekt treningowy i moc:
  * Aerobic Training Effect: {activity_stats.get('aerobic_te')}
  * Anaerobic Training Effect: {activity_stats.get('anaerobic_te')}
  * Średnia moc biegowa: {activity_stats.get('avg_power')}
- Splity kilometrowe:
{splits_section}

====================
ZADANIE DLA TRENERA:
Dokonaj precyzyjnej oceny według poniższego schematu:

1. WERDYKT REALIZACJI (Ocena w skali 1-10 + podsumowanie, czy bodziec został osiągnięty, czy nastąpiło przestymulowanie / niedostymulowanie).
2. AUDYT INTENSYWNOŚCI I FIZJOLOGII:
   - Czy strefy tętna i tempo były zgodne z planem?
   - Ocena Training Effect – czy bieg tlenowy nie stał się beztlenowy?
3. AUDYT BIOMECHANIKI I EKONOMII BIEGU:
   - Ocena kadencji (czy rytm był optymalny, czy wystąpiło człapanie <165 spm).
   - Ocena kontaktu z podłożem i odchylenia pionowego (czy energia nie uciekała w górę zamiast w przód).
4. WSKAZÓWKI REGENERACYJNE NA RESZTĘ DNIA (Rolowanie, nawodnienie, posiłek pobiegowy).
5. KOREKTA NA JUTRO (Jak dzisiejsza realizacja wpływa na plan na kolejny dzień).
"""
    return prompt

def main():
    # Załadowanie informacji
    GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
    GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Sprawdzenie poprawności danych.
    if not all([GARMIN_EMAIL, GARMIN_PASSWORD, GEMINI_API_KEY]):
        logger.error("Brak danych logowania! Upewnij się, że uzupełniłeś plik .env w tym samym folderze co skrypt.")
        sys.exit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)
    today = datetime.date.today()

    # Sprawdzenie czy dane z Garmin już zostały pobrane (dodane w celach diagnostycznych).
    USE_LOCAL_DATA = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]
    dump_file = "garmin_dump.json"

    if USE_LOCAL_DATA:
        logger.info(f"Omijam logowanie. Wczytuję surowe dane z pliku {dump_file}...")
        try:
            with open(dump_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f) # Zamienia tekst na Pythonowy słownik.
        except FileNotFoundError:
            logger.error(f"Nie znaleziono pliku {dump_file}. Uruchom skrypt z USE_LOCAL_DATA = 'False', aby go stworzyć!")
            sys.exit(1)
    else:
        # Pobiera dane kiedy nie zostały jeszcze pobrane.
        raw_data = fetch_garmin_data(GARMIN_EMAIL, GARMIN_PASSWORD, today)

        if raw_data is None:
            logger.error("Nie udało się pobrać danych z serwerów Garmina.")
            sys.exit(1)
            
        # Zapisanie danych w celach diagnostycznych (nie trzeba łączyć się z Garmin przy następnym wywołaniu).
        with open(dump_file, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=4, ensure_ascii=False)
        logger.info(f"Surowe dane zapisano pomyślnie do pliku {dump_file} do późniejszych testów.")

    # Wybór trybu działania: domyślnie 'plan', opcjonalnie 'verify'
    mode = "plan"
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["verify", "weryfikacja", "analiza"]:
        mode = "verify"

    plan_file = "current_plan.txt"
    verification_file = "last_verification.txt"

    # ==================== TRYB 1: PLANOWANIE TRENINGU (RANO) ====================
    if mode == "plan":
        # 2. Parsowanie danych
        garmin_stats = parse_garmin_data(raw_data)

        # 3. Parametry treningowe użytkownika
        training_context = {
            "goal": "Półmaraton poniżej 1:30",
            "phase": f"{today.strftime('%A')}, faza rozbudowy (Build)",
            "z1": "<135 bpm, wolniej niż 5:45 min/km",
            "z2": "135–150 bpm, tempo 5:10–5:30 min/km",
            "z3": "155–165 bpm, tempo 4:35–4:45 min/km",
            "z4": "168–176 bpm, tempo 4:10–4:20 min/km"
        }

        # Sprawdzamy, czy istnieje raport z ostatniej weryfikacji treningu
        last_verification = None
        if os.path.exists(verification_file):
            try:
                with open(verification_file, "r", encoding="utf-8") as vf:
                    last_verification = vf.read()
                logger.info(f"Wczytano raport z poprzedniej weryfikacji treningu ({verification_file}).")
            except Exception:
                pass

        # 4. Tworzenie promptu
        prompt = generate_prompt(garmin_stats, training_context, last_verification=last_verification)
        
        print("\n" + "="*50)
        print("WYGENEROWANY PROMPT PLANOWANIA:")
        print("="*50)
        print(prompt)

        # 5. Zapytanie do modelu Gemini
        print("\n" + "="*50)
        print("WYSYŁANIE DO GEMINI (model: gemini-3.6-flash)...")
        print("="*50)
        
        try:
            chat = client.chats.create(model='gemini-3.6-flash')
            response = chat.send_message(prompt)
            
            print("\n🏆 ODPOWIEDŹ TRENERA GEMINI (PLAN NA DZIŚ) 🏆\n")
            print(response.text)
            
            # Zapisujemy plan na dysku, aby móc go później zweryfikować
            with open(plan_file, "w", encoding="utf-8") as f:
                f.write(response.text)
            logger.info(f"Plan treningowy został zapisany w pliku {plan_file} do późniejszej weryfikacji.")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas komunikacji z Gemini API: {e}")

    # ==================== TRYB 2: WERYFIKACJA PO BIEGU ====================
    elif mode == "verify":
        logger.info("Uruchomiono tryb weryfikacji wykonanego treningu...")
        
        # 1. Odczytujemy wcześniej zaplanowany trening
        if not os.path.exists(plan_file):
            logger.error(f"Brak pliku {plan_file}! Najpierw uruchom skrypt w trybie planowania: python garmin_coach.py")
            sys.exit(1)

        with open(plan_file, "r", encoding="utf-8") as f:
            planned_workout = f.read()

        # 2. Szukamy ostatniej aktywności (najpierw sprawdzamy dzisiaj, potem wczoraj)
        activities = []
        if 'today' in raw_data and 'activities' in raw_data['today']:
            activities.extend(raw_data['today']['activities'])
        if 'yesterday' in raw_data and 'activities' in raw_data['yesterday']:
            activities.extend(raw_data['yesterday']['activities'])

        if not activities:
            logger.error("Nie znaleziono żadnej aktywności biegowej do zweryfikowania!")
            sys.exit(1)

        latest_act = activities[0]
        act_stats = parse_activity_biomechanics(latest_act)

        print("\n" + "="*50)
        print(f"📊 POBRANY BIEG DO AUDYTU: {act_stats['name']} ({act_stats['distance']})")
        print("="*50)
        for k, v in act_stats.items():
            print(f"- {k}: {v}")

        # 3. Tworzymy prompt weryfikacyjny
        verification_prompt = generate_verification_prompt(planned_workout, act_stats)

        print("\n" + "="*50)
        print("WYSYŁANIE RAPORTU DO GEMINI (Weryfikacja założeń)...")
        print("="*50)

        try:
            chat = client.chats.create(model='gemini-3.6-flash')
            response = chat.send_message(verification_prompt)

            print("\n🏆 RAPORT TRENERSKI PO BIEGU 🏆\n")
            print(response.text)

            # Zapisujemy werdykt, aby Gemini rano pamiętał, jak poszedł ten bieg
            with open(verification_file, "w", encoding="utf-8") as vf:
                vf.write(response.text)
            logger.info(f"Raport z weryfikacji zapisano do {verification_file} na potrzeby kolejnego planowania.")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas weryfikacji: {e}")

if __name__ == "__main__":
    main()
