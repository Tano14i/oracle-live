"""
apply_patches.py - Applica le 5 patch a oracle_live.py
Esegui nella cartella del progetto:
    python apply_patches.py
"""
import os
import shutil
from datetime import datetime

TARGET = "oracle_live.py"
BACKUP = f"oracle_live_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"

if not os.path.exists(TARGET):
    print(f"ERRORE: {TARGET} non trovato. Esegui dalla cartella Oracle Live.")
    exit(1)

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()

# Backup prima di modificare
shutil.copy2(TARGET, BACKUP)
print(f"Backup salvato: {BACKUP}")

patches = [
    # PATCH 1: Costanti V2
    (
        'TITAN_PRESSURE_MODEL_PATH = os.path.join(BASE_DIR, "titan_pressure_model.pkl")\n',
        'TITAN_PRESSURE_MODEL_PATH = os.path.join(BASE_DIR, "titan_pressure_model.pkl")\n\n# --- Modello v2 con soglia ottimale ---\nV2_MODEL_PATH = os.path.join(BASE_DIR, "oracle_brain_v2.pkl")\nV2_THRESHOLD_PATH = os.path.join(BASE_DIR, "oracle_brain_v2_threshold.txt")\nV2_DEFAULT_THRESHOLD = 0.71\n',
        "Costanti V2_MODEL_PATH, V2_THRESHOLD_PATH, V2_DEFAULT_THRESHOLD"
    ),
    # PATCH 2: Variabile globale soglia
    (
        'oracle_brain = None\ntitan_pressure_brain = None\n',
        'oracle_brain = None\ntitan_pressure_brain = None\noracle_v2_threshold = V2_DEFAULT_THRESHOLD\n',
        "Variabile globale oracle_v2_threshold"
    ),
    # PATCH 3: Boot carica modello v2
    (
        '    try:\n        oracle_brain = joblib.load(MODEL_PATH)\n        print("AI model loaded.")\n        log_event("BOOT", "Model loaded successfully")\n    except Exception:\n        oracle_brain = None\n        print("AI model not found.")\n        log_event("BOOT", "Model not found; running without ML model")',
        '    try:\n        oracle_brain = joblib.load(V2_MODEL_PATH)\n        print("AI model v2 loaded.")\n        log_event("BOOT", "Model v2 loaded successfully")\n        try:\n            with open(V2_THRESHOLD_PATH, "r") as _f:\n                oracle_v2_threshold = float(_f.read().strip())\n            print(f"Soglia ottimale v2: {oracle_v2_threshold}")\n            log_event("BOOT", f"V2 threshold loaded: {oracle_v2_threshold}")\n        except Exception:\n            oracle_v2_threshold = V2_DEFAULT_THRESHOLD\n            print(f"Threshold file non trovato, uso default: {oracle_v2_threshold}")\n    except Exception:\n        try:\n            oracle_brain = joblib.load(MODEL_PATH)\n            oracle_v2_threshold = 0.5\n            print("AI model v2 non trovato, caricato modello originale.")\n            log_event("BOOT", "Fallback to original model")\n        except Exception:\n            oracle_brain = None\n            oracle_v2_threshold = V2_DEFAULT_THRESHOLD\n            print("AI model non trovato.")\n            log_event("BOOT", "Model not found; running without ML model")',
        "Boot: carica oracle_brain_v2.pkl con soglia ottimale"
    ),
    # PATCH 4: Filtro soglia v2 nel radar_loop
    (
        '                    prob = oracle_brain.predict_proba(x_input)[0][1]\n                    market_in_window = is_market_window(market, minute_value, total_goals)\n                    if not market_in_window:',
        '                    prob = oracle_brain.predict_proba(x_input)[0][1]\n                    market_in_window = is_market_window(market, minute_value, total_goals)\n                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n                    if market_in_window and prob < oracle_v2_threshold:\n                        scan_debug["candidate_failed"] += 1\n                        clear_pending_signal_tracker(signal_key)\n                        log_event("V2_THRESHOLD_SKIP", f"fixture_id={fixture_id} market={market} prob={prob:.3f} threshold={oracle_v2_threshold}")\n                        continue\n                    if not market_in_window:',
        "Filtro soglia 0.71 nel radar_loop"
    ),
    # PATCH 5: is_market_window aggiornata
    (
        'def is_market_window(market: str, minute_value: int, total_goals: int) -> bool:\n    if market == MARKET_NEXT_GOAL:\n        return 1 <= minute_value <= 85\n    if not 1 <= minute_value <= 44:\n        return False\n    if market == MARKET_OVER05_HT:\n        return total_goals == 0\n    if market == MARKET_OVER15_HT:\n        return total_goals <= 1\n    return False',
        'def is_market_window(market: str, minute_value: int, total_goals: int) -> bool:\n    if market == MARKET_NEXT_GOAL:\n        return 1 <= minute_value <= 85\n    if market == MARKET_OVER15_HT:\n        # Disabilitato: WR storico 28.3% — market strutturalmente in perdita\n        return False\n    if not 1 <= minute_value <= 44:\n        return False\n    if market == MARKET_OVER05_HT:\n        # Limitato al minuto <= 20: WR crolla a 6-20% dopo\n        return total_goals == 0 and minute_value <= 20\n    return False',
        "is_market_window: disabilita OVER 1.5 HT, limita OVER 0.5 HT a minuto <= 20"
    ),
]

errors = []
for i, (old, new, desc) in enumerate(patches, 1):
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK - PATCH {i}: {desc}")
    else:
        errors.append(i)
        print(f"FAIL - PATCH {i}: testo non trovato — {desc}")

if errors:
    print(f"\nATTENZIONE: {len(errors)} patch fallite: {errors}")
    print("Il file originale NON è stato modificato.")
    print("Controlla che oracle_live.py sia la versione corretta.")
else:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nSUCCESSO: tutte le patch applicate a {TARGET}")
    print(f"Backup disponibile in: {BACKUP}")
    print("\nOra avvia il bot normalmente. Al boot vedrai:")
    print("  AI model v2 loaded.")
    print("  Soglia ottimale v2: 0.71")