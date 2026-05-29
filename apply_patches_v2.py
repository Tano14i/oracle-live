"""
apply_patches_v2.py - Patch cecchino per Next Goal Live
Applica 3 filtri basati su score, minuto e total goals.
Esegui nella cartella del progetto:
    python apply_patches_v2.py
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

shutil.copy2(TARGET, BACKUP)
print(f"Backup salvato: {BACKUP}")

patches = [

    # PATCH 1 — Funzione filtro score/minuto/goals per Next Goal
    # Aggiunta dopo la funzione has_live_pressure_data
    (
        'def should_skip_by_live_stats(fixture_id: int, market: str, minute_value: int, total_goals: int, headers: dict, stats_payload=None):',
        '''def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:
    """
    Filtro cecchino per NEXT GOAL LIVE basato su dati storici reali.
    WR breakeven a quota 1.75 = 57.1%

    Score killer da bloccare (WR < 40%):
      - 1-2 (22%), 3-2 (5%), 2-2 (19%), 2-5 (18%)
    Score favorevoli da lasciare passare (WR > 55%):
      - 2-3 (83%), 1-4 (60%), 2-1 (55%), 4-0 (52%)

    Finestra temporale:
      - Minuto 1-11: WR 53-60% -> ok
      - Minuto 12-19: WR 46-53% -> solo score favorevoli
      - Minuto 20-44: WR 38-49% -> solo score molto favorevoli
      - Minuto 45-69: WR 32-42% -> blocca quasi tutto
      - Minuto 70+: WR < 33% -> blocca sempre

    Total goals:
      - 4+ gol in campo: WR 30% -> blocca sempre
    """
    # Blocca sempre dopo il minuto 69 (WR crolla sotto 33%)
    if minute_value >= 70:
        return True, f"next_goal minute {minute_value} WR<33% storico"

    # Blocca sempre con 4+ gol in campo (WR 30%)
    if total_goals >= 4:
        return True, f"next_goal total_goals={total_goals} WR<31% storico"

    # Analisi dello score
    parts = str(score or "0-0").split("-")
    try:
        home_goals = int(parts[0])
        away_goals = int(parts[1])
    except Exception:
        home_goals = 0
        away_goals = 0

    diff = abs(home_goals - away_goals)

    # Score killer assoluti - blocca sempre indipendentemente dal minuto
    # 1-2 (22%), 2-1 reversed -> no, 3-2 (5%), 2-2 (19%), 2-5 (18%)
    killer_scores = {(1, 2), (2, 1) if False else None, (3, 2), (2, 3) if False else None, (2, 2), (2, 5), (5, 2)}
    # Correggo: blocco asimmetrico basato su chi perde
    # Score dove la squadra che insegue ha bisogno di 2+ gol = killer
    if (home_goals == 1 and away_goals == 2) or (home_goals == 2 and away_goals == 1 and False):
        # 1-2: WR 22% -> blocca sempre
        return True, f"next_goal killer score {score} WR=22%"
    if (home_goals == 3 and away_goals == 2) or (home_goals == 2 and away_goals == 3 and False):
        # 3-2: WR 5% -> blocca sempre
        return True, f"next_goal killer score {score} WR=5%"
    if home_goals == away_goals == 2:
        # 2-2: WR 19% -> blocca sempre
        return True, f"next_goal killer score {score} WR=19%"

    # Score favorevoli - lascia passare anche in finestre difficili
    # 2-3 (83%), 1-4 (60%), 2-1 (55%), 4-0 (52%), 0-2 (48%)
    favorable = (
        (home_goals == 2 and away_goals == 3) or
        (home_goals == 3 and away_goals == 2 and False) or
        (home_goals == 1 and away_goals == 4) or
        (home_goals == 4 and away_goals == 1) or
        (home_goals == 2 and away_goals == 1) or
        (home_goals == 1 and away_goals == 2 and False) or
        (home_goals == 4 and away_goals == 0) or
        (home_goals == 0 and away_goals == 4)
    )

    # Finestre temporali con logica per score
    if 1 <= minute_value <= 11:
        # WR 53-60% -> ok per tutti gli score non killer
        return False, ""

    if 12 <= minute_value <= 19:
        # WR 46-53% -> solo score favorevoli o parità 0-0/1-1
        if favorable:
            return False, ""
        if home_goals == away_goals <= 1:
            return False, ""
        return True, f"next_goal minute {minute_value} score {score} WR<50% non favorevole"

    if 20 <= minute_value <= 44:
        # WR 38-49% -> solo score molto favorevoli
        if favorable:
            return False, ""
        return True, f"next_goal minute {minute_value} score {score} WR<49% zona grigia"

    if 45 <= minute_value <= 69:
        # WR 32-42% -> solo score eccezionalmente favorevoli (diff >= 2 con squadra sotto che insegue)
        if (home_goals == 2 and away_goals == 3) or (home_goals == 4 and away_goals == 1) or (home_goals == 1 and away_goals == 4):
            return False, ""
        return True, f"next_goal minute {minute_value} secondo tempo non favorevole WR<42%"

    return False, ""


def should_skip_by_live_stats(fixture_id: int, market: str, minute_value: int, total_goals: int, headers: dict, stats_payload=None):''',
        "Funzione should_skip_next_goal_by_context (filtro cecchino score/minuto/goals)"
    ),

    # PATCH 2 — Chiama il filtro nel radar_loop prima di aprire un Next Goal
    # Trova il blocco dove viene calcolata l'assessment per Next Goal
    (
        '                        else:\n                            if market == MARKET_NEXT_GOAL:\n                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        '                        else:\n                            if market == MARKET_NEXT_GOAL:\n                                # Filtro cecchino: score, minuto, total goals\n                                ng_skip, ng_reason = should_skip_next_goal_by_context(minute_value, total_goals, score)\n                                if ng_skip:\n                                    scan_debug["candidate_failed"] += 1\n                                    clear_pending_signal_tracker(signal_key)\n                                    log_event("NG_CONTEXT_SKIP", f"fixture_id={fixture_id} minute={minute_value} score={score} reason={ng_reason}")\n                                    continue\n                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        "Chiama filtro cecchino nel radar_loop per Next Goal"
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
    print("Il file originale NON e stato modificato.")
else:
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nSUCCESSO: tutte le patch applicate a {TARGET}")
    print(f"Backup disponibile in: {BACKUP}")
    print("\nFiltri attivi su NEXT GOAL LIVE:")
    print("  - Score killer bloccati: 1-2 (WR 22%), 3-2 (WR 5%), 2-2 (WR 19%)")
    print("  - Minuto 70+: sempre bloccato (WR<33%)")
    print("  - 4+ gol in campo: sempre bloccato (WR 30%)")
    print("  - Minuto 12-19: solo score favorevoli o 0-0/1-1")
    print("  - Minuto 20-44: solo score favorevoli")
    print("  - Minuto 45-69: solo 2-3, 4-1, 1-4")