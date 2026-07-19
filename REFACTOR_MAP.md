# REFACTOR_MAP — Split meccanico di `oracle_live.py`

Mappa funzione → modulo per lo split del monolite (5.322 righe, codice fino a riga ~5124).
**Zero cambi di logica, zero rinomini.** Solo spostamento di codice + import.

## Struttura finale

```
oracle_live/
  __init__.py       # importa handlers (=> intero grafo): `import oracle_live` si comporta come il monolite
  constants.py
  state.py
  api_client.py     # NUOVO (deviazione 1): helper HTTP API-Football + cache pruning
  filters.py
  markets.py
  guards.py
  models.py
  messaging.py
  signals.py
  vip.py
  prematch.py
  reporting.py
  handlers.py
  runtime.py
main.py             # entrypoint: from oracle_live.runtime import main; main()
oracle_live.py      # shim retro-compatibile (stesso contenuto di main.py)
```

Nota import: `oracle_live.py` (file) e `oracle_live/` (package) coesistono — Python dà
precedenza al package per `import oracle_live`; il file resta eseguibile come script
(`python oracle_live.py`), che è l'unico modo in cui viene usato oggi (`run.bat`,
`launcher.py`, `Oracle_Launcher*.ps1`, Dockerfile→launcher.py). Nessun file del repo fa
`import oracle_live` da altro codice.

---

## constants.py

Costanti pure, nessuna dipendenza interna (solo `config`, `os`).

| Simbolo (righe originali) | Note |
|---|---|
| `BASE_DIR` (61) | definito qui, importato dagli altri moduli |
| `required_settings` + check `missing_settings` → `RuntimeError` (79–84, 139–143) | resta a livello modulo: l'errore di config mancante scatta all'import, identico a oggi |
| `LIVE_TRAINING_COLUMNS` (85–117) | |
| `TITAN_PRESSURE_MODEL_PATH` (118) | |
| `V2_MODEL_PATH`, `V2_THRESHOLD_PATH`, `V2_DEFAULT_THRESHOLD` (121–123) | |
| `TITAN_PRESSURE_FEATURE_COLUMNS` (124–136) | |
| `TITAN_PROMOTION_THRESHOLD`, `TITAN_PRESSURE_ALERT_THRESHOLD` (137–138) | |
| `TIER_APPROVED/CAUTION/LEARNING/GAMBLING` (179–182) | |
| `MARKET_OVER05_HT`, `MARKET_OVER15_HT`, `MARKET_NEXT_GOAL` (183–185) | |
| `SEPARATOR` (186) | |
| `VIP_PLAN_CODE`, `VIP_PLAN_NAME`, `VIP_SYNC_INTERVAL_SECONDS` (187–189) | |
| `FREE_ALLOWED_TIERS` (190) | |
| `AUTO_MARKET_SWITCH_ENABLED` (191) | |
| `PREMIUM_ALLOWED_MARKETS/LEAGUES/COUNTRIES`, `PREMIUM_BLOCKED_LEAGUES/COUNTRIES` (192–227) | |
| `LEGACY_TIER_KEYS` (228–232) | **spostato byte-identico** (stringhe mojibake): estrazione byte-level + verifica hash del blocco |
| `TIER_EMOJI` (233–237) | |
| `MARKET_PRESETS`, `DEFAULT_MARKET_MODE` (239–246) | |
| `TOP10_COUNTRIES` (248–259) | |
| `FILTER_PRESETS`, `DEFAULT_FILTER_MODE` (261–266) | |
| `COVERAGE_GUARD_ENABLED/THRESHOLD/HOURS` (267–269) | |
| `MANUAL_TEAM_ALIASES` (270–280) | |
| `YOUTH_EXCLUDED`, `NON_LEAGUE_EXCLUDED` (281–296) | |
| `SERIE_AB_PATTERNS` (297–308) | |
| `PROCESS_LOCK_PATH` (176) | |

## state.py

Stato condiviso: dict `stats`, TUTTI i lock, singleton runtime, persistenza `salva_dati_web`.
Nessun altro modulo definisce lock propri.

| Simbolo | Note |
|---|---|
| `bot = telebot.TeleBot(TOKEN_LIVE)` (145) | deviazione 4: singleton condiviso, serve a messaging/handlers/vip senza cicli |
| `logger` + setup handler (169–175), `log_event` (309–313) | deviazione 4 |
| `membership_store` (153) | deviazione 4 |
| `state_lock`, `analytics_lock` (=state_lock), `live_training_lock`, `missing_team_queue_lock`, `prematch_backend_lock` (156–160) | |
| Globali ribindabili: `running`, `shutdown_requested`, `df_matches`, `nomi_unici_db`, `oracle_brain`, `titan_pressure_brain`, `oracle_v2_threshold`, `last_vip_sync_ts`, `retrain_running`, `backfill_running`, `prematch_running`, `dashboard_process`, `ngrok_process`, `last_retrain_result`, `missing_team_queue` (146–168) | acceduti dagli altri moduli come `state.X` (vedi "Gestione stato condiviso") |
| `pending_free_timers` (155), `fixture_stats_cache` (167) | mai ribindati → importabili per nome |
| `team_match_cache`, `normalized_team_lookup`, `team_not_found_counts` | deviazione 8: oggi creati solo dentro `__main__` (5106–5108); diventano dict vuoti a livello modulo (comportamento identico in tutti i path raggiungibili: le funzioni che li usano escono prima se `nomi_unici_db` è vuoto) |
| `stats` dict (353–379) | |
| `default_analytics` (316), `default_prematch_last_report` (337), `default_prematch_watch_state` (341), `default_recap_delivery` (390) | |
| `now_utc` (381), `current_date_key` (386) | |
| `ensure_daily_analytics` (394) | chiama `salva_dati_web` → stesso modulo, nessun ciclo |
| `increment_analytics` (410), `increment_breakdown_counter` (418), `increment_market_settlement` (431), `increment_settled_breakdown` (448) | |
| `get_settled_bucket_stats` (465), `append_rolling_settled` (474), `get_rolling_bucket_stats` (495), `get_recent_rolling_stats` (573) | |
| `salva_dati_web` (1163) | persistenza `dati_web.json`; piccola → resta qui, niente `persistence.py` |
| `get_total_settled_count` (3340) | pura lettura di `stats`; usato da models/runtime |
| `ensure_live_training_dataset` (2640), `append_live_training_row` (2658), `update_live_training_outcome` (2665) | deviazione (vedi 11): persistenza CSV live-training con `live_training_lock`; qui per evitare ciclo models↔signals |

## api_client.py  *(nuovo modulo — deviazione 1)*

Helper HTTP API-Football usati sia da guards che da signals: separarli rompe il ciclo
guards↔signals. Cache (`fixture_stats_cache`) resta in `state.py`.

| Simbolo | Note |
|---|---|
| `fetch_fixture_status` (3469) | |
| `parse_stat_value` (3492), `normalize_stat_key` (3504) | |
| `prune_fixture_stats_cache` (3508) | |
| `fetch_fixture_stats` (3530) | |
| `fetch_next_goal_live_odds` (3606) | |

## filters.py

Filtri campionati/paesi, normalizzazione testo/squadre, alias, matching squadre,
coda missing-team, **coverage guard** (deviazione 2).

| Simbolo | Note |
|---|---|
| `normalizza_testo` (664), `normalizza_squadra` (670) | |
| `load_missing_team_queue` (1177), `save_missing_team_queue` (1193), `queue_missing_team_lookup` (1199) | |
| `get_missing_team_queue_count` (1230), `get_missing_team_queue_status_counts` (1234), `read_missing_team_queue_status_counts_from_disk` (1252) | |
| `build_team_lookup` (1277), `simplify_team_tokens` (1291), `get_controlled_aliases` (1305) | |
| `ensure_coverage_guard` (1337), `get_coverage_key` (1349), `is_coverage_blocked` (1357), `register_team_not_found` (1382) | deviazione 2: il brief li metteva in guards.py, ma usano `normalizza_testo` e sono usati da `get_league_filter_reason` (qui) → tenerli in filters.py evita il ciclo filters↔guards |
| `log_team_not_found` (1417), `get_top_team_not_found` (1429) | |
| `trova_squadra` (1434) | |
| `is_non_league_competition` (1514), `is_youth_competition` (1519), `is_allowed_serie_ab` (1524) | |
| `get_league_filter_reason` (1530), `is_league_allowed` (1546) | |
| `get_filter_mode` (953), `get_filter_label` (958), `set_filter_mode` (1548) | |
| `start_missing_team_backfill_job` (2918) | deviazione 10: job subprocess del dominio missing-team (usa la coda + `send_html_message_safe`) |

## markets.py

| Simbolo | Note |
|---|---|
| `get_market_mode` (962), `get_market_label` (967), `get_active_markets` (971), `set_market_mode` (1557) | |
| `get_routed_active_markets` (975) | |
| `get_market_router_score` (985), `prioritize_markets` (1027) | |
| `is_market_window` (1614) | |
| `is_market_winner` (1833), `is_first_half_closed` (1843) | |
| `get_minute_bucket` (604) | |
| `get_min_quota_for_tier` (3647) | usato da messaging |

## guards.py

Guard su performance live e statistiche live. (Coverage guard → filters.py, dev. 2.)

| Simbolo | Note |
|---|---|
| `check_negative_window` (519) | |
| `should_skip_by_live_performance` (525) | |
| `should_skip_next_goal_by_context` (3726) | |
| `should_skip_by_live_stats` (3821) | usa `fetch_fixture_stats` da api_client |

## models.py

Caricamento modelli + titan pressure + retrain.

| Simbolo | Note |
|---|---|
| `load_models()` | deviazione 9: NUOVA funzione che contiene, statement per statement, i due blocchi try/except di boot del `__main__` (5062–5093: caricamento v2 + threshold + fallback, titan pressure); scrive su `state.oracle_brain` / `state.oracle_v2_threshold` / `state.titan_pressure_brain`; chiamata da `runtime.main()` |
| `predict_titan_pressure_prob` (3651) | |
| `evaluate_titan_soft_layer` (3675) | |
| `has_live_pressure_data` (3713) | |
| `get_xg_rate` (3718) | |
| `format_ml_status` (2691) | |
| `run_retrain_from_bot` (2793) | |
| `start_retrain_job` (2893) | |
| `maybe_trigger_auto_retrain` (3347) | |

## messaging.py

Formattazione messaggi + invio sicuro + helper chat.

| Simbolo | Note |
|---|---|
| `escape_html` (676) | |
| `send_html_message_safe` (639) | |
| `is_private_chat` (931), `is_admin_message` (935) | deviazione 6: servono a vip.py e handlers.py → qui per evitare ciclo vip↔handlers |
| `format_edge_text` (1960) | |
| `format_signal_message` (1976) | usa `get_min_quota_for_tier` (markets) |
| `format_premium_signal_message` (2071) | |
| `format_signal_legend` (2093) | |
| `format_free_teaser_message` (2115) | |
| `format_settlement_message` (2130) | |
| `format_commands_help` (3988) | |
| `get_profile_label` (1848) | |

## signals.py

Apertura/chiusura segnali, tracker, esiti, delivery, radar loop, diagnostica radar.

| Simbolo | Note |
|---|---|
| `get_signal_key` (1035) | |
| `should_send_free_teaser` (1039) | |
| `build_delivery_targets_from_legacy` (1048), `migrate_monitor_entries` (1079) | |
| `prune_settled_signals` (1090), `clean_sent_signals` (1102) | |
| `get_team_metrics` (1629), `combine_team_metrics` (1670) | |
| `evaluate_signal_candidate` (1699), `evaluate_learning_candidate` (1781), `evaluate_pending_next_goal_candidate` (1878), `evaluate_snapshot_candidate` (1901), `evaluate_prewindow_snapshot_candidate` (1941) | |
| `clear_pending_signal_tracker` (1852), `register_pending_signal_tracker` (1857) | |
| `is_premium_private_signal` (2031) | |
| `get_market_debug_status` (2173), `format_radar_check_text` (2272) | deviazione 7: diagnostica del motore segnali; metterli in reporting creerebbe il ciclo reporting↔signals |
| `update_recent_signal` (3436), `edit_signal_message` (3443) | |
| `settle_missing_live_signals` (3859), `chiudi_scommessa` (3890) | chiama `maybe_send_performance_report` (reporting) e `maybe_trigger_auto_retrain` (models) — nessun ciclo: reporting/models non importano signals |
| `schedule_free_delivery` (4146), `record_signal_delivery` (4177) | |
| `radar_loop` (4221) | deviazione 3: il brief lo metteva in runtime.py, ma è avviato da un handler (`go_cmd`) → in runtime creerebbe il ciclo handlers↔runtime |

## vip.py

| Simbolo | Note |
|---|---|
| `create_vip_invite_link` (4039) | |
| `sync_vip_memberships` (4057) | |
| `vip_sync_loop` (4096) | |
| `send_vip_invoice` (4105) | |
| `format_member_status` (4128), `handle_vip_status` (4138) | |

(Gli handler `pre_checkout_handler` / `successful_payment_handler` stanno in handlers.py.)

## prematch.py

| Simbolo | Note |
|---|---|
| `extract_requested_date` (680) | usato solo dal comando /prematch_today |
| `format_prematch_reason` (691), `format_prematch_market_move` (712), `format_prematch_action_label` (728), `format_prematch_bet_type` (742) | |
| `format_prematch_today_report` (757), `format_prematch_watch_update` (791) | |
| `build_prematch_watch_snapshot` (814), `format_prematch_watch_delta` (833) | |
| `activate_prematch_watch` (900), `stop_prematch_watch` (921) | |
| `start_prematch_today_job` (3045) | |
| `prematch_auto_collect_loop` (3082), `prematch_watch_loop` (3113) | |

## reporting.py

| Simbolo | Note |
|---|---|
| `summarize_wr_bucket` (563), `format_rolling_overview` (592), `format_market_rolling_overview` (599) | |
| `format_top_counts` (616), `format_market_results` (623) | |
| `format_analytics_text` (2152) | |
| `format_admin_panel` (2330) | |
| `format_admin_recap` (2390), `format_vip_recap` (2406), `format_free_recap` (2421) | |
| `compute_performance_snapshot` (2434), `format_performance_by_market` (2492), `format_performance_report` (2504) | |
| `format_x_post_copy` (2553), `format_x_copy_message` (2568), `format_x_promo_copy` (2573), `format_x_promo_message` (2606) | |
| `maybe_send_performance_report` (2611) | |
| `send_daily_recap_if_due` (3375), `recap_loop` (3428) | |

## handlers.py

Tutti gli handler telebot (comandi + bottoni tastiera), tastiere, `require_admin_access`.
I decoratori `@bot.message_handler` si registrano all'import del modulo (come oggi
all'import del monolite).

| Simbolo | Note |
|---|---|
| `require_admin_access` (943) | usa `is_admin_message` da messaging |
| `build_main_keyboard` (3952), `build_filter_keyboard` (3964), `build_market_keyboard` (3972), `build_vip_keyboard` (3981) | |
| Comandi (4630–5055): `shutdown_cmd`, `start_cmd`, `dashboard_web_cmd`, `dashboard_public_cmd`, `dashboard_restart_cmd`, `vip_cmd`, `vip_status_cmd`, `paysupport_cmd`, `analytics_cmd`, `admin_cmd`, `radarcheck_cmd`, `prematch_today_cmd`, `prematch_watch_start_cmd`, `prematch_watch_stop_cmd`, `ml_status_cmd`, `retrain_cmd`, `backfill_missing_cmd`, `backfill_missing_all_cmd`, `xcopy_cmd`, `xpromo_cmd`, `help_cmd`, `legend_cmd` | |
| Pagamenti: `pre_checkout_handler` (4775), `successful_payment_handler` (4784) | logica in vip.py/membership_store |
| Bottoni: `go_cmd`, `dash_cmd`, `stop_cmd`, `filter_menu_cmd`, `market_menu_cmd`, `vip_menu_cmd`, `back_to_home_cmd`, `current_filter_cmd`, `current_market_cmd`, `vip_access_button_cmd`, `xcopy_button_cmd`, `xpromo_button_cmd`, `vip_status_button_cmd`, `commands_button_cmd`, `legend_button_cmd`, `admin_panel_button_cmd`, `ml_status_button_cmd`, `prematch_today_button_cmd`, `prematch_watch_on_button_cmd`, `prematch_watch_off_button_cmd`, `filter_top10_cmd`, `filter_serie_ab_cmd`, `filter_global_cmd`, `market_over05_cmd`, `market_over15_cmd`, `market_both_cmd`, `market_next_goal_cmd`, `market_ht_next_cmd` | |

## runtime.py

Process lock, boot, caricamento memoria, dashboard/ngrok, shutdown, polling.

| Simbolo | Note |
|---|---|
| import piattaforma lock (`msvcrt`/`fcntl`, righe 15–21) | |
| `process_lock_handle` (177) | usato solo qui |
| `acquire_process_lock` (1567), `release_process_lock` (1589), `atexit.register(release_process_lock)` (1613) | l'atexit scatta all'import di runtime (≈ all'import del monolite oggi) |
| `carica_memoria` (1108) | deviazione 5: chiama filters/markets/signals/state → in state.py creerebbe cicli; è codice di boot |
| `stop_radar` (3935), `request_shutdown` (3941) | |
| `get_local_dashboard_url` (3172), `find_ngrok_executable` (3188), `extract_ngrok_public_url` (3201) | |
| `start_dashboard_web_job` (3220), `start_dashboard_public_job` (3261), `restart_dashboard_job` (3306) | |
| `main()` | NUOVA funzione = blocco `if __name__ == "__main__"` (5056–5124) statement per statement: process lock → `models.load_models()` → `carica_memoria()` → `load_missing_team_queue()` → `ensure_live_training_dataset()` → thread (vip_sync_loop, recap_loop, prematch_auto_collect_loop, prematch_watch_loop) → caricamento `Matches.csv` in `state.df_matches`/`nomi_unici_db` + reset cache squadre → `build_team_lookup()` → loop `bot.polling(...)`. Importa `oracle_live.handlers` in cima al corpo (registrazione handler prima del polling; runtime non importa handlers a livello modulo per evitare il ciclo handlers→runtime) |

## main.py + shim oracle_live.py

```python
from oracle_live.runtime import main

if __name__ == "__main__":
    main()
```

Identici. `.bat`/`.ps1`/`launcher.py` continuano a lanciare `python oracle_live.py` senza modifiche.

---

## Gestione stato condiviso (regola del progetto)

- `stats`, tutti i lock, `pending_free_timers`, `fixture_stats_cache` non vengono mai
  ribindati → gli altri moduli fanno `from oracle_live.state import stats, state_lock, ...`
  e i corpi delle funzioni restano testualmente identici.
- I globali **ribindati** con `global X` (`running`, `shutdown_requested`, `oracle_brain`,
  `titan_pressure_brain`, `oracle_v2_threshold`, `retrain_running`, `backfill_running`,
  `prematch_running`, `dashboard_process`, `ngrok_process`, `last_retrain_result`,
  `last_vip_sync_ts`, `missing_team_queue`, `df_matches`, `nomi_unici_db`,
  `team_match_cache`, `normalized_team_lookup`, `team_not_found_counts`) vengono acceduti
  come attributo `state.X` dagli altri moduli (unica trasformazione testuale necessaria:
  `oracle_brain` → `state.oracle_brain` ecc., `global X` → rimosso/`state.X = ...`).
  Nessun cambio di logica: stessa semantica di lettura/scrittura condivisa del monolite.

## Deviazioni dal brief (riepilogo)

1. **`api_client.py` nuovo**: `fetch_fixture_status/stats/odds` + `parse_stat_value` +
   `normalize_stat_key` + `prune_fixture_stats_cache`. Serve sia a guards che a signals:
   modulo dedicato per rompere il ciclo guards↔signals.
2. **Coverage guard in `filters.py`** (non guards.py): usa `normalizza_testo` ed è usato da
   `get_league_filter_reason` → evita il ciclo filters↔guards.
3. **`radar_loop` in `signals.py`** (non runtime.py): è avviato dall'handler `go_cmd`;
   in runtime creerebbe il ciclo handlers↔runtime.
4. **`bot`, `logger`, `log_event`, `membership_store` in `state.py`**: singleton condivisi
   alla base del grafo (il brief non specificava dove metterli).
5. **`carica_memoria` in `runtime.py`**, `salva_dati_web` in `state.py`: carica_memoria
   dipende da filters/markets/signals → in state creerebbe cicli. Niente `persistence.py`
   (salva_dati_web è ~10 righe).
6. **`is_private_chat`/`is_admin_message` in `messaging.py`** (usate anche da vip.py);
   `require_admin_access` resta in handlers.py come da brief.
7. **`get_market_debug_status` + `format_radar_check_text` in `signals.py`**: usano gli
   evaluate_* del motore; in reporting creerebbero il ciclo reporting↔signals.
8. **`team_match_cache`/`normalized_team_lookup`/`team_not_found_counts`**: oggi creati solo
   dentro `__main__`; diventano dict vuoti a livello modulo in state.py. Comportamento
   identico in tutti i path raggiungibili (le funzioni che li usano ritornano prima quando
   `nomi_unici_db` è vuoto).
9. **`models.load_models()`**: wrappa il blocco di caricamento modelli del `__main__`
   (statement identici), chiamata da `runtime.main()`.
10. **`start_missing_team_backfill_job` in `filters.py`** (dominio coda missing-team).
11. **Helper CSV live-training (`ensure_live_training_dataset`, `append_live_training_row`,
    `update_live_training_outcome`) in `state.py`**: usati da signals E da
    `models.format_ml_status`/runtime → in signals creerebbero il ciclo models↔signals.
12. **`oracle_live/__init__.py` importa `handlers`**: così `import oracle_live` produce gli
    stessi effetti collaterali del monolite (creazione bot, registrazione handler, logger,
    check config). `main.py` aggiunto come entrypoint alternativo.

## Piano commit (un modulo per commit)

Durante la migrazione il monolite resta intatto; i moduli vengono creati nel package e il
monolite viene sostituito con lo shim solo nell'ultimo commit di codice.

1. `REFACTOR_MAP.md` (questo file)
2. `oracle_live/constants.py` (+ `__init__.py` vuoto provvisorio)
3. `oracle_live/state.py`
4. `oracle_live/api_client.py`
5. `oracle_live/filters.py`
6. `oracle_live/markets.py`
7. `oracle_live/guards.py`
8. `oracle_live/models.py`
9. `oracle_live/messaging.py`
10. `oracle_live/signals.py`
11. `oracle_live/vip.py`
12. `oracle_live/prematch.py`
13. `oracle_live/reporting.py`
14. `oracle_live/handlers.py`
15. `oracle_live/runtime.py` + shim `oracle_live.py` + `main.py` + `__init__.py` definitivo
16. README: nuova struttura cartelle

Dopo ogni commit: `python -c "import oracle_live.<modulo>"` (e dal commit 15
`python -c "import oracle_live"` + avvio a secco). Non esistono test nel repo
(nessun `test_oracle_live*`; i `test_*.py` presenti sono script manuali di prova API).

## Verifica finale prevista

1. Avvio a secco con `.env` fittizio → stesso comportamento/errore del monolite.
2. `grep` di tutte le funzioni pubbliche: nessun rinomino.
3. Diff LOC: somma moduli ≈ 5.124 righe di codice originale (± import/shim/def wrapper).
4. Hash byte-level del blocco `LEGACY_TIER_KEYS` identico all'originale.
5. README aggiornato.
