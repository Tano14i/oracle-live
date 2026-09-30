import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from momentum import (  # noqa: E402
    MOMENTUM_FLAT,
    MOMENTUM_RISING,
    MOMENTUM_UNKNOWN,
    FixtureStatsHistory,
    breakeven_wr,
    classify_momentum,
    momentum_score,
    partial_recommendation,
    quota_gate,
    second_half_gate,
    second_half_tier,
    skip_thresholds_for_quota,
)


def _stats(sog=0, shots=0, corners=0, da=0):
    return {"shots_on_goal": sog, "total_shots": shots, "corners": corners, "dangerous_attacks": da}


def test_history_delta_over_lookback():
    h = FixtureStatsHistory()
    h.record(1, 35, _stats(2, 6, 2), now_ts=1000)
    h.record(1, 40, _stats(3, 8, 3), now_ts=1300)
    h.record(1, 45, _stats(5, 12, 4), now_ts=1600)
    d = h.delta(1, 45, lookback_minutes=10)
    assert d["shots_on_goal_delta"] == 3
    assert d["total_shots_delta"] == 6
    assert d["corners_delta"] == 2
    assert d["span_minutes"] == 10


def test_history_same_minute_overwrites_and_empty_is_zero():
    h = FixtureStatsHistory()
    assert h.delta(9, 10)["span_minutes"] == 0
    h.record(9, 10, _stats(1, 1, 0))
    h.record(9, 10, _stats(2, 2, 0))
    h.record(9, 20, _stats(4, 5, 1))
    d = h.delta(9, 20, 10)
    assert d["shots_on_goal_delta"] == 2 and d["points"] == 2


def test_history_prune_stale():
    h = FixtureStatsHistory(max_age_seconds=100)
    h.record(1, 10, _stats(), now_ts=0)
    h.record(2, 10, _stats(), now_ts=1000)
    h.record(2, 15, _stats(1, 1, 0), now_ts=1010)
    h.prune(now_ts=1050)
    assert h.delta(1, 20)["points"] == 0
    assert h.delta(2, 20)["points"] == 2


@pytest.mark.parametrize(
    "delta,expected",
    [
        ({"shots_on_goal_delta": 2, "total_shots_delta": 2, "corners_delta": 0, "span_minutes": 10}, MOMENTUM_RISING),
        ({"shots_on_goal_delta": 1, "total_shots_delta": 1, "corners_delta": 1, "span_minutes": 8}, MOMENTUM_RISING),
        ({"shots_on_goal_delta": 0, "total_shots_delta": 4, "corners_delta": 0, "span_minutes": 10}, MOMENTUM_RISING),
        ({"shots_on_goal_delta": 0, "total_shots_delta": 1, "corners_delta": 0, "span_minutes": 10}, MOMENTUM_FLAT),
        ({"shots_on_goal_delta": 5, "total_shots_delta": 9, "corners_delta": 3, "span_minutes": 2}, MOMENTUM_UNKNOWN),
        (None, MOMENTUM_UNKNOWN),
    ],
)
def test_classify_momentum(delta, expected):
    assert classify_momentum(delta, 10) == expected


def test_momentum_score_monotone():
    assert momentum_score({"shots_on_goal_delta": 0, "total_shots_delta": 0, "corners_delta": 0}) == 0.0
    assert momentum_score({"shots_on_goal_delta": 2, "total_shots_delta": 4, "corners_delta": 1}) == pytest.approx(3.9)


def test_second_half_gate_rules():
    # fuori finestra
    ok, _, shadow = second_half_gate(30, 1, 6, "1-0")
    assert not ok and shadow
    ok, _, shadow = second_half_gate(60, 1, 6, "1-0")
    assert not ok
    # pochi tiri in porta
    ok, reason, _ = second_half_gate(47, 1, 3, "1-0")
    assert not ok and "shots on goal" in reason
    # troppi gol
    ok, reason, _ = second_half_gate(47, 4, 9, "2-2")
    assert not ok and "total_goals" in reason
    # 0-0: in finestra ma solo shadow
    ok, reason, shadow = second_half_gate(47, 0, 5, "0-0")
    assert ok and shadow and "0-0" in reason
    # caso buono
    ok, reason, shadow = second_half_gate(48, 2, 4, "1-1")
    assert ok and not shadow


def test_second_half_tier():
    assert second_half_tier(MOMENTUM_RISING, "C", "G") == "C"
    assert second_half_tier(MOMENTUM_FLAT, "C", "G") == "G"
    assert second_half_tier(MOMENTUM_UNKNOWN, "C", "G") == "G"


def test_breakeven_and_skip_thresholds():
    assert breakeven_wr(1.10) == pytest.approx(0.909, abs=1e-3)
    assert breakeven_wr(1.75) == pytest.approx(0.571, abs=1e-3)
    assert breakeven_wr(0) == 1.0
    today, rolling = skip_thresholds_for_quota(1.75)
    assert today == pytest.approx(0.421, abs=1e-3)
    assert rolling == pytest.approx(0.541, abs=1e-3)
    # le nuove soglie sono piu' severe delle vecchie 40/35%
    assert today > 0.40 and rolling > 0.40


def test_quota_gate():
    assert quota_gate(None, 1.40, True)[0] is True
    assert quota_gate(1.20, 1.40, True)[0] is False
    assert quota_gate(1.45, 1.40, True)[0] is True
    assert quota_gate(1.20, 1.40, False)[0] is True
    assert quota_gate("abc", 1.40, True)[0] is True


def test_partial_recommendation_text():
    assert "parziale" in partial_recommendation(MOMENTUM_RISING, 57, 1.40)
    assert "over totale" in partial_recommendation(MOMENTUM_FLAT, 57, 1.40)
    assert "non misurabile" in partial_recommendation(MOMENTUM_UNKNOWN, 57, 1.40)


# ---------------------------------------------------------------------------
# trainer_v2: calibrazione e feature opzionali
# ---------------------------------------------------------------------------

def test_trainer_v2_optional_features_and_calibration(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_LIVE", "x")
    monkeypatch.setenv("CHAT_ID", "1")
    monkeypatch.setenv("API_KEY", "x")
    import importlib
    import trainer_v2
    importlib.reload(trainer_v2)

    rng = np.random.default_rng(0)
    n = 260
    df = pd.DataFrame({col: rng.random(n) for col in trainer_v2.FEATURE_COLUMNS if col not in trainer_v2.OPTIONAL_FEATURE_COLUMNS})
    # target dipende da una feature -> il modello deve imparare la direzione giusta
    df["Outcome"] = np.where(df["ShotsOnGoalAtOpen"] + 0.3 * rng.random(n) > 0.6, "WIN", "LOSS")
    df["Tier"] = "CAUTION"
    df["Market"] = "NEXT GOAL LIVE"
    df["MinuteBucket"] = "1-14"
    df["OpenTimeUTC"] = pd.date_range("2026-01-01", periods=n, freq="h").astype(str)

    clean, stats = trainer_v2.apply_training_filters(df)
    assert stats["final"] == n
    for col in trainer_v2.OPTIONAL_FEATURE_COLUMNS:
        assert col in clean.columns and (clean[col] == 0.0).all()

    # bucket 1-14 per OVER 0.5 HT non viene piu' scartato
    df2 = df.copy()
    df2["Market"] = "OVER 0.5 HT"
    clean2, _ = trainer_v2.apply_training_filters(df2)
    assert len(clean2) == n

    model = trainer_v2.build_calibrated_model(len(clean))
    X = clean[trainer_v2.FEATURE_COLUMNS]
    y = (clean["Outcome"] == "WIN").astype(int)
    model.fit(X, y)
    probs = model.predict_proba(X)[:, 1]
    assert model.method == "sigmoid"  # < ISOTONIC_MIN_ROWS
    assert probs[y == 1].mean() > probs[y == 0].mean()
    table = trainer_v2.reliability_table(probs, y)
    assert table and all(0 <= r["real_wr"] <= 1 for r in table)
    # il wrapper calibrato espone i nomi feature come il RF nudo (usato da oracle_live)
    assert list(getattr(model, "feature_names_in_", [])) == trainer_v2.FEATURE_COLUMNS


def test_train_oracle_v2_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_LIVE", "x")
    monkeypatch.setenv("CHAT_ID", "1")
    monkeypatch.setenv("API_KEY", "x")
    import importlib
    import trainer_v2
    importlib.reload(trainer_v2)

    rng = np.random.default_rng(1)
    n = 240
    df = pd.DataFrame({col: rng.random(n) for col in trainer_v2.FEATURE_COLUMNS})
    df["Outcome"] = np.where(df["DNA"] > 0.45, "WIN", "LOSS")
    df["Tier"] = "APPROVED"
    df["Market"] = "NEXT GOAL 2H MOMENTUM"
    df["MinuteBucket"] = "45-55"
    df["OpenTimeUTC"] = pd.date_range("2026-01-01", periods=n, freq="h").astype(str)
    data_file = tmp_path / "live.csv"
    df.to_csv(data_file, index=False)

    monkeypatch.setattr(trainer_v2, "DATA_FILE", str(data_file))
    monkeypatch.setattr(trainer_v2, "MODEL_NAME", str(tmp_path / "m_v2.pkl"))
    monkeypatch.setattr(trainer_v2, "CANDIDATE_MODEL_NAME", str(tmp_path / "m_v2_candidate.pkl"))

    result = trainer_v2.train_oracle_v2()
    assert result["status"] == "ok"
    assert result["mode"] == "production"
    assert os.path.exists(result["model_path"])
    assert 0.4 <= result["optimal_threshold"] <= 0.85
    assert result["validation"]["calibration_method"] in {"sigmoid", "isotonic"}
    assert result["validation"]["reliability"]
    assert (tmp_path / "m_v2_threshold.txt").exists()
