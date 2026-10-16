import os
import sys
import re
import html
import json
import time
import logging
import urllib.request
from datetime import datetime
from dotenv import load_dotenv
from utils_html import markdown_to_html_doc, RE_BOLD

# Załadowanie zmiennych środowiskowych z pliku .env (jeśli uruchamiane lokalnie)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Główne katalogi i pliki
INPUT_DIR_PATH = "input"
STATE_FILE_PATH = os.path.join(INPUT_DIR_PATH, "telegram_state.json")
DAYS_PL = ("Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela")

# Prekompilowane wyrażenia regularne dla parsowania Markdown i podpisów
RE_DATE_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')
RE_DAY_NAME = re.compile(rf"({'|'.join(DAYS_PL)})", re.IGNORECASE)

RE_PLAN_KM = re.compile(
    r'(?:\|\s*Dystans całkowity biegowy \(km\)\s*\|[^|]*\|\s*([0-9.,]+)|'
    r'Łączny planowany kilometraż.*?([0-9.,]+)\s*(?:km)?|'
    r'Łączny dystans.*?([0-9.,]+)\s*(?:km)?)',
    re.IGNORECASE
)

RE_DAY_HEADERS = {
    day: re.compile(rf'###\s*{day}(?:\s*\([^)]*\))?\s*[-–:]\s*([^\n\r]+)', re.IGNORECASE)
    for day in DAYS_PL
}

RE_CLEAN_BRACKETS = re.compile(r'\[.*?\]')
RE_SCORE_VALUE = re.compile(r'(\d+(?:[.,]\d+)?\s*/\s*10)')


def _get_telegram_credentials():
    """Pobiera token bota oraz ID czatu ze zmiennych środowiskowych."""
    return os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")


def _make_telegram_request(url, data=None, headers=None, timeout=10):
    """
    Pomocnicza funkcja do wykonywania żądań HTTP do Telegram API za pomocą urllib.

    Args:
        url (str): Adres URL żądania.
        data (bytes, optional): Dane żądania w formacie bajtów (dla POST). Domyślnie None.
        headers (dict, optional): Słownik nagłówków HTTP. Domyślnie None.
        timeout (int, optional): Maksymalny czas oczekiwania na odpowiedź w sekundach. Domyślnie 10.

    Returns:
        bytes: Odpowiedź serwera w formacie bajtów lub None w przypadku błędu.
    """
    req_headers = {"User-Agent": "GeminiCoach/1.0", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except Exception as e:
        safe_url = re.sub(r'bot[^/]+/', 'bot***/', url)
        error_msg = str(e)
        if hasattr(e, 'read'):
            try:
                # Telegram często wysyła szczegóły błędu w ciele odpowiedzi
                error_msg += f" | Szczegóły: {e.read().decode('utf-8')}"
            except Exception:
                pass
        logger.warning(f"Błąd podczas odpytywania {safe_url}: {error_msg}")
        return None


def _truncate_telegram_caption(caption, max_length=1000, footer_text="Pełny materiał w załączniku HTML."):
    """
    Przycina tekst podpisu do limitu znaków Telegrama, dodając informację o załączniku.
    """
    if len(caption) <= max_length:
        return caption
    suffix = f"...\n\n📎 <i>{footer_text}</i>"
    cut = caption[:max_length - len(suffix)]
    # Zabezpieczenie przed ucięciem w środku tagu HTML
    if "<" in cut and cut.rfind("<") > cut.rfind(">"):
        cut = cut[:cut.rfind("<")]
    return cut + suffix


def extract_weekly_plan_caption(md_text):
    """
    Generuje caption dla planu tygodniowego do Telegrama.
    Pobiera wykaz zadeklarowanych dni z jednostkami oraz łączny planowany kilometraż biegowy.

    Args:
        md_text (str): Zawartość pliku Markdown (plan tygodniowy).

    Returns:
        str: Sformatowany tekst wiadomości dla Telegrama, sformatowany w HTML,
             o długości maksymalnej dostosowanej do limitów Telegrama.
    """
    day_entries = []
    for day in DAYS_PL:
        day_matches = RE_DAY_HEADERS[day].findall(md_text)
        if day_matches:
            combined = " + ".join(RE_BOLD.sub(r'\1', m).strip() for m in day_matches)
            day_entries.append(f"▪️ <b>{day}:</b> {html.escape(combined)}")

    km_match = RE_PLAN_KM.search(md_text)
    km_val = next((g.strip() for g in km_match.groups() if g), "") if km_match else ""
    km_info = f"\n\n📊 <b>Planowany dystans biegowy:</b> ~{km_val} km" if km_val else ""
    summary_days = "\n".join(day_entries) if day_entries else "▪️ Pełny harmonogram dni tygodnia w załączniku HTML."

    caption = (
        f"🗓️ <b>PLAN TRENINGOWY NA TEN TYDZIEŃ</b>\n\n"
        f"{summary_days}"
        f"{km_info}\n\n"
        f"📎 <i>Pełny plan w załączniku HTML poniżej.</i>"
    )
    return _truncate_telegram_caption(caption, footer_text="Pełny plan w załączniku HTML.")


def extract_daily_report_caption(md_text):
    """
    Pobiera z raportu dobowego zwięzłą informację (dymek czatu) o zrealizowanym treningu,
    ocenie egzekucji, stanie zasobów oraz decyzji adaptacyjnej na kolejny dzień.

    Args:
        md_text (str): Zawartość pliku Markdown raportu dobowego.

    Returns:
        str: Sformatowany podpis HTML dla Telegrama przycięty do bezpiecznego limitu.
    """
    # 1. Wyznaczenie daty audytowanego dnia
    target_date = "Dzisiaj"
    m_hdr = re.search(r"(?:#\s*AUDYT DZIENNY|##\s*1\.\s*AUDYT[^:]*):\s*([^\n\r]+)", md_text, re.I)
    if m_hdr:
        raw_date_str = m_hdr.group(1).strip()
        m_day = RE_DAY_NAME.search(raw_date_str)
        m_iso = RE_DATE_ISO.search(raw_date_str)
        if m_day and m_iso:
            target_date = f"{m_day.group(1).capitalize()}, {m_iso.group(0)}"
        elif m_iso:
            target_date = m_iso.group(0)
        else:
            target_date = RE_CLEAN_BRACKETS.sub('', raw_date_str).strip()
    else:
        m_iso = RE_DATE_ISO.search(md_text)
        if m_iso:
            target_date = m_iso.group(0)

    # 2. Identyfikacja zrealizowanych jednostek treningowych
    m_day_type = re.search(r"^-\s*Typ dnia:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)
    day_type = m_day_type.group(1).strip() if m_day_type else ""
    day_type_lower = day_type.lower()

    m_run = re.search(r"^-\s*Bieg:\s*(TAK|NIE)(?:\s*\(([0-9.,]+)\s*km(?:,\s*sesje:\s*([0-9]+))?\))?", md_text, re.MULTILINE | re.I)
    is_run_meta = bool(m_run and m_run.group(1).upper() == "TAK")
    run_km = m_run.group(2) if m_run and m_run.group(2) else ""

    m_run_type = re.search(r"^-\s*Typ treningu biegowego:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)
    run_type_meta = m_run_type.group(1).strip() if m_run_type else ""

    m_gym = re.search(r"^-\s*Siłownia:\s*(TAK|NIE)(?:\s*\(([^)]+)\))?", md_text, re.MULTILINE | re.I)
    is_gym_meta = bool(m_gym and m_gym.group(1).upper() == "TAK")
    gym_meta = m_gym.group(2).strip() if m_gym and m_gym.group(2) else ""

    profiles = [p.strip() for p in re.findall(r"^[*-]?\s*\*?\*?Profil jednostki\*?\*?:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)]
    m_char = re.search(r"^[*-]?\s*\*?\*?Charakter dnia\*?\*?:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)

    c_lower = md_text.lower()
    is_swim = any(k in c_lower for k in ("typ dnia: pływanie", "typ dnia: plywanie", "pool swim", "trening pływania"))

    workout_entries = []

    if is_run_meta:
        desc = profiles[0] if profiles else (run_type_meta if run_type_meta and run_type_meta != "Brak biegu" else "Bieg")
        km_str = f" ({run_km} km)" if run_km and run_km != "0.00" else ""
        workout_entries.append(f"🏃 <b>Trening biegowy:</b> {html.escape(desc)}{km_str}")

    if is_gym_meta:
        if len(profiles) > 1 and is_run_meta:
            desc = profiles[1]
        elif profiles and not is_run_meta:
            desc = profiles[0]
        else:
            desc = f"Siłownia {gym_meta}" if gym_meta else "Siłownia"
        workout_entries.append(f"🏋️ <b>Siłownia:</b> {html.escape(desc)}")

    if is_swim:
        desc = profiles[0] if profiles and not is_run_meta and not is_gym_meta else "Pływanie"
        m_swim_dist = re.search(r"(?:Pool Swim|Trening pływania)[^\n]*\n-\s*Dystans:\s*([0-9.,]+\s*(?:km|m))", md_text, re.I)
        dist_str = f" ({m_swim_dist.group(1)})" if m_swim_dist else ""
        workout_entries.append(f"🏊 <b>Pływanie:</b> {html.escape(desc)}{dist_str}")

    if not workout_entries:
        is_cycling = any(k in c_lower for k in ("rower", "cycling", "trenażer", "cross-training")) or "trening uzupełniający" in day_type_lower
        is_rest = (
            any(k in day_type_lower for k in ("regeneracja", "wolny", "rest", "brak"))
            or (not profiles and bool(m_char and any(k in m_char.group(1).lower() for k in ("regeneracja", "brak jednostki", "wolny"))))
        )
        if is_cycling:
            desc = profiles[0] if profiles else "Cross-training"
            workout_entries.append(f"🚴 <b>Cross-training:</b> {html.escape(desc)}")
        elif is_rest or not profiles:
            rest_desc = f" – {m_char.group(1).strip()}" if (is_rest and m_char) else ""
            if len(rest_desc) > 60:
                rest_desc = rest_desc[:57] + "..."
            workout_entries.append(f"🛋 <b>Trening:</b> Dzień wolny (Rest Day){html.escape(rest_desc)}")
        else:
            workout_entries.append(f"🏃 <b>Trening:</b> {html.escape(profiles[0])}")

    # 3. Ocena treningu / egzekucji planu
    re_score = re.search(r"^[*-]?\s*\*?\*?Ocena(?:\s+egzekucji(?:\s+planu)?|\s+treningu)?\*?\*?:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)
    if re_score:
        raw_score = re_score.group(1).strip().strip("[]")
        m_score_num = RE_SCORE_VALUE.search(raw_score)
        if m_score_num:
            score_num = m_score_num.group(1).replace(" ", "")
            after_dash = re.split(r"[-–—]", raw_score, maxsplit=1)
            if len(after_dash) > 1 and after_dash[1].strip():
                note = after_dash[1].strip()
                if "." in note and note.find(".") < 60:
                    note = note[:note.find(".")]
                if len(note) > 60:
                    note = note[:57] + "..."
                score_val = f"{score_num} – {note}"
            else:
                score_val = score_num
        else:
            score_val = raw_score[:60]
        workout_entries.append(f"⭐ <b>Ocena:</b> {html.escape(score_val)}")

    # 4. Stan zasobów i bilans autonomiczny
    re_cost = re.search(r"^[*-]?\s*\*?\*?(?:Bilans autonomiczny i drenaż zasobów|Koszt dzienny i stan zasobów|Koszt dzienny)[^\*:]*\*?\*?:\s*([^\n\r]+)", md_text, re.MULTILINE | re.I)
    if re_cost:
        raw_cost = re_cost.group(1).strip()
        end_sent = raw_cost.find(".")
        cost_val = raw_cost[:end_sent + 1] if end_sent > 15 else raw_cost
        if len(cost_val) > 120:
            cost_val = cost_val[:117] + "..."
        workout_entries.append(f"🔋 <b>Stan zasobów:</b> {html.escape(cost_val)}")

    # 5. Decyzja adaptacyjna trenera
    re_dec = re.search(r"^[*-]?\s*\*?\*?(?:DECYZJA ADAPTACYJNA(?:\s*/\s*STOPIEŃ GOTOWOŚCI)?|DECYZJA O KOREKCIE|STOPIEŃ GOTOWOŚCI)\*?\*?:\s*(?:[\n\r]+\s*)?([^\n\r]+)", md_text, re.MULTILINE | re.I)
    if re_dec:
        workout_entries.append(f"🧠 <b>Adaptacja na jutro:</b> {html.escape(re_dec.group(1).strip())}")

    caption = (
        f"📅 <b>AUDYT DNIA: {html.escape(target_date)}</b>\n\n"
        f"{chr(10).join(workout_entries)}\n\n"
        f"📎 <i>Pełny raport w załączniku HTML.</i>"
    )
    return _truncate_telegram_caption(caption, footer_text="Pełny raport w załączniku HTML.")


def send_telegram_document(file_bytes, filename, caption="", parse_mode="HTML"):
    """
    Wysyła plik jako załącznik na Telegram za pomocą żądania multipart/form-data.

    Jeśli wystąpi błąd parsowania HTML, wysyłanie jest automatycznie ponawiane
    jako zwykły tekst bez tagów HTML (parse_mode=None).

    Args:
        file_bytes (bytes): Zawartość pliku w bajtach.
        filename (str): Nazwa pliku dołączonego do wiadomości.
        caption (str, optional): Podpis wiadomości pod załącznikiem. Domyślnie "".
        parse_mode (str, optional): Tryb parsowania wiadomości (np. 'HTML' lub 'Markdown'). Domyślnie "HTML".

    Returns:
        bytes: Odpowiedź serwera w formacie bajtów, lub None w przypadku niepowodzenia.
    """
    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token or not chat_id:
        logger.warning("Brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID – pomijam wysyłkę dokumentu.")
        return None

    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    body = bytearray()

    def add_field(name, value):
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))

    add_field("chat_id", chat_id)
    if caption:
        add_field("caption", caption)
        if parse_mode:
            add_field("parse_mode", parse_mode)

    body.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f'Content-Type: text/html; charset=utf-8\r\n\r\n'.encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    response_data = _make_telegram_request(url, data=bytes(body), headers=headers, timeout=30)

    if response_data is None and parse_mode:
        plain_caption = re.sub(r'<[^>]+>', '', caption)
        logger.info("Ponawiam wysyłkę z podpisem w czystym tekście bez HTML...")
        return send_telegram_document(file_bytes, filename, caption=plain_caption, parse_mode=None)

    return response_data


def fetch_recent_telegram_messages(max_age_hours=36):
    """
    Pobiera najnowsze wiadomości użytkownika z Telegrama.

    Filtruje wiadomości według danego ID czatu, maksymalnego wieku oraz stanu
    z ostatniego uruchomienia, aby uniknąć ponownego przetwarzania.

    Args:
        max_age_hours (int, optional): Maksymalny wiek wiadomości w godzinach. Domyślnie 36.

    Returns:
        tuple: Krotka (tekst_notatek, nowy_stan_dict) jeśli znaleziono wiadomości, inaczej (None, None).
    """
    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token or not chat_id:
        logger.warning("Brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID – pomijam pobieranie wiadomości z Telegrama.")
        return None, None

    last_update_id = 0
    last_message_id = 0

    if os.path.exists(STATE_FILE_PATH):
        try:
            with open(STATE_FILE_PATH, "r", encoding="utf-8") as sf:
                sdata = json.load(sf)
                last_update_id = sdata.get("last_processed_update_id", 0)
                last_message_id = sdata.get("last_processed_message_id", 0)
        except Exception as e:
            logger.warning(f"Nie udało się odczytać pliku stanu Telegrama {STATE_FILE_PATH}: {e}")

    offset_param = f"&offset={last_update_id + 1}" if last_update_id > 0 else ""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?timeout=5&limit=100&allowed_updates=%5B%22message%22%5D{offset_param}"

    resp_data = _make_telegram_request(url, timeout=10)
    if not resp_data:
        return None, None

    try:
        data = json.loads(resp_data.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Błąd podczas dekodowania JSON odpowiedzi Telegram API: {e}")
        return None, None

    if not data.get("ok"):
        logger.warning(f"Odpowiedź Telegram API nie jest poprawna: {data}")
        return None, None

    results = data.get("result", [])
    if not results:
        return None, None

    now_ts = time.time()
    valid_msgs = []
    max_update_id = last_update_id
    max_message_id = last_message_id
    max_date = 0

    for upd in results:
        u_id = upd.get("update_id", 0)
        max_update_id = max(max_update_id, u_id)

        msg = upd.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue

        m_id = msg.get("message_id", 0)
        m_date = msg.get("date", 0)
        m_text = (msg.get("text") or msg.get("caption") or "").strip()

        if not m_text or m_id <= last_message_id:
            continue

        age_hours = (now_ts - m_date) / 3600.0
        if age_hours > max_age_hours:
            logger.info(f"Pominięto wiadomość z Telegrama starszą niż {max_age_hours}h ({age_hours:.1f}h).")
            continue

        valid_msgs.append((u_id, m_id, m_date, m_text))
        max_message_id = max(max_message_id, m_id)
        max_date = max(max_date, m_date)

    if not valid_msgs:
        return None, None

    valid_msgs.sort(key=lambda x: x[2])
    msg_blocks = [
        f"--- Treść wiadomości z Telegrama ({datetime.fromtimestamp(m_date).strftime('%Y-%m-%d %H:%M')}) ---\n{text}"
        for _, _, m_date, text in valid_msgs
    ]

    return "\n\n".join(msg_blocks), {
        "last_processed_update_id": max_update_id,
        "last_processed_message_id": max_message_id,
        "last_processed_timestamp": max_date,
        "last_updated_local": datetime.now().isoformat()
    }


def save_telegram_state(new_state):
    """
    Zapisuje zaktualizowany stan przetworzonych wiadomości z Telegrama do pliku JSON.

    Potwierdza również przetworzenie wiadomości w Telegram API poprzez
    wysłanie zapytania z odpowiednim offsetem.

    Args:
        new_state (dict): Nowy słownik stanu do zapisania.
    """
    if not new_state:
        return
    try:
        os.makedirs(os.path.dirname(STATE_FILE_PATH), exist_ok=True)
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as sf:
            json.dump(new_state, sf, indent=2, ensure_ascii=False)
        logger.info(f"Zapisano stan wiadomości Telegram do {STATE_FILE_PATH}")
    except Exception as e:
        logger.warning(f"Błąd zapisu stanu Telegrama do {STATE_FILE_PATH}: {e}")

    bot_token, _ = _get_telegram_credentials()
    u_id = new_state.get("last_processed_update_id")
    if bot_token and u_id:
        ack_url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={u_id + 1}&limit=1"
        _make_telegram_request(ack_url, timeout=5)


def finish_run(new_tg_state=None, debug=False):
    """
    Finalizuje działanie skryptu zapisując ewentualnie nowy stan wiadomości Telegram.
    W trybie debugowania operacja aktualizacji jest w pełni pomijana.

    Args:
        new_tg_state (dict, optional): Nowy stan Telegrama. Domyślnie None.
        debug (bool, optional): Flaga trybu debugowania, zapobiega mutacjom stanu. Domyślnie False.
    """
    if debug:
        logger.info("[DEBUG] Tryb debugowania aktywny: stan Telegrama pozostał nienaruszony.")
        return

    if new_tg_state:
        save_telegram_state(new_tg_state)


def _send_telegram_report(file_path, report_type="daily"):
    """
    Wewnętrzna funkcja wysyłająca raport Markdown na Telegram w postaci HTML.
    """
    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token or not chat_id:
        logger.warning("Brak zmiennych TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID. Pomijanie wysyłki na Telegram.")
        return 0

    if not os.path.exists(file_path):
        logger.error(f"Plik raportu do wysłania nie istnieje: {file_path}")
        return 1

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read().strip()
    except Exception as e:
        logger.error(f"Nie udało się odczytać pliku {file_path}: {e}")
        return 1

    if not md_content:
        logger.warning(f"Plik {file_path} jest pusty. Brak treści do wysłania.")
        return 0

    is_plan = (report_type == "plan")
    is_debug_file = "debug" in os.path.normpath(file_path).split(os.sep)

    date_match = RE_DATE_ISO.search(md_content)
    file_date_tag = date_match.group(0) if date_match else (datetime.now().strftime("%Y-%m-%d") if is_plan else "raport")

    if is_plan:
        caption = extract_weekly_plan_caption(md_content)
        title = "Plan Tygodniowy - Coach Gemini"
        attachment_filename = f"Plan_Tygodniowy_{file_date_tag}.html"
    else:
        caption = extract_daily_report_caption(md_content)
        title = "Raport Coach Gemini"
        attachment_filename = f"Raport_Coach_Gemini_{file_date_tag}.html"

    if is_debug_file:
        caption = _truncate_telegram_caption("🛠️ <b>[TRYB DEBUG]</b>\n\n" + caption)
        title = f"[DEBUG] {title}"
        attachment_filename = f"DEBUG_{attachment_filename}"

    html_file_path = os.path.splitext(file_path)[0] + ".html"
    html_content = markdown_to_html_doc(md_content, title=title)

    try:
        with open(html_file_path, "w", encoding="utf-8") as hf:
            hf.write(html_content)
        logger.info(f"Wygenerowano lokalny plik HTML: {html_file_path}")
    except Exception as e:
        logger.warning(f"Nie udało się zapisać lokalnego pliku HTML: {e}")

    logger.info(f"Wysyłanie raportu jako załącznik HTML na Telegram ({attachment_filename})...")
    if send_telegram_document(html_content.encode("utf-8"), attachment_filename, caption=caption):
        logger.info("✅ Raport został pomyślnie wysłany na Telegram jako załącznik HTML z podpisem!")
        return 0

    logger.error("❌ Błąd wysyłania raportu na Telegram.")
    return 1


def send_daily_report(file_path):
    """Wysyła dzienny raport treningowy na Telegram."""
    return _send_telegram_report(file_path, report_type="daily")


def send_weekly_plan(file_path):
    """Wysyła pełny plan tygodniowy na Telegram."""
    return _send_telegram_report(file_path, report_type="plan")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wysyła raporty treningowe Markdown na Telegram.")
    parser.add_argument("file", nargs="?", default="output/last_daily_report.md", help="Ścieżka do pliku (domyślnie: output/last_daily_report.md)")
    parser.add_argument("--type", choices=["daily", "plan"], default="daily", help="Rodzaj raportu: daily lub plan (domyślnie: daily)")

    args = parser.parse_args()
    sys.exit(send_weekly_plan(args.file) if args.type == "plan" else send_daily_report(args.file))
