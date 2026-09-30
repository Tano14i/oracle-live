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

Le quote per market usate per P/L e ROI sono configurabili: `QUOTA_O05_HT`, `QUOTA_O15_HT`, `QUOTA_NEXT_GOAL` (fallback `QUOTA`). **Sono solo un fallback**: quando il book espone la quota live, il P/L viene calcolato su quella (vedi sotto).

### Quote reali (`OpenOdd`)

Ogni segnale, reale o shadow, registra in `live_training_data.csv` la colonna `OpenOdd`: la quota effettivamente disponibile al momento dell'apertura. Per NEXT GOAL viene letta la linea `Over (gol correnti + 0.5)`, che e' l'esito su cui il segnale viene poi chiuso; se la linea non e' esposta il bot logga `LIVE_ODDS_NO_LINE` con gli esiti disponibili e lascia il campo vuoto.

`chiudi_scommessa` usa `OpenOdd` per il P/L quando e' valorizzata, e ricade sulla quota di config solo se manca. Senza questo dato ogni ROI del bot resta un'ipotesi: una strategia al 67% di win rate va in pari solo da quota 1.49 in su, e va verificato che il book la paghi davvero.

### Market `NEXT GOAL 2H MOMENTUM` (logica "47'")

Entra a inizio ripresa (46'-55') e si chiude come NEXT GOAL (WIN al primo gol dopo l'apertura). Regole, tutte in `momentum.py`:

- almeno **4 tiri in porta totali** all'apertura e meno di 4 gol in campo;
- **mai 0-0 in canale**: partendo da 0-0 all'intervallo un gol nel secondo tempo arriva nell'86% dei casi contro il 90.6% con qualsiasi altro punteggio, e a quota ~1.10 (breakeven 90.9%) e' in perdita. Lo 0-0 viene aperto solo come shadow `LEARNING` per raccogliere dati;
- tier iniziale dal **momentum** (delta tiri/angoli negli ultimi `MOMENTUM_LOOKBACK_MINUTES`): in salita -> `CAUTION`, piatto -> `GAMBLING`. Il modello ML non decide questo market finche' non ha righe proprie;
- **quota minima 1.40** (`QUOTA_2H_MOMENTUM`): sotto, il segnale resta shadow;
- **follow-up** dopo `MOMENTUM_FOLLOWUP_MINUTES` minuti: il bot confronta tiri e angoli con lo snapshot di apertura e risponde al messaggio del segnale con "parziale entro 75'/80' se quota >= minimo" oppure "solo over totale". Il verdetto finisce nel dataset (`MomentumPost`, `MomentumPostScore`) cosi' si potra' misurare se il parziale conviene davvero.

Si attiva con `MOMENTUM_2H_ENABLED=1` (default) in ogni modalita' che include NEXT GOAL, oppure da solo con `MARKET 2H MOMENTUM`.

### Regola quota minima applicata (`ENFORCE_MIN_QUOTA`)

Il minimo per tier (1.90 APPROVED, 1.70 CAUTION, 1.75 GAMBLING) era scritto nel messaggio ma mai applicato: un NEXT GOAL con quota live 1.30 veniva pubblicato lo stesso. Ora, se la quota live e' nota e sotto il minimo, il segnale va in shadow e la riga riporta `quota gate` nel motivo. Con quota ignota si pubblica con l'avviso.

### Skip adattivo agganciato al breakeven

`should_skip_by_live_performance` spegneva un market sotto il 40% e una lega sotto il 35%, cioe' molto sotto il breakeven (57.1% a quota 1.75): tra il 40% e il 57% il bot continuava a mandare segnali in perdita. Le soglie ora derivano dalla quota del market (`skip_thresholds_for_quota`): oggi -> breakeven − 15 punti su almeno 8 esiti; rolling -> breakeven − 3 punti su almeno 30 esiti degli ultimi 50. Lega e fascia minuto aggregano tutti i market, quindi usano la soglia della quota generica (`QUOTA`). Tutte le finestre rolling guardano solo gli ultimi 14 giorni: gli shadow non alimentano il rolling, e senza scadenza un market spento non si sarebbe piu' riacceso.

### Feature momentum nel modello

Le feature erano tutte fotografie all'apertura (`...AtOpen`). Il bot ora tiene uno storico stats per fixture (`FixtureStatsHistory`) e registra `ShotsOnGoalDelta10AtOpen`, `TotalShotsDelta10AtOpen`, `CornersDelta10AtOpen`, `MomentumScoreAtOpen`, `MomentumAtOpen`. Per le righe vecchie che non le hanno il trainer le riempie a 0.

### Trainer v2 in produzione, probabilita' calibrate

`oracle_live.py` importava `trainer.py` (split casuale, LEARNING nel training, nessuna calibrazione) e dopo ogni retrain ricaricava quel modello in memoria tenendo pero' la soglia v2: due cose incompatibili. Ora il retrain (manuale `/retrain` e automatico) usa `trainer_v2.py`, ricarica `oracle_brain_v2.pkl` e aggiorna la soglia. Il modello e' avvolto in `CalibratedClassifierCV` (sigmoid sotto 300 righe, isotonic sopra) e il report di retrain mostra la **reliability table** (probabilita' predetta -> WR reale per bin): e' l'unico modo per sapere se un "0.80" vale davvero l'80%. Con il modello calibrato le soglie dei tier non sono piu' i vecchi 0.88/0.80/0.72 (tarati su un RF grezzo, che con probabilita' vere non scatterebbero mai): `get_tier_prob_thresholds` le ricava dal breakeven della quota del market (+12 / +6 / +2 punti). Se la classe minoritaria e' troppo piccola per le fold, il trainer torna al RF nudo invece di far fallire il retrain. Corretto anche il filtro bucket di OVER 0.5 HT, che escludeva per errore le righe 1-14'.

Test: `python -m pytest -q tests`.

### Analisi shadow

`analyze_shadow_signals.py` legge `live_training_data.csv` (segnali reali + shadow LEARNING) e stampa WR per market/tier/fascia minuto con verdetto contro il breakeven della quota di ogni market. Serve a decidere con i dati se aprire la finestra HT estesa (`HT_PRESSURE_WINDOW_ENABLED`) e a verificare le finestre NEXT GOAL.

La sezione `ROI con QUOTE REALI` usa la colonna `OpenOdd` invece della quota di config: e' l'unico blocco dell'output che misura la redditivita' vera. Finche' resta vuoto, servono altri giorni di raccolta.

### Come vengono selezionati i segnali

L'ordine dei filtri e': finestra strutturale (market, minuto, score) -> profilo storico delle squadre (pace) -> modello come conferma. La probabilita' del modello **non** e' un cancello primario: presa da sola e' anticorrelata con l'esito, perche' assegna valori alti alle situazioni di pressione a fine partita, che sono quelle con meno tempo residuo. Dentro una finestra di minuto sana torna invece a discriminare, ed e' li' che viene applicata.

I candidati sotto la soglia del modello non vengono piu' scartati: restano registrati come shadow `LEARNING` (evento `V2_THRESHOLD_SHADOW`) senza essere pubblicati, cosi' la soglia stessa resta misurabile.

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
- export_titan_snapshots.py: esporta 
aw_snapshots dal DB Titan verso 	itan_raw_snapshots_export.csv in formato CSV pulito per analisi separata.
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


