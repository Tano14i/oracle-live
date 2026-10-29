"""
tennis_observer.py — Phase 1: data collector for set-1-comeback analysis.

Fonte: ESPN public scoreboard (ATP + WTA), no API key, no auth.
Scansiona ogni 60s. Quando il 1° set finisce → log su tennis_log.csv.
A partita chiusa → registra esito (HOME_WIN/AWAY_WIN/RETIRED) e
ComebackWin (1 se chi ha perso il 1° set vince il match).

Nessun segnale Telegram — solo raccolta dati.
"""

import csv
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

# ── paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LOG_CSV     = os.path.join(BASE_DIR, "tennis_log.csv")
PENDING     = os.path.join(BASE_DIR, "tennis_pending.json")
BOT_LOG     = os.path.join(BASE_DIR, "tennis_observer.log")

# ── endpoints ─────────────────────────────────────────────────────────────────
ESPN_URLS = [
    "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SCAN_INTERVAL = 60    # secondi tra una scansione e l'altra
STALE_HOURS   = 8     # dopo N ore senza esito → UNSETTLED

# ── CSV columns ───────────────────────────────────────────────────────────────
COLUMNS = [
    "CompId", "TournamentId", "Tour",
    "ObservedAtUTC",
    "Tournament", "Round", "Surface",
    "HomePlayer", "HomeRank",
    "AwayPlayer", "AwayRank",
    "Set1Home", "Set1Away", "Set1Loser",   # "home" o "away"
    "FinalScore",                           # es. "6-4 3-6 6-2"
    "Outcome",                              # HOME_WIN / AWAY_WIN / RETIRED / UNSETTLED
    "ComebackWin",                          # 1 se chi ha perso il set1 vince il match
]

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=BOT_LOG, level=logging.INFO,
    format="%(asctime)sZ | %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


# ── CSV helpers ───────────────────────────────────────────────────────────────
def ensure_csv():
    if not os.path.exists(LOG_CSV):
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()


def append_row(row: dict):
    ensure_csv()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore").writerow(row)


def update_row(comp_id: str, updates: dict):
    ensure_csv()
    rows = []
    with open(LOG_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["CompId"] == comp_id:
                r.update(updates)
            rows.append(r)
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ── pending state ─────────────────────────────────────────────────────────────
def load_pending() -> dict:
    if os.path.exists(PENDING):
        try:
            with open(PENDING, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_pending(state: dict):
    tmp = PENDING + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PENDING)


# ── ESPN helpers ──────────────────────────────────────────────────────────────
def fetch_all_competitions() -> list[dict]:
    """Scarica tutte le competizioni (live + recenti) da ATP e WTA."""
    out = []
    for url in ESPN_URLS:
        tour = "ATP" if "atp" in url else "WTA"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning(f"fetch {tour}: {exc}")
            continue
        for ev in data.get("events", []):
            tid      = str(ev.get("id", ""))
            tname    = ev.get("name", "")
            surface  = _surface_from_event(ev)
            for grp in ev.get("groupings", []):
                for comp in grp.get("competitions", []):
                    comp["_tour"]    = tour
                    comp["_tid"]     = tid
                    comp["_tname"]   = tname
                    comp["_surface"] = surface
                    out.append(comp)
    return out


def _surface_from_event(ev: dict) -> str:
    """Inferisce la superficie dal nome o da campi ESPN."""
    name = (ev.get("name") or "").lower()
    if any(w in name for w in ("roland garros", "monte-carlo", "roma", "clay", "madrid", "barcelona")):
        return "Clay"
    if any(w in name for w in ("wimbledon", "halle", "queen", "grass", "eastbourne", "s-hertogenbosch")):
        return "Grass"
    if any(w in name for w in ("indoor", "rotterdam", "sofia", "st. petersburg")):
        return "Indoor Hard"
    return "Hard"


# ── tennis logic ──────────────────────────────────────────────────────────────
def set_complete(h, a) -> bool:
    """True se i game h-a rappresentano un set finito."""
    try:
        h, a = int(h), int(a)
    except (TypeError, ValueError):
        return False
    m = max(h, a)
    return m >= 7 or (m >= 6 and abs(h - a) >= 2)


def linescores_of(competitor: dict) -> list[int]:
    return [int(ls.get("value", 0) or 0)
            for ls in competitor.get("linescores", [])
            if ls.get("value") is not None]


def player_name(competitor: dict) -> str:
    for key in ("athlete", "team"):
        obj = competitor.get(key) or {}
        for field in ("displayName", "shortDisplayName", "name", "abbreviation"):
            v = obj.get(field, "")
            if v:
                return v
    return "UNKNOWN"


def player_rank(competitor: dict) -> str:
    rank = competitor.get("rank") or competitor.get("seed") or ""
    return str(rank)


def final_score_str(home_ls: list, away_ls: list) -> str:
    sets = []
    for i in range(max(len(home_ls), len(away_ls))):
        h = home_ls[i] if i < len(home_ls) else "?"
        a = away_ls[i] if i < len(away_ls) else "?"
        sets.append(f"{h}-{a}")
    return " ".join(sets)


def round_name(comp: dict) -> str:
    try:
        return comp.get("round", {}).get("displayName", "") or ""
    except Exception:
        return ""


# ── observe / settle ──────────────────────────────────────────────────────────
FINISHED = {"post"}
RETIRED  = frozenset(["STATUS_RETIRED", "STATUS_WALKOVER", "STATUS_ABANDONED",
                       "STATUS_CANCELLED", "STATUS_FORFEIT"])


def observe_once(pending: dict) -> dict:
    competitions = fetch_all_competitions()

    live_count = sum(
        1 for c in competitions
        if c.get("status", {}).get("type", {}).get("state") == "in"
    )
    log.info(f"scan: {len(competitions)} competitions totali, {live_count} live")

    # Indice rapido per ID → dati aggiornati
    by_id = {str(c["id"]): c for c in competitions if c.get("id")}

    # ── settle match già aperti ──────────────────────────────────────────────
    for cid, voce in list(pending.items()):
        comp = by_id.get(cid)

        # Timeout staleness
        age_h = (now_ts() - voce.get("ts", now_ts())) / 3600
        if age_h > STALE_HOURS:
            log.info(f"settle UNSETTLED (stale {age_h:.1f}h): {voce.get('hp')} vs {voce.get('ap')}")
            pending.pop(cid)
            update_row(cid, {"Outcome": "UNSETTLED", "ComebackWin": ""})
            continue

        if comp is None:
            continue  # non ancora nell'indice, aspetta il prossimo scan

        state      = comp.get("status", {}).get("type", {}).get("state", "")
        status_name = comp.get("status", {}).get("type", {}).get("name", "")

        if state != "post":
            continue  # ancora in gioco

        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_ls = linescores_of(competitors[0])
        away_ls = linescores_of(competitors[1])
        final   = final_score_str(home_ls, away_ls)

        # Chi ha vinto più set vince il match
        home_sets = sum(1 for i in range(max(len(home_ls), len(away_ls)))
                        if (home_ls[i] if i < len(home_ls) else 0) >
                           (away_ls[i] if i < len(away_ls) else 0))
        away_sets = max(len(home_ls), len(away_ls)) - home_sets

        if status_name in RETIRED:
            outcome = "RETIRED"
        elif home_sets > away_sets:
            outcome = "HOME_WIN"
        elif away_sets > home_sets:
            outcome = "AWAY_WIN"
        else:
            outcome = "UNSETTLED"

        loser   = voce.get("loser")
        comeback = ""
        if outcome in ("HOME_WIN", "AWAY_WIN"):
            comeback = 1 if (
                (loser == "home" and outcome == "HOME_WIN") or
                (loser == "away" and outcome == "AWAY_WIN")
            ) else 0

        log.info(
            f"settle: {voce.get('hp')} vs {voce.get('ap')} "
            f"-> {outcome} comeback={comeback}  {final}"
        )
        pending.pop(cid)
        update_row(cid, {"FinalScore": final, "Outcome": outcome, "ComebackWin": comeback})

    # ── rilevamento fine 1° set ───────────────────────────────────────────────
    for comp in competitions:
        cid   = str(comp.get("id", ""))
        state = comp.get("status", {}).get("type", {}).get("state", "")

        if cid in pending:
            continue  # già aperto

        # Logga solo partite live; "pre" e "post" vengono ignorate per evitare
        # di raccogliere match storici del torneo e dati ESPN mal etichettati.
        if state != "in":
            continue

        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_ls = linescores_of(competitors[0])
        away_ls = linescores_of(competitors[1])

        # Set 1 completo se: entrambi hanno ≥ 2 set registrati
        # oppure entrambi hanno 1 set con punteggio valido
        if not home_ls or not away_ls:
            continue

        if len(home_ls) >= 2 and len(away_ls) >= 2:
            s1_done = True
        elif len(home_ls) == 1 and len(away_ls) == 1:
            s1_done = set_complete(home_ls[0], away_ls[0])
        else:
            s1_done = False

        if not s1_done:
            continue

        s1h = home_ls[0]
        s1a = away_ls[0]
        loser = "away" if s1h > s1a else "home"

        hp = player_name(competitors[0])
        ap = player_name(competitors[1])
        hr = player_rank(competitors[0])
        ar = player_rank(competitors[1])

        row = {
            "CompId":       cid,
            "TournamentId": comp.get("_tid", ""),
            "Tour":         comp.get("_tour", ""),
            "ObservedAtUTC": now_utc(),
            "Tournament":   comp.get("_tname", ""),
            "Round":        round_name(comp),
            "Surface":      comp.get("_surface", ""),
            "HomePlayer":   hp,
            "HomeRank":     hr,
            "AwayPlayer":   ap,
            "AwayRank":     ar,
            "Set1Home":     s1h,
            "Set1Away":     s1a,
            "Set1Loser":    loser,
            "FinalScore":   "",
            "Outcome":      "",
            "ComebackWin":  "",
        }
        append_row(row)
        pending[cid] = {
            "hp":    hp,
            "ap":    ap,
            "loser": loser,
            "ts":    now_ts(),
        }
        log.info(
            f"open: {hp} vs {ap}  set1={s1h}-{s1a}  loser={loser}  "
            f"[{comp.get('_tour')} {comp.get('_tname')} {round_name(comp)}]"
        )

    return pending


# ── main loop ─────────────────────────────────────────────────────────────────
def main():
    ensure_csv()
    pending = load_pending()
    log.info(f"tennis_observer avviato — {len(pending)} match pending")
    print(f"tennis_observer avviato | log -> {LOG_CSV} | ctrl+C per fermare")
    try:
        while True:
            pending = observe_once(pending)
            save_pending(pending)
            time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        save_pending(pending)
        log.info("tennis_observer fermato dall'utente")
        print("\nFermato.")


if __name__ == "__main__":
    main()
