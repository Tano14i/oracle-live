"""momentum.py — logica "seconda meta' / momentum" (ispirata al segnale 47' di Mazza Live).

Tutto qui e' puro (nessuna rete, nessun bot) cosi' e' testabile con pytest.

Cosa aggiunge rispetto al radar esistente:
  1. Storico stats per fixture -> delta tiri/angoli negli ultimi N minuti ("momentum").
     Le feature del modello erano tutte fotografie all'apertura (...AtOpen): mancava
     la dinamica. Il delta e' calcolato PRIMA dell'apertura, quindi e' una feature lecita.
  2. Gate secondo tempo (46'-55'): almeno 4 tiri in porta totali, meno di 4 gol.
     Lo 0-0 all'intervallo NON viene pubblicato: sui dati a disposizione un gol nel
     secondo tempo arriva nell'86% dei casi partendo da 0-0 contro il 90.6% con
     qualsiasi altro punteggio; a quota ~1.10 (breakeven 90.9%) e' una giocata in perdita.
     Va in shadow (LEARNING) per raccogliere dati, non in canale.
  3. Follow-up post-segnale: dopo N minuti si rilegge il momentum. Se sale -> ha senso
     l'over parziale (entro 75'/80') a quota >= QUOTA_2H_MOMENTUM; se e' piatto -> solo
     over totale. E' la parte che Mazza fa "a occhio" e che qui viene misurata e loggata.
  4. Soglie di skip derivate dal breakeven della quota, non fisse a 40/35%.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

MOMENTUM_RISING = "RISING"
MOMENTUM_FLAT = "FLAT"
MOMENTUM_UNKNOWN = "UNKNOWN"

# Chiavi di fetch_fixture_stats di cui tracciamo il delta.
TRACKED_STAT_KEYS = ("shots_on_goal", "total_shots", "corners", "dangerous_attacks")

# Soglie "Mazza": >=4 tiri in porta totali al fischio del secondo tempo.
SECOND_HALF_MIN_SHOTS_ON_GOAL = 4.0
SECOND_HALF_WINDOW = (46, 55)
SECOND_HALF_MAX_TOTAL_GOALS = 3  # con 4+ gol in campo il WR storico NEXT GOAL e' 30%


class FixtureStatsHistory:
    """Ring buffer per fixture di (minuto, stats, timestamp). Serve a calcolare i delta."""

    def __init__(self, max_points: int = 40, max_age_seconds: int = 3 * 3600):
        self.max_points = max_points
        self.max_age_seconds = max_age_seconds
        self._data: Dict[str, Deque[tuple]] = {}

    def record(self, fixture_id, minute_value: int, stats_payload: Optional[dict], now_ts: Optional[float] = None) -> None:
        if not isinstance(stats_payload, dict):
            return
        now_ts = time.time() if now_ts is None else now_ts
        key = str(fixture_id)
        buf = self._data.setdefault(key, deque(maxlen=self.max_points))
        snapshot = {k: float(stats_payload.get(k, 0.0) or 0.0) for k in TRACKED_STAT_KEYS}
        # Un solo punto per minuto: se il minuto non avanza sovrascrivo l'ultimo.
        if buf and int(buf[-1][0]) == int(minute_value):
            buf[-1] = (int(minute_value), snapshot, now_ts)
        else:
            buf.append((int(minute_value), snapshot, now_ts))

    def delta(self, fixture_id, minute_value: int, lookback_minutes: int = 10) -> dict:
        """Variazione delle stats fra 'ora' e il punto piu' vicino a (minute - lookback).

        span_minutes < lookback/2 -> dati insufficienti (momentum UNKNOWN).
        """
        key = str(fixture_id)
        buf = self._data.get(key)
        empty = {f"{k}_delta": 0.0 for k in TRACKED_STAT_KEYS}
        empty.update({"span_minutes": 0, "points": 0})
        if not buf or len(buf) < 2:
            return empty
        latest_minute, latest, _ = buf[-1]
        target = int(minute_value) - int(lookback_minutes)
        base = None
        for m, snap, _ in buf:
            if m <= target:
                base = (m, snap)
            else:
                break
        if base is None:
            base = (buf[0][0], buf[0][1])
        base_minute, base_snap = base
        out = {f"{k}_delta": round(latest[k] - base_snap[k], 1) for k in TRACKED_STAT_KEYS}
        out["span_minutes"] = int(latest_minute - base_minute)
        out["points"] = len(buf)
        return out

    def prune(self, now_ts: Optional[float] = None) -> None:
        now_ts = time.time() if now_ts is None else now_ts
        stale = [k for k, buf in self._data.items() if buf and now_ts - float(buf[-1][2]) > self.max_age_seconds]
        for k in stale:
            self._data.pop(k, None)

    def forget(self, fixture_id) -> None:
        self._data.pop(str(fixture_id), None)


def classify_momentum(delta: dict, lookback_minutes: int = 10) -> str:
    """RISING se la partita 'si muove' (regola Mazza: i tiri salgono), FLAT se statica."""
    if not isinstance(delta, dict):
        return MOMENTUM_UNKNOWN
    span = int(delta.get("span_minutes", 0) or 0)
    if span < max(3, lookback_minutes // 2):
        return MOMENTUM_UNKNOWN
    sog = float(delta.get("shots_on_goal_delta", 0.0) or 0.0)
    shots = float(delta.get("total_shots_delta", 0.0) or 0.0)
    corners = float(delta.get("corners_delta", 0.0) or 0.0)
    if sog >= 2 or shots >= 4 or (sog >= 1 and corners >= 1) or (shots >= 3 and corners >= 2):
        return MOMENTUM_RISING
    return MOMENTUM_FLAT


def momentum_score(delta: dict) -> float:
    """Scalare per il modello: 0 = fermo, cresce con tiri in porta, tiri e angoli recenti."""
    if not isinstance(delta, dict):
        return 0.0
    sog = float(delta.get("shots_on_goal_delta", 0.0) or 0.0)
    shots = float(delta.get("total_shots_delta", 0.0) or 0.0)
    corners = float(delta.get("corners_delta", 0.0) or 0.0)
    return round(1.0 * sog + 0.4 * shots + 0.3 * corners, 2)


def second_half_gate(minute_value: int, total_goals: int, shots_on_goal_total: float, score: str) -> Tuple[bool, str, bool]:
    """Gate del market NEXT GOAL 2H MOMENTUM.

    Ritorna (in_window, reason, shadow_only).
      - fuori finestra / pochi tiri / troppi gol -> (False, motivo, True)
      - 0-0 all'intervallo -> (True, motivo, True): si raccoglie il dato, non si pubblica
      - altrimenti -> (True, motivo, False)
    """
    lo, hi = SECOND_HALF_WINDOW
    if not lo <= int(minute_value) <= hi:
        return False, f"minute {minute_value} outside 2H window {lo}-{hi}", True
    if int(total_goals) > SECOND_HALF_MAX_TOTAL_GOALS:
        return False, f"total_goals={total_goals} >= 4: WR storico 30%", True
    if float(shots_on_goal_total or 0.0) < SECOND_HALF_MIN_SHOTS_ON_GOAL:
        return False, f"shots on goal {shots_on_goal_total:.0f} < {SECOND_HALF_MIN_SHOTS_ON_GOAL:.0f}", True
    if str(score).strip() == "0-0":
        return True, "0-0 at HT: base rate 86% < breakeven at ~1.10, shadow only", True
    return True, f"2H momentum gate ok | SoG {shots_on_goal_total:.0f} | score {score}", False


def second_half_tier(momentum: str, tier_caution: str, tier_gambling: str) -> str:
    """Tier iniziale del market 2H: non dipende dal modello finche' non ha righe proprie."""
    if momentum == MOMENTUM_RISING:
        return tier_caution
    return tier_gambling


def breakeven_wr(quota: float) -> float:
    try:
        q = float(quota)
    except (TypeError, ValueError):
        return 1.0
    return 1.0 / q if q > 1.0 else 1.0


def skip_thresholds_for_quota(quota: float) -> Tuple[float, float]:
    """(soglia 'oggi' su campione piccolo, soglia rolling su campione grande).

    Prima il bot spegneva un market sotto il 40% e una lega sotto il 35%: con breakeven
    57.1% (quota 1.75) continuava a mandare segnali fra il 40% e il 57%, cioe' in perdita.
    Ora: oggi -> breakeven - 15 punti (tollerante al rumore di 8 esiti);
         rolling -> breakeven - 3 punti su almeno 30 esiti.
    """
    be = breakeven_wr(quota)
    today = max(0.30, round(be - 0.15, 3))
    rolling = max(0.35, round(be - 0.03, 3))
    return today, rolling


def partial_recommendation(momentum: str, minute_value: int, min_quota: float) -> str:
    """Testo del follow-up post-segnale (regola Mazza 75'/80' vs over totale)."""
    if momentum == MOMENTUM_RISING:
        return (
            f"Momentum in salita al {minute_value}': ha senso l'over parziale "
            f"(entro 75'/80') solo se il book paga >= {min_quota:.2f}."
        )
    if momentum == MOMENTUM_FLAT:
        return f"Partita statica al {minute_value}': evitare il parziale, solo over totale (fine partita)."
    return f"Momentum non misurabile al {minute_value}' (stats live insufficienti)."


def quota_gate(live_odd: Optional[float], min_quota: float, enforce: bool) -> Tuple[bool, str]:
    """(pubblicabile, motivo). Se la quota e' nota e sotto il minimo -> shadow.

    Quota ignota: non si puo' far rispettare la regola, si pubblica con l'avviso nel messaggio.
    """
    if not enforce:
        return True, "quota gate disabled"
    if live_odd is None:
        return True, "live odd unavailable"
    try:
        odd = float(live_odd)
    except (TypeError, ValueError):
        return True, "live odd unparsable"
    if odd < float(min_quota):
        return False, f"live odd {odd:.2f} < min {float(min_quota):.2f}"
    return True, f"live odd {odd:.2f} >= min {float(min_quota):.2f}"
