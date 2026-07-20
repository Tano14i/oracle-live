#!/data/data/com.termux/files/usr/bin/bash
# Setup di Oracle Live dentro Termux (Android).
# Uso, dentro Termux:
#   pkg update -y && pkg install -y git git-lfs
#   git clone https://github.com/Tano14i/oracle-live.git
#   cd oracle-live && git checkout claude/oracle-live-refactor-kicsmd
#   bash deploy/setup_termux.sh
set -e

echo "== Pacchetti Termux =="
pkg update -y
pkg install -y python git git-lfs termux-api

echo "== Librerie scientifiche (pacchetti precompilati, pip non basta su Termux) =="
pkg install -y tur-repo || true
pkg install -y python-numpy || pip install numpy
pkg install -y python-pandas || pip install pandas
pkg install -y python-scikit-learn || pip install scikit-learn

echo "== File grandi (Matches.csv, modelli) via Git LFS =="
git lfs install
git lfs pull || echo ">>> git lfs pull fallito: se resta il puntatore, copia Matches.csv a mano (vedi DEPLOY.md)"

echo "== Dipendenze del bot =="
pip install --upgrade pip
pip install -r deploy/requirements-bot.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo ">>> Creato .env: apri con 'nano .env' e inserisci TOKEN_LIVE, CHAT_ID, CHANNEL_ID, API_KEY (e VIP_CHANNEL_ID se usi il VIP)."
fi

echo
echo "Setup completato."
echo "1) nano .env                        # inserisci i token"
echo "2) bash deploy/start_bot_termux.sh  # avvia il bot"
