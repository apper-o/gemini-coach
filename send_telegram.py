import os
import sys
import json
import logging
import urllib.request
import urllib.parse
from dotenv import load_dotenv

# Załadowanie zmiennych środowiskowych z pliku .env (jeśli uruchamiane lokalnie)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4000


def split_text_into_chunks(text, max_len=MAX_TELEGRAM_MESSAGE_LENGTH):
    """
    Dzieli długi tekst na fragmenty mieszczące się w limicie znaków Telegrama (4096 znaków).
    Zachowuje akapity i linie, nie ucinając zdań w połowie, jeśli to możliwe.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1  # +1 za znak nowej linii
        if current_length + line_len > max_len:
            if current_chunk:
                chunks.append("\n".join(current_chunk).strip())
                current_chunk = []
                current_length = 0

            # Jeśli pojedyncza linia jest dłuższa niż limit, podziel ją na sztywno
            if line_len > max_len:
                for i in range(0, len(line), max_len):
                    chunks.append(line[i:i + max_len])
            else:
                current_chunk.append(line)
                current_length = line_len
        else:
            current_chunk.append(line)
            current_length += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk).strip())

    return [c for c in chunks if c]


def send_telegram_message(bot_token, chat_id, message_text):
    """
    Wysyła pojedynczą wiadomość przez Telegram Bot API.
    Najpierw próbuje wysłać z parse_mode='Markdown'.
    W przypadku błędu składni Markdown automatycznie ponawia próbę w trybie czystego tekstu.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()

    # Próba 1: Markdown
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        _post(payload)
        return True
    except Exception as e_md:
        logger.warning(f"Wysyłka w formacie Markdown nie powiodła się ({e_md}). Ponawiam jako zwykły tekst...")

    # Próba 2: Czysty tekst (gwarancja dostarczenia)
    payload.pop("parse_mode", None)
    try:
        _post(payload)
        return True
    except Exception as e_plain:
        logger.error(f"Nie udało się wysłać wiadomości na Telegram: {e_plain}")
        return False


def send_report(file_path):
    """
    Wczytuje raport z pliku i wysyła go na Telegram.
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
            content = f.read().strip()
    except Exception as e:
        logger.error(f"Nie udało się odczytać pliku {file_path}: {e}")
        return 1

    if not content:
        logger.warning(f"Plik {file_path} jest pusty. Brak treści do wysłania.")
        return 0

    chunks = split_text_into_chunks(content)
    logger.info(f"Wysyłanie raportu na Telegram (liczba części: {len(chunks)})...")

    success = True
    for idx, chunk in enumerate(chunks, 1):
        prefix = f"🏃 **GARMIN COACH REPORT** (Część {idx}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        if not send_telegram_message(bot_token, chat_id, prefix + chunk):
            success = False

    if success:
        logger.info("✅ Raport został pomyślnie wysłany na Telegram!")
        return 0
    else:
        logger.error("❌ Wystąpiły błędy podczas wysyłania części raportu na Telegram.")
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            print("❌ Brak skonfigurowanych zmiennych TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID w .env")
            sys.exit(1)
        ok = send_telegram_message(bot_token, chat_id, "🤖 Cześć! To wiadomość testowa z Twojego asystenta Garmin Coach.")
        if ok:
            print("✅ Połączenie z botem Telegram działa prawidłowo!")
            sys.exit(0)
        else:
            print("❌ Błąd połączenia z Telegramem.")
            sys.exit(1)

    target_file = sys.argv[1] if len(sys.argv) > 1 else "output/last_daily_report.md"
    sys.exit(send_report(target_file))
