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

# Załadowanie zmiennych środowiskowych z pliku .env (jeśli uruchamiane lokalnie)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Prekompilowane wyrażenia regularne dla parsowania Markdown i podpisów

# Główne katalogi i pliki
INPUT_DIR = "input"
STATE_FILE_PATH = os.path.join(INPUT_DIR, "telegram_state.json")

RE_HR = re.compile(r'^(?:-{3,}|={3,})$')
RE_TABLE_DIVIDER = re.compile(r'^:?-+:?$')
RE_BOLD = re.compile(r'\*\*(.*?)\*\*')
RE_DATE_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')

RE_PLAN_KM = re.compile(
    r'(?:\|\s*Dystans całkowity biegowy \(km\)\s*\|[^|]*\|\s*([0-9.,]+)|'
    r'Łączny planowany kilometraż.*?([0-9.,]+)\s*(?:km)?|'
    r'Łączny dystans.*?([0-9.,]+)\s*(?:km)?)',
    re.IGNORECASE
)

RE_DAY_HEADERS = {
    day: re.compile(rf'###\s*{day}\s*[-–:]\s*([^\n\r]+)', re.IGNORECASE)
    for day in ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
}

RE_CAPTION_DATE = re.compile(
    r'(?:ADAPTACJA TRENINGU NA (?:DZIEŃ DZISIEJSZY|KOLEJNY DZIEŃ|DZIEŃ)|'
    r'OCENA GOTOWOŚCI I ADAPTACJA NA DZIEŃ KOLEJNY|'
    r'## Ocena trenera i adaptacja na dzień|'
    r'# TRENING (?:Z DNIA|SIŁOWY|BIEGOWY \+ SIŁOWNIA)|'
    r'# DZIEŃ WOLNY[^:]*):\s*([^\n\r]+)',
    re.IGNORECASE
)
RE_CLEAN_BRACKETS = re.compile(r'\[.*?\]')
RE_DECISION_SECTION = re.compile(
    r'\*\s*(?:DECYZJA ADAPTACYJNA(?:\s*/\s*STOPIEŃ GOTOWOŚCI)?|DECYZJA O KOREKCIE).*?:(.*?)(?=\*\s*Uzasadnienie|\*\s*ROZPISKA|###|\Z)',
    re.DOTALL | re.IGNORECASE
)
RE_SCHEDULE_SECTION = re.compile(
    r'\*\s*ROZPISKA NA (?:KOLEJNY )?DZIEŃ.*?:(.*?)(?=\*\s*Wytyczne|\*\s*Zalecenia|###|\Z)',
    re.DOTALL | re.IGNORECASE
)


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
    if headers is None:
        headers = {"User-Agent": "GeminiCoach/1.0"}
    elif "User-Agent" not in headers:
        headers["User-Agent"] = "GeminiCoach/1.0"
        
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except Exception as e:
        safe_url = re.sub(r'bot[^/]+/', 'bot***/', url)
        error_msg = str(e)
        if hasattr(e, 'read'):
            try:
                # Telegram często wysyła szczegóły błędu w ciele odpowiedzi
                error_body = e.read().decode('utf-8')
                error_msg += f" | Szczegóły: {error_body}"
            except:
                pass
        logger.warning(f"Błąd podczas odpytywania {safe_url}: {error_msg}")
        return None


def markdown_to_html_doc(md_text, title="Raport Coach Gemini"):
    """
    Konwertuje raport w formacie Markdown na pełny, nowoczesny dokument HTML.

    Dokument jest zoptymalizowany pod kątem ekranów smartfonów, włączając tryb ciemny
    (Dark Mode) oraz responsywne tabele. Obsługuje podstawowe znaczniki Markdown takie
    jak nagłówki, pogrubienia, listy i tabele.

    Args:
        md_text (str): Treść raportu w formacie Markdown.
        title (str, optional): Tytuł dokumentu HTML. Domyślnie "Raport Coach Gemini".

    Returns:
        str: Pełny kod HTML wygenerowanego dokumentu.
    """
    lines = md_text.splitlines()
    html_lines = []
    in_table = False
    in_list = False
    table_has_header = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table, table_has_header
        if in_table:
            html_lines.append("</tbody></table></div>")
            in_table = False
            table_has_header = False

    for line in lines:
        stripped = line.strip()

        # Pusta linia
        if not stripped:
            close_list()
            close_table()
            continue

        # Pozioma kreska
        if RE_HR.match(stripped):
            close_list()
            close_table()
            html_lines.append("<hr>")
            continue

        # Obsługa tabeli Markdown
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Sprawdzenie czy to linia podziału |---|---|
            if all(RE_TABLE_DIVIDER.match(c) for c in cells if c):
                continue

            if not in_table:
                in_table = True
                html_lines.append('<div class="table-wrapper"><table>')
                html_lines.append("<thead><tr>")
                for c in cells:
                    html_lines.append(f"<th>{html.escape(c)}</th>")
                html_lines.append("</tr></thead><tbody>")
                table_has_header = True
            else:
                html_lines.append("<tr>")
                for c in cells:
                    cell_html = html.escape(c)
                    # Zamiana **tekst** na pogrubienie wewnątrz komórki
                    cell_html = RE_BOLD.sub(r'<strong>\1</strong>', cell_html)
                    html_lines.append(f"<td>{cell_html}</td>")
                html_lines.append("</tr>")
            continue
        else:
            close_table()

        # Nagłówki
        if stripped.startswith("#### "):
            close_list()
            h_text = html.escape(stripped[5:].strip())
            html_lines.append(f"<h4>{h_text}</h4>")
            continue
        elif stripped.startswith("### "):
            close_list()
            h_text = html.escape(stripped[4:].strip())
            html_lines.append(f"<h3>{h_text}</h3>")
            continue
        elif stripped.startswith("## "):
            close_list()
            h_text = html.escape(stripped[3:].strip())
            html_lines.append(f"<h2>{h_text}</h2>")
            continue
        elif stripped.startswith("# "):
            close_list()
            h_text = html.escape(stripped[2:].strip())
            html_lines.append(f"<h1>{h_text}</h1>")
            continue

        # Elementy listy (* lub -)
        if stripped.startswith("* ") or stripped.startswith("- "):
            if not in_list:
                in_list = True
                html_lines.append("<ul>")
            item_text = html.escape(stripped[2:].strip())
            item_text = RE_BOLD.sub(r'<strong>\1</strong>', item_text)
            html_lines.append(f"<li>{item_text}</li>")
            continue
        else:
            close_list()

        # Zwykły akapit
        p_text = html.escape(stripped)
        p_text = RE_BOLD.sub(r'<strong>\1</strong>', p_text)
        html_lines.append(f"<p>{p_text}</p>")

    close_list()
    close_table()

    body_content = "\n".join(html_lines)

    css = """
    :root {
      --bg: #09090b;
      --card-bg: #121214;
      --border: #27272a;
      --border-subtle: #1c1c1f;
      --accent: #f4f4f5;
      --accent-muted: #a1a1aa;
      --text: #f4f4f5;
      --text-muted: #a1a1aa;
      --th-bg: #18181b;
      --tr-even: #0e0e10;
      --tr-odd: #141416;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      margin: 0;
      padding: 14px;
    }
    .container {
      max-width: 860px;
      margin: 0 auto;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px 22px;
      box-shadow: 0 12px 35px rgba(0, 0, 0, 0.85);
    }
    h1 { font-size: 1.4rem; color: #ffffff; margin-top: 6px; margin-bottom: 16px; border-bottom: 2px solid #3f3f46; padding-bottom: 8px; letter-spacing: -0.01em; }
    h2 { font-size: 1.2rem; color: #f4f4f5; margin-top: 26px; border-bottom: 1px solid var(--border); padding-bottom: 6px; letter-spacing: -0.01em; }
    h3 { font-size: 1.05rem; color: #e4e4e7; margin-top: 20px; margin-bottom: 8px; }
    h4 { font-size: 0.95rem; color: #d4d4d8; margin-top: 14px; margin-bottom: 6px; }
    p { margin: 8px 0; color: var(--text); }
    ul { margin: 8px 0; padding-left: 22px; }
    li { margin-bottom: 6px; color: var(--text-muted); }
    li strong, p strong { color: #ffffff; }
    hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
    .table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 16px 0; border-radius: 8px; border: 1px solid var(--border); background: var(--card-bg); }
    table { width: 100%; border-collapse: collapse; font-size: 0.86rem; white-space: nowrap; }
    th { background: var(--th-bg); color: #ffffff; padding: 10px 12px; font-weight: 600; text-align: left; border-bottom: 2px solid var(--border); }
    td { padding: 9px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text); }
    tr:nth-child(even) { background: var(--tr-even); }
    tr:nth-child(odd) { background: var(--tr-odd); }
    tr:hover { background: rgba(255, 255, 255, 0.05); }
    """

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="container">
    {body_content}
  </div>
</body>
</html>"""



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
    days_order = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    day_entries = []

    for day in days_order:
        day_matches = RE_DAY_HEADERS[day].findall(md_text)
        if day_matches:
            titles = [RE_BOLD.sub(r'\\1', m).strip() for m in day_matches]
            combined = " + ".join(titles)
            day_entries.append(f"▪️ <b>{day}:</b> {html.escape(combined)}")

    km_match = RE_PLAN_KM.search(md_text)
    km_val = ""
    if km_match:
        for g in km_match.groups():
            if g:
                km_val = g.strip()
                break

    km_info = f"\\n\\n📊 <b>Planowany dystans biegowy:</b> ~{km_val} km" if km_val else ""
    summary_days = "\\n".join(day_entries) if day_entries else "▪️ Pełny harmonogram dni tygodnia w załączniku HTML."

    caption = (
        f"🗓️ <b>PLAN TRENINGOWY NA TEN TYDZIEŃ</b>\\n\\n"
        f"{summary_days}"
        f"{km_info}\\n\\n"
        f"📎 <i>Pełny plan w załączniku HTML poniżej.</i>"
    )

    if len(caption) > 1000:
        caption = caption[:990] + "...\\n\\n📎 <i>Pełny plan w załączniku HTML.</i>"

    return caption


def extract_daily_report_caption(md_text):
    """
    Pobiera z raportu zwięzłą informację (dymek czatu) o dzisiejszym treningu i parametrach.
    """
    target_date = "Dzisiaj"
    date_match = RE_CAPTION_DATE.search(md_text)
    if date_match:
        target_date = date_match.group(1).strip()
        target_date = RE_CLEAN_BRACKETS.sub('', target_date).strip()

    re_profile = re.search(r'\*\s*\*\*Profil jednostki\*\*:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    re_score = re.search(r'\*\s*\*\*Ocena treningu\*\*:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    re_cost = re.search(r'\*\s*\*\*Koszt dzienny i stan zasobów[^\*]*\*\*:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    re_decision = re.search(r'\*\s*\*\*DECYZJA ADAPTACYJNA[^\*]*\*\*:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    
    if not re_decision:
        re_decision = re.search(r'\*\s*\*\*STOPIEŃ GOTOWOŚCI[^\*]*\*\*:\s*([^\n\r]+)', md_text, re.IGNORECASE)

    workout_lines = []
    
    if re_profile:
        workout_lines.append(f"🏃 <b>Trening:</b> {html.escape(re_profile.group(1).strip())}")
    else:
        workout_lines.append("🛋 <b>Trening:</b> Dzień wolny (Rest Day)")

    if re_score:
        score_val = re_score.group(1).strip().strip("[]")
        workout_lines.append(f"⭐ <b>Ocena:</b> {html.escape(score_val)}")
        
    if re_cost:
        workout_lines.append(f"🔋 <b>Stan zasobów:</b> {html.escape(re_cost.group(1).strip())}")
        
    if re_decision:
        decision_val = re_decision.group(1).strip()
        workout_lines.append(f"🧠 <b>Adaptacja na jutro:</b> {html.escape(decision_val)}")

    caption_workout = "\n".join(workout_lines)

    caption = (
        f"📅 <b>AUDYT DNIA: {html.escape(target_date)}</b>\n\n"
        f"{caption_workout}\n\n"
        f"📎 <i>Pełny raport w załączniku HTML.</i>"
    )

    if len(caption) > 1000:
        caption = caption[:990] + "...\n\n📎 <i>Pełny raport w załączniku.</i>"

    return caption


def send_telegram_document(file_bytes, filename, caption="", parse_mode="HTML"):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    """
    Wysyła plik jako załącznik na Telegram za pomocą żądania multipart/form-data.

    Jeśli wystąpi błąd parsowania HTML, wysyłanie jest automatycznie ponawiane
    jako zwykły tekst bez tagów HTML (parse_mode=None).

    Args:
        bot_token (str): Token autoryzacyjny bota Telegram.
        chat_id (str): ID docelowego czatu.
        file_bytes (bytes): Zawartość pliku w bajtach.
        filename (str): Nazwa pliku dołączonego do wiadomości.
        caption (str, optional): Podpis wiadomości pod załącznikiem. Domyślnie "".
        parse_mode (str, optional): Tryb parsowania wiadomości (np. 'HTML' lub 'Markdown'). Domyślnie "HTML".

    Returns:
        bytes: Odpowiedź serwera w formacie bajtów, lub None w przypadku niepowodzenia.
    """
    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    body = bytearray()

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode("utf-8"))

    if caption:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))
        if parse_mode:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n{parse_mode}\r\n'.encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b'Content-Type: text/html; charset=utf-8\r\n\r\n')
    body.extend(file_bytes)
    body.extend(b'\r\n')
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

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
        STATE_FILE_PATH (str, optional): Ścieżka do pliku JSON przechowującego stan.
        max_age_hours (int, optional): Maksymalny wiek wiadomości w godzinach. Domyślnie 36.

    Returns:
        tuple: Krotka (tekst_notatek, nowy_stan_dict) jeśli znaleziono wiadomości, inaczej (None, None).
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

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
        if u_id > max_update_id:
            max_update_id = u_id

        msg = upd.get("message")
        if not msg:
            continue

        m_chat_id = msg.get("chat", {}).get("id")
        if str(m_chat_id) != str(chat_id):
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
        if m_id > max_message_id:
            max_message_id = m_id
        if m_date > max_date:
            max_date = m_date

    if not valid_msgs:
        return None, None

    valid_msgs.sort(key=lambda x: x[2])
    msg_blocks = [
        f"--- Treść wiadomości z Telegrama ({datetime.fromtimestamp(m_date).strftime('%Y-%m-%d %H:%M')}) ---\\n{text}"
        for _, _, m_date, text in valid_msgs
    ]
    
    return "\\n\\n".join(msg_blocks), {
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
        STATE_FILE_PATH (str, optional): Ścieżka docelowa do pliku JSON.
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
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
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
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

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
        caption = "🛠️ <b>[TRYB DEBUG]</b>\n\n" + caption
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

    html_bytes = html_content.encode("utf-8")
    logger.info(f"Wysyłanie raportu jako załącznik HTML na Telegram ({attachment_filename})...")
    
    if send_telegram_document(html_bytes, attachment_filename, caption=caption):
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
    
    if args.type == "plan":
        sys.exit(send_weekly_plan(args.file))
    else:
        sys.exit(send_daily_report(args.file))
