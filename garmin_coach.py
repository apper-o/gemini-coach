import os
import datetime
import logging
import sys
from garminconnect import Garmin
from google import genai
from dotenv import load_dotenv
import json

# Załadowanie zmiennych z pliku .env
load_dotenv()

# Inicjalizacja loggera
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def fetch_garmin_data(email, password, target_date):
    """
    Łączy się garmin w celu pobrania surowych danych z zegarka.
    Pobiera dane biometryczne z dwóch dni:
    - WCZORAJ: całodzienny stres, kroki, aktywności treningowe
    - DZISIAJ: sen z minionej nocy, HRV, RHR, poranne Body Battery, trening
    """
    # Logowanie do serwisu Garmin Connect
    logger.info("Logowanie do Garmin Connect...")
    try:
        client = Garmin(email, password)
        client.login()
        logger.info("Pomyślnie zalogowano do Garmina.")
    except Exception as e:
        logger.error(f"Błąd logowania do Garmin Connect: {e}")
        return None

    # Przygotowanie zmiennych z datą.
    today_str = target_date.isoformat()
    yesterday_date = target_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.isoformat()
    
    logger.info(f"Pobieranie danych (Wczoraj: {yesterday_str}, Dzisiaj: {today_str})...")

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
        # Pobieramy RHR na dzień dzisiejszy
        data['today']['rhr'] = client.get_rhr_day(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać RHR z dzisiaj: {e}")

    # Pobieramy tętno z dzisiaj (zawiera m.in. lastSevenDaysAvgRestingHeartRate)
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

    # Dzisiejszy całodzienny poziom stresu (do momentu uruchomienia wieczorem)
    try:
        data['today']['stress'] = client.get_stress_data(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszego stresu: {e}")

    # Dzisiejszy bilans kroków i aktywności całodniowej
    try:
        data['today']['stats'] = client.get_user_summary(today_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszego bilansu kroków: {e}")

    # Dzisiejsze aktywności (np. bieg do weryfikacji)
    try:
        today_acts = client.get_activities_by_date(today_str, today_str)
        if today_acts:
            for act in today_acts:
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
        data['today']['activities'] = today_acts
    except Exception as e:
        logger.warning(f"Nie udało się pobrać dzisiejszych aktywności: {e}")

    # ==================== WCZORAJ (KONTEKST HISTORYCZNY) ====================
    # Całodzienny stres z wczoraj
    try:
        data['yesterday']['stress'] = client.get_stress_data(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego stresu: {e}")

    # Kroki i podsumowanie wczorajszego ruchu poza treningiem
    try:
        data['yesterday']['stats'] = client.get_user_summary(yesterday_str)
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszego bilansu kroków: {e}")

    # Wczorajsze aktywności treningowe (wszystkie, nie tylko bieg)
    try:
        acts = client.get_activities_by_date(yesterday_str, yesterday_str)
        if acts:
            # Dla każdej aktywności próbujemy dociągnąć szczegółowe splity kilometrowe i pogodę
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
        data['yesterday']['activities'] = acts
    except Exception as e:
        logger.warning(f"Nie udało się pobrać wczorajszych aktywności: {e}")

    return data

def parse_garmin_data(data):
    """
    Wyciąga najważniejsze informacje z JSON-ów API Garmina z perspektywy wieczornego podsumowania:
    - z dzisiejszego dnia (koszt dnia): dzisiejsze aktywności, kroki całodzienne, poziom stresu, wieczorny stan Body Battery
    - z minionej nocy (stan na start dnia): sen, fazy głęboka/REM, status HRV, nocne tętno spoczynkowe (RHR)
    - z wczorajszego dnia (jako tło do kumulacji zmęczenia): wczorajszy trening, kroki i stres
    """
    parsed = {
        # Baza regeneracyjna z minionej nocy (stan na start dnia):
        "hrv_status": "Brak danych o HRV",
        "rhr": "Brak danych o RHR",
        "sleep_score": "Brak danych o śnie",
        "deep_sleep": "Brak danych",
        "rem_sleep": "Brak danych",
        "sleep_insights": "Brak specyficznych uwag",
        "body_battery": "Brak danych",
        # Koszt dzisiejszego dnia (bilans kroków, stresu i energii):
        "today_steps": "Brak danych o krokach",
        "today_stress": "Brak danych o stresie",
        # Kontekst wczorajszy (tło historyczne):
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

    # --- Body Battery (Aktualny stan wieczorny + naładowanie po nocy) ---
    if today_data.get('body_battery') and len(today_data['body_battery']) > 0:
        bb_entry = today_data['body_battery'][0]
        bb_values = bb_entry.get('bodyBatteryValuesArray', [])
        valid_values = [v[1] for v in bb_values if len(v) >= 2 and isinstance(v[1], (int, float))]
        
        if valid_values:
            current_bb = valid_values[-1] # Aktualny stan wieczorny
            max_bb = max(valid_values)    # Maksimum po nocy
            drain = max_bb - current_bb
            drain_str = f", spadek w ciągu dnia: -{drain}" if drain > 0 else ""
            parsed['body_battery'] = f"Aktualnie wieczorem: {current_bb}/100 (Maksymalnie po nocy: {max_bb}/100{drain_str})"

    # ==================== KOSZT DZISIEJSZEGO DNIA ====================
    # --- Dzisiejsze kroki i bilans ruchu ---
    if today_data.get('stats'):
        t_steps = today_data['stats'].get('totalSteps')
        if t_steps is not None:
            cals = today_data['stats'].get('activeKilocalories')
            cals_str = f" (aktywne kalorie: {cals} kcal)" if cals else ""
            parsed['today_steps'] = f"{t_steps} kroków{cals_str}"

    # --- Dzisiejszy poziom stresu w ciągu dnia ---
    if today_data.get('stress'):
        t_stress = today_data['stress'].get('avgStressLevel')
        stress_qual = today_data['stress'].get('stressQualifier')
        if t_stress is not None and t_stress != -1:
            qual_str = f" ({stress_qual})" if stress_qual else ""
            parsed['today_stress'] = f"Średni poziom stresu: {t_stress}/100{qual_str}"

    # ==================== WCZORAJSZY DZIEŃ (TŁO HISTORYCZNE) ====================
    # --- Wczorajsze aktywności (Pełna biomechanika i fizjologia dla wszystkich jednostek) ---
    if yesterday_data.get('activities') and len(yesterday_data['activities']) > 0:
        yesterday_acts_texts = []
        for idx, act in enumerate(yesterday_data['activities']):
            act_details = parse_activity_biomechanics(act)
            if act_details:
                splits_text = ""
                if act_details.get('splits'):
                    splits_text = "\n    * Splity kilometrowe:\n" + "\n".join([f"    {s}" for s in act_details['splits']])

                act_entry = (
                    f"  [Jednostka {idx + 1}]: {act_details['name']} ({act_details['distance']} w {act_details['duration']}, tempo {act_details['pace']})\n"
                    f"    * Pogoda/Warunki: {act_details.get('weather', 'Brak danych')}\n"
                    f"    * Tętno: Średnie {act_details['avg_hr']} | Maksymalne {act_details['max_hr']}\n"
                    f"    * Biomechanika: Średnia kadencja {act_details['avg_cadence']}, krok {act_details['stride_length']}, kontakt {act_details['ground_contact_time']}, odchylenie {act_details['vertical_oscillation']}\n"
                    f"    * Obciążenie: Aerobic TE: {act_details['aerobic_te']}, Anaerobic TE: {act_details['anaerobic_te']}, Średnia moc: {act_details['avg_power']}"
                    f"{splits_text}"
                )
                yesterday_acts_texts.append(act_entry)

        if yesterday_acts_texts:
            parsed['yesterday_training'] = "\n\n".join(yesterday_acts_texts)

    # --- Wczorajsze kroki ---
    if yesterday_data.get('stats'):
        y_steps = yesterday_data['stats'].get('totalSteps')
        if y_steps is not None:
            parsed['yesterday_steps'] = f"{y_steps} kroków"

    # --- Wczorajszy stres ---
    if yesterday_data.get('stress'):
        y_stress = yesterday_data['stress'].get('avgStressLevel')
        if y_stress is not None and y_stress != -1:
            parsed['yesterday_stress'] = f"Średni poziom stresu: {y_stress}/100"

    # Fallback dla dzisiejszych danych w przypadku gdy API nie zwróciło today (np. stary zrzut danych)
    if parsed['today_steps'] == "Brak danych o krokach" and parsed['yesterday_steps'] != "Brak danych o krokach":
        parsed['today_steps'] = f"{parsed['yesterday_steps']} (uwaga: dane zastępcze z wczoraj)"
    if parsed['today_stress'] == "Brak danych o stresie" and parsed['yesterday_stress'] != "Brak danych o stresie":
        parsed['today_stress'] = f"{parsed['yesterday_stress']} (uwaga: dane zastępcze z wczoraj)"

    return parsed

def load_training_config(config_file=os.path.join("input", "training_config.json")):
    """
    Wczytuje kontekst treningowy, strefy tętna i cele biegacza z pliku JSON (w folderze input/).
    Jeśli plik nie istnieje, sprawdza lokalizację główną lub tworzy szablon w folderze input/.
    """
    input_dir = os.path.dirname(config_file)
    if input_dir:
        os.makedirs(input_dir, exist_ok=True)

    default_config = {
        "goal": "Maraton poniżej 4:00",
        "phase": "Taper",
        "time_left": "2 tygodnie",
        "max_hr": "202 bpm (szacowane)",
        "lthr": "ok. 176 bpm",
        "z1": "<123 bpm, regeneracja i schłodzenie",
        "z2": "123–144 bpm, baza tlenowa / bieg spokojny (tempo >6:00 min/km)",
        "z3": "144–162 bpm, tempo maratońskie (tempo ok. 4:50-5:40 min/km)",
        "z4": "162–181 bpm, próg mleczanowy LTHR (tempo ok. 4:10–4:40 min/km)",
        "z5": ">181 bpm, beztlen / interwały VO2max"
    }

    # Jeśli plik nie istnieje w folderze input/, sprawdzamy czy istnieje w katalogu głównym (migracja)
    legacy_file = "training_config.json"
    if not os.path.exists(config_file) and os.path.exists(legacy_file):
        try:
            with open(legacy_file, "r", encoding="utf-8") as lf:
                legacy_data = json.load(lf)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(legacy_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Przeniesiono konfigurację z {legacy_file} do {config_file}")
        except Exception:
            pass

    if not os.path.exists(config_file):
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"Utworzono domyślny plik konfiguracji treningowej: {config_file}")
        except Exception as e:
            logger.warning(f"Nie udało się utworzyć pliku {config_file}: {e}")
        return default_config

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            merged = default_config.copy()
            merged.update(user_config)
            return merged
    except Exception as e:
        logger.warning(f"Błąd odczytu {config_file}: {e}. Używam domyślnej konfiguracji.")
        return default_config

def load_user_note(note_file=os.path.join("input", "user_note.md")):
    """
    Wczytuje opcjonalną notatkę/wiadomość użytkownika do trenera z folderu input/ (np. uwagi o samopoczuciu, kontuzjach, czasie).
    Jeśli plik nie istnieje w input/, sprawdza katalog główny lub tworzy szablon z instrukcją.
    """
    input_dir = os.path.dirname(note_file)
    if input_dir:
        os.makedirs(input_dir, exist_ok=True)

    # Migracja z katalogu głównego, jeśli plik tam istnieje
    legacy_file = "user_note.md"
    if not os.path.exists(note_file) and os.path.exists(legacy_file):
        try:
            with open(legacy_file, "r", encoding="utf-8") as lf:
                legacy_text = lf.read()
            if legacy_text.strip():
                with open(note_file, "w", encoding="utf-8") as f:
                    f.write(legacy_text)
                logger.info(f"Przeniesiono notatkę z {legacy_file} do {note_file}")
        except Exception:
            pass

    if not os.path.exists(note_file):
        try:
            with open(note_file, "w", encoding="utf-8") as f:
                f.write("# Twoja wiadomość/uwagi do Trenera Gemini\n"
                        "# Możesz tu wpisać dowolne bieżące informacje, np.:\n"
                        "# - 'Czuję lekkie zmęczenie w czwórgłowych po wczorajszych schodach'\n"
                        "# - 'W czwartek mam czas tylko rano na max 45 minut'\n"
                        "# - 'W sobotę chcę biegać w terenie krosowym'\n"
                        "# Trener uwzględni te uwagi w promptcie. Linie zaczynające się od '#' są ignorowane.\n")
        except Exception:
            pass
        return None

    try:
        with open(note_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        valid = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        content = "\n".join(valid).strip()
        return content if content else None
    except Exception as e:
        logger.warning(f"Nie udało się odczytać pliku {note_file}: {e}")
        return None

def generate_weekly_plan_prompt(days_preferences, training_context, history_context=None, user_note=None):
    """
    Tworzy prompt dla Gemini do ułożenia kompletnego planu treningowego na cały tydzień
    na podstawie deklaracji użytkownika (np. Czwartek: Tempo) oraz historii poprzednich treningów.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA POPRZEDNICH TRENINGÓW (ARCHIWUM Z OSTATNICH TYGODNI):
{history_context}
"""

    note_section = ""
    if user_note:
        note_section = f"""
====================
DODATKOWE UWAGI I WIADOMOŚĆ OD BIEGACZA:
{user_note}
"""

    prompt = f"""Działasz jako doświadczony trener biegania długodystansowego i fizjolog sportowy.
Twoim zadaniem jest ułożenie szczegółowego, zbalansowanego planu treningowego na nadchodzący tydzień.

====================
KONTEKST I CELE BIEGACZA:
- Główny cel biegowy: {training_context.get('goal', 'Brak')}
- Faza treningowa: {training_context.get('phase', 'Faza rozbudowy (Build)')}
- Strefy tętna i tempa bazowe:
  * Z1 (Rozgrzewka / Regeneracja): {training_context.get('z1', 'brak danych')}
  * Z2 (Bieg spokojny): {training_context.get('z2', 'brak danych')}
  * Z3 (Bieg umiarkowany / Tempo maratońskie): {training_context.get('z3', 'brak danych')}
  * Z4 (Próg mleczanowy LTHR): {training_context.get('z4', 'brak danych')}
  * Z5 (Beztlen / VO2max): {training_context.get('z5', 'brak danych')}
{hist_section}
====================
PREFERENCJE BIEGACZA NA TEN TYDZIEŃ (DNI I TYPY TRENINGÓW):
{days_preferences}
{note_section}
====================
WYTYCZNE DLA TRENERA:
1. Dla KAŻDEGO zadeklarowanego dnia rozpisz dokładną, kompletną jednostkę treningową:
   - Bieg rozgrzewkowy (dystans)
   - Część główna (dokładne serie, dystans odcinków, sugerowane tempo min/km, czas i forma przerwy w truchcie/marszu, strefa tętna - docelowe przewidywane tętno)
   - Schłodzenie (dystans)
   - Cel fizjologiczny jednostki (np. rozwój enzymów oksydacyjnych, utylizacja kwasu mlekowego)
2. W dni niezadeklarowane (dni wolne) określ zalecenia regeneracyjne (np. spacer, rolowanie, sen, mobilność, cross-trening).
3. W dni z treningiem siłowym nie rozpisuj ćwiczeń - uwzględnij jedynie samą obecność siłowni w planie oraz dodaj krótką wskazówkę, czy w razie treningu nóg powinienem je oszczędzać.
4. Uwzględnij progresję względem poprzednich tygodni (zasada +5-10% objętości lub adaptacji prędkości) oraz wszelkie dodatkowe uwagi biegacza.
5. Nie podawaj ćwiczeń na rozgrzewkę, a jedynie dystans truchtu.
6. Dodaj sumaryczny planowany kilometraż tygodnia oraz Rozkład objętości (np. % w strefie tlenowej Z1-Z2 vs. akcenty jakościowe Z3–Z5).

Rozpisz plan czytelnie z nagłówkiem dla każdego dnia tygodnia (od Poniedziałku do Niedzieli). 
Przejdź od razu do planu bez wstępów motywacyjnych i zbędnych komentarzy na początku odpowiedzi.
"""
    return prompt

def generate_weekly_suggestions_prompt(training_context, history_context=None, current_recovery=None, user_note=None):
    """
    Tworzy prompt dla Gemini w trybie 'suggest', w którym model sugeruje jedynie cele/rodzaje
    treningów na poszczególne dni tygodnia (bez szczegółowej rozpiski kilometrów, serii i przerw).
    Wynik jest bezpośrednio gotowy do skopiowania lub zapisania jako szablon w weekly_preferences.md.
    """
    hist_section = ""
    if history_context:
        hist_section = f"""
====================
HISTORIA POPRZEDNICH TRENINGÓW (ARCHIWUM Z OSTATNICH TYGODNI):
{history_context}
"""

    note_section = ""
    if user_note:
        note_section = f"""
====================
DODATKOWE UWAGI I WIADOMOŚĆ OD BIEGACZA:
{user_note}
"""

    rec_section = ""
    if current_recovery:
        rec_section = f"""
====================
AKTUALNY STAN ORGANIZMU (BIOMETRIA Z GARMINA):
- HRV: {current_recovery.get('hrv_status')}
- RHR: {current_recovery.get('rhr')}
- Sen: {current_recovery.get('sleep_score')} (Głęboki: {current_recovery.get('deep_sleep')}, REM: {current_recovery.get('rem_sleep')})
- Body Battery: {current_recovery.get('body_battery')}
- Dzisiejsze kroki w ciągu dnia: {current_recovery.get('today_steps')}
- Dzisiejszy poziom stresu: {current_recovery.get('today_stress')}
"""

    prompt = f"""Działasz jako doświadczony trener biegania długodystansowego i periodyzacji treningowej.
Twoim celem NIE jest rozpisywanie szczegółowych treningów (nie podawaj kilometrów, serii, interwałów, przerw ani stoperów).

Twoim jedynym zadaniem jest ZAPROPONOWANIE TYPÓW I CELÓW TRENINGÓW na każdy dzień nadchodzącego tygodnia (od Poniedziałku do Niedzieli).

====================
KONTEKST I CELE BIEGACZA:
- Główny cel biegowy: {training_context.get('goal', 'Brak')}
- Faza treningowa: {training_context.get('phase', 'Faza rozbudowy (Build)')}
{rec_section}
{hist_section}
{note_section}
====================
ZASADY DOBORU TYPÓW TRENINGU:
1. Zadbaj o prawidłowy balans obciążeń (zasada hard/easy: nie planuj dwóch mocnych akcentów z rzędu).
2. Wybierz odpowiednie typy jednostek z puli:
   - Easy run: baza tlenowa (Z2) 
   - Przebieżki
   - Bieg progowy / Tempo run (Threshold / Z4)
   - VO2max / Interwały (beztlen)
   - Long Run (Z2)
   - Long Run z akcentem (Z2 / Z3)
   - Recovery run (Z1)
   - Wolne / Regeneracja
   - Trening uzupełniający / Siła biegowa / Core
   - Siłownia: partia górna / partia dolna / full body workout (wszystkie z uwzględnieniem Core)
3. Uwzględnij historię ostatnich treningów (co było biegane, jaka faza), cel główny oraz uwagi biegacza.

====================
FORMAT ODPOWIEDZI:
Odpowiedź MUSI być zwięzła i przejrzysta.
Podaj TYLKO listę dni tygodnia wraz z proponowanym rodzajem treningu w formacie:
Dzień: Rodzaj treningu (krótkie 2-3 słowa doprecyzowania celu)

Przykład pożądanego formatu:
Poniedziałek: Wolne / regeneracja
Wtorek: Easy + przebieżki
Środa: Trening uzupełniający (core/mobilność)
Czwartek: Bieg progowy (Tempo Z4)
Piątek: Wolne
Sobota: Długie wybieganie (Long Run Z2)
Niedziela: Recovery run (Z1)

W normalnych warunkach zaplanuj 4 dni treningu biegowego i 2 dni treningu siłowego w tym 1 dzień na fbw oraz 1 dzień upper body.
Jeśli parametry są słabe LUB zostało inaczej zapisane w notatkach od biegacza zmodyfikuj ilość treningów.
Zaplanuj maksymalnie 2 (lub 3, wliczając Long Run) akcenty jakościowe w tygodniu, resztę przeznaczając na regenerację i bieg spokojny (zasada 80/20).


Pod listą możesz dodać maksymalnie 2-3 zdania zwięzłego trenerskiego uzasadnienia tej struktury mikrocyklu.
Zacznij odpowiedź bezpośrednio od Poniedziałku, bez żadnych zdań wstępnych ani powitań.
"""
    return prompt

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

    prompt = f"""Działasz jako doświadczony trener biegania, fizjolog sportowy i analityk danych biegowych. 
Twoim zadaniem jest zaplanowanie dzisiejszej jednostki treningowej na podstawie mojego aktualnego celu biegowego, 
parametrów biometrycznych z zegarka Garmin Forerunner oraz analizy i weryfikacji ostatnio wykonanego biegu.

Zanim zaproponujesz trening, dokonaj krótkiej, precyzyjnej analizy wg poniższych kategorii, 
biorąc pod uwagę zasady fizjologii (jeśli jakichś danych brakuje, pomiń daną kategorię lub opisz możliwe ryzyka bazując na reszcie):

1. Regeneracja i układ autonomiczny: 
   - Analiza HRV, tętna spoczynkowego (RHR) i architektury snu (faza głęboka - mięśnie, faza REM - układ nerwowy). 
   - Wskazówka: krótki sen głęboki (<20%) to gorsza regeneracja mięśniowa; spadek HRV to sygnał przeciążenia.
2. Obciążenie treningowe i bilans dnia: 
   - Oceniasz wpływ dzisiejszego ruchu/kroków, poziomu stresu oraz wczorajszego treningu na zasoby.
3. Zarządzanie energią i planowanie:
   - Na podstawie Body Battery i jakości nocy, zaplanuj ułożenie energii na zadania i wskaż optymalny trening.

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
[DZISIEJSZY KOSZT DNIA I WIECZORNY STAN]:
- Ruch w ciągu dnia / kroki: {garmin_stats.get('today_steps')}
- Poziom stresu w ciągu dnia: {garmin_stats.get('today_stress')}
- Aktualne Body Battery: {garmin_stats.get('body_battery')}

[STAN WYJŚCIOWY Z POPRZEDZAJĄCEJ NOCY]:
- Status HRV: {garmin_stats.get('hrv_status')}
- Tętno spoczynkowe (RHR): {garmin_stats.get('rhr')}
- Sleep Score: {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski Garmina o śnie: {garmin_stats.get('sleep_insights')}

[KONTEKST DNIA POPRZEDNIEGO]:
- Wczorajszy trening: {garmin_stats.get('yesterday_training')}
- Wczorajsze kroki: {garmin_stats.get('yesterday_steps')}
- Wczorajszy stres: {garmin_stats.get('yesterday_stress')}

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
        "avg_hr": f"{activity.get('averageHR', 'Brak'):.2f} bpm" if isinstance(activity.get('averageHR'), (int, float)) else f"{activity.get('averageHR', 'Brak')} bpm",
        "max_hr": f"{activity.get('maxHR', 'Brak'):.2f} bpm" if isinstance(activity.get('maxHR'), (int, float)) else f"{activity.get('maxHR', 'Brak')} bpm",
        # Biomechanika (z nadgarstka Forerunner 165)
        "avg_cadence": f"{int(round(activity['averageRunningCadenceInStepsPerMinute']))} spm" if activity.get('averageRunningCadenceInStepsPerMinute') is not None else (f"{int(round(activity['averageRunCadence']))} spm" if activity.get('averageRunCadence') is not None else "Brak"),
        "max_cadence": f"{int(round(activity['maxRunningCadenceInStepsPerMinute']))} spm" if activity.get('maxRunningCadenceInStepsPerMinute') is not None else (f"{int(round(activity['maxRunCadence']))} spm" if activity.get('maxRunCadence') is not None else "Brak"),
        "stride_length": f"{activity.get('avgStrideLength', 0) / 100:.2f} m" if activity.get('avgStrideLength') else "Brak",
        "ground_contact_time": f"{activity.get('avgGroundContactTime'):.2f} ms" if isinstance(activity.get('avgGroundContactTime'), (int, float)) else f"{activity.get('avgGroundContactTime', 'Brak')} ms",
        "vertical_oscillation": f"{activity.get('avgVerticalOscillation'):.2f} cm" if isinstance(activity.get('avgVerticalOscillation'), (int, float)) else f"{activity.get('avgVerticalOscillation', 'Brak')} cm",
        "vertical_ratio": f"{activity.get('avgVerticalRatio'):.2f} %" if isinstance(activity.get('avgVerticalRatio'), (int, float)) else f"{activity.get('avgVerticalRatio', 'Brak')} %",
        # Przewyższenia
        "elevation_gain": f"{int(activity.get('elevationGain', 0))}",
        "elevation_loss": f"{int(activity.get('elevationLoss', 0))}",
        # Obciążenie treningowe
        "aerobic_te": f"{activity.get('aerobicTrainingEffect', 0):.2f}/5.0 ({activity.get('trainingEffectLabel', '')})" if isinstance(activity.get('aerobicTrainingEffect'), (int, float)) else f"{activity.get('aerobicTrainingEffect', 'Brak')}/5.0 ({activity.get('trainingEffectLabel', '')})",
        "anaerobic_te": f"{activity.get('anaerobicTrainingEffect', 0):.2f}/5.0" if isinstance(activity.get('anaerobicTrainingEffect'), (int, float)) else f"{activity.get('anaerobicTrainingEffect', 'Brak')}/5.0",
        "avg_power": f"{activity.get('avgPower'):.2f} W" if isinstance(activity.get('avgPower'), (int, float)) else f"{activity.get('avgPower', 'Brak')} W",
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

    # --- Ekstrakcja splitów kilometrowych z pełnymi metrykami ---
    splits_raw = activity.get('splits_data')
    parsed_splits = []
    if splits_raw and isinstance(splits_raw, dict):
        lap_list = splits_raw.get('lapDTOs', [])
        cumulative_time_sec = 0.0

        for idx, lap in enumerate(lap_list):
            lap_num = idx + 1
            lap_dist = lap.get('distance', 0) / 1000
            lap_dur = lap.get('duration', 0)
            cumulative_time_sec += lap_dur
            
            # Formatowanie czasu (Time & Cumulative Time)
            dur_m, dur_s = int(lap_dur // 60), int(lap_dur % 60)
            cum_m, cum_s = int(cumulative_time_sec // 60), int(cumulative_time_sec % 60)
            dur_str = f"{dur_m}:{dur_s:02d}"
            cum_str = f"{cum_m}:{cum_s:02d}"

            # Tempo (Avg Pace, Best Pace, Moving Pace)
            lap_speed = lap.get('averageSpeed', 0)
            lap_pace = f"{int((1000/lap_speed)//60)}:{int((1000/lap_speed)%60):02d} min/km" if lap_speed > 0 else "Brak"
            
            max_speed = lap.get('maxSpeed', 0)
            best_pace = f"{int((1000/max_speed)//60)}:{int((1000/max_speed)%60):02d} min/km" if max_speed > 0 else "Brak"

            mov_speed = lap.get('averageMovingSpeed', 0)
            mov_pace = f"{int((1000/mov_speed)//60)}:{int((1000/mov_speed)%60):02d} min/km" if mov_speed > 0 else lap_pace

            gap_speed = lap.get('avgGradeAdjustedSpeed', 0)
            gap_pace = f"{int((1000/gap_speed)//60)}:{int((1000/gap_speed)%60):02d} min/km" if gap_speed > 0 else "Brak"

            # Tętno (Avg HR, Max HR)
            avg_hr = int(lap['averageHR']) if lap.get('averageHR') is not None else "Brak"
            max_hr = int(lap['maxHR']) if lap.get('maxHR') is not None else "Brak"

            # Przewyższenia (Total Ascent, Total Descent)
            ascent = int(lap.get('elevationGain', 0))
            descent = int(lap.get('elevationLoss', 0))

            # Moc (Avg Power, Max Power, Normalized Power)
            avg_pwr = int(lap['averagePower']) if lap.get('averagePower') is not None else "Brak"
            max_pwr = int(lap['maxPower']) if lap.get('maxPower') is not None else "Brak"

            # Kadencja (Avg & Max Run Cadence)
            raw_cad = lap.get('averageRunCadence') or lap.get('averageRunningCadenceInStepsPerMinute')
            avg_cad = int(round(raw_cad)) if raw_cad is not None else "Brak"
            max_cad = int(round(lap['maxRunCadence'])) if lap.get('maxRunCadence') is not None else "Brak"

            # Biomechanika (GCT, Stride, Vert Osc, Vert Ratio, GCT Balance)
            gct = f"{lap['groundContactTime']:.1f} ms" if lap.get('groundContactTime') is not None else "Brak"
            stride = f"{lap['strideLength']/100:.2f} m" if lap.get('strideLength') is not None else "Brak"
            vert_osc = f"{lap['verticalOscillation']:.2f} cm" if lap.get('verticalOscillation') is not None else "Brak"
            vert_ratio = f"{lap['verticalRatio']:.2f} %" if lap.get('verticalRatio') is not None else "Brak"
            gct_balance = f"{lap['groundContactBalanceLeft']:.1f}% L" if lap.get('groundContactBalanceLeft') is not None else "Brak"

            # Inne (Kalorie, Temperatura, Czas w ruchu)
            cals = int(lap.get('calories', 0))
            temp = f"{lap.get('averageTemperature', 0):.0f}°C" if lap.get('averageTemperature') is not None else "Brak"
            mov_time_s = int(lap.get('movingDuration', lap_dur))
            mov_time_str = f"{mov_time_s//60}:{mov_time_s%60:02d}"

            # Konstrukcja szczegółowej linii splitu
            split_line = (
                f"  * Km {lap_num} ({lap_dist:.2f} km) | Czas: {dur_str} (Łącznie: {cum_str}, W ruchu: {mov_time_str}) | "
                f"Tempo: {lap_pace} (GAP: {gap_pace}, Najlepsze: {best_pace}, Ruch: {mov_pace}) | "
                f"Tętno: {avg_hr} bpm (Max: {max_hr} bpm) | Przewyższenia: +{ascent}m / -{descent}m | "
                f"Moc: {avg_pwr} W (Max: {max_pwr} W) | Kadencja: {avg_cad} spm (Max: {max_cad} spm) | "
                f"Biomechanika: Krok {stride}, GCT {gct}, Balans GCT: {gct_balance}, Odchylenie {vert_osc}, Współczynnik {vert_ratio} | "
                f"Kalorie: {cals} kcal | Temp: {temp}"
            )
            parsed_splits.append(split_line)

    res["splits"] = parsed_splits
    return res

def generate_verification_prompt(planned_workout, activity_stats, garmin_stats=None, weekly_plan_context=None, user_profile=None, user_note=None):
    """
    Tworzy prompt dla Gemini do weryfikacji wykonanego treningu oraz całodziennej/nocnej regeneracji,
    a następnie sprawdzenia założeń na kolejny trening z planu tygodniowego i ich modyfikacji.
    """
    if user_profile is None:
        user_profile = {
            "max_hr": "ok. 202 bpm (szacowane)",
            "hr_zones": "Z1: <123 bpm, Z2: 123-144 bpm, Z3: 144-162 bpm, Z4: 162-181 bpm, Z5: >181 bpm"
        }

    splits_section = "Brak szczegółowych splitów (dzień bez treningu biegowego lub brak danych)"
    if activity_stats and activity_stats.get('splits'):
        splits_section = "\n".join(activity_stats['splits'])

    # Dane regeneracyjne z minionej nocy i koszt dzisiejszego dnia
    recovery_section = "Brak bieżących danych regeneracyjnych"
    if garmin_stats:
        recovery_section = f"""[STAN NA START DZISIEJSZEGO DNIA (REGENERACJA Z POPRZEDZAJĄCEJ NOCY)]:
- Status HRV z nocy: {garmin_stats.get('hrv_status')}
- Nocne tętno spoczynkowe (RHR): {garmin_stats.get('rhr')}
- Ocena i architektura snu: {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski Garmina o śnie: {garmin_stats.get('sleep_insights')}

[KOSZT DZISIEJSZEGO DNIA (OBCIĄŻENIE CODZIENNE I ENERGIA)]:
- Dzisiejsze kroki w ciągu dnia (w tym trening i aktywność pozatreningowa): {garmin_stats.get('today_steps')}
- Dzisiejszy średni poziom stresu: {garmin_stats.get('today_stress')}
- Poziom energii Body Battery: {garmin_stats.get('body_battery')}"""

    yesterday_section = ""
    if garmin_stats and garmin_stats.get('yesterday_training') and garmin_stats.get('yesterday_training') != "Brak aktywności (dzień wolny)":
        yesterday_section = f"""
====================
KONTEKST DNIA POPRZEDNIEGO (WCZORAJSZY TRENING):
{garmin_stats.get('yesterday_training')}
"""

    weekly_plan_section = ""
    if weekly_plan_context:
        weekly_plan_section = f"""
====================
AKTUALNY PLAN TYGODNIOWY (I KOLEJNE ZAPLANOWANE TRENINGI):
{weekly_plan_context}
"""

    note_section = ""
    if user_note:
        note_section = f"""
====================
DODATKOWE UWAGI I SAMOPOCZUCIE BIEGACZA:
{user_note}
"""

    activity_section = "Dzisiaj nie odnotowano treningu biegowego (Dzień wolny / Regeneracja)."
    if activity_stats:
        # Obsługa listy aktywności lub pojedynczej aktywności
        stats_list = activity_stats if isinstance(activity_stats, list) else [activity_stats]
        act_blocks = []

        for idx, act in enumerate(stats_list):
            splits_text = "Brak szczegółowych splitów dla tej jednostki"
            if act.get('splits'):
                splits_text = "\n".join(act['splits'])

            prefix = f"[JEDNOSTKA {idx + 1} z {len(stats_list)}]: " if len(stats_list) > 1 else ""
            block = f"""{prefix}{act.get('name')} | {act.get('distance')} w czasie {act.get('duration')} (Średnie tempo: {act.get('pace')})
- Warunki atmosferyczne i pogoda: {act.get('weather', 'Brak danych')}
- Przewyższenia (wznios/spadek): +{act.get('elevation_gain', '0')}m / -{act.get('elevation_loss', '0')}m
- Tętno: Średnie {act.get('avg_hr')} | Maksymalne {act.get('max_hr')}
  * Czas w strefach: {act.get('time_in_zones', 'według splitów i stref powyżej')}
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

    prompt = f"""Działasz jako rygorystyczny, analityczny trener biegania, fizjolog sportowy i biomechanik.
Skrypt jest uruchamiany WIECZOREM, po zakończeniu całego dnia i po wykonaniu wszystkich ewentualnych jednostek treningowych.

Twoim kluczowym zadaniem jest:
1. DOKŁADNY AUDYT I OCENA DZISIEJSZEGO DNIA (TRENING LUB DZIEŃ WOLNY / REST DAY):
   - W przypadku wykonania biegu (lub kilku jednostek, np. rozgrzewka + bieg główny + schłodzenie): Porównaj wykonane jednostki z planem na dzisiaj, oceń zgodność ze strefami, tempem i kadencją oraz wskaż uzyskane efekty fizjologiczne.
   - W przypadku DNIA WOLNEGO: Potwierdź odpoczynek, sprawdź czy był zaplanowany w planie tygodniowym i oceń odnowę biologiczną.
2. OCENA KOSZTU DZISIEJSZEGO DNIA I REGENERACJI:
   - Zbadaj bilans dzisiejszego dnia: dzisiejsze kroki (całkowity ruch), średni poziom stresu w ciągu dnia oraz aktualne wieczorne Body Battery (ile zasobów energii pozostało na koniec dnia).
   - Uwzględnij sen i nocne HRV z poprzedzającej nocy jako bazę wyjściową, z którą zawodnik zaczynał dzisiejszy dzień.
3. WERYFIKACJA I ADAPTACJA TRENINGU NA JUTRO (KOLEJNY DZIEŃ Z PLANU TYGODNIOWEGO):
   - Sprawdź w planie tygodniowym, co jest zaplanowane na JUTRO.
   - Na podstawie dzisiejszego zmęczenia (trening + kroki + stres + wieczorne Body Battery) oceń, czy zawodnik zdoła się zregenerować przez nadchodzącą noc i wykonać jutrzejszą jednostkę.
   - Podejmij decyzję: zatwierdź jutrzejszy trening lub zmodyfikuj go (złagodź intensywność, przenieś akcent, zamień na rozbieganie lub zalecaj wolne).

====================
PROFIL BIEGACZA I STREFY:
- HR max: {user_profile.get('max_hr')} | Próg mleczanowy (LTHR): {user_profile.get('lthr', 'nieznany')}
- Przybliżone strefy tętna: {user_profile.get('hr_zones')}

====================
PLANOWANY TRENING NA DZISIAJ (ZAŁOŻENIA DO WERYFIKACJI):
{planned_workout or 'Brak sztywnego planu / Trening swobodny (porównaj ze strukturą z planu tygodniowego poniżej)'}

====================
RZECZYWISTE DANE Z DZISIEJSZEGO BIEGU:
{activity_section}

====================
BIOMETRIA REGENERACJI I KOSZT DZISIEJSZEGO DNIA:
{recovery_section}
{yesterday_section}
{weekly_plan_section}
{note_section}
====================
ZADANIE DLA TRENERA — ODPOWIEDZ W NASTĘPUJĄCYCH PUNKTACH:

1. AUDYT DZISIEJSZEGO DNIA (TRENING LUB DZIEŃ WOLNY / REST DAY):
   - W przypadku wykonania biegu:
     * Ocena wykonania w skali 1–10.
     * Status: [Zrealizowany wzorowo / Przekroczona intensywność / Za wolno / Inna jednostka niż planowano].
     * Porównanie założeń z realizacją (dystans, tempo, tętno, dryf, biomechanika, anomalie).
   - W przypadku DNIA WOLNEGO (brak biegu / Rest Day):
     * Potwierdź, że dzień był dniem odpoczynku/regeneracji.
     * Oceń, czy dzień wolny był zaplanowany w planie tygodniowym, czy wynika z braku aktywności.

2. EFEKTY FIZJOLOGICZNE / OCENA REGENERACJI W DNIU WOLNYM:
   - W przypadku biegu: główny bodziec (mitochondria, mleczan itp.), ocena Aerobic TE i Anaerobic TE, koszt fizjologiczny.
   - W przypadku DNIA WOLNEGO: oceń stopień odnowy biologicznej, odbudowę glikogenu oraz obniżenie zmęczenia nerwowo-mięśniowego.

3. AUDYT KOSZTU DNIA I STANU FIZJOLOGICZNEGO:
   - Koszt dzisiejszego dnia: analiza dzisiejszej liczby kroków (w tym aktywności pozatreningowej), dzisiejszego średniego stresu oraz wieczornego stanu Body Battery (ile energii pozostało po całym dniu).
   - Wpływ snu z poprzedzającej nocy, nocnego HRV i RHR na tolerancję dzisiejszego dnia.

4. SPRAWDZENIE I ADAPTACJA JUTRZEJSZEGO TRENINGU Z PLANU TYGODNIOWEGO:
   - Wskaż, jaki trening jest zaplanowany na JUTRO w planie tygodniowym.
   - OCENA GOTOWOŚCI NA JUTRZEJSZY TRENING:
     * Czy wieczorny stan energii, dzisiejsze obciążenie krokami/stresem i biometria pozwalają na realizację jutrzejszej jednostki (zwłaszcza jeśli to akcent lub długie wybieganie)?
     * DECYZJA O KOREKCIE:
       - Jeśli wskaźniki są optymalne -> potwierdź planowany trening na jutro (podaj pełną rozgrzewkę, część główną i schłodzenie).
       - Jeśli wskaźniki sygnalizują niedostateczną regenerację lub wyczerpanie -> zmodyfikuj plan na jutro (np. obniż intensywność, zamień na lekki bieg Z1/Z2, przenieś akcent lub zalecaj wolne).
   - Podaj DOKŁADNĄ ROZPISKĘ jutrzejszej jednostki po weryfikacji (rozgrzewka, część główna z tempami/strefami, schłodzenie) oraz wskazówki na nadchodzącą noc.
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

    input_dir = "input"
    os.makedirs(input_dir, exist_ok=True)
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    # Sprawdzenie czy dane z Garmin już zostały pobrane (dodane w celach diagnostycznych).
    USE_LOCAL_DATA = os.getenv("USE_LOCAL_DATA", "False").lower() in ["true", "1"]
    dump_file = os.path.join(input_dir, "garmin_dump.json")

    # Migracja garmin_dump.json z katalogu głównego do input/ jeśli istnieje
    legacy_dump = "garmin_dump.json"
    if not os.path.exists(dump_file) and os.path.exists(legacy_dump):
        try:
            with open(legacy_dump, "r", encoding="utf-8") as lf:
                legacy_data = json.load(lf)
            with open(dump_file, "w", encoding="utf-8") as f:
                json.dump(legacy_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Przeniesiono {legacy_dump} do {dump_file}")
        except Exception:
            pass

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

    # Wybór trybu działania:
    # 'daily'   - domyślnie: codzienna weryfikacja i adaptacja po biegu / wieczorem
    # 'week'    - pełne planowanie tygodniowe ze szczegółami (kilometry, tempa, serie) na podstawie input/weekly_preferences.md -> output/weekly_plan.md
    # 'suggest' - sugestia typów/celów treningów na cały tydzień (np. Wtorek: Easy, Czwartek: Tempo progowe) bez rozpisywania km -> input/weekly_preferences.md
    mode = "daily"
    if len(sys.argv) > 1:
        arg_mode = sys.argv[1].lower()
        if arg_mode in ["suggest", "sugestia", "sugeruj", "propozycja"]:
            mode = "suggest"
        elif arg_mode in ["week", "tydzien", "plan-tygodnia", "weekly"]:
            mode = "week"

    history_dir = "trainings_history"
    os.makedirs(history_dir, exist_ok=True)

    preferences_file = os.path.join(input_dir, "weekly_preferences.md")
    weekly_plan_file = os.path.join(output_dir, "weekly_plan.md")
    config_file = os.path.join(input_dir, "training_config.json")
    note_file = os.path.join(input_dir, "user_note.md")

    # Migracja weekly_plan.md z katalogu głównego do output/ jeśli istnieje
    legacy_plan = "weekly_plan.md"
    if not os.path.exists(weekly_plan_file) and os.path.exists(legacy_plan):
        try:
            with open(legacy_plan, "r", encoding="utf-8") as lf:
                plan_txt = lf.read()
            with open(weekly_plan_file, "w", encoding="utf-8") as f:
                f.write(plan_txt)
            logger.info(f"Przeniesiono {legacy_plan} do {weekly_plan_file}")
        except Exception:
            pass

    # Automatyczna migracja weekly_preferences z katalogu głównego, jeśli plik tam istnieje
    for legacy_pref in ["weekly_preferences.md", "weekly_preferences.txt"]:
        if not os.path.exists(preferences_file) and os.path.exists(legacy_pref):
            try:
                with open(legacy_pref, "r", encoding="utf-8") as lf:
                    pref_content = lf.read()
                with open(preferences_file, "w", encoding="utf-8") as pf:
                    pf.write(pref_content)
                logger.info(f"Przeniesiono preferencje z {legacy_pref} do {preferences_file}")
                break
            except Exception:
                pass

    # 1. Wczytujemy konfigurację biegacza z pliku training_config.json (lub tworzymy szablon w input/)
    training_context = load_training_config(config_file)
    logger.info(f"Wczytano konfigurację biegacza z pliku {config_file} (Cel: {training_context.get('goal')}).")

    # 2. Wczytujemy opcjonalną notatkę / wiadomość użytkownika do trenera z input/user_note.md
    user_note = load_user_note(note_file)
    if user_note:
        logger.info(f"Wczytano dodatkową notatkę użytkownika z pliku {note_file}.")
        print(f"📝 Wczytano Twoją wiadomość z {note_file}:\n   \"{user_note}\"\n")

    # 3. Wczytujemy historię poprzednich treningów z folderu trainings_history
    training_history_entries = []
    try:
        history_files = sorted(os.listdir(history_dir), reverse=True)
        # Pobieramy do 10 ostatnich treningów
        for fname in history_files[:10]:
            fpath = os.path.join(history_dir, fname)
            with open(fpath, "r", encoding="utf-8") as hf:
                training_history_entries.append(hf.read())
        if training_history_entries:
            logger.info(f"Wczytano historię {len(training_history_entries)} ostatnich treningów z folderu {history_dir}.")
    except Exception as e:
        logger.warning(f"Nie udało się wczytać historii treningów: {e}")

    history_context = "\n\n" + "-"*40 + "\n\n".join(training_history_entries) if training_history_entries else None

    # Profil tętna do weryfikacji
    user_profile = {
        "max_hr": training_context.get("max_hr", "ok. 202 bpm (szacowane)"),
        "lthr": training_context.get("lthr", "ok. 176 bpm"),
        "hr_zones": f"Z1: {training_context.get('z1')}, Z2: {training_context.get('z2')}, Z3: {training_context.get('z3')}, Z4: {training_context.get('z4')}, Z5: {training_context.get('z5')}"
    }

    # ==================== TRYB 3: SUGESTIE TYPÓW TRENINGÓW (SUGGEST) ====================
    if mode == "suggest":
        print("\n" + "="*60)
        print("💡 TRYB SUGESTII TYPÓW TRENINGÓW NA TYDZIEŃ (GEMINI COACH) 💡")
        print("="*60)
        print("Model analizuje Twoją historię treningową, fazę i biometrię, aby zaproponować cele/typy treningów.")

        garmin_stats = parse_garmin_data(raw_data)
        suggest_prompt = generate_weekly_suggestions_prompt(
            training_context=training_context,
            history_context=history_context,
            current_recovery=garmin_stats,
            user_note=user_note
        )

        print("\n" + "="*50)
        print("WYSYŁANIE ZAPYTANIA O SUGESTIE DO GEMINI...")
        print("="*50)

        try:
            chat = client.chats.create(model='gemini-3.6-flash')
            response = chat.send_message(suggest_prompt)

            print("\n💡 PROPONOWANY PODZIAŁ TYPÓW TRENINGU NA TEN TYDZIEŃ 💡\n")
            print(response.text)

            # Zapisujemy wygenerowane sugestie do weekly_preferences.md z zachowaniem możliwości ręcznej edycji
            with open(preferences_file, "w", encoding="utf-8") as pf:
                pf.write("# Sugestia wygenerowana przez Trenera Gemini na podstawie historii i biometrii\n")
                pf.write("# Możesz zmodyfikować poniższe linie według własnych planów, a następnie uruchomić 'python garmin_coach.py week'\n\n")
                pf.write(response.text)

            logger.info(f"Sugestie typów treningów zapisano do pliku: {preferences_file}")
            print(f"\n✅ Zapisano propozycję do pliku: {preferences_file}")
            print(f"👉 Jeśli chcesz coś zmienić, wyedytuj '{preferences_file}', a następnie uruchom:")
            print(f"   python garmin_coach.py week")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas generowania sugestii: {e}")

    # ==================== TRYB 1: PLANOWANIE TYGODNIOWE (RAZ W TYGODNIU) ====================
    elif mode == "week":
        print("\n" + "="*60)
        print("🗓️  TRYB PLANOWANIA TYGODNIOWEGO (GEMINI COACH) 🗓️")
        print("="*60)

        # Sprawdzamy czy plik preferencji istnieje
        if not os.path.exists(preferences_file):
            print(f"⚠️  Nie znaleziono pliku '{preferences_file}'!")
            print("👉 Wskazówka: Możesz wygenerować sugestię za pomocą polecenia:")
            print("   python garmin_coach.py suggest")
            print("   lub utworzyć plik ręcznie, wpisując np.:\nWtorek: Easy\nCzwartek: Tempo progowe\nSobota: Long run\n")
            
            # Tworzymy pusty plik z instrukcją
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

        week_prompt = generate_weekly_plan_prompt(
            days_preferences,
            training_context,
            history_context=history_context,
            user_note=user_note
        )

        print("\n" + "="*50)
        print("WYSYŁANIE PLANU DO GEMINI (Generowanie planu na cały tydzień)...")
        print("="*50)

        try:
            chat = client.chats.create(model='gemini-3.6-flash')
            response = chat.send_message(week_prompt)

            print("\n🏆 ROZPISKA PLANU NA CAŁY TYDZIEŃ OD TRENERA 🏆\n")
            print(response.text)

            with open(weekly_plan_file, "w", encoding="utf-8") as wf:
                wf.write(response.text)
            logger.info(f"Plan tygodniowy został zapisany do pliku: {weekly_plan_file}")
            print(f"\n✅ Zapisano plan do: {weekly_plan_file}. Będzie on podstawą do codziennej weryfikacji i adaptacji!")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas generowania planu tygodniowego: {e}")

    # ==================== TRYB 2: CODZIENNA WERYFIKACJA I ADAPTACJA (PO BIEGU / WIECZOREM) ====================
    elif mode == "daily":
        logger.info("Uruchomiono tryb codziennej weryfikacji treningu, regeneracji i adaptacji...")

        # 1. Parsujemy dane biometryczne z dzisiejszego poranka i nocy oraz wczorajszego dnia
        garmin_stats = parse_garmin_data(raw_data)

        # 2. Wczytujemy plan tygodniowy, jeśli istnieje
        weekly_plan_content = None
        if os.path.exists(weekly_plan_file):
            try:
                with open(weekly_plan_file, "r", encoding="utf-8") as wf:
                    weekly_plan_content = wf.read()
            except Exception:
                pass

        # 3. Szukamy dzisiejszych aktywności do analizy (może być ich kilka: rozgrzewka, bieg główny, schłodzenie)
        today_acts = raw_data.get('today', {}).get('activities', [])
        all_today_stats = []
        for act in today_acts:
            st = parse_activity_biomechanics(act)
            if st:
                all_today_stats.append(st)

        days_pl = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
        today_day_name = f"{days_pl[today.weekday()]} ({today.isoformat()})"

        if all_today_stats:
            print("\n" + "="*50)
            print(f"📊 POBRANO AKTYWNOŚCI DO AUDYTU ({len(all_today_stats)} jednostek dzisiaj):")
            print("="*50)
            for idx, act_st in enumerate(all_today_stats):
                prefix = f"Jednostka {idx + 1}: " if len(all_today_stats) > 1 else ""
                print(f"\n▶️ {prefix}{act_st['name']} ({act_st['distance']}, tempo: {act_st['pace']})")
                for k, v in act_st.items():
                    if k not in ['splits', 'name', 'distance', 'pace']:
                        print(f"   - {k}: {v}")

            planned_workout_desc = (
                f"Założenia na dzień: {today_day_name} według załączonego planu tygodniowego. "
                f"Dzisiaj zarejestrowano łącznie {len(all_today_stats)} jednostek treningowych (np. rozgrzewka, część główna, schłodzenie). "
                f"Odszukaj sekcję odpowiadającą temu dniu w planie tygodniowym i sprawdź zgodność wykonania całości lub poszczególnych etapów."
            )
        else:
            print("\n" + "="*50)
            print(f"🛌 DZIEŃ BEZ BIEGU / REST DAY: {today_day_name}")
            print("="*50)
            print("Dzisiaj nie odnotowano aktywności biegowej.")
            print("Model przeprowadzi audyt regeneracji w dniu wolnym i sprawdzi gotowość na kolejny trening z planu!")

            planned_workout_desc = (
                f"Dzień: {today_day_name}. W dniu dzisiejszym NIE BYŁO TRENINGU BIEGOWEGO (Dzień wolny / Rest Day). "
                f"Sprawdź w planie tygodniowym, czy dzień wolny był zaplanowany. "
                f"Skup się na ocenie regeneracji (sen, HRV, RHR, Body Battery, dzisiejsze kroki i stres) i przygotowaniu oraz adaptacji do JUTRZEJSZEGO treningu."
            )

        verification_prompt = generate_verification_prompt(
            planned_workout=planned_workout_desc,
            activity_stats=all_today_stats if all_today_stats else None,
            garmin_stats=garmin_stats,
            weekly_plan_context=weekly_plan_content,
            user_profile=user_profile,
            user_note=user_note
        )

        print("\n" + "="*50)
        print("WYSYŁANIE RAPORTU DO GEMINI (Audyt biegu + Regeneracja + Adaptacja kolejnego dnia)...")
        print("="*50)

        try:
            chat = client.chats.create(model='gemini-3.6-flash')
            response = chat.send_message(verification_prompt)

            print("\n🏆 RAPORT TRENERSKI I ADAPTACJA KOLEJNEGO TRENINGU 🏆\n")
            print(response.text)

            # Zapisujemy raport do archiwum trainings_history/YYYY-MM-DD.md (zarówno po biegu, jak i w dniu wolnym)
            workout_date = today.isoformat()
            history_file_path = os.path.join(history_dir, f"{workout_date}.md")

            if all_today_stats:
                # Jeśli była przynajmniej jedna jednostka, pobieramy datę z pierwszej
                first_raw_act = today_acts[0] if today_acts else None
                if first_raw_act:
                    act_start = first_raw_act.get('startTimeLocal', '')
                    if len(act_start) >= 10:
                        workout_date = act_start[:10]
                        history_file_path = os.path.join(history_dir, f"{workout_date}.md")

                acts_archive_blocks = []
                for idx, act_s in enumerate(all_today_stats):
                    splits_formatted = "\n".join(act_s.get('splits', []))
                    single_block = f"""### Jednostka {idx + 1}: {act_s['name']}
- Warunki pogodowe: {act_s.get('weather', 'Brak danych')}
- Dystans: {act_s['distance']} | Czas: {act_s['duration']} | Średnie tempo: {act_s['pace']}
- Tętno: Średnie {act_s['avg_hr']} | Max {act_s['max_hr']}
- Training Effect: Aerobowy {act_s['aerobic_te']} | Beztlenowy {act_s['anaerobic_te']}
- Biomechanika: Średnia kadencja {act_s['avg_cadence']}, Krok {act_s['stride_length']}, Kontakt z podłożem {act_s['ground_contact_time']}, Odchylenie pionowe {act_s['vertical_oscillation']}

#### Splity:
{splits_formatted}"""
                    acts_archive_blocks.append(single_block)

                archive_content = f"""# TRENING Z DNIA: {workout_date} ({today_day_name})
Liczba zarejestrowanych jednostek: {len(all_today_stats)}

## Biometria regeneracyjna i bilans dnia:
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Dzisiejszy całodzienny stres: {garmin_stats.get('today_stress')}
- Dzisiejsze kroki (cały dzień): {garmin_stats.get('today_steps')}

## Zarejestrowane aktywności:
{chr(10).join(acts_archive_blocks)}

## Ocena trenera i adaptacja na jutrzejszy dzień:
{response.text}
"""
            else:
                archive_content = f"""# DZIEŃ WOLNY / REST DAY: {workout_date} ({today_day_name})
Aktywność: Brak biegu (Regeneracja / Odpoczynek)

## Biometria regeneracyjna i bilans dnia:
- HRV (miniona noc): {garmin_stats.get('hrv_status')}
- RHR (miniona noc): {garmin_stats.get('rhr')}
- Sen (miniona noc): {garmin_stats.get('sleep_score')} (Głęboki: {garmin_stats.get('deep_sleep')}, REM: {garmin_stats.get('rem_sleep')})
- Wnioski o śnie: {garmin_stats.get('sleep_insights')}
- Body Battery: {garmin_stats.get('body_battery')}
- Dzisiejszy całodzienny stres: {garmin_stats.get('today_stress')}
- Dzisiejsze kroki (cały dzień): {garmin_stats.get('today_steps')}

## Ocena trenera i adaptacja na jutrzejszy dzień:
{response.text}
"""
            with open(history_file_path, "w", encoding="utf-8") as hf:
                hf.write(archive_content)
            logger.info(f"Raport z dnia {workout_date} zapisano do archiwum: {history_file_path}")

            # Zapisujemy również bieżący wynik do output/last_daily_report.md
            latest_daily_file = os.path.join(output_dir, "last_daily_report.md")
            with open(latest_daily_file, "w", encoding="utf-8") as lf:
                lf.write(archive_content)
            logger.info(f"Bieżący wynik działania daily zapisano do pliku: {latest_daily_file}")
            print(f"\n✅ Zapisano raport do: {latest_daily_file} oraz archiwum {history_file_path}")
        except Exception as e:
            logger.error(f"Wystąpił błąd podczas weryfikacji i adaptacji: {e}")

if __name__ == "__main__":
    main()
