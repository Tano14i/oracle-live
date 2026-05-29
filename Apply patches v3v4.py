"""
apply_patches_v3v4.py - UI migliorata + xG filtro Next Goal
Ripristina prima il backup poi esegui:

    copy oracle_live_backup_20260408_213544.py oracle_live.py
    python apply_patches_v3v4.py
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

if "xg_home" in src or "get_xg_rate" in src:
    print("ATTENZIONE: patch xG gia presente. Ripristina il backup prima.")
    exit(1)

shutil.copy2(TARGET, BACKUP)
print("Backup salvato: " + BACKUP)

real_patches = [
    (
        'def predict_titan_pressure_prob(',
        'def fetch_next_goal_live_odds(fixture_id: int, headers: dict):\n    cache_key = "ng_odds_" + str(fixture_id)\n    now_ts = time.time()\n    cached = fixture_stats_cache.get(cache_key)\n    if isinstance(cached, dict) and now_ts - float(cached.get("ts", 0.0)) < 60:\n        return cached.get("data")\n    try:\n        response = requests.get(\n            "https://v3.football.api-sports.io/odds/live",\n            headers=headers, params={"fixture": fixture_id, "bet": 5}, timeout=10,\n        )\n        if response.status_code != 200:\n            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}\n            return None\n        items = response.json().get("response", [])\n        if not items:\n            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}\n            return None\n        odds_values = []\n        for item in items:\n            for bm in item.get("bookmakers", []):\n                for bet in bm.get("bets", []):\n                    for v in bet.get("values", []):\n                        try:\n                            ov = float(v.get("odd", 0))\n                            if ov > 1.0:\n                                odds_values.append(ov)\n                        except Exception:\n                            pass\n        if not odds_values:\n            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}\n            return None\n        avg_odd = round(sum(odds_values) / len(odds_values), 2)\n        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": avg_odd}\n        return avg_odd\n    except Exception as exc:\n        log_event("LIVE_ODDS_ERROR", "fid=" + str(fixture_id) + " err=" + str(exc))\n        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}\n        return None\n\n\ndef get_min_quota_for_tier(tier: str) -> float:\n    return {"APPROVED": 1.90, "CAUTION": 1.70, "GAMBLING": 1.75, "LEARNING": 1.75}.get(tier, 1.75)\n\n\ndef predict_titan_pressure_prob(',
        'PATCH 1: fetch_next_goal_live_odds e get_min_quota_for_tier',
    ),
    (
        'def format_signal_message(\n    tier: str, country: str, match_up: str, dna: float, prob: float, minute_value: int, score: str, market: str, reason: str = ""\n) -> str:\n    edge_text = format_edge_text(reason, market)\n    edge_line = f"<b>EDGE:</b> {edge_text}\\n" if edge_text else ""\n    signal_label = "MODEL" if market == MARKET_NEXT_GOAL else "CONF"\n    profile_label = get_profile_label(tier)\n    if market == MARKET_NEXT_GOAL and tier == TIER_GAMBLING:\n        profile_label = "HIGH-RISK NEXT-GOAL VALUE"\n    return (\n        f"<b>{TIER_EMOJI.get(tier, \'\\U0001F916\')} {escape_html(tier)}</b>\\n"\n        f"{SEPARATOR}\\n"\n        f"<b>MARKET:</b> {escape_html(market)}\\n"\n        f"<b>COUNTRY:</b> {escape_html(country)}\\n"\n        f"<b>MATCH:</b> {escape_html(match_up)}\\n"\n        f"<b>DNA:</b> {dna} | <b>{signal_label}:</b> {prob * 100:.1f}%\\n"\n        f"<b>MINUTE:</b> {minute_value}\' | {escape_html(score)}\\n"\n        f"{edge_line}"\n        f"{SEPARATOR}\\n"\n        f"<b>PROFILE:</b> {escape_html(profile_label)}"\n    )',
        'def format_signal_message(\n    tier: str, country: str, match_up: str, dna: float, prob: float, minute_value: int, score: str, market: str, reason: str = "", live_odd=None\n) -> str:\n    tier_icons = {TIER_APPROVED: "\\U0001F947", TIER_CAUTION: "\\u26A0", TIER_GAMBLING: "\\U0001F3AF"}\n    emoji = tier_icons.get(tier, "\\U0001F916")\n    tier_profiles = {\n        TIER_APPROVED: "Segnale selezionato — alta precisione",\n        TIER_CAUTION: "Setup giocabile — rischio controllato",\n        TIER_GAMBLING: "Setup aggressivo — rischio elevato",\n    }\n    profile_label = tier_profiles.get(tier, "Segnale automatico")\n    if dna >= 3.5:\n        pace_label = "Partita ad altissimo scoring (media " + str(dna) + " gol)"\n    elif dna >= 2.8:\n        pace_label = "Partita ad alto scoring (media " + str(dna) + " gol)"\n    elif dna >= 2.2:\n        pace_label = "Partita a medio scoring (media " + str(dna) + " gol)"\n    else:\n        pace_label = "Partita a basso scoring (media " + str(dna) + " gol)"\n    import re as _re\n    parts = [p.strip() for p in str(reason or "").split("|") if p.strip()]\n    confirm_line = ""\n    if market == MARKET_NEXT_GOAL and parts:\n        m_cycles = _re.search(r"x(\\d+)", parts[0])\n        if m_cycles:\n            cycles = int(m_cycles.group(1))\n            if cycles >= 4:\n                confirm_line = "\\U0001F504 Confermato su " + str(cycles) + " rilevamenti\\n"\n            elif cycles >= 2:\n                confirm_line = "\\U0001F504 Rilevato su " + str(cycles) + " scansioni\\n"\n    min_quota = get_min_quota_for_tier(tier)\n    if live_odd is not None:\n        if live_odd >= min_quota:\n            quota_line = "\\U0001F4B0 Quota live: <b>" + str(live_odd) + "</b> \\u2705 (min " + str(min_quota) + ")\\n"\n        else:\n            quota_line = "\\U0001F4B0 Quota live: <b>" + str(live_odd) + "</b> \\u26A0 sotto soglia, attendi " + str(min_quota) + "+\\n"\n    else:\n        quota_line = "\\U0001F4B0 Entra solo sopra quota <b>" + str(min_quota) + "</b>\\n"\n    if market == MARKET_NEXT_GOAL:\n        mkt_header = emoji + " <b>NEXT GOAL</b> — <b>" + escape_html(tier) + "</b>"\n    else:\n        mkt_header = emoji + " <b>" + escape_html(market) + "</b> — <b>" + escape_html(tier) + "</b>"\n    min_str = str(minute_value) + "\' | " + escape_html(score)\n    return (\n        mkt_header + "\\n"\n        + SEPARATOR + "\\n"\n        + "\\U0001F30D " + escape_html(country) + " — " + escape_html(match_up) + "\\n"\n        + "\\u23F1 " + min_str + "\\n\\n"\n        + "\\U0001F525 " + escape_html(pace_label) + "\\n"\n        + confirm_line + quota_line\n        + SEPARATOR + "\\n"\n        + "\\U0001F4CC " + escape_html(profile_label)\n    )',
        'PATCH 2: Nuovo formato format_signal_message',
    ),
    (
        '                        full_msg = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason)',
        '                        live_odd = None\n                        if market == MARKET_NEXT_GOAL:\n                            live_odd = fetch_next_goal_live_odds(fixture_id, headers)\n                        full_msg = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)',
        'PATCH 3: Recupera quota live nel radar_loop',
    ),
    (
        'def format_premium_signal_message(\n    tier: str,\n    country: str,\n    league_name: str,\n    match_up: str,\n    dna: float,\n    prob: float,\n    minute_value: int,\n    score: str,\n    market: str,\n    reason: str = "",\n) -> str:\n    base_message = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason)',
        'def format_premium_signal_message(\n    tier: str,\n    country: str,\n    league_name: str,\n    match_up: str,\n    dna: float,\n    prob: float,\n    minute_value: int,\n    score: str,\n    market: str,\n    reason: str = "",\n    live_odd=None,\n) -> str:\n    base_message = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)',
        'PATCH 4: live_odd in format_premium_signal_message',
    ),
    (
        '                        if is_private_premium:\n                            private_premium_msg = format_premium_signal_message(\n                                tier,\n                                country,\n                                league_name,\n                                match_up,\n                                dna,\n                                prob,\n                                minute_value,\n                                score,\n                                market,\n                                reason,\n                            )',
        '                        if is_private_premium:\n                            private_premium_msg = format_premium_signal_message(\n                                tier,\n                                country,\n                                league_name,\n                                match_up,\n                                dna,\n                                prob,\n                                minute_value,\n                                score,\n                                market,\n                                reason,\n                                live_odd=live_odd,\n                            )',
        'PATCH 5: Passa live_odd a format_premium_signal_message',
    ),
    (
        '            "dangerous_attacks": 0.0,\n            "possession_diff": 0.0,\n        }',
        '            "dangerous_attacks": 0.0,\n            "possession_diff": 0.0,\n            "xg_home": 0.0,\n            "xg_away": 0.0,\n            "shots_insidebox": 0.0,\n            "goalkeeper_saves": 0.0,\n        }',
        'PATCH 6: Campi xG in totals',
    ),
    (
        '                elif stat_key == "dangerous attacks":\n                    totals["dangerous_attacks"] += stat_value\n                elif stat_key == "ball possession":\n                    team_possession = stat_value',
        '                elif stat_key == "dangerous attacks":\n                    totals["dangerous_attacks"] += stat_value\n                elif stat_key == "expected goals":\n                    if team_index == 0:\n                        totals["xg_home"] = stat_value\n                    else:\n                        totals["xg_away"] = stat_value\n                elif stat_key == "shots insidebox":\n                    totals["shots_insidebox"] += stat_value\n                elif stat_key == "goalkeeper saves":\n                    totals["goalkeeper_saves"] += stat_value\n                elif stat_key == "ball possession":\n                    team_possession = stat_value',
        'PATCH 7: Estrai xG, shots_insidebox, goalkeeper_saves',
    ),
    (
        'def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        'def get_xg_rate(stats_payload: dict, minute_value: int) -> float:\n    if not isinstance(stats_payload, dict) or minute_value <= 0:\n        return 0.0\n    xg_h = float(stats_payload.get("xg_home", 0.0) or 0.0)\n    xg_a = float(stats_payload.get("xg_away", 0.0) or 0.0)\n    return round((xg_h + xg_a) / max(1, minute_value), 4)\n\n\ndef should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:',
        'PATCH 8: Funzione get_xg_rate',
    ),
    (
        '                dna = combined_metrics["avg_total_goals"]\n                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))',
        '                dna = combined_metrics["avg_total_goals"]\n                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))\n                xg_threshold_bonus = 0.0',
        'PATCH 9: Inizializza xg_threshold_bonus',
    ),
    (
        '                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        '                                xg_rate = get_xg_rate(stats_payload, minute_value)\n                                if xg_rate > 0.0 and xg_rate < 0.010 and minute_value >= 15:\n                                    scan_debug["candidate_failed"] += 1\n                                    clear_pending_signal_tracker(signal_key)\n                                    log_event("NG_XG_SKIP", "fid=" + str(fixture_id) + " min=" + str(minute_value) + " xgr=" + str(xg_rate))\n                                    continue\n                                if xg_rate >= 0.030:\n                                    xg_threshold_bonus = -0.05\n                                    log_event("NG_XG_BONUS", "fid=" + str(fixture_id) + " xgr=" + str(xg_rate) + " b=-0.05")\n                                elif xg_rate >= 0.025:\n                                    xg_threshold_bonus = -0.03\n                                    log_event("NG_XG_BONUS", "fid=" + str(fixture_id) + " xgr=" + str(xg_rate) + " b=-0.03")\n                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)',
        'PATCH 10: Filtro xG e bonus soglia',
    ),
    (
        '                    # Filtro soglia v2: salta se prob sotto soglia ottimale\n                    if market_in_window and prob < oracle_v2_threshold:\n                        scan_debug["candidate_failed"] += 1\n                        clear_pending_signal_tracker(signal_key)\n                        log_event("V2_THRESHOLD_SKIP", f"fixture_id={fixture_id} market={market} prob={prob:.3f} threshold={oracle_v2_threshold}")\n                        continue',
        '                    # Filtro soglia v2 con eventuale bonus xG\n                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else 0.0)\n                    if market_in_window and prob < effective_threshold:\n                        scan_debug["candidate_failed"] += 1\n                        clear_pending_signal_tracker(signal_key)\n                        log_event("V2_THRESHOLD_SKIP", "fid=" + str(fixture_id) + " mkt=" + str(market) + " prob=" + str(round(prob,3)) + " thr=" + str(round(effective_threshold,2)))\n                        continue',
        'PATCH 11: Applica bonus xG alla soglia v2',
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
print("  - Messaggio segnale rinnovato con DNA in italiano e quota live")
print("  - xG estratto dalle statistiche live")
print("  - Partite xG_rate < 0.010/min dopo min 15 bloccate")
print("  - Partite xG_rate >= 0.030/min: soglia 0.71 -> 0.66")
print("  - Partite xG_rate >= 0.025/min: soglia 0.71 -> 0.68")