"""Test di integrazione leggeri: importano oracle_live con env finti e bot mockato e
verificano i punti toccati (routing 2H, quota per tier/market, soglie di skip, follow-up)."""
import os
import sys
import types as pytypes

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def ol(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ol")
    for k, v in {
        "TOKEN_LIVE": "123:abc", "CHAT_ID": "1", "CHANNEL_ID": "@c", "API_KEY": "k",
        "VIP_CHANNEL_ID": "@v",
        "WEB_DATA_PATH": str(tmp / "web.json"), "MEMBERS_DB_PATH": str(tmp / "m.db"),
        "LOG_FILE_PATH": str(tmp / "log.txt"), "LIVE_TRAINING_DATA_PATH": str(tmp / "live.csv"),
        "MISSING_TEAMS_QUEUE_PATH": str(tmp / "q.json"), "MODEL_PATH": str(tmp / "brain.pkl"),
        "CSV_PATH": str(tmp / "Matches.csv"),
    }.items():
        os.environ[k] = v
    import telebot

    class FakeBot:
        def __init__(self, *a, **k):
            self.sent = []
        def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text, kw))
            return pytypes.SimpleNamespace(message_id=len(self.sent))
        def message_handler(self, *a, **k):
            return lambda f: f
        def callback_query_handler(self, *a, **k):
            return lambda f: f
        def __getattr__(self, name):
            if name.endswith("_handler"):
                return lambda *a, **k: (lambda f: f)
            return lambda *a, **k: None

    telebot.TeleBot = FakeBot
    import importlib
    import config
    importlib.reload(config)
    import trainer_v2
    importlib.reload(trainer_v2)
    import oracle_live
    importlib.reload(oracle_live)
    return oracle_live


def test_routed_markets_include_2h(ol):
    ol.stats["market_mode"] = "HT_NEXT"
    markets = ol.get_routed_active_markets()
    assert ol.MARKET_2H_MOMENTUM in markets
    assert ol.MARKET_NEXT_GOAL in markets


def test_market_window_and_router(ol):
    assert ol.is_market_window(ol.MARKET_2H_MOMENTUM, 47, 1)
    assert not ol.is_market_window(ol.MARKET_2H_MOMENTUM, 44, 1)
    assert not ol.is_market_window(ol.MARKET_2H_MOMENTUM, 50, 4)
    order = ol.prioritize_markets([ol.MARKET_NEXT_GOAL, ol.MARKET_2H_MOMENTUM], 48, 1)
    assert order[0] == ol.MARKET_2H_MOMENTUM


def test_min_quota_market_aware(ol):
    assert ol.get_min_quota_for_tier("APPROVED") == 1.90
    assert ol.get_min_quota_for_tier("GAMBLING", ol.MARKET_2H_MOMENTUM) == pytest.approx(1.40)


def test_minute_buckets_extended(ol):
    assert ol.get_minute_bucket(44) == "36-44"
    assert ol.get_minute_bucket(47) == "45-55"
    assert ol.get_minute_bucket(60) == "56-69"
    assert ol.get_minute_bucket(80) == "70+"


def test_skip_thresholds_follow_breakeven(ol):
    ol.ensure_daily_analytics()
    analytics = ol.stats["daily_analytics"]
    # 4W-6L = 40%: prima passava (soglia 40%), ora e' sotto 42.1% (breakeven 57% - 15)
    analytics["settled_by_market"] = {ol.MARKET_NEXT_GOAL: {"WIN": 4, "LOSS": 6}}
    skip, reason = ol.should_skip_by_live_performance(ol.MARKET_NEXT_GOAL, "L", "1-14")
    assert skip and "market" in reason
    # rolling 50: 16W-14L = 53% < 54.1%
    analytics["settled_by_market"] = {}
    now = ol.now_utc().isoformat()
    ol.stats["rolling_settled"] = [
        {"market": ol.MARKET_NEXT_GOAL, "league_name": "L", "minute_bucket": "1-14", "outcome": "WIN" if i < 16 else "LOSS", "time": now}
        for i in range(30)
    ]
    skip, reason = ol.should_skip_by_live_performance(ol.MARKET_NEXT_GOAL, "L2", "1-14")
    assert skip and "rolling50" in reason
    # stessi esiti ma vecchi di 20 giorni: fuori dalla finestra di 14 giorni, il market si riaccende
    old = (ol.now_utc() - ol.timedelta(days=20)).isoformat()
    for item in ol.stats["rolling_settled"]:
        item["time"] = old
    assert ol.should_skip_by_live_performance(ol.MARKET_NEXT_GOAL, "L2", "1-14")[0] is False
    # 20W-10L = 67%: passa
    ol.stats["rolling_settled"] = [
        {"market": ol.MARKET_NEXT_GOAL, "league_name": "L", "minute_bucket": "1-14", "outcome": "WIN" if i < 20 else "LOSS", "time": now}
        for i in range(30)
    ]
    assert ol.should_skip_by_live_performance(ol.MARKET_NEXT_GOAL, "L2", "1-14")[0] is False
    # lega/minuto usano la soglia generica (QUOTA 1.75 -> 42.1%) anche per OVER 0.5 HT
    analytics["settled_by_league"] = {"L3": {"WIN": 3, "LOSS": 3}}
    assert ol.should_skip_by_live_performance(ol.MARKET_OVER05_HT, "L3", "1-14")[0] is False
    analytics["settled_by_league"] = {"L3": {"WIN": 2, "LOSS": 4}}
    assert ol.should_skip_by_live_performance(ol.MARKET_OVER05_HT, "L3", "1-14")[0] is True
    analytics["settled_by_league"] = {}


def test_momentum_followup_sends_once_and_records(ol):
    ol.ensure_live_training_dataset()
    key = "999:NEXT GOAL 2H MOMENTUM"
    ol.append_live_training_row({"SignalKey": key, "Market": ol.MARKET_2H_MOMENTUM, "Status": "pending"})
    info = {
        "status": "pending", "market": ol.MARKET_2H_MOMENTUM, "tier": "CAUTION", "match_up": "A vs B",
        "open_minute": 47, "open_stats": {"shots_on_goal": 4, "total_shots": 9, "corners": 3},
        "delivery_targets": [
            {"chat_id": "1", "message_id": 5, "audience": "admin", "original_text": "x"},
            {"chat_id": "@c", "message_id": 6, "audience": "free", "original_text": "x"},
        ],
        "shadow_only": False, "momentum_followup_sent": False,
    }
    ol.bot.sent.clear()
    # un NEXT GOAL di primo tempo non riceve il follow-up 75'/80'
    ng_info = dict(info, market=ol.MARKET_NEXT_GOAL, open_minute=20)
    ol.maybe_send_momentum_followup("998:NEXT GOAL LIVE", ng_info, {"shots_on_goal": 9, "total_shots": 20, "corners": 6}, 40)
    assert not ol.bot.sent and not ng_info["momentum_followup_sent"]
    # troppo presto: nessun invio
    ol.maybe_send_momentum_followup(key, info, {"shots_on_goal": 6, "total_shots": 13, "corners": 4}, 51)
    assert not ol.bot.sent and not info["momentum_followup_sent"]
    # dopo 8': invio (solo admin/vip, non al canale free) + colonna aggiornata
    ol.maybe_send_momentum_followup(key, info, {"shots_on_goal": 6, "total_shots": 13, "corners": 4}, 56)
    assert len(ol.bot.sent) == 1 and "parziale" in ol.bot.sent[0][1] and ol.bot.sent[0][0] == "1"
    assert info["momentum_post"] == "RISING"
    import pandas as pd
    df = pd.read_csv(os.environ["LIVE_TRAINING_DATA_PATH"])
    row = df[df["SignalKey"] == key].iloc[0]
    assert row["MomentumPost"] == "RISING" and float(row["MomentumPostScore"]) > 0
    # secondo giro: niente doppio invio
    ol.maybe_send_momentum_followup(key, info, {"shots_on_goal": 8, "total_shots": 16, "corners": 5}, 66)
    assert len(ol.bot.sent) == 1


def test_training_columns_contain_momentum(ol):
    for col in ["ShotsOnGoalDelta10AtOpen", "MomentumScoreAtOpen", "MomentumAtOpen", "MomentumPost"]:
        assert col in ol.LIVE_TRAINING_COLUMNS
    assert set(ol.TRAINER_FEATURE_COLUMNS) >= {"ShotsOnGoalDelta10AtOpen", "MomentumScoreAtOpen"}
