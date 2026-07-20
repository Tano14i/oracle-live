#!/data/data/com.termux/files/usr/bin/bash
# Avvia il bot su Termux con wake-lock e riavvio automatico su crash.
cd "$(dirname "$0")/.."

# Impedisce ad Android di sospendere Termux (compare la notifica del lucchetto).
termux-wake-lock 2>/dev/null || true

echo "Oracle Live in esecuzione su Termux. Per fermarlo: CTRL+C due volte."
while true; do
    python oracle_live.py
    code=$?
    echo "Bot terminato (exit $code). Riavvio tra 10 secondi... CTRL+C per uscire."
    sleep 10
done
