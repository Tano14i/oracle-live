# Deploy di Oracle Live in cloud (niente PC acceso)

Dopo il deploy, TUTTO si comanda dal telefono via Telegram: AVVIA AI RADAR, STOP,
ANALISI, /retrain, ecc. Il PC serve solo per la configurazione iniziale (una volta)
o per gli aggiornamenti del codice.

## Opzione A — VPS (consigliata)

Un piccolo VPS (Hetzner CX22 ~4€/mese, oppure Contabo/OVH/DigitalOcean) è la
soluzione più solida per questo bot: processo sempre acceso, dati su disco vero
(vip_members.db, live_training_data.csv, modelli), nessuna pausa per inattività.

### Setup una tantum (~10 minuti, si può fare anche da telefono con un'app SSH tipo Termius)

1. Crea il VPS (Ubuntu 22.04/24.04) e collegati in SSH come root.
2. Esegui:

   ```bash
   apt-get update && apt-get install -y git
   git clone https://github.com/Tano14i/oracle-live.git /opt/oracle-live
   cd /opt/oracle-live
   git checkout claude/oracle-live-refactor-kicsmd   # o main dopo il merge
   bash deploy/setup_vps.sh
   ```

3. Inserisci i token nel file `.env`:

   ```bash
   nano /opt/oracle-live/.env    # TOKEN_LIVE, CHAT_ID, CHANNEL_ID, API_KEY, VIP_CHANNEL_ID...
   systemctl restart oracle-live
   ```

4. Copia i dati storici dal PC (una volta sola, per non ripartire da zero):

   ```bash
   # dal PC (PowerShell), nella cartella del bot:
   scp Matches.csv live_training_data.csv web_stats.json vip_members.db oracle_brain*.pkl root@IP_DEL_VPS:/opt/oracle-live/
   ```

   poi sul VPS: `chown oracle:oracle /opt/oracle-live/* && systemctl restart oracle-live`

5. Verifica dal telefono: apri il bot su Telegram → `/start` → AVVIA AI RADAR.

### Gestione quotidiana

- Tutto via Telegram (radar, analisi, retrain, dashboard KPI via ADMIN PANEL).
- Log: `journalctl -u oracle-live -f`
- Aggiornamento codice: `cd /opt/oracle-live && git pull && systemctl restart oracle-live`
- Il servizio riparte da solo su crash e al reboot del VPS.

## Opzione B — Hugging Face Spaces (già predisposta nel repo)

`launcher.py` + `Dockerfile` sono già scritti per HF Spaces: avviano il bot come
sottoprocesso (con watchdog di riavvio) e la dashboard Streamlit sulla porta 7860.
Lo Space di riferimento è `Fabio14i/oracle-live` (vedi `HF_SPACE_REPO` in launcher.py).

Passi:

1. Crea (o riusa) uno Space **Docker** su huggingface.co e carica il contenuto del repo.
2. In *Settings → Variables and secrets* aggiungi come **Secrets**: `TOKEN_LIVE`,
   `CHAT_ID`, `CHANNEL_ID`, `API_KEY`, `VIP_CHANNEL_ID` (config.py legge le env,
   il file .env non serve).
3. **Persistent storage (fondamentale)**: in *Settings → Storage* attiva lo storage
   persistente (a pagamento, ~5$/mese). Senza, `/data` viene azzerato a ogni
   riavvio: perderesti dataset live, membri VIP e modelli.
4. **Keep-alive**: gli Space free/CPU vengono messi in pausa dopo ~48h senza
   traffico HTTP. Registra l'URL della dashboard dello Space su un ping gratuito
   (es. UptimeRobot, check ogni 5 minuti) per tenerlo sveglio.

Limiti rispetto al VPS: costo simile una volta aggiunto lo storage persistente,
ma con più parti mobili (pausa/riavvii dello Space, LFS per i file grossi).
Per un bot con pagamenti VIP e dataset che cresce, il VPS resta più affidabile.

## Opzione C — hardware di casa senza PC

- **Raspberry Pi** (anche un Pi 3/4 usato): stessa procedura dell'opzione A.
- **Vecchio telefono Android con Termux**: funziona, ma fragile (kill in background,
  reboot); sconsigliato per il VIP billing.

## Nota sui dati

Ovunque tu lo ospiti, questi file sono lo "stato" del bot e vanno preservati/backuppati:
`vip_members.db`, `live_training_data.csv`, `web_stats.json`, `oracle_brain*.pkl`,
`Matches.csv`, `missing_teams_queue.json`. Sul VPS un backup è una riga di cron con
`tar` + `scp`/rclone; su HF Spaces vivono in `/data` (solo con storage persistente).
