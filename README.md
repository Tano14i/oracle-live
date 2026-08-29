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

- `oracle_live.py`: runtime live principale con Telegram bot, polling API, filtri campionati, market HT, messaggi editabili, funnel free e VIP billing.
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
- `FILTRO GLOBAL U23`: campionati globali, includendo anche le competizioni U23 e inferiori. **Default** per massimizzare il volume segnali (obiettivo 10+/giorno); la qualita' per lega e' protetta dai circuit breaker per-lega.
- `FILTRO ATTUALE`: mostra il preset attivo.

Nota: il filtro attivo viene persistito in `web_stats.json`; su installazioni gia' avviate va cambiato dal bot (`MENU FILTRI`), il default vale solo al primo avvio.

## Market bot

- `MARKET O0.5 HT`: segnali solo `OVER 0.5 HT` (finestra 0-0 entro il 20'; estendibile al 21-28' sotto pressione con `HT_PRESSURE_WINDOW_ENABLED=1`, da attivare solo dopo verifica con `analyze_shadow_signals.py`).
- `MARKET O1.5 HT`: segnali solo `OVER 1.5 HT` (di fatto disabilitato: WR storico 28.3%).
- `MARKET BOTH HT`: monitora entrambi i market HT in parallelo sulla stessa partita.
- `MARKET NEXT GOAL` / `MARKET HT + NEXT`: aggiunge `NEXT GOAL LIVE`, ristretto alle finestre storicamente profittevoli (minuto 1-11 libero, 12-19 solo score favorevoli o parita', 20-44 solo score con WR ben sopra il breakeven, 45+ bloccato). **Default: HT + NEXT.**
- `MARKET ATTUALE`: mostra la modalita market attiva.

Le quote per market usate per P/L e ROI sono configurabili: `QUOTA_O05_HT`, `QUOTA_O15_HT`, `QUOTA_NEXT_GOAL` (fallback `QUOTA`).

### Analisi shadow

`analyze_shadow_signals.py` legge `live_training_data.csv` (segnali reali + shadow LEARNING) e stampa WR per market/tier/fascia minuto con verdetto contro il breakeven della quota di ogni market. Serve a decidere con i dati se aprire la finestra HT estesa (`HT_PRESSURE_WINDOW_ENABLED`) e a verificare le finestre NEXT GOAL.

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


