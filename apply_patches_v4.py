"""
apply_patches_v4.py - xG (expected goals) come filtro per Next Goal Live
Esegui nella cartella del progetto:
    python apply_patches_v4.py
"""
import os
import shutil
from datetime import datetime

TARGET = "oracle_live.py"
BACKUP = f"oracle_live_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"

if not os.path.exists(TARGET):
    print(f"ERRORE: {TARGET} non trovato.")
    exit(1)

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()

shutil.copy2(TARGET, BACKUP)
print(f"Backup salvato: {BACKUP}")

patches = [

    # PATCH 1 - Aggiungi campi xG a totals in fetch_fixture_stats
    (
        '        totals = {\n'
        '            "shots_on_goal": 0.0,\n'
        '            "total_shots": 0.0,\n'
        '            "corners": 0.0,\n'
        '            "red_cards": 0.0,\n'
        '            "red_cards_home": 0.0,\n'
        '            "red_cards_away": 0.0,\n'
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '        }',
        '        totals = {\n'
        '            "shots_on_goal": 0.0,\n'
        '            "total_shots": 0.0,\n'
        '            "corners": 0.0,\n'
        '            "red_cards": 0.0,\n'
        '            "red_cards_home": 0.0,\n'
        '            "red_cards_away": 0.0,\n'
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '            "xg_home": 0.0,\n'
        '            "xg_away": 0.0,\n'
        '            "shots_insidebox": 0.0,\n'
        '            "goalkeeper_saves": 0.0,\n'
        '        }',
        "Aggiungi campi xG, shots_insidebox, goalkeeper_saves a totals"
    ),

    # PATCH 2 - Estrai xG nel loop statistiche
    (
        '                elif stat_key == "dangerous attacks":\n'
        '                    totals["dangerous_attacks"] += stat_value\n'
        '                elif stat_key == "ball possession":\n'
        '                    team_possession = stat_value',
        '                elif stat_key == "dangerous attacks":\n'
        '                    totals["dangerous_attacks"] += stat_value\n'
        '                elif stat_key == "expected goals":\n'
        '                    if team_index == 0:\n'
        '                        totals["xg_home"] = stat_value\n'
        '                    else:\n'
        '                        totals["xg_away"] = stat_value\n'
        '                elif stat_key == "shots insidebox":\n'
        '                    totals["shots_insidebox"] += stat_value\n'
        '                elif stat_key == "goalkeeper saves":\n'
        '                    totals["goalkeeper_saves"] += stat_value\n'
        '                elif stat_key == "ball possession":\n'
        '                    team_possession = stat_value',
        "Estrai xG, shots_insidebox, goalkeeper_saves"
    ),

    # PATCH 3 - Aggiungi funzione get_xg_rate prima di should_skip_next_goal_by_context
    (
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        'def get_xg_rate(stats_payload: dict, minute_value: int) -> float:\n'
        '    """\n'
        '    Calcola il tasso xG per minuto della partita.\n'
        '    Riferimento: >= 0.025 calda, >= 0.015 media, < 0.010 difensiva.\n'
        '    """\n'
        '    if not isinstance(stats_payload, dict) or minute_value <= 0:\n'
        '        return 0.0\n'
        '    xg_home = float(stats_payload.get("xg_home", 0.0) or 0.0)\n'
        '    xg_away = float(stats_payload.get("xg_away", 0.0) or 0.0)\n'
        '    return round((xg_home + xg_away) / max(1, minute_value), 4)\n'
        '\n'
        '\n'
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        "Aggiungi get_xg_rate"
    ),

    # PATCH 4 - Inizializza xg_threshold_bonus a livello fixture
    (
        '                xg_threshold_bonus = 0.0  # inizializzato qui, aggiornato nel blocco Next Goal',
        '                xg_threshold_bonus = 0.0  # inizializzato qui, aggiornato nel blocco Next Goal',
        "Gia presente - skip"
    ),

    # PATCH 5 - Aggiungi filtro xG dopo il filtro cecchino nel radar_loop
    (
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        '                                # Filtro xG: blocca partite troppo difensive\n'
        '                                xg_rate = get_xg_rate(stats_payload, minute_value)\n'
        '                                if xg_rate > 0.0 and xg_rate < 0.010 and minute_value >= 15:\n'
        '                                    scan_debug["candidate_failed"] += 1\n'
        '                                    clear_pending_signal_tracker(signal_key)\n'
        '                                    log_event("NG_XG_SKIP", f"fixture_id={fixture_id} minute={minute_value} xg_rate={xg_rate:.4f}")\n'
        '                                    continue\n'
        '                                # Bonus xG: soglia abbassata se partita caldissima\n'
        '                                if xg_rate >= 0.030:\n'
        '                                    xg_threshold_bonus = -0.05\n'
        '                                    log_event("NG_XG_BONUS", f"fixture_id={fixture_id} xg_rate={xg_rate:.4f} bonus=-0.05")\n'
        '                                elif xg_rate >= 0.025:\n'
        '                                    xg_threshold_bonus = -0.03\n'
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        "Aggiungi filtro xG e bonus soglia per Next Goal"
    ),

    # PATCH 6 - Applica bonus alla soglia v2
    (
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n'
        '                    # Applica bonus xG se la partita e caldissima\n'
        '                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n'
        '                    if market_in_window and prob < effective_threshold:',
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n'
        '                    # Applica bonus xG se la partita e caldissima\n'
        '                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n'
        '                    if market_in_window and prob < effective_threshold:',
        "Gia presente - skip"
    ),

]

# Le patch 4 e 6 sono placeholder, gestiamo separatamente le due principali
real_patches = [
    (
        '        totals = {\n'
        '            "shots_on_goal": 0.0,\n'
        '            "total_shots": 0.0,\n'
        '            "corners": 0.0,\n'
        '            "red_cards": 0.0,\n'
        '            "red_cards_home": 0.0,\n'
        '            "red_cards_away": 0.0,\n'
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '        }',
        '        totals = {\n'
        '            "shots_on_goal": 0.0,\n'
        '            "total_shots": 0.0,\n'
        '            "corners": 0.0,\n'
        '            "red_cards": 0.0,\n'
        '            "red_cards_home": 0.0,\n'
        '            "red_cards_away": 0.0,\n'
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '            "xg_home": 0.0,\n'
        '            "xg_away": 0.0,\n'
        '            "shots_insidebox": 0.0,\n'
        '            "goalkeeper_saves": 0.0,\n'
        '        }',
        "PATCH 1: Campi xG in totals"
    ),
    (
        '                elif stat_key == "dangerous attacks":\n'
        '                    totals["dangerous_attacks"] += stat_value\n'
        '                elif stat_key == "ball possession":\n'
        '                    team_possession = stat_value',
        '                elif stat_key == "dangerous attacks":\n'
        '                    totals["dangerous_attacks"] += stat_value\n'
        '                elif stat_key == "expected goals":\n'
        '                    if team_index == 0:\n'
        '                        totals["xg_home"] = stat_value\n'
        '                    else:\n'
        '                        totals["xg_away"] = stat_value\n'
        '                elif stat_key == "shots insidebox":\n'
        '                    totals["shots_insidebox"] += stat_value\n'
        '                elif stat_key == "goalkeeper saves":\n'
        '                    totals["goalkeeper_saves"] += stat_value\n'
        '                elif stat_key == "ball possession":\n'
        '                    team_possession = stat_value',
        "PATCH 2: Estrai xG, shots_insidebox, goalkeeper_saves"
    ),
    (
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        'def get_xg_rate(stats_payload: dict, minute_value: int) -> float:\n'
        '    """\n'
        '    Calcola il tasso xG per minuto della partita.\n'
        '    Riferimento: >= 0.025 calda, >= 0.015 media, < 0.010 difensiva.\n'
        '    """\n'
        '    if not isinstance(stats_payload, dict) or minute_value <= 0:\n'
        '        return 0.0\n'
        '    xg_home = float(stats_payload.get("xg_home", 0.0) or 0.0)\n'
        '    xg_away = float(stats_payload.get("xg_away", 0.0) or 0.0)\n'
        '    return round((xg_home + xg_away) / max(1, minute_value), 4)\n'
        '\n'
        '\n'
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        "PATCH 3: Funzione get_xg_rate"
    ),
    (
        '                dna = combined_metrics["avg_total_goals"]\n'
        '                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))',
        '                dna = combined_metrics["avg_total_goals"]\n'
        '                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))\n'
        '                xg_threshold_bonus = 0.0',
        "PATCH 4: Inizializza xg_threshold_bonus"
    ),
    (
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        '                                # Filtro xG: blocca partite troppo difensive\n'
        '                                xg_rate = get_xg_rate(stats_payload, minute_value)\n'
        '                                if xg_rate > 0.0 and xg_rate < 0.010 and minute_value >= 15:\n'
        '                                    scan_debug["candidate_failed"] += 1\n'
        '                                    clear_pending_signal_tracker(signal_key)\n'
        '                                    log_event("NG_XG_SKIP", f"fixture_id={fixture_id} minute={minute_value} xg_rate={xg_rate:.4f}")\n'
        '                                    continue\n'
        '                                # Bonus xG: soglia abbassata se partita caldissima\n'
        '                                if xg_rate >= 0.030:\n'
        '                                    xg_threshold_bonus = -0.05\n'
        '                                    log_event("NG_XG_BONUS", f"fixture_id={fixture_id} xg_rate={xg_rate:.4f} bonus=-0.05")\n'
        '                                elif xg_rate >= 0.025:\n'
        '                                    xg_threshold_bonus = -0.03\n'
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        "PATCH 5: Filtro xG e bonus soglia"
    ),
    (
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n'
        '                    if market_in_window and prob < oracle_v2_threshold:\n'
        '                        scan_debug["candidate_failed"] += 1\n'
        '                        clear_pending_signal_tracker(signal_key)\n'
        '                        log_event("V2_THRESHOLD_SKIP", f"fixture_id={fixture_id} market={market} prob={prob:.3f} threshold={oracle_v2_threshold}")\n'
        '                        continue',
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n'
        '                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n'
        '                    if market_in_window and prob < effective_threshold:\n'
        '                        scan_debug["candidate_failed"] += 1\n'
        '                        clear_pending_signal_tracker(signal_key)\n'
        '                        log_event("V2_THRESHOLD_SKIP", f"fixture_id={fixture_id} market={market} prob={prob:.3f} threshold={effective_threshold:.2f}")\n'
        '                        continue',
        "PATCH 6: Applica bonus xG alla soglia v2"
    ),
]

errors = []
for i, (old, new, desc) in enumerate(real_patches, 1):
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK - {desc}")
    else:
        errors.append(i)
        print(f"FAIL - {desc}")

if errors:
    print(f"\nATTENZIONE: patch {errors} fallite. File NON modificato.")
else:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nSUCCESSO: tutte le patch applicate a {TARGET}")
    print(f"Backup: {BACKUP}")
    print("\nCosa cambia:")
    print("  - fetch_fixture_stats ora estrae xG home/away, shots_insidebox, goalkeeper_saves")
    print("  - Partite con xG_rate < 0.010/min dopo il 15' bloccate (troppo difensive)")
    print("  - Partite con xG_rate >= 0.030/min: soglia scende da 0.71 a 0.66")
    print("  - Partite con xG_rate >= 0.025/min: soglia scende da 0.71 a 0.68")
    print("\nNel log:")
    print("  NG_XG_SKIP  -> partita bloccata (difensiva)")
    print("  NG_XG_BONUS -> soglia abbassata (partita calda)")