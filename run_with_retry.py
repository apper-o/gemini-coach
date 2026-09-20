#!/usr/bin/env python3
"""
Skrypt automatycznego wznawiania (retry) dla garmin_coach.py.
Uruchamia garmin_coach.py we wskazanym trybie (daily, week, suggest)
z wykładniczym czasem oczekiwania (exponential backoff):
4s -> 8s -> 16s -> 32s -> 64s -> 128s -> 256s -> max 300s (5 minut).
"""

import sys
import time
import subprocess
from datetime import datetime


INITIAL_DELAY = 4      # Początkowy czas oczekiwania w sekundach
MAX_DELAY = 300        # Maksymalny czas oczekiwania (5 minut = 300 sekund)
BACKOFF_FACTOR = 2     # Mnożnik wykładniczy


def format_duration(seconds):
    """Czytelne formatowanie czasu (sekundy lub minuty i sekundy)."""
    if seconds >= 60:
        minutes = seconds // 60
        rem_sec = seconds % 60
        if rem_sec > 0:
            return f"{minutes} min {rem_sec} s"
        return f"{minutes} min"
    return f"{seconds} s"


def main():
    # Pobranie trybu z argumentu CLI (domyślnie 'daily')
    mode = "daily"
    if len(sys.argv) > 1:
        mode = sys.argv[1].strip().lower()

    valid_modes = ["daily", "week", "suggest", "sugestia", "sugeruj", "tydzien", "plan-tygodnia", "weekly"]
    if mode not in valid_modes:
        print(f"⚠️  Nieznany tryb: '{mode}'. Dostępne tryby: daily, week, suggest.")
        print("Użycie: python3 run_with_retry.py [daily|week|suggest]")
        sys.exit(1)

    print("=" * 65)
    print(f"🚀 GARMIN COACH RUNNER (AUTO-RETRY) | TRYB: {mode.upper()}")
    print(f"Strategia ponawiania: od {INITIAL_DELAY}s do max {format_duration(MAX_DELAY)} (x{BACKOFF_FACTOR})")
    print("=" * 65)

    delay = INITIAL_DELAY
    attempt = 1

    while True:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] ▶️  Rozpoczynam próbę #{attempt} (tryb: {mode})...\n")

        try:
            # Uruchamiamy garmin_coach.py w tym samym środowisku Pythona (venv / systemowy)
            cmd = [sys.executable, "garmin_coach.py", mode]
            process = subprocess.run(cmd)

            if process.returncode == 0:
                print("\n" + "=" * 65)
                print(f"🎉 SUKCES! Gemini zwróciło odpowiedź w próbie #{attempt}.")
                print("=" * 65)
                sys.exit(0)
            else:
                print("\n" + "-" * 65)
                print(f"❌ Próba #{attempt} zakończyła się błędem (kod wyjścia: {process.returncode}).")

        except KeyboardInterrupt:
            print("\n\n🛑 Przerwano wykonywanie przez użytkownika (Ctrl+C). Do widzenia!")
            sys.exit(130)
        except Exception as e:
            print(f"\n❌ Nieoczekiwany błąd podczas uruchamiania procesu: {e}")

        # Odliczanie do kolejnej próby
        print(f"⏳ Czekam {format_duration(delay)} przed kolejną próbą...")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            print("\n\n🛑 Przerwano oczekiwanie przez użytkownika (Ctrl+C).")
            sys.exit(130)

        # Zwiększenie opóźnienia wykładniczo do limitu MAX_DELAY
        delay = min(delay * BACKOFF_FACTOR, MAX_DELAY)
        attempt += 1


if __name__ == "__main__":
    main()
