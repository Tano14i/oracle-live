"""
apply_patches_v4_fixed.py - xG come filtro Next Goal Live (versione corretta)
Esegui nella cartella del progetto DOPO aver ripristinato il backup:
    copy oracle_live_backup_20260408_214342.py oracle_live.py
    python apply_patches_v4_fixed.py
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

# Verifica che sia il file corretto (senza patch v4 gia applicate)
if "xg_home" in src:
    print("ATTENZIONE: il file sembra avere gia la patch v4 applicata.")
    print("Ripristina prima il backup:")
    print("  copy oracle_live_backup_20260408_214342.py oracle_live.py")
    exit(1)

shutil.copy2(TARGET, BACKUP)
print(f"Backup salvato: {BACKUP}")

real_patches = [

    # PATCH 1 - Aggiungi campi xG a totals in fetch_fixture_stats
    (
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '        }',
        '            "dangerous_attacks": 0.0,\n'
        '            "possession_diff": 0.0,\n'
        '            "xg_home": 0.0,\n'
        '            "xg_away": 0.0,\n'
        '            "shots_insidebox": 0.0,\n'
        '            "goalkeeper_saves": 0.0,\n'
        '        }',
        "PATCH 1: Campi xG in totals"
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
        "PATCH 2: Estrai xG, shots_insidebox, goalkeeper_saves"
    ),

    # PATCH 3 - Aggiungi funzione get_xg_rate
    (
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        'def get_xg_rate(stats_payload: dict, minute_value: int) -> float:\n'
        '    """\n'
        '    Tasso xG per minuto. Riferimento:\n'
        '    >= 0.025 partita calda, >= 0.015 media, < 0.010 difensiva.\n'
        '    """\n'
        '    if not isinstance(stats_payload, dict) or minute_value <= 0:\n'
        '        return 0.0\n'
        '    xg_h = float(stats_payload.get("xg_home", 0.0) or 0.0)\n'
        '    xg_a = float(stats_payload.get("xg_away", 0.0) or 0.0)\n'
        '    return round((xg_h + xg_a) / max(1, minute_value), 4)\n'
        '\n'
        '\n'
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        "PATCH 3: Funzione get_xg_rate"
    ),

    # PATCH 4 - Inizializza xg_threshold_bonus a livello fixture nel radar_loop
    (
        '                dna = combined_metrics["avg_total_goals"]\n'
        '                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))',
        '                dna = combined_metrics["avg_total_goals"]\n'
        '                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))\n'
        '                xg_threshold_bonus = 0.0',
        "PATCH 4: Inizializza xg_threshold_bonus"
    ),

    # PATCH 5 - Filtro xG dopo filtro cecchino nel radar_loop
    # Usa format() invece di f-string con :.4f per evitare problemi
    (
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        '                                xg_rate = get_xg_rate(stats_payload, minute_value)\n'
        '                                if xg_rate > 0.0 and xg_rate < 0.010 and minute_value >= 15:\n'
        '                                    scan_debug["candidate_failed"] += 1\n'
        '                                    clear_pending_signal_tracker(signal_key)\n'
        '                                    log_event("NG_XG_SKIP", "fixture_id=" + str(fixture_id) + " min=" + str(minute_value) + " xg_rate=" + str(xg_rate))\n'
        '                                    continue\n'
        '                                if xg_rate >= 0.030:\n'
        '                                    xg_threshold_bonus = -0.05\n'
        '                                    log_event("NG_XG_BONUS", "fixture_id=" + str(fixture_id) + " xg_rate=" + str(xg_rate) + " bonus=-0.05")\n'
        '                                elif xg_rate >= 0.025:\n'
        '                                    xg_threshold_bonus = -0.03\n'
        '                                    log_event("NG_XG_BONUS", "fixture_id=" + str(fixture_id) + " xg_rate=" + str(xg_rate) + " bonus=-0.03")\n'
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        "PATCH 5: Filtro xG e bonus soglia"
    ),

    # PATCH 6 - Applica bonus xG alla soglia v2
    (
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n'
        '                    if market_in_window and prob < oracle_v2_threshold:\n'
        '                        scan_debug["candidate_failed"] += 1\n'
        '                        clear_pending_signal_tracker(signal_key)\n'
        '                        log_event("V2_THRESHOLD_SKIP", f"fixture_id={fixture_id} market={market} prob={prob:.3f} threshold={oracle_v2_threshold}")\n'
        '                        continue',
        '                    # Filtro soglia v2 con eventuale bonus xG\n'
        '                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n'
        '                    if market_in_window and prob < effective_threshold:\n'
        '                        scan_debug["candidate_failed"] += 1\n'
        '                        clear_pending_signal_tracker(signal_key)\n'
        '                        log_event("V2_THRESHOLD_SKIP", "fixture_id=" + str(fixture_id) + " market=" + str(market) + " prob=" + str(round(prob, 3)) + " thr=" + str(round(effective_threshold, 2)))\n'
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

# Verifica sintassi finale
try:
    compile(src, TARGET, "exec")
    print("\nVerifica sintassi: OK")
    syntax_ok = True
except SyntaxError as e:
    print(f"\nERRORE SINTASSI: {e}")
    print("File NON salvato. Controlla il backup.")
    syntax_ok = False

if errors:
    print(f"\nATTENZIONE: patch {errors} fallite. File NON modificato.")
elif not syntax_ok:
    print("File NON salvato per errori di sintassi.")
else:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nSUCCESSO: tutte le patch applicate e sintassi verificata.")
    print(f"Backup: {BACKUP}")
    print("\nCosa cambia:")
    print("  - fetch_fixture_stats estrae xG home/away, shots_insidebox, goalkeeper_saves")
    print("  - Partite xG_rate < 0.010/min dopo min 15 bloccate (difensive)")
    print("  - Partite xG_rate >= 0.030/min: soglia 0.71 -> 0.66 (bonus)")
    print("  - Partite xG_rate >= 0.025/min: soglia 0.71 -> 0.68 (bonus lieve)")
    print("\nNel log:")
    print("  NG_XG_SKIP  -> partita bloccata (difensiva)")
    print("  NG_XG_BONUS -> soglia abbassata (partita calda)")