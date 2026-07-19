import os
from pathlib import Path

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split

from config import LIVE_TRAINING_DATA_PATH, MODEL_PATH

DATA_FILE = LIVE_TRAINING_DATA_PATH
MODEL_NAME = MODEL_PATH
_model_path = Path(MODEL_PATH)
CANDIDATE_MODEL_NAME = str(_model_path.with_name(f"{_model_path.stem}_candidate{_model_path.suffix or '.pkl'}"))
MIN_PRODUCTION_ROWS = 30
MIN_CANDIDATE_ROWS = 15
# Righe minime per usare la calibrazione isotonica (sotto si usa sigmoid, piu' robusta su pochi dati)
MIN_ISOTONIC_ROWS = 400

# Feature storiche originali: obbligatorie (le righe senza vengono escluse, come prima).
CORE_FEATURE_COLUMNS = [
    "DNA",
    "Minute",
    "TotalGoalsAtOpen",
    "AvgTotalGoals",
    "AvgHTGoals",
    "HomeAvgTotalGoals",
    "AwayAvgTotalGoals",
    "HomeAvgHTGoals",
    "AwayAvgHTGoals",
    "ShotsOnGoalAtOpen",
    "TotalShotsAtOpen",
    "CornersAtOpen",
    "RedCardsAtOpen",
    "TitanPressureScore",
]

# One-hot del mercato: il modello deve sapere QUALE mercato sta predicendo
# (O0.5 HT, O1.5 HT e NEXT GOAL sono problemi diversi con base rate diversi).
MARKET_ONE_HOT = {
    "MarketOver05HT": "OVER 0.5 HT",
    "MarketOver15HT": "OVER 1.5 HT",
    "MarketNextGoal": "NEXT GOAL LIVE",
}

# Feature live aggiuntive: opzionali (0.0 sulle righe storiche che non le hanno,
# cosi' il dataset legacy resta utilizzabile).
EXTRA_LIVE_FEATURES = [
    "ShotsInsideBoxAtOpen",
    "GoalkeeperSavesAtOpen",
    "XgRateAtOpen",
]

FEATURE_COLUMNS = CORE_FEATURE_COLUMNS + list(MARKET_ONE_HOT.keys()) + EXTRA_LIVE_FEATURES


def ensure_model_feature_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Deriva le one-hot del mercato e riempie le feature opzionali mancanti."""
    market_series = frame["Market"] if "Market" in frame.columns else pd.Series("", index=frame.index)
    market_series = market_series.fillna("").astype(str)
    for column, market_label in MARKET_ONE_HOT.items():
        frame[column] = (market_series == market_label).astype(float)
    for column in EXTRA_LIVE_FEATURES:
        if column not in frame.columns:
            frame[column] = 0.0
        else:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def build_calibrated_model(rows: int) -> CalibratedClassifierCV:
    method = "isotonic" if rows >= MIN_ISOTONIC_ROWS else "sigmoid"
    base = RandomForestClassifier(n_estimators=200, random_state=42, min_samples_leaf=3)
    return CalibratedClassifierCV(base, method=method, cv=3)


def train_oracle():
    result = {
        "status": "error",
        "message": "",
        "rows": 0,
        "settled_rows": 0,
        "excluded_rows": 0,
        "model_path": "",
        "mode": "none",
        "feature_importances": {},
        "validation": {},
        "calibration": "none",
    }

    print("Starting Oracle live-model training...")

    if not os.path.exists(DATA_FILE):
        result["message"] = f"Error: dataset file not found: {DATA_FILE}"
        print(result["message"])
        return result

    df = pd.read_csv(DATA_FILE)
    if df.empty:
        result["message"] = "Error: live dataset is empty."
        print(result["message"])
        return result

    settled = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    settled_count = len(settled)
    result["settled_rows"] = settled_count
    if settled_count < MIN_CANDIDATE_ROWS:
        result["message"] = (
            f"Too few settled signals for a candidate model: {settled_count}. "
            f"At least {MIN_CANDIDATE_ROWS} WIN/LOSS rows are required."
        )
        print(result["message"])
        return result

    settled = ensure_model_feature_columns(settled)

    for column in FEATURE_COLUMNS:
        if column not in settled.columns:
            result["message"] = f"Error: missing feature column in dataset: {column}"
            print(result["message"])
            return result

    # Le righe legacy vengono escluse solo se mancano le feature CORE:
    # le feature nuove/opzionali sono gia' state riempite con 0.0.
    full_feature_mask = settled[CORE_FEATURE_COLUMNS].notna().all(axis=1)
    excluded_rows = int((~full_feature_mask).sum())
    settled = settled.loc[full_feature_mask].copy()
    settled_count = len(settled)
    result["rows"] = settled_count
    result["excluded_rows"] = excluded_rows
    if settled_count < MIN_CANDIDATE_ROWS:
        result["message"] = (
            f"Too few full-feature settled signals for a candidate model: {settled_count}. "
            f"Excluded settled rows with missing features: {excluded_rows}. "
            f"At least {MIN_CANDIDATE_ROWS} full-feature WIN/LOSS rows are required."
        )
        print(result["message"])
        return result

    settled["target"] = settled["Outcome"].apply(lambda value: 1 if value == "WIN" else 0)

    X = settled[FEATURE_COLUMNS]
    y = settled["target"]

    # Il RandomForest "nudo" serve per le feature importance; il modello salvato
    # e' la versione calibrata, cosi' predict_proba e' una probabilita' reale
    # utilizzabile per il calcolo dell'EV contro le quote.
    importance_model = RandomForestClassifier(n_estimators=200, random_state=42, min_samples_leaf=3)
    print(
        f"Training on {settled_count} full-feature settled signals..."
        f" Excluded settled rows with missing features: {excluded_rows}."
    )

    validation = {}
    if settled_count >= 20 and y.nunique() > 1:
        X_train, X_valid, y_train, y_valid = train_test_split(
            X,
            y,
            test_size=0.25,
            random_state=42,
            stratify=y,
        )
        try:
            valid_model = build_calibrated_model(len(X_train))
            valid_model.fit(X_train, y_train)
        except Exception as exc:
            print(f"Calibration failed on validation split ({exc}); falling back to uncalibrated model.")
            valid_model = RandomForestClassifier(n_estimators=200, random_state=42, min_samples_leaf=3)
            valid_model.fit(X_train, y_train)
        valid_probs = valid_model.predict_proba(X_valid)[:, 1]
        valid_preds = (valid_probs >= 0.5).astype(int)
        validation = {
            "accuracy": float(accuracy_score(y_valid, valid_preds)),
            "log_loss": float(log_loss(y_valid, valid_probs, labels=[0, 1])),
            "rows": int(len(X_valid)),
        }

    importance_model.fit(X, y)

    model = None
    if y.nunique() > 1:
        try:
            model = build_calibrated_model(settled_count)
            model.fit(X, y)
            result["calibration"] = "isotonic" if settled_count >= MIN_ISOTONIC_ROWS else "sigmoid"
        except Exception as exc:
            print(f"Calibration failed ({exc}); saving uncalibrated model.")
            model = None
    if model is None:
        model = importance_model
        result["calibration"] = "none"

    target_model = MODEL_NAME if settled_count >= MIN_PRODUCTION_ROWS else CANDIDATE_MODEL_NAME
    joblib.dump(model, target_model)

    importances = dict(zip(FEATURE_COLUMNS, importance_model.feature_importances_))
    result["feature_importances"] = importances
    result["validation"] = validation
    result["model_path"] = target_model

    if settled_count >= MIN_PRODUCTION_ROWS:
        result["status"] = "ok"
        result["mode"] = "production"
        result["message"] = (
            f"Production model saved successfully to '{MODEL_NAME}'. "
            f"Trained on {settled_count} full-feature settled rows; excluded {excluded_rows} settled rows with missing features. "
            f"Calibration: {result['calibration']}."
        )
    else:
        result["status"] = "ok"
        result["mode"] = "candidate"
        result["message"] = (
            f"Sample still too small for production: {settled_count}. "
            f"Excluded settled rows with missing features: {excluded_rows}. "
            f"Candidate model saved to '{CANDIDATE_MODEL_NAME}' without replacing '{MODEL_NAME}'. "
            f"Calibration: {result['calibration']}."
        )

    print(result["message"])
    if validation:
        print(
            "Validation snapshot:"
            f" accuracy={validation['accuracy']:.3f}"
            f" log_loss={validation['log_loss']:.3f}"
            f" rows={validation['rows']}"
        )
    print("Feature importance:")
    for name, value in sorted(importances.items(), key=lambda item: item[1], reverse=True):
        print(f"- {name}: {value:.4f}")
    return result


if __name__ == "__main__":
    train_oracle()
