import os
import sys
import re
import html
import json
import time
import logging
import urllib.request
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv

# Załadowanie zmiennych środowiskowych z pliku .env (jeśli uruchamiane lokalnie)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Prekompilowane wyrażenia regularne dla parsowania Markdown i podpisów
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


def markdown_to_html_doc(md_text, title="Raport Coach Gemini"):
    """
    Konwertuje raport w formacie Markdown na pełny, nowoczesny dokument HTML
    zoptymalizowany pod kątem ekranów smartfonów (Dark Mode, responsywne tabele).
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
    h1 {
      font-size: 1.4rem;
      color: #ffffff;
      margin-top: 6px;
      margin-bottom: 16px;
      border-bottom: 2px solid #3f3f46;
      padding-bottom: 8px;
      letter-spacing: -0.01em;
    }
    h2 {
      font-size: 1.2rem;
      color: #f4f4f5;
      margin-top: 26px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
      letter-spacing: -0.01em;
    }
    h3 {
      font-size: 1.05rem;
      color: #e4e4e7;
      margin-top: 20px;
      margin-bottom: 8px;
    }
    h4 {
      font-size: 0.95rem;
      color: #d4d4d8;
      margin-top: 14px;
      margin-bottom: 6px;
    }
    p { margin: 8px 0; color: var(--text); }
    ul { margin: 8px 0; padding-left: 22px; }
    li { margin-bottom: 6px; color: var(--text-muted); }
    li strong, p strong { color: #ffffff; }
    hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
    .table-wrapper {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      margin: 16px 0;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--card-bg);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
      white-space: nowrap;
    }
    th {
      background: var(--th-bg);
      color: #ffffff;
      padding: 10px 12px;
      font-weight: 600;
      text-align: left;
      border-bottom: 2px solid var(--border);
    }
    td {
      padding: 9px 12px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text);
    }
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


def is_weekly_plan_content(md_text, file_path=""):
    """
    Sprawdza, czy przekazany plik lub treść Markdown to plan tygodniowy.
    """
    if "weekly_plan" in str(file_path).lower():
        return True
    lower = md_text.lower()
    days = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
    matched = sum(1 for d in days if f"### {d}" in lower or f"## {d}" in lower or f"* **{d}" in lower)
    return matched >= 3 or "tabela porównawcza mikrocykli" in lower or "plan na cały tydzień" in lower


def extract_weekly_plan_caption(md_text):
    """
    Ekstrahuje zwięzły dymek Telegrama dla planu tygodniowego:
    wykaz zadeklarowanych dni z jednostkami oraz łączny planowany kilometraż biegowy.
    """
    days_order = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    day_entries = []

    for day in days_order:
        # Szukamy nagłówków dni tygodnia: ### Poniedziałek - ... lub ### Poniedziałek: ...
        day_matches = RE_DAY_HEADERS[day].findall(md_text)
        if day_matches:
            titles = [RE_BOLD.sub(r'\1', m).strip() for m in day_matches]
            combined = " + ".join(titles)
            day_entries.append(f"▪️ <b>{day}:</b> {html.escape(combined)}")

    # Wyszukiwanie łącznego dystansu z tabeli mikrocykli lub podsumowania
    km_match = RE_PLAN_KM.search(md_text)
    km_val = ""
    if km_match:
        for g in km_match.groups():
            if g:
                km_val = g.strip()
                break

    km_info = f"\n\n📊 <b>Planowany dystans biegowy:</b> ~{km_val} km" if km_val else ""
    summary_days = "\n".join(day_entries) if day_entries else "▪️ Pełny harmonogram dni tygodnia w załączniku HTML."

    caption = (
        f"🗓️ <b>PLAN TRENINGOWY NA TEN TYDZIEŃ</b>\n\n"
        f"{summary_days}"
        f"{km_info}\n\n"
        f"📎 <i>Pełna rozpiska, serie, ciężary i zalecenia w załączniku HTML poniżej.</i>"
    )

    if len(caption) > 1000:
        caption = caption[:990] + "...\n\n📎 <i>Pełny plan w załączniku HTML.</i>"

    return caption


def extract_concise_caption(md_text):
    """
    Ekstrahuje z raportu wyłącznie informację o dacie oraz treningu na dziś
    zgodnie z wytycznymi użytkownika (krótki, czytelny dymek czatu).
    W niedzielę (koniec mikrocyklu) prezentuje ogólny stopień gotowości bez treningu.
    """
    # 1. Poszukiwanie daty
    target_date = "Dzisiaj"
    date_match = RE_CAPTION_DATE.search(md_text)

    if date_match:
        target_date = date_match.group(1).strip()
        # Wyczyszczenie zbędnych dopisków
        target_date = RE_CLEAN_BRACKETS.sub('', target_date).strip()

    # 2. Poszukiwanie sekcji treningu / adaptacji
    decision_match = RE_DECISION_SECTION.search(md_text)
    schedule_match = RE_SCHEDULE_SECTION.search(md_text)

    raw_schedule = schedule_match.group(1).strip() if schedule_match else ""
    raw_decision = decision_match.group(1).strip() if decision_match else ""

    is_end_of_microcycle = (
        "koniec mikrocyklu" in raw_schedule.lower()
        or "koniec mikrocyklu" in raw_decision.lower()
        or any(w in raw_decision.upper() for w in ["PEŁNA GOTOWOŚĆ", "UMIARKOWANE ZMĘCZENIE", "GŁĘBOKIE ZMĘCZENIE", "WYMAGANA REGENERACJA"])
    )

    if is_end_of_microcycle:
        readiness_str = ""
        for line in raw_decision.split("\n"):
            clean = line.strip().strip("* -[]")
            if clean:
                readiness_str = clean
                break
        readiness_part = f"\n▪️ <b>Stopień gotowości:</b> {html.escape(readiness_str)}" if readiness_str else ""
        caption = (
            f"📅 <b>{html.escape(target_date)}</b>\n\n"
            f"🏁 <b>KONIEC MIKROCYKLU:</b>{readiness_part}\n"
            f"▪️ Za ułożenie nowego planu na kolejny tydzień odpowiada tryb <code>plan</code>.\n\n"
            f"📎 <i>Pełna analiza audytu i zalecenia regeneracyjne w załączniku HTML poniżej.</i>"
        )
        if len(caption) > 1000:
            caption = caption[:990] + "...\n\n📎 <i>Pełny raport w załączniku.</i>"
        return caption

    workout_lines = []
    # Budujemy pigułkę informacyjną dla zwykłych dni
    if schedule_match:
        for l in raw_schedule.split("\n"):
            clean_l = l.strip().lstrip("* -").strip()
            if clean_l and not clean_l.startswith("###"):
                workout_lines.append(f"▪️ {clean_l}")

    if decision_match and not workout_lines:
        clean_dec = raw_decision.strip()
        if clean_dec:
            workout_lines.append(f"▪️ {clean_dec}")

    # Fallback jeśli raport nie zawierał sztywnych nagłówków
    if not workout_lines:
        workout_lines.append("▪️ Szczegóły zaplanowanej jednostki znajdziesz w załączonym raporcie.")

    # Ograniczenie liczby linii do 5, by dymek był zawsze zwięzły
    caption_workout = "\n".join(workout_lines[:5])

    caption = (
        f"📅 <b>{html.escape(target_date)}</b>\n\n"
        f"🎯 <b>TRENING NA DZIŚ:</b>\n"
        f"{caption_workout}\n\n"
        f"📎 <i>Pełna analiza, splity i tabele w załączniku HTML poniżej.</i>"
    )

    # Telegram caption limit to 1024 znaki
    if len(caption) > 1000:
        caption = caption[:990] + "...\n\n📎 <i>Pełny raport w załączniku.</i>"

    return caption


def send_telegram_document(bot_token, chat_id, file_bytes, filename, caption="", parse_mode="HTML"):
    """
    Wysyła plik HTML jako załącznik na Telegram za pomocą żądania multipart/form-data.
    W razie błędu parsowania HTML w podpisie (caption) automatycznie ponawia próbę jako zwykły tekst.
    """
    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    body = bytearray()

    # Pole: chat_id
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode("utf-8"))

    # Pole: caption
    if caption:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode("utf-8"))
        if parse_mode:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n{parse_mode}\r\n'.encode("utf-8"))

    # Pole: document
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b'Content-Type: text/html; charset=utf-8\r\n\r\n')
    body.extend(file_bytes)
    body.extend(b'\r\n')

    # Zamknięcie boundary
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except Exception as e:
        logger.warning(f"Błąd wysyłki dokumentu z podpisem ({e}).")
        if parse_mode:
            plain_caption = re.sub(r'<[^>]+>', '', caption)
            logger.info("Ponawiam wysyłkę z podpisem w czystym tekście bez HTML...")
            return send_telegram_document(bot_token, chat_id, file_bytes, filename, caption=plain_caption, parse_mode=None)
        logger.error(f"Nie udało się wysłać dokumentu na Telegram: {e}")
        return None


def fetch_recent_telegram_messages(bot_token=None, chat_id=None, state_file=None, max_age_hours=36):
    """
    Pobiera najnowsze wiadomości od użytkownika z czatu Telegrama (np. raport z Hevy lub notatkę z siłowni).
    Filtruje wiadomości:
    - tylko z autoryzowanego TELEGRAM_CHAT_ID,
    - nie starsze niż max_age_hours (domyślnie 36h),
    - o ID wiadomości wyższym niż ostatnio przetworzone (zapisane w state_file).

    Zwraca:
      (tekst_notatek, nowy_stan_dict) lub (None, None)
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.info("Brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID – pomijam pobieranie wiadomości z Telegrama.")
        return None, None

    state_file = state_file or os.path.join("input", "telegram_state.json")
    last_update_id = 0
    last_message_id = 0

    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as sf:
                sdata = json.load(sf)
                last_update_id = sdata.get("last_processed_update_id", 0)
                last_message_id = sdata.get("last_processed_message_id", 0)
        except Exception as e:
            logger.warning(f"Nie udało się odczytać pliku stanu Telegrama {state_file}: {e}")

    offset_param = f"&offset={last_update_id + 1}" if last_update_id > 0 else ""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?timeout=5&limit=100&allowed_updates=%5B%22message%22%5D{offset_param}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GarminCoach/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Błąd podczas odpytywania Telegram API o wiadomości: {e}")
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

        if not m_text:
            continue

        if m_id <= last_message_id:
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

    msg_blocks = []
    for u_id, m_id, m_date, text in valid_msgs:
        dt_str = datetime.fromtimestamp(m_date).strftime("%Y-%m-%d %H:%M")
        msg_blocks.append(f"--- Treść wiadomości z Telegrama ({dt_str}) ---\n{text}")

    combined_text = "\n\n".join(msg_blocks)
    new_state = {
        "last_processed_update_id": max_update_id,
        "last_processed_message_id": max_message_id,
        "last_processed_timestamp": max_date,
        "last_updated_local": datetime.now().isoformat()
    }

    return combined_text, new_state


def save_telegram_state(new_state, state_file=None, bot_token=None):
    """
    Zapisuje stan przetworzonych wiadomości (aby uniknąć dublowania w kolejnych dniach)
    oraz potwierdza offset w Telegram API.
    """
    if not new_state:
        return
    state_file = state_file or os.path.join("input", "telegram_state.json")
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as sf:
            json.dump(new_state, sf, indent=2, ensure_ascii=False)
        logger.info(f"Zapisano stan wiadomości Telegram do {state_file}")
    except Exception as e:
        logger.warning(f"Błąd zapisu stanu Telegrama do {state_file}: {e}")

    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    u_id = new_state.get("last_processed_update_id")
    if bot_token and u_id:
        try:
            ack_url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={u_id + 1}&limit=1"
            req = urllib.request.Request(ack_url, headers={"User-Agent": "GarminCoach/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception:
            pass


def finish_run(new_tg_state=None, debug=False, note_file=None):
    """
    Zapisuje zaktualizowany stan Telegrama po udanym wykonaniu trybu.
    W trybie debug (debug=True) operacja ta jest pomijana, aby chronić stan wiadomości.
    """
    if debug:
        logger.info("[DEBUG] Tryb debugowania aktywny: pominięto aktualizację stanu Telegrama.")
        print("\n📄 [DEBUG] Stan Telegrama pozostał nienaruszony.")
        return

    # Kompatybilność wsteczna na wypadek wywołania ze starej sygnatury finish_run(note_file, new_tg_state, debug)
    if isinstance(note_file, dict) and new_tg_state is None:
        new_tg_state = note_file

    if new_tg_state:
        save_telegram_state(new_tg_state)


def send_report(file_path):
    """
    Główna funkcja: konwertuje raport Markdown na HTML, generuje zwięzły podpis
    (data + trening na dziś) i wysyła elegancki załącznik na Telegram.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.info("Brak zmiennych TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID. Pomijanie wysyłki na Telegram.")
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

    # 1. Rozpoznanie typu raportu (plan tygodniowy vs raport dzienny) oraz trybu debug
    is_plan = is_weekly_plan_content(md_content, file_path)
    is_debug_file = "debug" in os.path.normpath(file_path).split(os.sep)

    date_match = RE_DATE_ISO.search(md_content)

    if is_plan:
        caption = extract_weekly_plan_caption(md_content)
        title = "Plan Tygodniowy - Coach Gemini"
        file_date_tag = date_match.group(0) if date_match else datetime.now().strftime("%Y-%m-%d")
        attachment_filename = f"Plan_Tygodniowy_{file_date_tag}.html"
    else:
        caption = extract_concise_caption(md_content)
        title = "Raport Coach Gemini"
        file_date_tag = date_match.group(0) if date_match else "raport"
        attachment_filename = f"Raport_Coach_Gemini_{file_date_tag}.html"

    # Wyróżnienie wizualne dla raportów z trybu piaskownicy (debug)
    if is_debug_file:
        caption = "🛠️ <b>[TRYB DEBUG / TEST]</b>\n\n" + caption
        title = f"[DEBUG] {title}"
        attachment_filename = f"DEBUG_{attachment_filename}"

    # 2. Odczyt pre-renderowanego HTML lub konwersja raportu Markdown
    html_file_path = os.path.splitext(file_path)[0] + ".html"
    html_content = None
    if os.path.exists(html_file_path) and os.path.getmtime(html_file_path) >= os.path.getmtime(file_path):
        try:
            with open(html_file_path, "r", encoding="utf-8") as hf:
                cached_html = hf.read()
            if cached_html.strip():
                html_content = cached_html
        except Exception:
            pass

    if not html_content:
        html_content = markdown_to_html_doc(md_content, title=title)
        try:
            with open(html_file_path, "w", encoding="utf-8") as hf:
                hf.write(html_content)
            logger.info(f"Wygenerowano lokalny plik HTML: {html_file_path}")
        except Exception as e:
            logger.warning(f"Nie udało się zapisać lokalnego pliku HTML: {e}")

    html_bytes = html_content.encode("utf-8")

    logger.info(f"Wysyłanie raportu jako załącznik HTML na Telegram ({attachment_filename})...")
    res = send_telegram_document(bot_token, chat_id, html_bytes, attachment_filename, caption=caption)

    if res:
        logger.info("✅ Raport został pomyślnie wysłany na Telegram jako załącznik HTML z podpisem!")
        return 0
    else:
        logger.error("❌ Błąd wysyłania raportu na Telegram.")
        return 1


if __name__ == "__main__":
    target_file = sys.argv[1] if len(sys.argv) > 1 else "output/last_daily_report.md"
    sys.exit(send_report(target_file))
