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
from sklearn.calibration import CalibratedClassifierCV
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

ISOTONIC_MIN_ROWS = 300   # sotto questa soglia isotonic sovradatta: si usa sigmoid


def build_forest() -> RandomForestClassifier:
    """La foresta regolarizzata, in un posto solo.

    Validazione e produzione devono usare gli stessi vincoli: cambiarli fra le due
    rende il giudizio inutile, e tenerli in due punti li fa divergere.
    """
    return RandomForestClassifier(
        n_estimators=300,
        random_state=42,
        max_depth=8,
        min_samples_leaf=30,
        max_features="sqrt",
        class_weight="balanced",
    )


def build_calibrated_model(n_rows: int, min_class_count: int | None = None):
    """Foresta con probabilita' calibrate.

    Un 0.80 di un Random Forest grezzo e' la frazione di alberi che ha votato si',
    non una probabilita': non si puo' confrontare con il breakeven di una quota.
    Misurato sui segnali pubblicati, la correlazione fra probabilita' del modello ed
    esito era 0.016, cioe' nulla. Senza calibrazione ogni regola costruita sul
    prodotto probabilita' x quota amplifica l'errore del modello invece di
    selezionare valore: simulato sui dati reali, un gate a valore atteso portava il
    ROI da -12% a -26%.

    Se la classe minoritaria ha meno campioni delle fold la calibrazione non e'
    possibile: si torna alla foresta nuda invece di far fallire il retrain.
    """
    base = build_forest()
    method = "isotonic" if n_rows >= ISOTONIC_MIN_ROWS else "sigmoid"
    cv = 5 if n_rows >= 100 else 3
    if min_class_count is not None:
        cv = min(cv, int(min_class_count))
    if cv < 2:
        return base
    return CalibratedClassifierCV(base, method=method, cv=cv)


def reliability_table(probs, y_true, bins: int = 5) -> list:
    """Per ogni fascia di probabilita' predetta: quanti segnali e win rate reale.

    E' il modo di leggere se un 0.80 del modello vale davvero l'80%. Senza questa
    tabella la calibrazione resta un'affermazione.
    """
    probs = np.asarray(probs, dtype=float)
    y_true = np.asarray(y_true, dtype=int)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (probs >= lo) & (probs < hi) if i < bins - 1 else (probs >= lo) & (probs <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "n": n,
            "mean_prob": round(float(probs[mask].mean()), 3),
            "real_wr": round(float(y_true[mask].mean()), 3),
        })
    return rows


def apply_training_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Applica i filtri di qualità al dataset e restituisce il dataframe filtrato
    insieme a un dizionario con il conteggio delle righe escluse per motivo.
    """
    stats = {
        "input": len(df),
        "excluded_duplicate_signals": 0,
        "excluded_not_settled": 0,
        "excluded_learning_tier": 0,
        "excluded_invalid_market_bucket": 0,
        "excluded_missing_features": 0,
        "final": 0,
    }

    # 0. Un segnale, una riga.
    # Finche' restava pendente, lo stesso segnale veniva riaccodato a ogni
    # scansione: 30.260 righe per 3.512 segnali reali, con punte di 135 copie.
    # I duplicati non sono neutri, pesano i perdenti (chi il gol lo prende subito
    # si chiude alla prima scansione e lascia una riga sola), e le copie tardive
    # portano uno stato a partita avanzata sotto colonne che si chiamano "AtOpen".
    # Si tiene la prima riga: e' l'unica scattata davvero al momento della decisione.
    deduped = df.drop_duplicates(subset="SignalKey", keep="first").copy()
    stats["excluded_duplicate_signals"] = stats["input"] - len(deduped)

    # 1. Solo WIN/LOSS
    settled = deduped[deduped["Outcome"].isin(["WIN", "LOSS"])].copy()
    stats["excluded_not_settled"] = len(deduped) - len(settled)

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
    print(f"  Esclusi (righe duplicate): {excl_stats['excluded_duplicate_signals']}")
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

    # Divisione temporale in tre fasce.
    # La soglia va scelta su dati diversi da quelli su cui la si giudica: sceglierla
    # sullo stesso test set la adatta al test set. Il modello precedente aveva una
    # soglia di 0.83 trovata massimizzando la precision proprio sul test, e fuori
    # campione selezionava al contrario (46.8% sopra soglia, 69.5% sotto).
    validation = {}
    optimal_threshold = 0.5
    test_probs = None
    promote = False
    promote_reason = "validazione non eseguita: dataset troppo piccolo"

    if len(clean) >= MIN_CANDIDATE_ROWS * 2 and y.nunique() > 1:
        ordered = clean.sort_values("OpenTimeUTC").reset_index(drop=True) \
            if "OpenTimeUTC" in clean.columns else clean.reset_index(drop=True)
        n = len(ordered)
        i_train, i_val = int(n * 0.60), int(n * 0.80)
        train_df = ordered.iloc[:i_train]
        val_df = ordered.iloc[i_train:i_val]
        test_df = ordered.iloc[i_val:]

        X_train, y_train = train_df[FEATURE_COLUMNS], train_df["target"]
        X_val, y_val = val_df[FEATURE_COLUMNS], val_df["target"]
        X_test, y_test = test_df[FEATURE_COLUMNS], test_df["target"]

        print(f"\nSplit temporale: {len(X_train)} train / {len(X_val)} validazione / {len(X_test)} test")
        print(f"Win rate  train {y_train.mean()*100:.1f}% | "
              f"validazione {y_val.mean()*100:.1f}% | test {y_test.mean()*100:.1f}%")
        result["win_rate_test"] = round(float(y_test.mean()) * 100, 2)

        # Foresta regolarizzata. Senza limiti di profondita' e con foglie da 5
        # campioni, 300 alberi su ~2.600 righe memorizzano il periodo di
        # addestramento: il modello precedente correlava +0.33 in campione e
        # -0.17 fuori.
        val_model = build_calibrated_model(len(X_train), int(y_train.value_counts().min()))
        val_model.fit(X_train, y_train)

        # Soglia scelta sulla fascia di validazione, non sul test.
        # Si richiede una copertura minima: massimizzare la sola precision spinge
        # la soglia in alto finche' restano pochi casi fortunati.
        val_probs = val_model.predict_proba(X_val)[:, 1]
        base_val = float(y_val.mean())
        min_coverage = max(20, int(len(y_val) * 0.10))
        best_threshold, best_lift = 0.5, -1.0
        for thr in np.arange(0.40, 0.86, 0.01):
            selected = val_probs >= thr
            if selected.sum() < min_coverage:
                continue
            lift = float(y_val[selected].mean()) - base_val
            if lift > best_lift:
                best_lift, best_threshold = lift, thr
        optimal_threshold = round(float(best_threshold), 2)

        # Giudizio finale sulla fascia di test, mai toccata finora.
        test_probs = val_model.predict_proba(X_test)[:, 1]
        base_test = float(y_test.mean())
        selected_test = test_probs >= optimal_threshold
        n_selected = int(selected_test.sum())
        wr_selected = float(y_test[selected_test].mean()) if n_selected else 0.0
        wr_rejected = float(y_test[~selected_test].mean()) if (~selected_test).sum() else 0.0
        lift_test = wr_selected - base_test

        validation = {
            "accuracy": float(accuracy_score(y_test, (test_probs >= 0.5).astype(int))),
            "log_loss": float(log_loss(y_test, test_probs, labels=[0, 1])),
            "optimal_threshold": optimal_threshold,
            "rows_test": int(len(X_test)),
            "base_rate_test": round(base_test * 100, 2),
            "wr_selected": round(wr_selected * 100, 2),
            "wr_rejected": round(wr_rejected * 100, 2),
            "signals_above_threshold": n_selected,
            "lift_test": round(lift_test * 100, 2),
            "calibration": getattr(val_model, "method", "nessuna"),
            "reliability": reliability_table(test_probs, y_test),
        }

        print()
        print("Tabella di affidabilita' (probabilita' predetta -> win rate reale):")
        print(f"  calibrazione: {validation['calibration']}")
        for row in validation["reliability"]:
            print(f"    {row['bin']}  n={row['n']:<4} predetto {row['mean_prob']:.3f}"
                  f" -> reale {row['real_wr']:.3f}")

        print(f"\nGiudizio sulla fascia di test (mai usata prima):")
        print(f"  soglia scelta in validazione: {optimal_threshold}")
        print(f"  tasso base sul test:          {base_test*100:.1f}%")
        print(f"  win rate sopra soglia:        {wr_selected*100:.1f}%  (n={n_selected})")
        print(f"  win rate sotto soglia:        {wr_rejected*100:.1f}%")
        print(f"  guadagno rispetto al caso:    {lift_test*100:+.1f} punti")

        # Cancello di promozione: il modello entra in produzione solo se
        # dimostra di selezionare meglio del caso su dati mai visti.
        MIN_LIFT = 0.03
        MIN_SELECTED = 30
        if n_selected < MIN_SELECTED:
            promote_reason = f"solo {n_selected} segnali sopra soglia nel test (minimo {MIN_SELECTED})"
        elif lift_test < MIN_LIFT:
            promote_reason = (f"guadagno {lift_test*100:+.1f} punti sotto il minimo "
                              f"di {MIN_LIFT*100:.0f}")
        elif wr_selected <= wr_rejected:
            promote_reason = "i segnali scartati vincono quanto o piu' di quelli tenuti"
        else:
            promote = True
            promote_reason = f"guadagno {lift_test*100:+.1f} punti su {n_selected} segnali"

    # Il modello finale usa gli stessi vincoli di quello validato: cambiare
    # iperparametri fra validazione e produzione renderebbe il giudizio inutile.
    final_model = build_calibrated_model(len(X), int(y.value_counts().min()))
    final_model.fit(X, y)

    if promote and len(clean) >= MIN_PRODUCTION_ROWS:
        target_path = MODEL_NAME
        print(f"\nPROMOSSO in produzione: {promote_reason}")
    else:
        target_path = CANDIDATE_MODEL_NAME
        print(f"\nNON promosso, salvato come candidato: {promote_reason}")
        print("  Il modello in produzione resta invariato.")
    joblib.dump(final_model, target_path)
    result["promoted"] = promote
    result["promote_reason"] = promote_reason

    # La soglia in produzione si scrive solo se il modello e' stato promosso:
    # altrimenti resterebbe attiva una soglia di un modello mai validato.
    threshold_path = str(Path(target_path).with_suffix("")) + "_threshold.txt"
    with open(threshold_path, "w") as f:
        f.write(str(optimal_threshold))
    print(f"Soglia salvata in: {threshold_path}")

    # Soglie dei tier dai percentili della distribuzione di QUESTO modello.
    #
    # Con soglie fisse il tier si svuota appena il riaddestramento sposta la
    # distribuzione: le vecchie 0.60/0.56/0.50 erano tarate su una media di 0.52 e
    # dopo la calibrazione venivano superate dal 100% dei segnali pubblicati, il che
    # ha reso GAMBLING irraggiungibile e la condizione di probabilita' sempre vera.
    # Prendendo i percentili fra i segnali che superano la soglia di pubblicazione,
    # i tre tier restano popolati per costruzione.
    tiers_path = str(Path(target_path).with_suffix("")) + "_tiers.txt"
    try:
        above = np.asarray(test_probs, dtype=float)
        above = above[above >= optimal_threshold]
        if above.size >= 20:
            cut_caution, cut_approved = (float(x) for x in np.percentile(above, [33, 66]))
            with open(tiers_path, "w") as f:
                f.write(f"{cut_caution:.4f} {cut_approved:.4f}")
            print(f"Soglie tier salvate in: {tiers_path}"
                  f"  (CAUTION {cut_caution:.3f} | APPROVED {cut_approved:.3f})")
            result["tier_prob_cuts"] = [round(cut_caution, 4), round(cut_approved, 4)]
        else:
            print(f"Soglie tier non aggiornate: solo {above.size} segnali sopra la soglia")
    except Exception as exc:
        print(f"Soglie tier non calcolabili: {exc}")

    # Il wrapper calibrato non espone feature_importances_: si media sugli alberi
    # interni. Senza questo il report del retrain resterebbe muto.
    try:
        if hasattr(final_model, "calibrated_classifiers_"):
            inner = [cc.estimator for cc in final_model.calibrated_classifiers_]
            importances = dict(zip(FEATURE_COLUMNS,
                                   np.mean([m.feature_importances_ for m in inner], axis=0)))
        else:
            importances = dict(zip(FEATURE_COLUMNS, final_model.feature_importances_))
    except Exception as exc:
        print(f"Feature importances non disponibili: {exc}")
        importances = {}
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
