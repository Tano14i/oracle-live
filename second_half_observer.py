"""L'osservatore del 47esimo minuto: segnale con statistiche, e misura.

Fa due cose insieme.

Per te: al minuto 46-48, su una partita 0-0 all'intervallo, manda un messaggio
con corner, attacchi, attacchi pericolosi, tiri in porta, tiri fuori porta,
cartellini e possesso. I campi che l'API non fornisce vengono dichiarati
"non disponibile" invece di stampati a zero - e' il difetto che ha tenuto
"dangerous attacks" a 0,00 per mesi facendolo sembrare misurato.

Per la misura: registra ogni snapshot in second_half_log.csv e poi l'esito, cosi'
la domanda di Ten - i tiri al 45' spostano il 74,2%? - diventa verificabile sui
tuoi dati invece che sulla sua impressione o sulla mia. Oggi non e' verificabile:
il bot nel secondo tempo non valuta nulla, quindi non ha un solo dato dopo il 45'.

Perche' e' un modulo separato e non un market nel radar loop.

Il tasso base misurato su 164.590 partite 0-0 all'intervallo e' 74,2%, cioe' un
pareggio a quota 1,348; su "gol nel secondo tempo" il book paga 1,08-1,15, che
vuol dire perdere il 18% per scommessa. Pubblicare questo market sui canali
free e VIP a quelle quote sarebbe spedire una perdita misurata a chi paga.
Quindi l'osservatore manda solo al canale admin, registra la quota live quando
c'e', e la decisione di pubblicarlo resta tua - informata dai dati che questo
stesso modulo raccoglie.
"""
import csv
import os
import threading
import time
from typing import Optional

import requests

from config import API_KEY, CHAT_ID
from second_half import (LINE_BREAK, MIN_QUOTA, capture_fields, format_stats_block,
                         missing_fields, second_half_gate)

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "second_half_log.csv")
COLUMNS = [
    "ObservedAtUTC", "FixtureId", "LeagueName", "Country", "MatchUp", "Minute",
    "Corners", "Attacks", "DangerousAttacks", "ShotsOnGoal", "ShotsOffGoal",
    "YellowCards", "RedCards", "PossessionHome", "PossessionAway",
    "LiveOdd", "MissingFields", "Outcome", "CloseScore", "SettledTimeUTC",
]

# Campi grezzi -> colonne del registro. Quelli assenti restano vuoti, non zero.
FIELD_COLUMNS = [
    ("Corners", ("corner kicks",)),
    ("Attacks", ("attacks",)),
    ("DangerousAttacks", ("dangerous attacks",)),
    ("ShotsOnGoal", ("shots on goal",)),
    ("ShotsOffGoal", ("shots off goal",)),
    ("YellowCards", ("yellow cards",)),
    ("RedCards", ("red cards",)),
]

SCAN_SECONDS = 40
_lock = threading.Lock()
_seen = {}          # fixture_id -> riga in attesa di esito


def ensure_log() -> None:
    if os.path.exists(LOG_PATH):
        return
    with _lock:
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=COLUMNS).writeheader()


def append_row(row: dict) -> None:
    ensure_log()
    with _lock:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=COLUMNS).writerow(
                {k: row.get(k, "") for k in COLUMNS})


def total_from(fields: dict, names: tuple) -> Optional[float]:
    trovati = [fields[n] for n in names if fields.get(n) is not None]
    return float(sum(trovati)) if trovati else None


def build_row(fixture: dict, capture: dict, live_odd: Optional[float], now_iso: str) -> dict:
    totals = capture.get("totals", {})
    row = {
        "ObservedAtUTC": now_iso,
        "FixtureId": fixture["fixture"]["id"],
        "LeagueName": fixture["league"]["name"],
        "Country": fixture["league"]["country"],
        "MatchUp": f'{fixture["teams"]["home"]["name"]} vs {fixture["teams"]["away"]["name"]}',
        "Minute": fixture["fixture"]["status"].get("elapsed"),
        "PossessionHome": capture.get("home", {}).get("ball possession", ""),
        "PossessionAway": capture.get("away", {}).get("ball possession", ""),
        "LiveOdd": "" if live_odd is None else live_odd,
        "MissingFields": "|".join(missing_fields(capture)),
    }
    for colonna, names in FIELD_COLUMNS:
        valore = total_from(totals, names)
        row[colonna] = "" if valore is None else valore
    return row


def format_message(row: dict, capture: dict) -> str:
    """Il messaggio per il canale admin."""
    quota = row.get("LiveOdd")
    if quota in (None, ""):
        riga_quota = "QUOTA LIVE: non disponibile"
    else:
        giudizio = "sopra il pareggio" if float(quota) >= MIN_QUOTA else "SOTTO il pareggio"
        riga_quota = f"QUOTA LIVE: {float(quota):.2f} ({giudizio} di {MIN_QUOTA:.2f})"
    parti = [
        "SEGNALE 47' - GOL NEL SECONDO TEMPO",
        "-" * 28,
        f"MATCH: {row['MatchUp']}",
        f"{row['Country']} - {row['LeagueName']}",
        f"MINUTO: {row['Minute']}' | 0-0 all'intervallo",
        "-" * 28,
        format_stats_block(capture),
        "-" * 28,
        riga_quota,
        f"TASSO BASE: 74,2% su 164.590 partite 0-0 all'intervallo",
        f"PAREGGIO RICHIESTO: quota {1 / 0.742:.3f}",
        "-" * 28,
        "Solo osservazione: non pubblicato su free/VIP.",
    ]
    return LINE_BREAK.join(parti)


def observe_once(headers: dict, send, fetch_odd=None) -> int:
    """Un giro: cerca le partite nella finestra, manda e registra. Torna quante."""
    try:
        live = requests.get("https://v3.football.api-sports.io/fixtures",
                            headers=headers, params={"live": "all"}, timeout=20)
        if live.status_code != 200:
            return 0
        fixtures = live.json().get("response", [])
    except Exception:
        return 0

    from datetime import datetime, timezone
    aperti = 0
    for fixture in fixtures:
        fid = fixture["fixture"]["id"]
        stato = fixture["fixture"]["status"]
        goals = fixture.get("goals") or {}
        total_goals = (goals.get("home") or 0) + (goals.get("away") or 0)
        ok, _ = second_half_gate(stato.get("elapsed"), total_goals, stato.get("short", ""))
        if not ok or fid in _seen:
            continue
        try:
            stats = requests.get("https://v3.football.api-sports.io/fixtures/statistics",
                                 headers=headers, params={"fixture": fid}, timeout=20)
            payload = stats.json().get("response", []) if stats.status_code == 200 else []
        except Exception:
            payload = []
        capture = capture_fields(payload)
        live_odd = None
        if fetch_odd is not None:
            try:
                live_odd = fetch_odd(fid)
            except Exception:
                live_odd = None
        now_iso = datetime.now(timezone.utc).isoformat()
        row = build_row(fixture, capture, live_odd, now_iso)
        _seen[fid] = row
        append_row(row)
        try:
            send(format_message(row, capture))
        except Exception:
            pass
        aperti += 1
    return aperti


def settle_once(headers: dict) -> int:
    """Chiude gli snapshot in attesa: WIN al primo gol, LOSS a fine partita."""
    from datetime import datetime, timezone
    chiusi = 0
    for fid in list(_seen):
        try:
            r = requests.get("https://v3.football.api-sports.io/fixtures",
                             headers=headers, params={"id": fid}, timeout=20)
            items = r.json().get("response", []) if r.status_code == 200 else []
        except Exception:
            continue
        if not items:
            continue
        fixture = items[0]
        goals = fixture.get("goals") or {}
        casa = goals.get("home") or 0
        fuori = goals.get("away") or 0
        stato = fixture["fixture"]["status"].get("short", "")
        esito = None
        if casa + fuori > 0:
            esito = "WIN"
        elif stato in {"FT", "AET", "PEN"}:
            esito = "LOSS"
        if esito is None:
            continue
        row = dict(_seen.pop(fid))
        row["Outcome"] = esito
        row["CloseScore"] = f"{casa}-{fuori}"
        row["SettledTimeUTC"] = datetime.now(timezone.utc).isoformat()
        append_row(row)
        chiusi += 1
    return chiusi


def observer_loop(send, fetch_odd=None, stop=None) -> None:
    """Il ciclo. `send` manda il messaggio, `stop()` dice quando smettere."""
    headers = {"x-apisports-key": API_KEY}
    ensure_log()
    while not (stop() if stop else False):
        try:
            observe_once(headers, send, fetch_odd)
            settle_once(headers)
        except Exception as exc:
            print(f"second_half_observer: {exc}")
        time.sleep(SCAN_SECONDS)


def default_sender(bot):
    """Manda solo al canale admin: il market non e' validato per free/VIP."""
    def send(text: str) -> None:
        if CHAT_ID:
            bot.send_message(CHAT_ID, text)
    return send
