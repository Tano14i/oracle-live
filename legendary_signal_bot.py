"""
legendary_signal_bot.py — bot PARALLELO e indipendente dal bot di produzione
oracle_live (nessuna scrittura sul suo stato/DB, nessun invio ai canali
free/VIP). Replica la logica ESATTA descritta nel video "Il Pronostico
Leggendario":

  1. Al minuto ~47 (appena iniziato il secondo tempo) controlla i tiri in
     porta totali (casa + trasferta) accumulati fino a quel momento.
  2. Se sono >= 4, invia un segnale: giocare il prossimo gol / Over.
  3. Quota minima 1,40 (dal video). Se la quota "Prossimo Gol" live e'
     sotto 1,40, il segnale viene comunque inviato ma etichettato "quota
     bassa" (il video suggerisce di aspettare quota migliore, non di
     saltare la partita).
  4. ~18 minuti dopo il trigger (circa minuto 65) ricontrolla l'andamento:
     se i tiri in porta sono saliti rispetto al trigger, la partita e'
     "movimentata" (nel video: giocare entro il 75'-80'); se sono rimasti
     uguali, e' "statica" (nel video: aspettare fino al 90').
  5. Le partite 0-0 al trigger vengono etichettate CAUTION — nel video
     stesso, 7 delle sue 8 partite perse partivano 0-0. Etichetta
     informativa nel messaggio, il segnale parte comunque.

Ogni messaggio include anche il dato del nostro test su 13.804 partite
reali (backtest/test_ht_signal.py nel repo match-predictor): 0-0
all'intervallo -> 76.0% un altro gol; gia' sbloccata -> 79.6% — la stessa
convenzione di trasparenza gia' usata nel bot di produzione (es. WR
storico mostrato per ogni market in markets.py).

Manda i segnali SOLO alla chat admin (CHAT_ID), mai ai canali free/VIP —
e' un bot di segnali, non piazza scommesse.

Uso:
    python legendary_signal_bot.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from config import API_KEY, CHAT_ID, TOKEN_LIVE

MIN_SHOTS_ON_TARGET = 4          # soglia tiri in porta combinati al trigger (dal video)
MIN_QUOTA = 1.40                 # quota minima dal video
TRIGGER_MINUTE_MIN = 46          # finestra minuto in cui scattare il controllo trigger
TRIGGER_MINUTE_MAX = 50
FOLLOWUP_DELAY_MINUTES = 18      # ~minuto 65, per il controllo "movimentata vs statica"
POLL_INTERVAL_SECONDS = 60
STATE_PATH = Path(__file__).resolve().parent / "legendary_signal_state.json"

HEADERS = {"x-apisports-key": API_KEY}
AF_BASE = "https://v3.football.api-sports.io"


# ─── STATO (persistente su file, per non duplicare segnali tra riavvii) ────
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ─── API-FOOTBALL (stessi endpoint/convenzioni di oracle_live/api_client.py) ─
def fetch_live_fixtures() -> list[dict]:
    try:
        r = requests.get(f"{AF_BASE}/fixtures", headers=HEADERS, params={"live": "all"}, timeout=20)
        if r.status_code != 200:
            return []
        return r.json().get("response", [])
    except Exception as exc:
        print(f"[errore] fetch_live_fixtures: {exc}")
        return []


def fetch_shots_on_target(fixture_id: int) -> float | None:
    try:
        r = requests.get(f"{AF_BASE}/fixtures/statistics", headers=HEADERS, params={"fixture": fixture_id}, timeout=20)
        if r.status_code != 200:
            return None
        items = r.json().get("response", [])
        if not items:
            return None
        total = 0.0
        for team_stats in items:
            for stat in team_stats.get("statistics", []):
                stat_type = str(stat.get("type", "")).strip().lower()
                if stat_type == "shots on goal":
                    val = stat.get("value")
                    try:
                        total += float(val) if val is not None else 0.0
                    except (TypeError, ValueError):
                        pass
        return total
    except Exception as exc:
        print(f"[errore] fetch_shots_on_target({fixture_id}): {exc}")
        return None


def fetch_next_goal_odds(fixture_id: int) -> float | None:
    """Quota live media per 'Next Goal' (bet id 5) — stesso market gia'
    usato da oracle_live/api_client.py per MARKET_NEXT_GOAL, il piu'
    vicino al 'prossimo gol/Over' descritto nel video."""
    try:
        r = requests.get(f"{AF_BASE}/odds/live", headers=HEADERS, params={"fixture": fixture_id, "bet": 5}, timeout=10)
        if r.status_code != 200:
            return None
        items = r.json().get("response", [])
        odds_values = []
        for item in items:
            for bm in item.get("bookmakers", []):
                for bet in bm.get("bets", []):
                    for v in bet.get("values", []):
                        try:
                            ov = float(v.get("odd", 0))
                            if ov > 1.0:
                                odds_values.append(ov)
                        except Exception:
                            pass
        if not odds_values:
            return None
        return round(sum(odds_values) / len(odds_values), 2)
    except Exception as exc:
        print(f"[errore] fetch_next_goal_odds({fixture_id}): {exc}")
        return None


# ─── TELEGRAM ────────────────────────────────────────────────────────────
def send_telegram_message(text: str) -> None:
    if not TOKEN_LIVE or not CHAT_ID:
        print("[avviso] TOKEN_LIVE o CHAT_ID non configurati — messaggio solo su console:\n" + text)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN_LIVE}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as exc:
        print(f"[errore] invio Telegram fallito: {exc}")


# ─── LOGICA DEL SEGNALE (replica esatta del video) ─────────────────────────
def format_trigger_message(fixture: dict, shots: float, odds: float | None, ht_zero: bool) -> str:
    teams = fixture["teams"]
    minute = fixture["fixture"]["status"].get("elapsed", 0)
    home, away = teams["home"]["name"], teams["away"]["name"]
    goals = fixture["goals"]
    score = f"{goals.get('home', 0)}-{goals.get('away', 0)}"
    league = fixture["league"]["name"]

    quota_line = f"Quota live 'Prossimo Gol': {odds}" if odds else "Quota live non disponibile (controlla a mano)"
    quota_flag = ""
    if odds is not None:
        quota_flag = " ✅ sopra la soglia 1.40" if odds >= MIN_QUOTA else " ⚠️ sotto 1.40 — il video suggerisce di aspettare una quota migliore, non di saltare"

    caution = ""
    if ht_zero:
        caution = (
            "\n⚠️ CAUTELA: partita 0-0 al trigger. Nel video stesso, 7 delle 8 partite perse partivano 0-0. "
            "Sul nostro test (13.804 partite reali): 0-0 all'intervallo -> altro gol nel 76.0% dei casi; "
            "gia' sbloccata -> 79.6% (differenza reale ma piccola, +3.6 punti)."
        )

    return (
        f"🚨 <b>SEGNALE LEGGENDARIO</b> (parallelo, solo segnalazione)\n\n"
        f"{home} vs {away} ({league})\n"
        f"Minuto {minute} | Risultato {score}\n"
        f"Tiri in porta combinati: {shots:.0f} (soglia {MIN_SHOTS_ON_TARGET})\n"
        f"{quota_line}{quota_flag}\n"
        f"{caution}\n\n"
        f"Prossimo controllo (~minuto {minute + FOLLOWUP_DELAY_MINUTES}): andamento tiri per capire se giocare entro il 75'-80' o aspettare il 90'."
    )


def format_followup_message(fixture: dict, shots_now: float, shots_at_trigger: float) -> str:
    teams = fixture["teams"]
    minute = fixture["fixture"]["status"].get("elapsed", 0)
    home, away = teams["home"]["name"], teams["away"]["name"]
    goals = fixture["goals"]
    score = f"{goals.get('home', 0)}-{goals.get('away', 0)}"

    if shots_now > shots_at_trigger:
        verdict = "📈 MOVIMENTATA — tiri in porta saliti da {:.0f} a {:.0f}. Nel video: giocare entro il 75'-80', non aspettare il 90'.".format(shots_at_trigger, shots_now)
    else:
        verdict = "➡️ STATICA — tiri in porta invariati ({:.0f}). Nel video: aspettare l'Over totale fino al 90'.".format(shots_now)

    return (
        f"🔁 <b>AGGIORNAMENTO SEGNALE LEGGENDARIO</b>\n\n"
        f"{home} vs {away}\n"
        f"Minuto {minute} | Risultato {score}\n"
        f"{verdict}"
    )


# ─── LOOP PRINCIPALE ─────────────────────────────────────────────────────
def run():
    if not API_KEY:
        print("[errore] API_KEY non configurata in .env — impossibile partire.")
        return

    state = load_state()
    state.setdefault("triggered", {})  # fixture_id (str) -> {shots_at_trigger, trigger_minute, followed_up}

    print("Bot segnali 'leggendario' avviato (parallelo, solo Telegram admin, nessuna scommessa automatica).")

    while True:
        try:
            live_fixtures = fetch_live_fixtures()
            for fixture in live_fixtures:
                fid = str(fixture["fixture"]["id"])
                minute = fixture["fixture"]["status"].get("elapsed") or 0
                goals = fixture.get("goals", {})

                # --- Trigger: minuto 46-50, non ancora segnalato ---
                if fid not in state["triggered"] and TRIGGER_MINUTE_MIN <= minute <= TRIGGER_MINUTE_MAX:
                    shots = fetch_shots_on_target(fixture["fixture"]["id"])
                    if shots is None:
                        continue
                    if shots >= MIN_SHOTS_ON_TARGET:
                        odds = fetch_next_goal_odds(fixture["fixture"]["id"])
                        ht_zero = (goals.get("home", 0) or 0) + (goals.get("away", 0) or 0) == 0
                        msg = format_trigger_message(fixture, shots, odds, ht_zero)
                        send_telegram_message(msg)
                        print(f"[segnale] {fixture['teams']['home']['name']} vs {fixture['teams']['away']['name']} — tiri {shots}")
                    state["triggered"][fid] = {
                        "shots_at_trigger": shots,
                        "trigger_minute": minute,
                        "followed_up": False,
                        "fired": shots >= MIN_SHOTS_ON_TARGET,
                    }
                    save_state(state)

                # --- Follow-up: ~18 minuti dopo il trigger, solo se il segnale era partito ---
                elif fid in state["triggered"]:
                    entry = state["triggered"][fid]
                    if entry.get("fired") and not entry.get("followed_up"):
                        if minute >= entry["trigger_minute"] + FOLLOWUP_DELAY_MINUTES:
                            shots_now = fetch_shots_on_target(fixture["fixture"]["id"])
                            if shots_now is not None:
                                msg = format_followup_message(fixture, shots_now, entry["shots_at_trigger"])
                                send_telegram_message(msg)
                                print(f"[follow-up] {fixture['teams']['home']['name']} vs {fixture['teams']['away']['name']}")
                            entry["followed_up"] = True
                            save_state(state)

            # Pulizia: rimuovi ogni fixture non piu' live, indipendentemente da
            # fired/followed_up. Una volta che la partita esce dall'elenco live
            # (finita, o sparita dal feed), non c'e' piu' nessun follow-up da
            # fare — tenerla in stato in attesa di un followed_up che per le
            # partite mai "fired" non arriva mai era la causa di una crescita
            # senza limite del file nel tempo.
            live_ids = {str(f["fixture"]["id"]) for f in live_fixtures}
            for fid in list(state["triggered"].keys()):
                if fid not in live_ids:
                    state["triggered"].pop(fid, None)
            save_state(state)

        except Exception as exc:
            print(f"[errore] ciclo principale: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
