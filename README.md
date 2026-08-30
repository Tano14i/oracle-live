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

### Strato di analisi AI

`oracle_ai.py` aggiunge un'analisi scritta ai segnali, usando Claude con ricerca web.

**Non sceglie le partite.** La selezione resta ai numeri misurati: finestra di 50 partite, ritmo di primo tempo sulle sole partite a dato noto, soglie verificate su 357.573 partite con gruppo di controllo. L'AI interviene dopo, e fa due cose che i numeri non sanno fare: spiega il segnale in prosa per il canale VIP, e cerca il contesto qualitativo che il dataset non contiene — infortuni, formazioni, squalifiche, motivazione di classifica, meteo.

Puo' restituire tre verdetti: `CONFERMA`, `ATTENZIONE` (fatti concreti che riducono i gol attesi) e `SALTA` (solo per fatti gravi e verificati). Il veto e' consultivo e sempre motivato.

Due garanzie nel codice: il prompt vieta di inventare statistiche — l'AI ragiona sui numeri che riceve e per il contesto cita le fonti trovate; e ogni fallimento (rete, quota, rifiuto, verdetto illeggibile) restituisce `CONFERMA`, cosi' il segnale non dipende mai dalla disponibilita' dell'AI.

Spento di default. Si attiva con `ORACLE_AI_ENABLED=1` e `ANTHROPIC_API_KEY` nel `.env`. Il prompt di sistema e' identico a ogni chiamata e viene messo in cache, quindi il costo per segnale resta basso.

**Consegna asincrona.** La chiamata con ricerca web impiega decine di secondi, mentre il segnale deve uscire entro il minuto 5. Il bot quindi pubblica subito e poi modifica il messaggio aggiungendo l'analisi, su tutti i canali: admin, VIP e free. Il teaser free parte dopo `FREE_DELAY_SECONDS`, quindi di norma include gia' l'analisi senza bisogno di una modifica.

Conseguenza da conoscere: **nel live il verdetto e' informativo**, perche' quando arriva il segnale e' gia' partito. Il veto che puo' davvero impedire una giocata e' quello sul radar prematch, dove le ore prima del calcio d'inizio lasciano il tempo di decidere.

### Radar pre-match OVER 0.5 HT

`prematch_radar.py` applica alle partite in programma lo stesso filtro sul ritmo di primo tempo che il bot usa in diretta. Il filtro e' interamente storico, quindi si puo' calcolare prima del fischio d'inizio.

**Non serve a scommettere prematch.** Le quote prematch di questo mercato sono piu' corte di quelle live: rilevate fra 1.13 e 1.45, mediana 1.27, contro 1.40-1.53 al minuto 1-5. A 1.27 il pareggio richiede il 78.7%, che nemmeno il tier CAUTION (75.0% misurato nel backtest) raggiunge. Aspettare i primi minuti vale circa 18 punti di quota.

Serve invece a **presidiare i calci d'inizio giusti**: il bot live aggancia solo il 59% delle partite entro il minuto 5, e sapere in anticipo quali contano elimina quella perdita.

Comandi: `--date`, `--min-tier`, `--with-odds` (una chiamata per candidata), `--known-leagues` (solo campionati gia' incontrati dal bot). Salva la watchlist in `prematch_radar_watchlist.json`; nel bot Telegram e' il comando `/prematch_today`.

Un limite da conoscere: il ritmo alto premia divisioni minori e giovanili, dove il mercato spesso non esiste. Su 72 candidate del tier APPROVED solo 9 avevano una quota prematch esposta.

Ha sostituito lo scanner di anomalie sulle quote che stava in `oracle_prematch/`. Quello cercava cali sospetti prima del kickoff ma non registrava alcun esito, quindi il suo punteggio non e' mai stato verificato; si era fermato il 30 marzo 2026 e aveva accumulato 30 GB di risposte API grezze che nessuno leggeva. `PREMATCH_AUTO_COLLECT_ENABLED` e' ora spento di default.

### Dati di primo tempo e soglie OVER 0.5 HT

`football_data_ht_import.py` scarica i CSV gratuiti di football-data.co.uk (22 divisioni europee, colonne `HTHG`/`HTAG`) e li fonde in `Matches.csv` agganciando le partite su data e nomi normalizzati. Comandi: `--download`, `--report` (quante righe correggerebbe, senza scrivere), `--write`.

Serviva perche' in `Matches.csv` il primo tempo era assente nel 91% delle partite con 2+ gol, e `get_team_metrics` lo sostituiva con un valore ricavato dal ritmo totale (`avg_total_goals * 0.38`, limitato a [0.8, 1.35]). Siccome il minimo inventato coincideva con la soglia richiesta, il filtro sul ritmo HT non filtrava nulla.

Due conseguenze in `oracle_live.py`:

- `TEAM_HISTORY_WINDOW` e' 50, non 12. Misurato su 53.698 partite con HT reale: la correlazione con i gol del primo tempo passa da 0.071 (finestra 12) a 0.107 (finestra 50). I gol di primo tempo sono rari, quindi serve piu' campione.
- le soglie di `avg_ht_goals` per OVER 0.5 HT sono 1.10 / 1.30 / 1.60, non 0.80 / 0.86 / 1.00. Win rate osservato per fascia, contro un breakeven del 69% a quota 1.45: 0.7-0.9 = 64.0%, 0.9-1.1 = 67.3%, 1.1-1.3 = 70.0%, 1.3-1.6 = 73.5%, 1.6+ = 78.4%. La vecchia soglia accettava proprio la fascia in perdita.

Le metriche marcate `ht_synthetic` non possono aprire un segnale reale sui market di primo tempo, ne' tramite i tier ne' tramite le scorciatoie di pressione.

### La colonna `HTKnown`

Nel CSV "primo tempo 0-0" e "primo tempo sconosciuto" si scrivevano entrambi `0`. L'ambiguita' costringeva `get_team_metrics` a indovinare con un'euristica quali zeri fossero dati mancanti, e metteva un tetto artificiale dell'82% a qualunque misura di copertura: il 17-18% delle partite con 2+ gol e' davvero 0-0 all'intervallo, quindi indistinguibile da un buco.

`HTKnown` vale 1 solo quando la fonte espone davvero il primo tempo. Entrambe le fonti lo permettono: football-data.co.uk ha le colonne `HTHG`/`HTAG` sempre valorizzate, l'API distingue lo zero dal nullo in `score.halftime`.

Con la colonna presente, `get_team_metrics` calcola `avg_ht_goals` **solo sulle partite in cui il dato e' noto**, e marca `ht_synthetic` quando quelle note sono meno di 6. Senza la colonna resta l'euristica precedente, come riserva.

La differenza non e' cosmetica: su una squadra con 6 partite note a media 2.0 e 4 righe senza dato, l'euristica restituiva 1.2 invece di 2.0, facendola scendere sotto la soglia CAUTION.

`api_football_league_import.py` importa lo storico un campionato alla volta (una chiamata restituisce l'intera stagione, ~380 partite, contro 3 chiamate per singola squadra) e traccia le coppie campionato-stagione gia' fatte, cosi' si puo' procedere a lotti.

### Grafie duplicate delle squadre

`normalize_team_names.py` unifica le grafie diverse della stessa squadra (`LIVERPOOL FOOTBALL CLUB` e `LIVERPOOL`), che spezzavano lo storico fra le varianti e facevano agganciare a `trova_squadra` la variante sbagliata, a volte quella senza primo tempo.

I candidati vengono proposti da una regola conservativa che toglie solo i marcatori generici (`football`, `club`, `association`, `fc`, `afc`) e devono poi superare due prove che dimostrerebbero il contrario: le due squadre si sono mai affrontate, e hanno mai giocato lo stesso giorno contro avversari diversi e con punteggio diverso. Un gruppo che fallisce una prova non viene accorpato — cosi' restano separati `CLUB NACIONAL` da `NACIONAL`, e `BARCELONA` o `EVERTON`, che in questo dataset sono ambigui perche' esistono anche club omonimi sudamericani.

`--dedupe-matches` gestisce il caso residuo: nomi troppo ambigui per essere unificati ma partite comunque riconoscibili come identiche (stessa data, stesso punteggio, stesso nome ridotto per entrambe le squadre). Fra due copie vince quella con il primo tempo reale.

Comandi: `--report`, `--write`, `--dedupe-matches --write`.

### Filtro quote

Un segnale viene pubblicato solo se la quota live copre il proprio breakeven: sotto `MIN_ODD_O05_HT` / `MIN_ODD_O15_HT` / `MIN_ODD_NEXT_GOAL` viene scartato con evento `ODDS_GATE_SKIP`. Con `ODDS_GATE_STRICT=1` vengono scartati anche i segnali per cui la quota non e' recuperabile.

Serve a un problema misurato: NEXT GOAL vince il 62.8% delle volte nella finestra 1-19, ma il mercato reale paga 1.02-1.13, dove il breakeven e' il 91.7%. Erano segnali vinti sul campo e in perdita in cassa (-31.5% per puntata). Con il filtro attivo quel market si spegne da solo finche' non ritrova valore, senza doverlo disabilitare a mano.

OVER 0.5 HT invece paga davvero 1.40-1.53 nei primi 5 minuti, contro un WR misurato del 72.5%: e' l'unica finestra con margine positivo trovata finora.

### Quote reali (`OpenOdd`)

Ogni segnale, reale o shadow, registra in `live_training_data.csv` la colonna `OpenOdd`: la quota effettivamente disponibile al momento dell'apertura. Per NEXT GOAL viene letta la linea `Over (gol correnti + 0.5)`, che e' l'esito su cui il segnale viene poi chiuso; se la linea non e' esposta il bot logga `LIVE_ODDS_NO_LINE` con gli esiti disponibili e lascia il campo vuoto.

`chiudi_scommessa` usa `OpenOdd` per il P/L quando e' valorizzata, e ricade sulla quota di config solo se manca. Senza questo dato ogni ROI del bot resta un'ipotesi: una strategia al 67% di win rate va in pari solo da quota 1.49 in su, e va verificato che il book la paghi davvero.

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


