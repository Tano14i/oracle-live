---
title: Oracle Live
emoji: ⚽
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Oracle Live

Progetto Python per analisi storica, training di un modello semplice, invio di segnali live via Telegram e monetizzazione VIP via Stars.

## File principali

- `oracle_live.py`: shim di avvio retro-compatibile (`python oracle_live.py` continua a funzionare); il codice vive nel package `oracle_live/`.
- `main.py`: entrypoint equivalente allo shim (`python main.py`).
- `oracle_live/`: package del runtime live (Telegram bot, polling API, filtri campionati, market HT, messaggi editabili, funnel free e VIP billing), diviso in moduli:
  - `constants.py`: tier, market, preset, filtri, soglie, liste PREMIUM_*, `LEGACY_TIER_KEYS`.
  - `state.py`: dict `stats`, lock, singleton condivisi (`bot`, `logger`, `membership_store`), persistenza `salva_dati_web`, helper CSV live-training.
  - `api_client.py`: helper HTTP API-Football (status/statistiche fixture, quote live) e cache.
  - `markets.py`: `MARKET_PRESETS`, market router, finestre e vincitori market.
  - `messaging.py`: formattazione messaggi, `escape_html`, `send_html_message_safe`, teaser free.
  - `filters.py`: filtri campionati/paesi, normalizzazioni, alias e matching squadre, coverage guard, coda missing-team.
  - `guards.py`: guard su performance live e statistiche live.
  - `models.py`: caricamento modelli (v2 + threshold, titan pressure), retrain.
  - `reporting.py`: analytics, recap giornalieri, performance report, /xcopy /xpromo.
  - `prematch.py`: report prematch, watch state, delta, loop di monitoraggio.
  - `vip.py`: billing Telegram Stars, sync membri, inviti/revoche, reminder.
  - `signals.py`: apertura/chiusura segnali, tracker, esiti, radar loop.
  - `handlers.py`: tutti gli handler telebot (comandi + tastiere).
  - `runtime.py`: process lock, boot (`main()`), dashboard/ngrok, shutdown, polling.
  - La mappa completa funzione → modulo è in `REFACTOR_MAP.md`.
- `analyze_performance.py`: report WR/ROI/calibrazione sul dataset live (`python analyze_performance.py`).

## Modello ed EV gate

- Il modello ora riceve il **mercato come feature** (one-hot O0.5 HT / O1.5 HT / Next Goal) piu' tiri in area, parate e xG-rate al momento dell'apertura; le probabilita' sono **calibrate** (sigmoid, isotonic sopra 400 righe settled), quindi `Prob` e' utilizzabile per il valore atteso.
- **EV gate**: quando la quota live e' disponibile, un segnale pubblico apre solo se `prob * quota - 1 >= EV_MIN_EDGE` (default 3%). Next Goal usa gia' le quote live (bet=5); per attivare il gate sui mercati HT imposta `LIVE_ODDS_BET_ID_OVER05_HT` / `LIVE_ODDS_BET_ID_OVER15_HT` in `.env`. Quota ed EV all'apertura vengono salvati nel dataset (`OddsAtOpen`, `EVAtOpen`).
- Le guardie "cold" su mercati/leghe/fasce orarie ora scattano solo con campioni statisticamente sensati (15/12/12 esiti giornalieri) invece di 4-5.
- Dopo il primo retrain con il nuovo trainer, usa `python analyze_performance.py` per verificare calibrazione e ROI per fascia di quota.
- `vip_membership.py`: storage SQLite per iscritti VIP e fatture.
- `dashboard.py`: dashboard Streamlit che legge `web_stats.json`.
- `backtest.py`: genera `cleaned_training_data.csv` a partire da `Matches.csv`.
- `trainer.py`: addestra `oracle_brain.pkl`.
- `migrate_historical_signals.py`: recupera i segnali storici salvabili da `web_stats.json` verso `live_training_data.csv`.
- `updater.py`: aggiorna `Matches.csv` da fonti esterne.

## Modello canali

- `CHAT_ID`: feed admin completo per controllo interno.
- `CHANNEL_ID`: canale free/pubblico. Riceve tutti i segnali pubblici (`APPROVED`, `CAUTION`, `GAMBLING`) in formato teaser.
- `VIP_CHANNEL_ID`: canale premium. Riceve i segnali completi e gli aggiornamenti finali editati.

## Funnel free -> VIP

- il free vede solo teaser, non confidenza completa e non dettagli premium.
- il free riceve tutti i segnali pubblici del bot (`APPROVED`, `CAUTION`, `GAMBLING`).
- il teaser free puo essere pubblicato con ritardo `FREE_DELAY_SECONDS`.
- admin e VIP ricevono subito il segnale completo.

## Avvio rapido

1. Crea `.env` partendo da `.env.example`.
2. Imposta `CHANNEL_ID` come canale free e `VIP_CHANNEL_ID` come canale premium.
3. Imposta `VIP_PRICE_XTR`, `VIP_DURATION_DAYS` e, se vuoi, `FREE_DELAY_SECONDS`.
4. Facoltativo: imposta `LOG_FILE_PATH` per salvare il log runtime su file.
5. Installa le dipendenze con `pip install -r requirements.txt`.
6. Esegui `python backtest.py`.
7. Esegui `python trainer.py`.
8. Avvia il bot con `python oracle_live.py`.
9. Avvia la dashboard con `streamlit run dashboard.py`.

## Filtri bot

- `FILTRO TOP 10`: solo Spagna, Italia, Olanda, Francia, Germania, Inghilterra, Belgio, Polonia, Portogallo e Turchia.
- `FILTRO SERIE A/B`: solo prime e seconde divisioni dei 10 paesi sopra.
- `FILTRO GLOBAL U23`: campionati globali, includendo anche le competizioni U23 e inferiori.
- `FILTRO ATTUALE`: mostra il preset attivo.

## Market bot

- `MARKET O0.5 HT`: segnali solo `OVER 0.5 HT`.
- `MARKET O1.5 HT`: segnali solo `OVER 1.5 HT`.
- `MARKET BOTH HT`: monitora entrambi i market in parallelo sulla stessa partita.
- `MARKET ATTUALE`: mostra la modalita market attiva.

## VIP monetization

- `/vip`: invia invoice Telegram Stars in chat privata.
- `/vip_status`: mostra stato e scadenza dell'abbonamento.
- `/paysupport`: mostra il contatto supporto pagamenti.
- `/admin`: apre il pannello admin con KPI, membri, pagamenti e rinnovi.
- `/xcopy`: genera il testo performance pronto da copiare su X.
- `/xpromo`: genera un testo promo casuale, descrittivo e pronto per X.
- `VIP ACCESS`, `VIP STATUS` e `ADMIN PANEL`: pulsanti rapidi nel bot.
- `COMANDI` e `/help`: guida rapida delle funzioni disponibili nel bot.
- `LEGEND` e `/legend`: legenda dei segnali e spiegazione dei campi mostrati nei messaggi.
- la tastiera principale e compatta: `MENU FILTRI`, `MENU MARKET` e `MENU VIP` aprono i sottomenu dedicati.
- dopo il pagamento il bot crea un invite link monouso per il canale VIP.
- il bot revoca gli utenti VIP scaduti dal canale configurato.
- ogni `REPORT_EVERY_N_SETTLED` segnali chiusi, dopo almeno `REPORT_MIN_SETTLED`, invia un performance report con Win Rate, ROI, Units e scenario bankroll.
- il canale free riceve teaser, il VIP riceve i dettagli monetizzabili.



## Titan Dataset Tools

- inspect_titan_db.py: ispeziona il database Titan e mostra schema, righe utili e sample dei dati live raccolti.
- export_titan_snapshots.py: esporta aw_snapshots dal DB Titan verso 	itan_raw_snapshots_export.csv in formato CSV pulito per analisi separata.
- 	rain_titan_pressure_model.py: addestra un modello separato 	itan_pressure_model.pkl usando gli snapshot Titan come pressure-model live di supporto.
- i dati Titan sono utili come dataset live secondario per ricerca e pressure modeling, ma non vanno mischiati direttamente con il training HT principale senza mappatura del target.

Comandi utili:

- python inspect_titan_db.py
- python export_titan_snapshots.py
- python train_titan_pressure_model.py

## API-FOOTBALL Coverage Update

- `api_football_coverage_updater.py`: scarica fixture storiche finite da API-FOOTBALL, mantiene anche i goal HT quando presenti, fa backup e merge dentro `Matches.csv`.

Comandi esempio:

- `python api_football_coverage_updater.py --country Uganda --country Tanzania --season 2025 --season 2026`
- `python api_football_coverage_updater.py --league-id 307 --league-id 308 --season 2025`
## Logging

- il bot scrive eventi runtime in LOG_FILE_PATH (default: oracle_live.log).
- eventi principali: avvio bot, apertura segnale, edit messaggi, esiti WIN/LOSS, reminder VIP, revoche VIP e restart polling.
## Missing-Team Backfill

- `api_football_missing_team_backfill.py`: legge la coda locale dei `TEAM_NOT_FOUND`, prova a risolvere i team via API-FOOTBALL e importa le fixture storiche finite in `Matches.csv`.
- il bot aggiorna automaticamente la coda in `MISSING_TEAMS_QUEUE_PATH` quando incontra squadre sconosciute.

Comando esempio:

- `python api_football_missing_team_backfill.py --limit 25 --season 2025 --season 2026`


