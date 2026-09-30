"""Simula un giro di radar_loop con API mockate per verificare il flusso 2H end-to-end."""
import os
import sys
import threading

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_oracle_live_integration import ol  # noqa: F401,E402  (fixture condivisa)


class FakeModel:
    def predict_proba(self, X):
        return [[0.3, 0.7]]


def _run_one_scan(ol, minute, score, sog, odd, monkeypatch):
    goals_h, goals_a = [int(x) for x in score.split("-")]
    fixture = {
        "fixture": {"id": 4242, "status": {"elapsed": minute, "short": "2H"}},
        "teams": {"home": {"name": "Alpha"}, "away": {"name": "Beta"}},
        "league": {"country": "Italy", "name": "Serie A"},
        "goals": {"home": goals_h, "away": goals_a},
    }

    class Resp:
        status_code = 200
        def json(self):
            return {"response": [fixture]}

    calls = {"n": 0}
    def fake_get(url, **kw):
        calls["n"] += 1
        return Resp()

    monkeypatch.setattr(ol.requests, "get", fake_get)
    monkeypatch.setattr(ol, "sync_vip_memberships", lambda *a, **k: None)
    monkeypatch.setattr(ol, "get_league_filter_reason", lambda c, l: None)
    monkeypatch.setattr(ol, "trova_squadra", lambda name, c, l: name)
    metrics = {"team": "x", "metrics_ok": True, "reason": "ok", "matches": 12, "avg_total_goals": 2.9, "avg_ht_goals": 1.2}
    monkeypatch.setattr(ol, "get_team_metrics", lambda t: dict(metrics))
    monkeypatch.setattr(ol, "combine_team_metrics", lambda h, a: {
        "metrics_ok": True, "matches": 12, "avg_total_goals": 2.9, "avg_ht_goals": 1.2,
        "home_avg_total_goals": 2.9, "away_avg_total_goals": 2.9, "home_avg_ht_goals": 1.2, "away_avg_ht_goals": 1.2,
    })
    monkeypatch.setattr(ol, "fetch_fixture_stats", lambda fid, h: {
        "shots_on_goal": sog, "total_shots": sog * 2, "corners": 3, "red_cards": 0,
        "dangerous_attacks": 40, "possession_diff": 0, "xg_home": 0.8, "xg_away": 0.6,
        "shots_insidebox": 5, "goalkeeper_saves": 3,
    })
    monkeypatch.setattr(ol, "fetch_next_goal_live_odds", lambda fid, h, tg=0: odd)
    monkeypatch.setattr(ol, "settle_missing_live_signals", lambda *a, **k: None)
    monkeypatch.setattr(ol, "salva_dati_web", lambda *a, **k: None)
    monkeypatch.setattr(ol, "maybe_trigger_auto_retrain", lambda *a, **k: None)
    monkeypatch.setattr(ol, "predict_titan_pressure_prob", lambda *a, **k: None)
    monkeypatch.setattr(ol, "evaluate_titan_soft_layer", lambda *a, **k: {"score": 0, "promote": False, "label": ""})
    ol.oracle_brain = FakeModel()
    ol.stats["market_mode"] = "MOMENTUM_2H"

    # un solo giro: sleep interrompe il loop
    def stop_sleep(_):
        ol.running = False
    monkeypatch.setattr(ol.time, "sleep", stop_sleep)
    ol.running = True
    ol.shutdown_requested = False
    ol.radar_loop()


def test_2h_flow_quota_gate_then_publish(ol, monkeypatch):
    ol.ensure_live_training_dataset()
    ol.stats["monitor_risultati"] = {}
    ol.stats["segnali_inviati"] = []
    ol.bot.sent.clear()
    key = ol.get_signal_key(4242, ol.MARKET_2H_MOMENTUM)

    # 1) 47', 1-1, 5 tiri in porta, quota 1.25 < 1.40 -> shadow (nessun messaggio)
    _run_one_scan(ol, 47, "1-1", 5, 1.25, monkeypatch)
    info = ol.stats["monitor_risultati"][key]
    assert info["shadow_only"] is True and info["tier"] == ol.TIER_LEARNING
    assert not ol.bot.sent
    df = pd.read_csv(os.environ["LIVE_TRAINING_DATA_PATH"])
    row = df[df["SignalKey"] == key].iloc[0]
    assert row["Market"] == ol.MARKET_2H_MOMENTUM and row["MinuteBucket"] == "45-55"
    assert "quota gate" in str(row["Reason"])

    # 2) stessa partita ma quota 1.50 -> pubblicato in canale
    ol.stats["monitor_risultati"] = {}
    ol.stats["segnali_inviati"] = []
    _run_one_scan(ol, 48, "1-1", 5, 1.50, monkeypatch)
    info = ol.stats["monitor_risultati"][key]
    assert info["shadow_only"] is False
    assert info["tier"] in {ol.TIER_CAUTION, ol.TIER_GAMBLING}
    assert info["open_minute"] == 48 and info["open_stats"]["shots_on_goal"] == 5
    assert any("NEXT GOAL 2H" in s[1] for s in ol.bot.sent)

    # 2b) stessa scansione ripetuta: il segnale pendente non viene riaperto (niente righe duplicate)
    open_minute_before = info["open_minute"]
    _run_one_scan(ol, 49, "1-1", 6, 1.50, monkeypatch)
    df = pd.read_csv(os.environ["LIVE_TRAINING_DATA_PATH"])
    assert int((df["SignalKey"] == key).sum()) == 2  # una riga dal caso 1, una dal caso 2
    assert ol.stats["monitor_risultati"][key]["open_minute"] == open_minute_before

    # 3) 0-0 all'intervallo con quota buona -> comunque shadow
    ol.stats["monitor_risultati"] = {}
    ol.stats["segnali_inviati"] = []
    ol.bot.sent.clear()
    _run_one_scan(ol, 47, "0-0", 6, 1.60, monkeypatch)
    info = ol.stats["monitor_risultati"][key]
    assert info["shadow_only"] is True and not ol.bot.sent

    # 4) 47' con 3 tiri in porta -> nessun segnale, neanche shadow
    ol.stats["monitor_risultati"] = {}
    ol.stats["segnali_inviati"] = []
    _run_one_scan(ol, 47, "1-0", 3, 1.60, monkeypatch)
    assert key not in ol.stats["monitor_risultati"]

    # 5) segnale pendente + gol -> WIN con P/L sulla quota live
    ol.stats["monitor_risultati"] = {}
    ol.stats["segnali_inviati"] = []
    _run_one_scan(ol, 48, "1-1", 5, 1.50, monkeypatch)
    profit = {"v": 0.0}
    monkeypatch.setattr(ol, "salva_dati_web", lambda *a, **k: profit.__setitem__("v", k.get("nuovo_profitto", 0.0)))
    monkeypatch.setattr(ol, "edit_signal_message", lambda *a, **k: None)
    _run_one_scan(ol, 60, "2-1", 7, 1.50, monkeypatch)
    assert ol.stats["monitor_risultati"][key]["status"] == "settled"
    assert ol.stats["monitor_risultati"][key]["edited_outcome"] == "WIN"


def test_tier_thresholds_follow_calibration(ol):
    ol.model_is_calibrated = False
    assert ol.get_tier_prob_thresholds(ol.MARKET_NEXT_GOAL) == (0.82, 0.72, 0.64)
    ol.model_is_calibrated = True
    a, c, g = ol.get_tier_prob_thresholds(ol.MARKET_NEXT_GOAL)  # quota 1.75 -> breakeven 0.571
    assert a == pytest.approx(0.691, abs=1e-3) and c == pytest.approx(0.631, abs=1e-3) and g == pytest.approx(0.591, abs=1e-3)
    a, c, g = ol.get_tier_prob_thresholds(ol.MARKET_OVER05_HT)  # quota 1.30 -> breakeven 0.769
    assert g > 0.769 and a <= 0.95
    ol.model_is_calibrated = False
