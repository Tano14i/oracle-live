#!/usr/bin/env bash
# Setup di Oracle Live su un VPS Ubuntu/Debian pulito.
# Uso (da root sul VPS):
#   apt-get update && apt-get install -y git
#   git clone https://github.com/Tano14i/oracle-live.git /opt/oracle-live
#   cd /opt/oracle-live && git checkout claude/oracle-live-refactor-kicsmd
#   bash deploy/setup_vps.sh
# Poi modifica /opt/oracle-live/.env con i tuoi token e:
#   systemctl restart oracle-live
set -euo pipefail

APP_DIR="/opt/oracle-live"

if [ ! -d "$APP_DIR" ]; then
    echo "Repo non trovato in $APP_DIR. Clonalo prima (vedi commenti in testa allo script)."
    exit 1
fi

echo "== Pacchetti di sistema =="
apt-get update
apt-get install -y python3 python3-venv python3-pip

echo "== Utente di servizio =="
id -u oracle >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin oracle

echo "== Virtualenv e dipendenze =="
cd "$APP_DIR"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "== File .env =="
if [ ! -f .env ]; then
    cp .env.example .env
    echo ">>> Creato $APP_DIR/.env da .env.example: DEVI inserire TOKEN_LIVE, CHAT_ID, CHANNEL_ID, API_KEY (e VIP_CHANNEL_ID se usi il VIP)."
fi

chown -R oracle:oracle "$APP_DIR"

echo "== Servizio systemd =="
cp deploy/oracle-live.service /etc/systemd/system/oracle-live.service
systemctl daemon-reload
systemctl enable oracle-live

if grep -q "^TOKEN_LIVE=..*" .env; then
    systemctl restart oracle-live
    echo "== Bot avviato. Stato: =="
    systemctl --no-pager status oracle-live || true
else
    echo ">>> .env non ancora compilato: compila i token e poi esegui: systemctl restart oracle-live"
fi

echo
echo "Comandi utili:"
echo "  journalctl -u oracle-live -f     # log live"
echo "  systemctl restart oracle-live    # riavvio"
echo "  cd $APP_DIR && git pull && systemctl restart oracle-live   # aggiornamento"
