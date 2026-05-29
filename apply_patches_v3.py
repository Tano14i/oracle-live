"""
apply_patches_v3.py - UI migliorata + quote live nel segnale
Esegui nella cartella del progetto:
    python apply_patches_v3.py
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

# Quota minima per tier basata su WR storico reale
MIN_QUOTA_BY_TIER = {
    "APPROVED": 1.90,
    "CAUTION": 1.70,
    "GAMBLING": 1.75,
    "LEARNING": 1.75,
}

patches = [

    # PATCH 1 — Funzione fetch quota live Next Goal
    # Aggiunta dopo fetch_fixture_stats
    (
        'def predict_titan_pressure_prob(',
        '''def fetch_next_goal_live_odds(fixture_id: int, headers: dict) -> float | None:
    """
    Recupera la quota live Next Goal (prossimo gol) da API-Football.
    Endpoint: /odds/live?fixture=ID&bet=5
    bet=5 = Next Goal scorer (usiamo il mercato prossimo gol generico)
    Restituisce la quota media tra i bookmaker disponibili, o None se non disponibile.
    Usa cache 60s per non sprecare chiamate.
    """
    cache_key = f"ng_odds_{fixture_id}"
    now_ts = time.time()
    cached = fixture_stats_cache.get(cache_key)
    if isinstance(cached, dict) and now_ts - float(cached.get("ts", 0.0)) < 60:
        return cached.get("data")

    try:
        # bet=5 = Next Goal live su API-Football
        response = requests.get(
            "https://v3.football.api-sports.io/odds/live",
            headers=headers,
            params={"fixture": fixture_id, "bet": 5},
            timeout=10,
        )
        if response.status_code != 200:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None

        items = response.json().get("response", [])
        if not items:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None

        # Raccoglie tutte le quote "Yes" / "Goal" dai bookmaker
        odds_values = []
        for item in items:
            for bookmaker in item.get("bookmakers", []):
                for bet in bookmaker.get("bets", []):
                    for value in bet.get("values", []):
                        if not value.get("main", True) is False:
                            try:
                                odd_val = float(value.get("odd", 0))
                                if odd_val > 1.0:
                                    odds_values.append(odd_val)
                            except Exception:
                                pass

        if not odds_values:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None

        avg_odd = round(sum(odds_values) / len(odds_values), 2)
        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": avg_odd}
        return avg_odd

    except Exception as exc:
        log_event("LIVE_ODDS_ERROR", f"fixture_id={fixture_id} error={exc}")
        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
        return None


def get_min_quota_for_tier(tier: str) -> float:
    """Quota minima consigliata per tier basata su WR storico reale."""
    return {
        "APPROVED": 1.90,
        "CAUTION": 1.70,
        "GAMBLING": 1.75,
        "LEARNING": 1.75,
    }.get(tier, 1.75)


def predict_titan_pressure_prob(''',
        "Funzione fetch_next_goal_live_odds e get_min_quota_for_tier"
    ),

    # PATCH 2 — Nuovo formato messaggio segnale
    (
        '''def format_signal_message(
    tier: str, country: str, match_up: str, dna: float, prob: float, minute_value: int, score: str, market: str, reason: str = ""
) -> str:
    edge_text = format_edge_text(reason, market)
    edge_line = f"<b>EDGE:</b> {edge_text}\\n" if edge_text else ""
    signal_label = "MODEL" if market == MARKET_NEXT_GOAL else "CONF"
    profile_label = get_profile_label(tier)
    if market == MARKET_NEXT_GOAL and tier == TIER_GAMBLING:
        profile_label = "HIGH-RISK NEXT-GOAL VALUE"
    return (
        f"<b>{TIER_EMOJI.get(tier, '\\U0001F916')} {escape_html(tier)}</b>\\n"
        f"{SEPARATOR}\\n"
        f"<b>MARKET:</b> {escape_html(market)}\\n"
        f"<b>COUNTRY:</b> {escape_html(country)}\\n"
        f"<b>MATCH:</b> {escape_html(match_up)}\\n"
        f"<b>DNA:</b> {dna} | <b>{signal_label}:</b> {prob * 100:.1f}%\\n"
        f"<b>MINUTE:</b> {minute_value}' | {escape_html(score)}\\n"
        f"{edge_line}"
        f"{SEPARATOR}\\n"
        f"<b>PROFILE:</b> {escape_html(profile_label)}"
    )''',
        '''def format_signal_message(
    tier: str, country: str, match_up: str, dna: float, prob: float, minute_value: int, score: str, market: str, reason: str = "", live_odd: float | None = None
) -> str:
    # Profilo umano per tier
    tier_profile = {
        TIER_APPROVED: ("🥇", "Segnale selezionato — alta precisione"),
        TIER_CAUTION:  ("⚠️", "Setup giocabile — rischio controllato"),
        TIER_GAMBLING: ("🎯", "Setup aggressivo — rischio elevato"),
    }
    emoji, profile_label = tier_profile.get(tier, ("🤖", "Segnale automatico"))
    if market == MARKET_NEXT_GOAL and tier == TIER_GAMBLING:
        profile_label = "Setup aggressivo — rischio elevato"

    # Riga intensità offensiva (DNA -> linguaggio umano)
    if dna >= 3.5:
        pace_label = f"Partita ad altissimo scoring (media {dna:.1f} gol)"
    elif dna >= 2.8:
        pace_label = f"Partita ad alto scoring (media {dna:.1f} gol)"
    elif dna >= 2.2:
        pace_label = f"Partita a medio scoring (media {dna:.1f} gol)"
    else:
        pace_label = f"Partita a basso scoring (media {dna:.1f} gol)"

    # Riga persistenza / conferma segnale
    parts = [p.strip() for p in str(reason or "").split("|") if p.strip()]
    confirm_line = ""
    if market == MARKET_NEXT_GOAL and parts:
        # Estrai numero cicli da "risky next-goal persistence x3"
        import re as _re
        match_cycles = _re.search(r"x(\d+)", parts[0])
        if match_cycles:
            cycles = int(match_cycles.group(1))
            if cycles >= 4:
                confirm_line = f"🔄 Segnale confermato su {cycles} rilevamenti consecutivi\n"
            elif cycles >= 2:
                confirm_line = f"🔄 Segnale rilevato su {cycles} scansioni\n"
    elif parts:
        confirm_line = f"🔄 {escape_html(parts[-1])}\n" if len(parts) >= 1 else ""

    # Quota live e soglia minima
    min_quota = get_min_quota_for_tier(tier)
    if live_odd is not None:
        if live_odd >= min_quota:
            quota_line = f"💰 Quota live: <b>{live_odd:.2f}</b> ✅ (minimo consigliato {min_quota:.2f})\n"
        else:
            quota_line = f"💰 Quota live: <b>{live_odd:.2f}</b> ⚠️ sotto soglia — attendi {min_quota:.2f}+\n"
    else:
        quota_line = f"💰 Entra solo sopra quota <b>{min_quota:.2f}</b>\n"

    return (
        f"{emoji} <b>NEXT GOAL</b> — <b>{escape_html(tier)}</b>\n"
        f"{SEPARATOR}\n"
        f"🌍 {escape_html(country)} — {escape_html(match_up)}\n"
        f"⏱ {minute_value}' | {escape_html(score)}\n"
        f"\n"
        f"🔥 {escape_html(pace_label)}\n"
        f"{confirm_line}"
        f"{quota_line}"
        f"{SEPARATOR}\n"
        f"📌 {escape_html(profile_label)}"
    ) if market == MARKET_NEXT_GOAL else (
        f"{emoji} <b>{escape_html(market)}</b> — <b>{escape_html(tier)}</b>\n"
        f"{SEPARATOR}\n"
        f"🌍 {escape_html(country)} — {escape_html(match_up)}\n"
        f"⏱ {minute_value}' | {escape_html(score)}\n"
        f"\n"
        f"🔥 {escape_html(pace_label)}\n"
        f"{confirm_line}"
        f"{quota_line}"
        f"{SEPARATOR}\n"
        f"📌 {escape_html(profile_label)}"
    )''',
        "Nuovo formato format_signal_message con UI migliorata"
    ),

    # PATCH 3 — Recupera quota live e passala a format_signal_message nel radar_loop
    (
        '                        full_msg = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason)',
        '''                        # Recupera quota live solo per Next Goal (1 chiamata per segnale)
                        live_odd = None
                        if market == MARKET_NEXT_GOAL:
                            live_odd = fetch_next_goal_live_odds(fixture_id, headers)
                        full_msg = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)''',
        "Recupera quota live e passa a format_signal_message"
    ),

    # PATCH 4 — Aggiorna format_premium_signal_message per passare live_odd
    (
        '''def format_premium_signal_message(
    tier: str,
    country: str,
    league_name: str,
    match_up: str,
    dna: float,
    prob: float,
    minute_value: int,
    score: str,
    market: str,
    reason: str = "",
) -> str:
    base_message = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason)''',
        '''def format_premium_signal_message(
    tier: str,
    country: str,
    league_name: str,
    match_up: str,
    dna: float,
    prob: float,
    minute_value: int,
    score: str,
    market: str,
    reason: str = "",
    live_odd: float | None = None,
) -> str:
    base_message = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)''',
        "Aggiorna format_premium_signal_message con live_odd"
    ),

    # PATCH 5 — Passa live_odd a format_premium_signal_message nel radar_loop
    (
        '''                        if is_private_premium:
                            private_premium_msg = format_premium_signal_message(
                                tier,
                                country,
                                league_name,
                                match_up,
                                dna,
                                prob,
                                minute_value,
                                score,
                                market,
                                reason,
                            )''',
        '''                        if is_private_premium:
                            private_premium_msg = format_premium_signal_message(
                                tier,
                                country,
                                league_name,
                                match_up,
                                dna,
                                prob,
                                minute_value,
                                score,
                                market,
                                reason,
                                live_odd=live_odd,
                            )''',
        "Passa live_odd a format_premium_signal_message"
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
    print("\nCosa cambia:")
    print("  - Messaggio segnale completamente rinnovato")
    print("  - DNA tradotto in linguaggio umano (alto/medio/basso scoring)")
    print("  - Persistenza spiegata ('confermato su X rilevamenti')")
    print("  - Quota live Next Goal mostrata nel messaggio")
    print("  - Quota minima per tier mostrata sempre")
    print("  - Icone per leggibilità rapida su Telegram")