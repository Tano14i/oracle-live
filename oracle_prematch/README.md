# Oracle PreMatch

Scanner separato per anomalie pre-match.

Obiettivo reale:

- filtrare tanti match in una watchlist corta
- far emergere movimenti anomali prima del kickoff
- supportare review umana e monitoraggio live

Non promette:

- match truccati sicuri
- profitto automatico
- edge sistematico solo con pre-match

## Cosa contiene

- `main.py`: CLI del progetto
- `sample_feed.json`: feed di esempio per partire subito
- `storage.py`: persistenza SQLite di run e alert
- `scoring.py`: logica MVP per il risk score
- `telegram_alerts.py`: invio opzionale degli alert a Telegram

## Avvio rapido

1. `python Oracle_PreMatch.py init-db`
2. `python Oracle_PreMatch.py scan`
3. `python Oracle_PreMatch.py report`

Output generati:

- `oracle_prematch/prematch_watchlist.db`
- `oracle_prematch/output/latest_watchlist.json`
- `oracle_prematch/output/latest_watchlist.txt`

## Feed input

Lo scanner legge un JSON con una lista `fixtures`.

Campi principali:

- `fixture_id`
- `sport`
- `country`
- `league`
- `home_team`
- `away_team`
- `kickoff_utc`
- `public_news_hits`
- `tags`
- `notes`
- `snapshots`

Ogni snapshot supporta:

- `captured_at_utc`
- `home_odds`
- `draw_odds`
- `away_odds`
- `over25_odds`
- `under25_odds`
- `bookmaker_count`

## Logica score MVP

Il punteggio combina:

- entita del drop quota
- velocita del movimento
- vicinanza al kickoff
- coerenza del movimento
- contesto niche o low-liquidity
- penalita per news pubbliche
- penalita top league

Stati finali:

- `WATCH LIVE`
- `MANUAL REVIEW`
- `WATCHLIST`
- `IGNORE`

## Telegram

Per inviare gli alert:

1. duplica `.env.prematch.example` in `.env.prematch`
2. compila `PREMATCH_TELEGRAM_BOT_TOKEN`
3. compila `PREMATCH_TELEGRAM_CHAT_ID`
4. esegui `python Oracle_PreMatch.py scan --send-telegram`

## Feed reale con API-FOOTBALL

Comandi utili:

1. `python Oracle_PreMatch.py list-bookmakers`
2. `python Oracle_PreMatch.py fetch-odds --date 2026-03-29`
3. opzionale: `python Oracle_PreMatch.py fetch-odds --date 2026-03-29 --league-id 135 --season 2025`
4. ripeti `fetch-odds` dopo qualche minuto per accumulare almeno 2 snapshot per match

Comportamento reale:

- al primo `fetch-odds` il bot salva snapshot correnti nel DB
- dal secondo `fetch-odds` in poi puo confrontare i movimenti e creare la watchlist
- usa mediana quote bookmaker API-FOOTBALL per ridurre rumore e spike singoli
- arricchisce i nomi squadre via endpoint `fixtures`
- se integrato dentro `oracle_live.py`, puo anche raccogliere snapshot in automatico in backend

Variabili da compilare in `.env.prematch`:

- `PREMATCH_API_FOOTBALL_KEY`
- `PREMATCH_API_FOOTBALL_LOOKBACK_HOURS`

## Evoluzioni consigliate

- adapter per OddsAPI o feed proprietario
- storico dei movimenti nel DB
- classificazione dei falsi positivi
- monitor live post-watchlist
- dashboard dedicata
