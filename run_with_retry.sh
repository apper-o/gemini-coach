#!/bin/bash
# Skrypt bash ponawiający garmin_coach.py do skutku z wykładniczym czasem oczekiwania.
# Użycie: ./run_with_retry.sh [daily | week | suggest]

MODE="${1:-daily}"
INITIAL_DELAY=4
MAX_DELAY=300
DELAY=$INITIAL_DELAY
ATTEMPT=1

# Wykrycie Pythona (z venv jeśli istnieje, lub systemowego)
if [ -f "venv/bin/python3" ]; then
    PYTHON_BIN="venv/bin/python3"
elif [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python3"
fi

echo "================================================================="
echo "🚀 GARMIN COACH RUNNER (AUTO-RETRY BASH) | TRYB: $MODE"
echo "Strategia ponawiania: od ${INITIAL_DELAY}s do max 5 min (x2)"
echo "Interpreter Pythona: $PYTHON_BIN"
echo "================================================================="

while true; do
    echo ""
    echo "[$(date '+%H:%M:%S')] ▶️  Rozpoczynam próbę #$ATTEMPT (tryb: $MODE)..."
    echo ""

    if $PYTHON_BIN garmin_coach.py "$MODE"; then
        echo ""
        echo "================================================================="
        echo "🎉 SUKCES! Program zakończył się powodzeniem w próbie #$ATTEMPT."
        echo "================================================================="
        exit 0
    else
        echo ""
        echo "-----------------------------------------------------------------"
        echo "❌ Próba #$ATTEMPT zakończyła się błędem."
        echo "⏳ Czekam ${DELAY}s przed kolejną próbą..."
        echo "-----------------------------------------------------------------"
        sleep "$DELAY"

        # Zwiększenie czasu oczekiwania x2, maksymalnie do 300 sekund
        DELAY=$(( DELAY * 2 ))
        if [ "$DELAY" -gt "$MAX_DELAY" ]; then
            DELAY=$MAX_DELAY
        fi
        ATTEMPT=$(( ATTEMPT + 1 ))
    fi
done
