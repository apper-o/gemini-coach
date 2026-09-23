import os
import sys
import re
import html
import json
import logging
import urllib.request
import urllib.parse
from dotenv import load_dotenv

# Załadowanie zmiennych środowiskowych z pliku .env (jeśli uruchamiane lokalnie)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def markdown_to_html_doc(md_text, title="Raport Garmin Coach"):
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
        if re.match(r'^-{3,}$', stripped) or re.match(r'^={3,}$', stripped):
            close_list()
            close_table()
            html_lines.append("<hr>")
            continue

        # Obsługa tabeli Markdown
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Sprawdzenie czy to linia podziału |---|---|
            if all(re.match(r'^:?-+:?$', c) for c in cells if c):
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
                    cell_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', cell_html)
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
            item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
            html_lines.append(f"<li>{item_text}</li>")
            continue
        else:
            close_list()

        # Zwykły akapit
        p_text = html.escape(stripped)
        p_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', p_text)
        html_lines.append(f"<p>{p_text}</p>")

    close_list()
    close_table()

    body_content = "\n".join(html_lines)

    css = """
    :root {
      --bg: #0b0f19;
      --card-bg: #161f30;
      --border: #23324d;
      --accent: #38bdf8;
      --accent-green: #22c55e;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --th-bg: #1e293b;
      --tr-even: #121a29;
      --tr-odd: #182337;
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
      box-shadow: 0 8px 30px rgba(0,0,0,0.5);
    }
    h1 {
      font-size: 1.45rem;
      color: var(--accent);
      margin-top: 6px;
      margin-bottom: 16px;
      border-bottom: 2px solid var(--accent);
      padding-bottom: 8px;
    }
    h2 {
      font-size: 1.25rem;
      color: #7dd3fc;
      margin-top: 26px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
    }
    h3 {
      font-size: 1.1rem;
      color: #bae6fd;
      margin-top: 20px;
      margin-bottom: 8px;
    }
    h4 {
      font-size: 0.98rem;
      color: #e0f2fe;
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
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
      white-space: nowrap;
    }
    th {
      background: var(--th-bg);
      color: var(--accent);
      padding: 10px 12px;
      font-weight: 600;
      text-align: left;
      border-bottom: 2px solid var(--border);
    }
    td {
      padding: 9px 12px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
    }
    tr:nth-child(even) { background: var(--tr-even); }
    tr:nth-child(odd) { background: var(--tr-odd); }
    tr:hover { background: rgba(56, 189, 248, 0.12); }
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


def extract_concise_caption(md_text):
    """
    Ekstrahuje z raportu wyłącznie informację o dacie oraz treningu na dziś
    zgodnie z wytycznymi użytkownika (krótki, czytelny dymek czatu).
    """
    # 1. Poszukiwanie daty
    target_date = "Dzisiaj"
    date_match = re.search(r'ADAPTACJA TRENINGU NA DZIEŃ DZISIEJSZY:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'ADAPTACJA TRENINGU NA KOLEJNY DZIEŃ:\s*([^\n\r]+)', md_text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'# TRENING Z DNIA:\s*([^\n\r]+)', md_text, re.IGNORECASE)

    if date_match:
        target_date = date_match.group(1).strip()
        # Wyczyszczenie zbędnych dopisków
        target_date = re.sub(r'\[.*?\]', '', target_date).strip()

    # 2. Poszukiwanie sekcji treningu / adaptacji
    workout_lines = []

    # Szukamy sekcji 'ROZPISKA NA DZIEŃ DZISIEJSZY' lub 'DECYZJA O KOREKCIE'
    decision_match = re.search(
        r'\*\s*DECYZJA O KOREKCIE.*?:(.*?)(?=\*\s*Uzasadnienie|\*\s*ROZPISKA|###|\Z)',
        md_text,
        re.DOTALL | re.IGNORECASE
    )
    schedule_match = re.search(
        r'\*\s*ROZPISKA NA DZIEŃ DZISIEJSZY.*?:(.*?)(?=\*\s*Wytyczne|###|\Z)',
        md_text,
        re.DOTALL | re.IGNORECASE
    )

    if not schedule_match:
        schedule_match = re.search(
            r'\*\s*ROZPISKA NA KOLEJNY DZIEŃ.*?:(.*?)(?=\*\s*Wytyczne|###|\Z)',
            md_text,
            re.DOTALL | re.IGNORECASE
        )

    # Budujemy pigułkę informacyjną
    if schedule_match:
        raw_schedule = schedule_match.group(1).strip()
        for l in raw_schedule.split("\n"):
            clean_l = l.strip().lstrip("* -").strip()
            if clean_l and not clean_l.startswith("###"):
                workout_lines.append(f"▪️ {clean_l}")

    if decision_match and not workout_lines:
        clean_dec = decision_match.group(1).strip()
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


def send_telegram_document(bot_token, chat_id, file_bytes, filename, caption=""):
    """
    Wysyła plik HTML jako załącznik na Telegram za pomocą żądania multipart/form-data.
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
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="parse_mode"\r\n\r\nHTML\r\n'.encode("utf-8"))

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
        logger.error(f"Błąd wysyłki dokumentu na Telegram: {e}")
        return None


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

    # 1. Przygotowanie zwięzłego dymku czatu (data + trening)
    caption = extract_concise_caption(md_content)

    # 2. Konwersja pełnego raportu Markdown na elegancki HTML
    html_content = markdown_to_html_doc(md_content, title="Raport Garmin Coach")
    html_bytes = html_content.encode("utf-8")

    # Zapis pliku HTML również lokalnie w katalogu output/
    html_file_path = os.path.splitext(file_path)[0] + ".html"
    try:
        with open(html_file_path, "w", encoding="utf-8") as hf:
            hf.write(html_content)
        logger.info(f"Wygenerowano lokalny plik HTML: {html_file_path}")
    except Exception as e:
        logger.warning(f"Nie udało się zapisać lokalnego pliku HTML: {e}")

    # Określenie nazwy załącznika
    date_match = re.search(r'\d{4}-\d{2}-\d{2}', md_content)
    file_date_tag = date_match.group(0) if date_match else "raport"
    attachment_filename = f"Raport_Garmin_{file_date_tag}.html"

    logger.info(f"Wysyłanie raportu jako załącznik HTML na Telegram ({attachment_filename})...")
    res = send_telegram_document(bot_token, chat_id, html_bytes, attachment_filename, caption=caption)

    if res:
        logger.info("✅ Raport został pomyślnie wysłany na Telegram jako załącznik HTML z podpisem!")
        return 0
    else:
        logger.error("❌ Błąd wysyłania raportu na Telegram.")
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            print("❌ Brak skonfigurowanych zmiennych TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID w .env")
            sys.exit(1)

        test_html = "<h1>Test Garmin Coach</h1><p>Wszystko działa idealnie!</p>".encode("utf-8")
        test_caption = "📅 <b>Test</b>\n\n🎯 <b>TRENING NA DZIŚ:</b>\n▪️ Test połączenia bota z załącznikiem HTML."
        ok = send_telegram_document(bot_token, chat_id, test_html, "test.html", caption=test_caption)
        if ok:
            print("✅ Testowy załącznik wysłany pomyślnie na Telegram!")
            sys.exit(0)
        else:
            print("❌ Błąd połączenia z Telegramem.")
            sys.exit(1)

    target_file = sys.argv[1] if len(sys.argv) > 1 else "output/last_daily_report.md"
    sys.exit(send_report(target_file))
