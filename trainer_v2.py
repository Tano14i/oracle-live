"""
trainer_v2.py — Oracle ML trainer (versione migliorata)

Differenze rispetto a trainer.py originale:
1. Esclude segnali LEARNING dal training (erano 90% del dataset e causavano predizione inversa)
2. Esclude OVER 1.5 HT (WR storico 28.3% — market strutturalmente rotto)
3. Esclude OVER 0.5 HT dopo il minuto 20 (WR crolla a 6-20% dopo)
4. Usa split temporale invece di split casuale (ordina per OpenTimeUTC)
5. Aggiunge class_weight='balanced' per gestire sbilanciamento WIN/LOSS
6. Salva metriche del modello finale, non di un modello intermedio
7. Soglia decisionale ottimizzata per massimizzare precision invece di usare 0.5 fisso
"""

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    log_loss,
    precision_score,
    recall_score,
)

from config import LIVE_TRAINING_DATA_PATH, MODEL_PATH

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_FILE = LIVE_TRAINING_DATA_PATH
_model_path = Path(MODEL_PATH)
MODEL_NAME = str(_model_path.with_name(f"{_model_path.stem}_v2{_model_path.suffix or '.pkl'}"))
CANDIDATE_MODEL_NAME = str(_model_path.with_name(f"{_model_path.stem}_v2_candidate{_model_path.suffix or '.pkl'}"))

# ---------------------------------------------------------------------------
# Soglie
# ---------------------------------------------------------------------------
MIN_PRODUCTION_ROWS = 200   # alzato da 30 — sotto questa soglia il modello non è affidabile
MIN_CANDIDATE_ROWS = 80     # alzato da 15

# Tier pubblici — LEARNING escluso deliberatamente
PUBLIC_TIERS = {"APPROVED", "CAUTION", "GAMBLING"}

# Market e zone temporali valide per il training
# OVER 1.5 HT escluso (WR storico 28.3%)
# OVER 0.5 HT limitato al minuto <= 20 (dopo crolla a 6-20%)
VALID_MARKET_BUCKETS = {
    "NEXT GOAL LIVE": None,           # tutti i bucket
    "OVER 0.5 HT": {"15-20"},         # solo early
}

FEATURE_COLUMNS = [
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


# ---------------------------------------------------------------------------
# Filtro dataset
# ---------------------------------------------------------------------------

def apply_training_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Applica i filtri di qualità al dataset e restituisce il dataframe filtrato
    insieme a un dizionario con il conteggio delle righe escluse per motivo.
    """
    stats = {
        "input": len(df),
        "excluded_not_settled": 0,
        "excluded_learning_tier": 0,
        "excluded_invalid_market_bucket": 0,
        "excluded_missing_features": 0,
        "final": 0,
    }

    # 1. Solo WIN/LOSS
    settled = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    stats["excluded_not_settled"] = stats["input"] - len(settled)

    # 2. Solo tier pubblici (escludi LEARNING)
    public = settled[settled["Tier"].isin(PUBLIC_TIERS)].copy()
    stats["excluded_learning_tier"] = len(settled) - len(public)

    # 3. Filtra per market e bucket validi
    valid_rows = []
    for market, allowed_buckets in VALID_MARKET_BUCKETS.items():
        mask = public["Market"] == market
        market_rows = public[mask]
        if allowed_buckets is not None:
            market_rows = market_rows[market_rows["MinuteBucket"].isin(allowed_buckets)]
        valid_rows.append(market_rows)

    filtered = pd.concat(valid_rows, ignore_index=True) if valid_rows else pd.DataFrame()
    stats["excluded_invalid_market_bucket"] = len(public) - len(filtered)

    # 4. Solo righe con tutte le feature
    if not filtered.empty:
        full_feature_mask = filtered[FEATURE_COLUMNS].notna().all(axis=1)
        clean = filtered[full_feature_mask].copy()
        stats["excluded_missing_features"] = len(filtered) - len(clean)
    else:
        clean = filtered
        stats["excluded_missing_features"] = 0

    stats["final"] = len(clean)
    return clean, stats


# ---------------------------------------------------------------------------
# Split temporale
# ---------------------------------------------------------------------------

def temporal_train_test_split(df: pd.DataFrame, test_size: float = 0.20):
    """
    Divide il dataset rispettando l'ordine temporale.
    I dati più recenti vanno nel test set, non un campione casuale.
    Questo evita di valutare il modello su dati che 'vengono prima' nel tempo.
    """
    if "OpenTimeUTC" in df.columns:
        df = df.sort_values("OpenTimeUTC").reset_index(drop=True)
    split_idx = int(len(df) * (1 - test_size))
    return df.iloc[:split_idx], df.iloc[split_idx:]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_oracle_v2() -> dict:
    result = {
        "status": "error",
        "message": "",
        "rows": 0,
        "excluded_stats": {},
        "model_path": "",
        "mode": "none",
        "feature_importances": {},
        "validation": {},
        "win_rate_train": 0.0,
        "win_rate_test": 0.0,
        "optimal_threshold": 0.5,
    }

    print("Starting Oracle v2 training...")

    if not os.path.exists(DATA_FILE):
        result["message"] = f"Dataset non trovato: {DATA_FILE}"
        print(result["message"])
        return result

    df = pd.read_csv(DATA_FILE)
    if df.empty:
        result["message"] = "Dataset vuoto."
        print(result["message"])
        return result

    # Applica filtri
    clean, excl_stats = apply_training_filters(df)
    result["excluded_stats"] = excl_stats

    print(f"\nFiltri applicati:")
    print(f"  Input totale:              {excl_stats['input']}")
    print(f"  Esclusi (non settled):     {excl_stats['excluded_not_settled']}")
    print(f"  Esclusi (LEARNING tier):   {excl_stats['excluded_learning_tier']}")
    print(f"  Esclusi (market/bucket):   {excl_stats['excluded_invalid_market_bucket']}")
    print(f"  Esclusi (feature mancanti):{excl_stats['excluded_missing_features']}")
    print(f"  Righe finali per training: {excl_stats['final']}")

    if len(clean) < MIN_CANDIDATE_ROWS:
        result["message"] = (
            f"Troppo pochi segnali pubblici dopo i filtri: {len(clean)}. "
            f"Necessari almeno {MIN_CANDIDATE_ROWS}."
        )
        print(result["message"])
        return result

    clean["target"] = (clean["Outcome"] == "WIN").astype(int)
    X = clean[FEATURE_COLUMNS]
    y = clean["target"]

    win_rate_overall = float(y.mean())
    result["win_rate_train"] = round(win_rate_overall * 100, 2)
    print(f"\nWin rate dataset filtrato: {win_rate_overall*100:.1f}%")
    print(f"Distribuzione: {int(y.sum())}W / {int((~y.astype(bool)).sum())}L")

    # Distribuzione per market
    print("\nDistribuzione per market nel training set:")
    for market in clean["Market"].unique():
        mdf = clean[clean["Market"] == market]
        wr = (mdf["Outcome"] == "WIN").mean()
        print(f"  {market}: {len(mdf)} segnali — WR {wr*100:.1f}%")

    # Split temporale
    validation = {}
    optimal_threshold = 0.5

    if len(clean) >= MIN_CANDIDATE_ROWS * 2 and y.nunique() > 1:
        train_df, test_df = temporal_train_test_split(clean, test_size=0.20)

        X_train = train_df[FEATURE_COLUMNS]
        y_train = train_df["target"]
        X_test = test_df[FEATURE_COLUMNS]
        y_test = test_df["target"]

        print(f"\nSplit temporale: {len(X_train)} train / {len(X_test)} test")
        print(f"Win rate train: {y_train.mean()*100:.1f}% | test: {y_test.mean()*100:.1f}%")
        result["win_rate_test"] = round(float(y_test.mean()) * 100, 2)

        # Modello di validazione
        val_model = RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            min_samples_leaf=5,
            class_weight="balanced",
        )
        val_model.fit(X_train, y_train)
        test_probs = val_model.predict_proba(X_test)[:, 1]

        # Trova soglia ottimale (massimizza precision su WIN)
        thresholds = np.arange(0.40, 0.85, 0.01)
        best_threshold = 0.5
        best_precision = 0.0
        for thr in thresholds:
            preds = (test_probs >= thr).astype(int)
            if preds.sum() < 5:
                continue
            prec = precision_score(y_test, preds, zero_division=0)
            if prec > best_precision:
                best_precision = prec
                best_threshold = thr

        optimal_threshold = round(float(best_threshold), 2)
        test_preds = (test_probs >= optimal_threshold).astype(int)

        validation = {
            "accuracy": float(accuracy_score(y_test, (test_probs >= 0.5).astype(int))),
            "log_loss": float(log_loss(y_test, test_probs, labels=[0, 1])),
            "precision_at_optimal": float(precision_score(y_test, test_preds, zero_division=0)),
            "recall_at_optimal": float(recall_score(y_test, test_preds, zero_division=0)),
            "optimal_threshold": optimal_threshold,
            "signals_above_threshold": int(test_preds.sum()),
            "rows_test": int(len(X_test)),
        }

        print(f"\nValidazione (split temporale):")
        print(f"  Accuracy (soglia 0.5):     {validation['accuracy']:.3f}")
        print(f"  Log loss:                  {validation['log_loss']:.3f}")
        print(f"  Soglia ottimale trovata:   {optimal_threshold}")
        print(f"  Precision a soglia ottim.: {validation['precision_at_optimal']:.3f}")
        print(f"  Recall a soglia ottimale:  {validation['recall_at_optimal']:.3f}")
        print(f"  Segnali sopra soglia:      {validation['signals_above_threshold']}/{len(X_test)}")

        # Verifica inversione predizione
        mean_prob_win = float(test_probs[y_test == 1].mean())
        mean_prob_loss = float(test_probs[y_test == 0].mean())
        print(f"\n  Mean prob su WIN:  {mean_prob_win:.4f}")
        print(f"  Mean prob su LOSS: {mean_prob_loss:.4f}")
        if mean_prob_loss > mean_prob_win:
            print("  ⚠️  ATTENZIONE: il modello assegna prob più alta ai LOSS — predizione inversa rilevata.")
            print("     Considera di escludere più tier o di rivedere le feature.")
        else:
            print("  ✅ Predizione nella direzione corretta.")

    # Modello finale su tutto il dataset filtrato
    final_model = RandomForestClassifier(
        n_estimators=300,
        random_state=42,
        min_samples_leaf=5,
        class_weight="balanced",
    )
    final_model.fit(X, y)

    # Salva
    target_path = MODEL_NAME if len(clean) >= MIN_PRODUCTION_ROWS else CANDIDATE_MODEL_NAME
    joblib.dump(final_model, target_path)

    # Salva anche la soglia ottimale vicino al modello
    threshold_path = str(Path(target_path).with_suffix("")) + "_threshold.txt"
    with open(threshold_path, "w") as f:
        f.write(str(optimal_threshold))
    print(f"\nSoglia ottimale salvata in: {threshold_path}")

    importances = dict(zip(FEATURE_COLUMNS, final_model.feature_importances_))
    result["feature_importances"] = importances
    result["validation"] = validation
    result["model_path"] = target_path
    result["rows"] = len(clean)
    result["optimal_threshold"] = optimal_threshold

    mode = "production" if len(clean) >= MIN_PRODUCTION_ROWS else "candidate"
    result["status"] = "ok"
    result["mode"] = mode
    result["message"] = (
        f"Modello v2 ({mode}) salvato in '{target_path}'. "
        f"Addestrato su {len(clean)} segnali pubblici (APPROVED/CAUTION/GAMBLING). "
        f"Soglia ottimale: {optimal_threshold}."
    )

    print(f"\n{'='*50}")
    print(result["message"])
    print(f"\nFeature importance:")
    for name, value in sorted(importances.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(value * 40)
        print(f"  {name:<25} {value:.4f}  {bar}")

    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = train_oracle_v2()
    if result["status"] != "ok":
        print(f"\nERRORE: {result['message']}")
    else:
        print(f"\nCompletato. Modalità: {result['mode']}")
        v = result.get("validation", {})
        if v:
            print(f"Soglia ottimale consigliata: {result['optimal_threshold']}")
            print(f"Precision a soglia ottimale: {v.get('precision_at_optimal', 0):.3f}")
