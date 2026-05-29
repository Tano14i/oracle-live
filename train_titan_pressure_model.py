import joblib
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "titan_raw_snapshots_export.csv"
MODEL_PATH = BASE_DIR / "titan_pressure_model.pkl"
MIN_ROWS = 50

FEATURE_COLUMNS = [
    "DNAxG",
    "Minute",
    "ScoreDiff",
    "TotalGoalsAtSignal",
    "TotalShots",
    "ShotsOnGoal",
    "DangerousAttacks",
    "Corners",
    "PossessionDiff",
    "RedCardsHome",
    "RedCardsAway",
]


def train_titan_pressure_model():
    result = {
        "status": "error",
        "message": "",
        "rows": 0,
        "model_path": str(MODEL_PATH),
        "feature_importances": {},
        "validation": {},
    }

    print("Starting Titan pressure-model training...")

    if not DATA_FILE.exists():
        result["message"] = f"Dataset file not found: {DATA_FILE}"
        print(result["message"])
        return result

    df = pd.read_csv(DATA_FILE)
    if df.empty:
        result["message"] = "Dataset is empty."
        print(result["message"])
        return result

    for column in FEATURE_COLUMNS + ["TargetOutcome"]:
        if column not in df.columns:
            result["message"] = f"Missing required column: {column}"
            print(result["message"])
            return result

    df = df.copy()
    for column in FEATURE_COLUMNS + ["TargetOutcome"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=FEATURE_COLUMNS + ["TargetOutcome"]).copy()
    df["target"] = df["TargetOutcome"].astype(int)

    rows = len(df)
    result["rows"] = rows
    if rows < MIN_ROWS:
        result["message"] = f"Too few rows for Titan pressure model: {rows}. Need at least {MIN_ROWS}."
        print(result["message"])
        return result

    X = df[FEATURE_COLUMNS]
    y = df["target"]

    model = RandomForestClassifier(n_estimators=300, random_state=42, min_samples_leaf=3)
    validation = {}

    print(f"Training on {rows} Titan snapshots...")

    if rows >= 100 and y.nunique() > 1:
        X_train, X_valid, y_train, y_valid = train_test_split(
            X,
            y,
            test_size=0.25,
            random_state=42,
            stratify=y,
        )
        model.fit(X_train, y_train)
        valid_probs = model.predict_proba(X_valid)[:, 1]
        valid_preds = (valid_probs >= 0.5).astype(int)
        validation = {
            "accuracy": float(accuracy_score(y_valid, valid_preds)),
            "log_loss": float(log_loss(y_valid, valid_probs, labels=[0, 1])),
            "rows": int(len(X_valid)),
        }

    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)

    importances = dict(zip(FEATURE_COLUMNS, model.feature_importances_))
    result["status"] = "ok"
    result["message"] = f"Titan pressure model saved to '{MODEL_PATH.name}'"
    result["feature_importances"] = importances
    result["validation"] = validation

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
    train_titan_pressure_model()
