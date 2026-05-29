"""
apply_patches_v5.py - shots_insidebox + goalkeeper_saves per OVER 0.5 HT
Esegui nella cartella del progetto (dopo apply_patches_v3v4):
    python apply_patches_v5.py
"""
import os, shutil
from datetime import datetime

TARGET = "oracle_live.py"
BACKUP = "oracle_live_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".py"

if not os.path.exists(TARGET):
    print("ERRORE: " + TARGET + " non trovato.")
    exit(1)

with open(TARGET, "r", encoding="utf-8-sig") as f:
    src = f.read()

if "shots insidebox < 2 after min 10" in src:
    print("ATTENZIONE: patch v5 gia presente.")
    exit(1)

shutil.copy2(TARGET, BACKUP)
print("Backup salvato: " + BACKUP)

real_patches = [
    (
        '    if market == MARKET_OVER05_HT:\n        if minute_value >= 22 and shots_on_goal < 1:\n            return True, "no shots on target pressure"\n        if minute_value >= 24 and total_shots < 6:\n            return True, "low total shots pressure"\n        if minute_value >= 28 and total_shots < 8 and corners < 2:\n            return True, "weak attacking pressure"\n\n    if market == MARKET_OVER15_HT:',
        '    if market == MARKET_OVER05_HT:\n        shots_insidebox = float(stats_payload.get("shots_insidebox", 0.0) or 0.0)\n        goalkeeper_saves = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0)\n        if minute_value >= 10 and shots_insidebox < 2:\n            return True, "shots insidebox < 2 after min 10 — partita bloccata"\n        if minute_value >= 22 and shots_on_goal < 1:\n            return True, "no shots on target pressure"\n        if minute_value >= 24 and total_shots < 6:\n            return True, "low total shots pressure"\n        if minute_value >= 28 and total_shots < 8 and corners < 2:\n            return True, "weak attacking pressure"\n\n    if market == MARKET_OVER15_HT:',
        'PATCH 1: Filtro shots_insidebox per OVER 0.5 HT',
    ),
    (
        '                    # Filtro soglia v2 con eventuale bonus xG\n                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n                    if market_in_window and prob < effective_threshold:',
        '                    ht_threshold_bonus = 0.0\n                    if market == MARKET_OVER05_HT and isinstance(stats_payload, dict):\n                        sib = float(stats_payload.get("shots_insidebox", 0.0) or 0.0)\n                        gks = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0)\n                        xgr = get_xg_rate(stats_payload, minute_value)\n                        if sib >= 6 and gks >= 3:\n                            ht_threshold_bonus = -0.06\n                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " gks=" + str(gks) + " b=-0.06")\n                        elif sib >= 4 and gks >= 2:\n                            ht_threshold_bonus = -0.04\n                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " gks=" + str(gks) + " b=-0.04")\n                        elif sib >= 3 and xgr >= 0.025:\n                            ht_threshold_bonus = -0.02\n                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " xgr=" + str(xgr) + " b=-0.02")\n                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else ht_threshold_bonus)\n                    if market_in_window and prob < effective_threshold:',
        'PATCH 2: Bonus soglia OVER 0.5 HT con shots_insidebox + goalkeeper_saves',
    ),
]

errors = []
for i, (old, new, desc) in enumerate(real_patches, 1):
    if old in src:
        src = src.replace(old, new, 1)
        print("OK - " + desc)
    else:
        errors.append(i)
        print("FAIL - " + desc)

if errors:
    print("\nATTENZIONE: patch " + str(errors) + " fallite. File NON modificato.")
    exit(1)

try:
    compile(src, TARGET, "exec")
    print("\nVerifica sintassi: OK")
except SyntaxError as e:
    print("\nERRORE SINTASSI: " + str(e))
    print("File NON salvato.")
    exit(1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(src)

print("\nSUCCESSO: tutte le patch applicate.")
print("Backup: " + BACKUP)
print("\nCosa cambia:")
print("  OVER 0.5 HT — filtro shots_insidebox:")
print("    Bloccato se shots_insidebox < 2 dopo il minuto 10")
print("  OVER 0.5 HT — bonus soglia pressione:")
print("    -0.06 se shots_insidebox>=6 e goalkeeper_saves>=3")
print("    -0.04 se shots_insidebox>=4 e goalkeeper_saves>=2")
print("    -0.02 se shots_insidebox>=3 e xG rate alto")
print("  Nel log: HT_PRESSURE_BONUS")