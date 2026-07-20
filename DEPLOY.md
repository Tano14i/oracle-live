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
- **Telefono Android con Termux**: procedura sotto. Costo zero, ma leggi le avvertenze.

### Setup su Termux (Android)

Dentro l'app Termux, incolla in ordine:

```bash
pkg update -y && pkg install -y git git-lfs
git clone https://github.com/Tano14i/oracle-live.git
cd oracle-live
git checkout claude/oracle-live-refactor-kicsmd   # o main dopo il merge
bash deploy/setup_termux.sh
nano .env                          # inserisci TOKEN_LIVE, CHAT_ID, CHANNEL_ID, API_KEY...
bash deploy/start_bot_termux.sh    # avvia il bot (resta aperto, con auto-riavvio)
```

Poi, nelle impostazioni Android (una volta sola):

1. **Batteria → Termux → Nessuna restrizione** (altrimenti Android uccide il bot).
2. Non chiudere Termux dalle app recenti: lascialo in background (la notifica
   con il lucchetto indica il wake-lock attivo).
3. Facoltativo ma consigliato: installa **Termux:Boot** (da F-Droid) per far
   ripartire il bot al riavvio del telefono — crea `~/.termux/boot/oracle.sh` con:

   ```bash
   #!/data/data/com.termux/files/usr/bin/bash
   bash ~/oracle-live/deploy/start_bot_termux.sh
   ```

Per portare i dati storici dal PC (membri VIP, dataset live) senza ripartire da zero:
mandati i file via Telegram (Messaggi salvati) o Google Drive, salvali in Download,
poi in Termux:

```bash
termux-setup-storage    # autorizza l'accesso ai file (una volta)
cp /sdcard/Download/vip_members.db /sdcard/Download/live_training_data.csv /sdcard/Download/web_stats.json ~/oracle-live/ 2>/dev/null
```

**Avvertenze oneste**: il bot vive solo finché il telefono è acceso e connesso;
se usi questo stesso telefono tutti i giorni, un riavvio o la modalità aereo lo
fermano (e con lui i segnali e il monitoraggio VIP). Per iniziare gratis va
benissimo; quando il canale VIP inizia a incassare, sposta il bot su un VPS
(opzione A) o su Oracle Cloud Always Free — la migrazione è: copia dei file
dati + stessa procedura di setup.

## Nota sui dati

Ovunque tu lo ospiti, questi file sono lo "stato" del bot e vanno preservati/backuppati:
`vip_members.db`, `live_training_data.csv`, `web_stats.json`, `oracle_brain*.pkl`,
`Matches.csv`, `missing_teams_queue.json`. Sul VPS un backup è una riga di cron con
`tar` + `scp`/rclone; su HF Spaces vivono in `/data` (solo con storage persistente).
