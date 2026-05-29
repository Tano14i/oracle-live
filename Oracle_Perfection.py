import json
import math
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split

from config import LIVE_TRAINING_DATA_PATH
from trainer import FEATURE_COLUMNS


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(LIVE_TRAINING_DATA_PATH)
PACKAGE_PATH = BASE_DIR / "oracle_perfection_package.joblib"
REPORT_PATH = BASE_DIR / "oracle_perfection_report.json"
GATEKEEPER_PATH = BASE_DIR / "oracle_perfection_gatekeeper.json"

MIN_ROWS_GLOBAL = 120
MIN_ROWS_REGIME = 90
MIN_CLASS_ROWS = 12
WIN_LABEL = "WIN"
LOSS_LABEL = "LOSS"
ALLOWED_OUTCOMES = {WIN_LABEL, LOSS_LABEL}
DEFAULT_BLEND_WEIGHTS = {
    "win": 0.55,
    "fast": 0.25,
    "quality": 0.20,
}


@dataclass
class PreparedData:
    frame: pd.DataFrame
    feature_columns: list
    target_columns: list


def clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    return (numerator / denominator).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def minute_phase(minute_value: float) -> str:
    if minute_value <= 25:
        return "15_25"
    if minute_value <= 35:
        return "26_35"
    if minute_value <= 44:
        return "36_44"
    return "45_plus"


def infer_settlement_minutes(df: pd.DataFrame) -> pd.Series:
    if "OpenTimeUTC" not in df.columns or "SettledTimeUTC" not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    opened = pd.to_datetime(df["OpenTimeUTC"], errors="coerce", utc=True)
    settled = pd.to_datetime(df["SettledTimeUTC"], errors="coerce", utc=True)
    minutes = (settled - opened).dt.total_seconds().div(60.0)
    return minutes.where(minutes >= 0)


def build_targets(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working["target_win"] = (working["Outcome"] == WIN_LABEL).astype(int)
    settlement_minutes = infer_settlement_minutes(working)
    working["settlement_minutes"] = settlement_minutes.fillna(9999.0)
    working["target_fast_win"] = (
        (working["Outcome"] == WIN_LABEL) & (working["settlement_minutes"] <= 45.0)
    ).astype(int)
    working["target_quality"] = (
        (working["Outcome"] == WIN_LABEL)
        & (working["Prob"].between(0.58, 0.90))
        & (working["Minute"] >= 15)
        & (working["Minute"] <= 35)
    ).astype(int)
    return working


def build_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for column in FEATURE_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working["Prob"] = pd.to_numeric(working["Prob"], errors="coerce").fillna(0.0)

    working["Minute"] = working["Minute"].clip(lower=0)
    working["RemainingFirstHalf"] = np.maximum(0.0, 45.0 - working["Minute"])
    working["ShotIntensity"] = safe_div(working["TotalShotsAtOpen"], working["Minute"] + 1.0)
    working["ShotOnTargetRate"] = safe_div(working["ShotsOnGoalAtOpen"], working["TotalShotsAtOpen"] + 1.0)
    working["CornerIntensity"] = safe_div(working["CornersAtOpen"], working["Minute"] + 1.0)
    working["DisciplineDrag"] = working["RedCardsAtOpen"].clip(lower=0)
    working["GoalNeed"] = np.maximum(0.0, 2.0 - working["TotalGoalsAtOpen"])
    working["HTGap"] = (working["HomeAvgHTGoals"] - working["AwayAvgHTGoals"]).abs()
    working["FTGap"] = (working["HomeAvgTotalGoals"] - working["AwayAvgTotalGoals"]).abs()
    working["PaceBlend"] = (
        0.35 * working["AvgHTGoals"]
        + 0.35 * working["AvgTotalGoals"]
        + 0.15 * working["HomeAvgTotalGoals"]
        + 0.15 * working["AwayAvgTotalGoals"]
    )
    working["PressureComposite"] = (
        0.40 * working["TitanPressureScore"]
        + 0.25 * working["ShotsOnGoalAtOpen"]
        + 0.20 * working["CornersAtOpen"]
        + 0.15 * working["TotalShotsAtOpen"]
    )
    working["DNAxMinute"] = working["DNA"] * (working["Minute"] + 1.0)
    working["DNAxPace"] = working["DNA"] * working["PaceBlend"]
    working["PressurePerMinute"] = safe_div(working["PressureComposite"], working["Minute"] + 1.0)
    working["UrgencyScore"] = working["GoalNeed"] * (1.0 + safe_div(working["RemainingFirstHalf"], pd.Series(45.0, index=working.index)))
    working["DataRichness"] = working[FEATURE_COLUMNS].notna().mean(axis=1)
    working["MinutePhase"] = working["Minute"].apply(minute_phase)
    working["RegimeKey"] = working["Market"].fillna("UNKNOWN").astype(str) + "__" + working["MinutePhase"]
    return working


def prepare_training_frame() -> PreparedData:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Dataset not found: {DATA_FILE}")

    df = pd.read_csv(DATA_FILE)
    settled = df[df["Outcome"].isin(ALLOWED_OUTCOMES)].copy()
    missing = [column for column in FEATURE_COLUMNS if column not in settled.columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {', '.join(missing)}")

    settled = settled.loc[settled[FEATURE_COLUMNS].notna().all(axis=1)].copy()
    if len(settled) < MIN_ROWS_GLOBAL:
        raise ValueError(f"Need at least {MIN_ROWS_GLOBAL} full-feature settled rows, found {len(settled)}")

    settled = build_engineered_features(settled)
    settled = build_targets(settled)

    feature_columns = FEATURE_COLUMNS + [
        "RemainingFirstHalf",
        "ShotIntensity",
        "ShotOnTargetRate",
        "CornerIntensity",
        "DisciplineDrag",
        "GoalNeed",
        "HTGap",
        "FTGap",
        "PaceBlend",
        "PressureComposite",
        "DNAxMinute",
        "DNAxPace",
        "PressurePerMinute",
        "UrgencyScore",
        "DataRichness",
    ]
    target_columns = ["target_win", "target_fast_win", "target_quality"]
    return PreparedData(frame=settled, feature_columns=feature_columns, target_columns=target_columns)


def build_sample_weight(df: pd.DataFrame) -> np.ndarray:
    tier_boost = df["Tier"].map({"APPROVED": 1.15, "CAUTION": 1.10, "GAMBLING": 0.92, "LEARNING": 0.88}).fillna(1.0)
    quick_resolution_boost = np.where(df["settlement_minutes"] <= 45, 1.08, 1.0)
    data_richness_boost = 0.85 + 0.30 * df["DataRichness"]
    return (tier_boost * quick_resolution_boost * data_richness_boost).astype(float).to_numpy()


def fit_calibrated(estimator, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray):
    class_counts = y.value_counts()
    min_class = int(class_counts.min()) if not class_counts.empty else 0
    if min_class >= 3:
        model = CalibratedClassifierCV(estimator, method="sigmoid", cv=3)
        model.fit(X, y, sample_weight=sample_weight)
        return model
    estimator.fit(X, y, sample_weight=sample_weight)
    return estimator


def predict_prob(model, X: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    scores = model.decision_function(X)
    return 1.0 / (1.0 + np.exp(-scores))


def fit_ensemble_bundle(df: pd.DataFrame, feature_columns: list, target_column: str) -> dict:
    X = df[feature_columns]
    y = df[target_column].astype(int)
    if y.nunique() < 2:
        constant_prob = float(y.iloc[0]) if len(y) else 0.0
        return {
            "target": target_column,
            "feature_columns": feature_columns,
            "models": {},
            "constant_prob": constant_prob,
        }
    sample_weight = build_sample_weight(df)
    models = {
        "rf": fit_calibrated(
            RandomForestClassifier(
                n_estimators=400,
                min_samples_leaf=4,
                random_state=42,
                n_jobs=-1,
            ),
            X,
            y,
            sample_weight,
        ),
        "et": fit_calibrated(
            ExtraTreesClassifier(
                n_estimators=400,
                min_samples_leaf=4,
                random_state=43,
                n_jobs=-1,
            ),
            X,
            y,
            sample_weight,
        ),
        "hgb": fit_calibrated(
            HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_depth=6,
                min_samples_leaf=12,
                random_state=44,
            ),
            X,
            y,
            sample_weight,
        ),
    }
    return {"target": target_column, "feature_columns": feature_columns, "models": models}


def predict_bundle_prob(bundle: dict, X: pd.DataFrame) -> np.ndarray:
    if "constant_prob" in bundle:
        return np.full(len(X), float(bundle["constant_prob"]), dtype=float)
    probs = [predict_prob(model, X[bundle["feature_columns"]]) for model in bundle["models"].values()]
    stacked = np.vstack(probs)
    return stacked.mean(axis=0)


def evaluate_global_holdout(df: pd.DataFrame, feature_columns: list) -> dict:
    X = df[feature_columns]
    y = df["target_win"].astype(int)
    weights = build_sample_weight(df)
    X_train, X_valid, y_train, y_valid, w_train, _ = train_test_split(
        X,
        y,
        weights,
        test_size=0.25,
        random_state=42,
        stratify=y,
    )
    train_frame = df.loc[X_train.index].copy()
    train_frame = train_frame.assign(target_win=y_train.values)
    bundle = fit_ensemble_bundle(train_frame, feature_columns, "target_win")
    probs = predict_bundle_prob(bundle, X_valid)
    preds = (probs >= 0.5).astype(int)
    calibration_bins = []
    valid_df = pd.DataFrame({"prob": probs, "y": y_valid.to_numpy()})
    valid_df["bin"] = pd.cut(valid_df["prob"], bins=np.linspace(0, 1, 6), include_lowest=True)
    for bucket, group in valid_df.groupby("bin", observed=False):
        if group.empty:
            continue
        calibration_bins.append(
            {
                "bucket": str(bucket),
                "rows": int(len(group)),
                "avg_prob": round(float(group["prob"].mean()), 4),
                "win_rate": round(float(group["y"].mean()), 4),
            }
        )
    return {
        "accuracy": round(float(accuracy_score(y_valid, preds)), 4),
        "log_loss": round(float(log_loss(y_valid, probs, labels=[0, 1])), 4),
        "rows": int(len(X_valid)),
        "calibration_bins": calibration_bins,
    }


def build_gatekeeper(df: pd.DataFrame) -> dict:
    leagues = {}
    for league_name, group in df.groupby("LeagueName"):
        if len(group) < 15:
            continue
        leagues[str(league_name)] = {
            "rows": int(len(group)),
            "win_rate": round(float(group["target_win"].mean()), 4),
            "avg_prob": round(float(group["Prob"].mean()), 4),
        }

    regimes = {}
    for regime_key, group in df.groupby("RegimeKey"):
        if len(group) < 20:
            continue
        regimes[str(regime_key)] = {
            "rows": int(len(group)),
            "win_rate": round(float(group["target_win"].mean()), 4),
            "quality_rate": round(float(group["target_quality"].mean()), 4),
        }

    minute_buckets = {}
    for bucket, group in df.groupby("MinuteBucket"):
        minute_buckets[str(bucket)] = {
            "rows": int(len(group)),
            "win_rate": round(float(group["target_win"].mean()), 4),
        }

    return {
        "leagues": leagues,
        "regimes": regimes,
        "minute_buckets": minute_buckets,
        "premium_rules": {
            "allowed_market": "NEXT GOAL LIVE",
            "minute_min": 15,
            "minute_max": 35,
            "min_prob": 0.66,
            "min_quality_score": 0.62,
            "min_league_rows": 15,
            "min_league_win_rate": 0.58,
            "min_regime_rows": 20,
            "min_regime_win_rate": 0.57,
            "blocked_leagues": ["Serie A", "Eerste Divisie", "Bundesliga", "Championship", "Liga MX"],
            "blocked_countries": ["Brazil", "Greece", "Romania"],
        },
    }


def fit_regime_models(df: pd.DataFrame, feature_columns: list) -> dict:
    regime_models = {}
    for regime_key, group in df.groupby("RegimeKey"):
        if len(group) < MIN_ROWS_REGIME:
            continue
        class_counts = group["target_win"].value_counts()
        if len(class_counts) < 2 or int(class_counts.min()) < MIN_CLASS_ROWS:
            continue
        regime_models[str(regime_key)] = {
            "win": fit_ensemble_bundle(group, feature_columns, "target_win"),
            "fast": fit_ensemble_bundle(group, feature_columns, "target_fast_win"),
            "quality": fit_ensemble_bundle(group, feature_columns, "target_quality"),
            "rows": int(len(group)),
        }
    return regime_models


def blend_scores(win_prob: np.ndarray, fast_prob: np.ndarray, quality_prob: np.ndarray) -> np.ndarray:
    return np.clip(
        DEFAULT_BLEND_WEIGHTS["win"] * win_prob
        + DEFAULT_BLEND_WEIGHTS["fast"] * fast_prob
        + DEFAULT_BLEND_WEIGHTS["quality"] * quality_prob,
        0.0,
        1.0,
    )


def score_with_package(package: dict, frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    working = build_engineered_features(working)
    features = package["feature_columns"]
    gatekeeper = package["gatekeeper"]
    global_models = package["global_models"]
    regime_models = package["regime_models"]

    win_probs = []
    fast_probs = []
    quality_probs = []
    chosen_regimes = []

    for _, row in working.iterrows():
        row_frame = pd.DataFrame([row])
        regime_key = str(row_frame["RegimeKey"].iloc[0])
        bundle_group = regime_models.get(regime_key, global_models)
        chosen_regimes.append(regime_key if regime_key in regime_models else "GLOBAL")
        win_probs.append(float(predict_bundle_prob(bundle_group["win"], row_frame[features])[0]))
        fast_probs.append(float(predict_bundle_prob(bundle_group["fast"], row_frame[features])[0]))
        quality_probs.append(float(predict_bundle_prob(bundle_group["quality"], row_frame[features])[0]))

    working["perfection_win_prob"] = np.array(win_probs)
    working["perfection_fast_prob"] = np.array(fast_probs)
    working["perfection_quality_prob"] = np.array(quality_probs)
    working["perfection_score"] = blend_scores(
        working["perfection_win_prob"].to_numpy(),
        working["perfection_fast_prob"].to_numpy(),
        working["perfection_quality_prob"].to_numpy(),
    )
    working["perfection_regime_model"] = chosen_regimes

    league_stats = gatekeeper["leagues"]
    regime_stats = gatekeeper["regimes"]
    minute_stats = gatekeeper["minute_buckets"]
    rules = gatekeeper["premium_rules"]

    edge_scores = []
    premium_flags = []
    premium_reasons = []
    for _, row in working.iterrows():
        league_name = str(row.get("LeagueName", ""))
        regime_key = str(row.get("RegimeKey", ""))
        minute_bucket = str(row.get("MinuteBucket", ""))
        league_wr = float(league_stats.get(league_name, {}).get("win_rate", 0.5))
        regime_wr = float(regime_stats.get(regime_key, {}).get("win_rate", 0.5))
        minute_wr = float(minute_stats.get(minute_bucket, {}).get("win_rate", 0.5))
        baseline = 0.50 * league_wr + 0.30 * regime_wr + 0.20 * minute_wr
        edge_score = float(row["perfection_score"]) - baseline
        edge_scores.append(round(edge_score, 4))

        blocked_leagues = set(rules["blocked_leagues"])
        blocked_countries = set(rules["blocked_countries"])
        if str(row.get("Market", "")) != rules["allowed_market"]:
            premium_flags.append(False)
            premium_reasons.append("market")
            continue
        if str(row.get("Tier", "")) not in {"APPROVED", "CAUTION"}:
            premium_flags.append(False)
            premium_reasons.append("tier")
            continue
        if int(row.get("Minute", 0)) < rules["minute_min"] or int(row.get("Minute", 0)) > rules["minute_max"]:
            premium_flags.append(False)
            premium_reasons.append("minute")
            continue
        if float(row.get("Prob", 0.0)) < rules["min_prob"]:
            premium_flags.append(False)
            premium_reasons.append("prob")
            continue
        if float(row["perfection_score"]) < rules["min_quality_score"]:
            premium_flags.append(False)
            premium_reasons.append("quality_score")
            continue
        if league_name in blocked_leagues:
            premium_flags.append(False)
            premium_reasons.append("league_blocked")
            continue
        if str(row.get("Country", "")) in blocked_countries:
            premium_flags.append(False)
            premium_reasons.append("country_blocked")
            continue
        if float(league_stats.get(league_name, {}).get("rows", 0)) >= rules["min_league_rows"]:
            if float(league_stats.get(league_name, {}).get("win_rate", 0.0)) < rules["min_league_win_rate"]:
                premium_flags.append(False)
                premium_reasons.append("league_wr")
                continue
        if float(regime_stats.get(regime_key, {}).get("rows", 0)) >= rules["min_regime_rows"]:
            if float(regime_stats.get(regime_key, {}).get("win_rate", 0.0)) < rules["min_regime_win_rate"]:
                premium_flags.append(False)
                premium_reasons.append("regime_wr")
                continue
        if edge_score <= 0:
            premium_flags.append(False)
            premium_reasons.append("edge")
            continue
        premium_flags.append(True)
        premium_reasons.append("premium_ok")

    working["perfection_edge_score"] = edge_scores
    working["perfection_is_premium"] = premium_flags
    working["perfection_reason"] = premium_reasons
    return working


def build_report(df: pd.DataFrame, validation: dict, package: dict) -> dict:
    def summarize(group_cols):
        rows = []
        grouped = df.groupby(group_cols)
        for key, group in grouped:
            rows.append(
                {
                    "key": key if isinstance(key, str) else " | ".join(map(str, key if isinstance(key, tuple) else [key])),
                    "rows": int(len(group)),
                    "win_rate": round(float(group["target_win"].mean()), 4),
                    "fast_rate": round(float(group["target_fast_win"].mean()), 4),
                    "quality_rate": round(float(group["target_quality"].mean()), 4),
                    "avg_prob": round(float(group["Prob"].mean()), 4),
                }
            )
        return sorted(rows, key=lambda item: (-item["win_rate"], -item["rows"]))

    scored = score_with_package(package, df.tail(min(400, len(df))))
    premium_preview = scored.loc[scored["perfection_is_premium"]].copy()
    premium_preview = premium_preview.sort_values("perfection_score", ascending=False).head(25)

    return {
        "dataset_rows": int(len(df)),
        "settled_rows": int(len(df)),
        "full_feature_rows": int(len(df)),
        "validation": validation,
        "top_leagues": summarize(["LeagueName"])[:15],
        "bottom_leagues": sorted(summarize(["LeagueName"]), key=lambda item: (item["win_rate"], -item["rows"]))[:15],
        "minute_buckets": summarize(["MinuteBucket"]),
        "regimes": summarize(["RegimeKey"])[:20],
        "premium_preview_rows": premium_preview[
            [
                "FixtureId",
                "Country",
                "LeagueName",
                "Market",
                "Minute",
                "Tier",
                "Prob",
                "perfection_score",
                "perfection_edge_score",
                "perfection_reason",
            ]
        ].to_dict(orient="records"),
    }


def train_oracle_perfection() -> dict:
    prepared = prepare_training_frame()
    df = prepared.frame
    feature_columns = prepared.feature_columns

    global_models = {
        "win": fit_ensemble_bundle(df, feature_columns, "target_win"),
        "fast": fit_ensemble_bundle(df, feature_columns, "target_fast_win"),
        "quality": fit_ensemble_bundle(df, feature_columns, "target_quality"),
    }
    regime_models = fit_regime_models(df, feature_columns)
    gatekeeper = build_gatekeeper(df)
    validation = evaluate_global_holdout(df, feature_columns)

    package = {
        "version": "oracle_perfection_v1",
        "data_path": str(DATA_FILE),
        "feature_columns": feature_columns,
        "global_models": global_models,
        "regime_models": regime_models,
        "gatekeeper": gatekeeper,
        "metadata": {
            "rows": int(len(df)),
            "regime_models": int(len(regime_models)),
            "blend_weights": DEFAULT_BLEND_WEIGHTS,
        },
    }
    report = build_report(df, validation, package)

    joblib.dump(package, PACKAGE_PATH)
    GATEKEEPER_PATH.write_text(json.dumps(gatekeeper, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "package_path": str(PACKAGE_PATH),
        "report_path": str(REPORT_PATH),
        "gatekeeper_path": str(GATEKEEPER_PATH),
        "rows": int(len(df)),
        "regime_models": int(len(regime_models)),
        "validation": validation,
    }


def main() -> None:
    result = train_oracle_perfection()
    print("ORACLE PERFECTION READY")
    print(f"Rows used: {result['rows']}")
    print(f"Regime models: {result['regime_models']}")
    print(f"Package: {result['package_path']}")
    print(f"Report: {result['report_path']}")
    print(f"Gatekeeper: {result['gatekeeper_path']}")
    print(
        "Validation:"
        f" accuracy={result['validation']['accuracy']:.3f}"
        f" log_loss={result['validation']['log_loss']:.3f}"
        f" rows={result['validation']['rows']}"
    )


if __name__ == "__main__":
    main()
