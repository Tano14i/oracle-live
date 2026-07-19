import html
import os
import threading

import joblib
import pandas as pd

from config import AUTO_RETRAIN_EVERY_N_SETTLED, CHAT_ID, MODEL_PATH
from trainer import (
    CANDIDATE_MODEL_NAME,
    DATA_FILE as TRAINER_DATA_FILE,
    FEATURE_COLUMNS as TRAINER_FEATURE_COLUMNS,
    MIN_CANDIDATE_ROWS,
    MIN_PRODUCTION_ROWS,
    train_oracle,
)

from oracle_live import state
from oracle_live.constants import (
    MARKET_OVER05_HT,
    MARKET_OVER15_HT,
    TITAN_PRESSURE_FEATURE_COLUMNS,
    TITAN_PRESSURE_MODEL_PATH,
    V2_DEFAULT_THRESHOLD,
    V2_MODEL_PATH,
    V2_THRESHOLD_PATH,
)
from oracle_live.state import (
    bot,
    ensure_live_training_dataset,
    get_total_settled_count,
    live_training_lock,
    log_event,
    logger,
    salva_dati_web,
    state_lock,
    stats,
)

def load_models() -> None:
    try:
        state.oracle_brain = joblib.load(V2_MODEL_PATH)
        print("AI model v2 loaded.")
        log_event("BOOT", "Model v2 loaded successfully")
        try:
            with open(V2_THRESHOLD_PATH, "r") as _f:
                state.oracle_v2_threshold = float(_f.read().strip())
            print(f"Soglia ottimale v2: {state.oracle_v2_threshold}")
            log_event("BOOT", f"V2 threshold loaded: {state.oracle_v2_threshold}")
        except Exception:
            state.oracle_v2_threshold = V2_DEFAULT_THRESHOLD
            print(f"Threshold file non trovato, uso default: {state.oracle_v2_threshold}")
    except Exception:
        try:
            state.oracle_brain = joblib.load(MODEL_PATH)
            state.oracle_v2_threshold = 0.5
            print("AI model v2 non trovato, caricato modello originale.")
            log_event("BOOT", "Fallback to original model")
        except Exception:
            state.oracle_brain = None
            state.oracle_v2_threshold = V2_DEFAULT_THRESHOLD
            print("AI model non trovato.")
            log_event("BOOT", "Model not found; running without ML model")

    try:
        state.titan_pressure_brain = joblib.load(TITAN_PRESSURE_MODEL_PATH)
        print("Titan pressure model loaded.")
        log_event("BOOT", "Titan pressure model loaded successfully")
    except Exception:
        state.titan_pressure_brain = None
        print("Titan pressure model not found.")
        log_event("BOOT", "Titan pressure model not found; soft booster disabled")


def format_ml_status() -> str:
    ensure_live_training_dataset()
    if not os.path.exists(TRAINER_DATA_FILE):
        return (
            "<b>ML STATUS</b>\n\n"
            f"Dataset not found: <code>{html.escape(TRAINER_DATA_FILE)}</code>"
        )

    try:
        with live_training_lock:
            df = pd.read_csv(TRAINER_DATA_FILE)
    except Exception as exc:
        return (
            "<b>ML STATUS</b>\n\n"
            f"Dataset read error: <code>{html.escape(str(exc))}</code>"
        )

    total_rows = len(df)
    settled_rows = int(df["Outcome"].isin(["WIN", "LOSS"]).sum()) if "Outcome" in df.columns else 0

    missing_features = [column for column in TRAINER_FEATURE_COLUMNS if column not in df.columns]
    if missing_features:
        full_feature_rows = 0
        full_feature_settled_rows = 0
        live_format_rows = 0
        live_format_settled_rows = 0
    else:
        full_feature_mask = df[TRAINER_FEATURE_COLUMNS].notna().all(axis=1)
        full_feature_rows = int(full_feature_mask.sum())
        settled_mask = df["Outcome"].isin(["WIN", "LOSS"]) if "Outcome" in df.columns else pd.Series([False] * len(df))
        full_feature_settled_rows = int((full_feature_mask & settled_mask).sum())
        live_format_mask = df[["AvgTotalGoals", "AvgHTGoals", "HomeAvgTotalGoals", "AwayAvgTotalGoals", "HomeAvgHTGoals", "AwayAvgHTGoals"]].notna().any(axis=1)
        live_format_rows = int(live_format_mask.sum())
        live_format_settled_rows = int((live_format_mask & settled_mask).sum())

    migrated_rows = max(0, total_rows - live_format_rows)
    migrated_settled_rows = max(0, settled_rows - live_format_settled_rows)

    candidate_exists = os.path.exists(CANDIDATE_MODEL_NAME)
    production_exists = os.path.exists(MODEL_PATH)
    active_model = MODEL_PATH if production_exists else (CANDIDATE_MODEL_NAME if candidate_exists else "none")

    last_retrain_total_rows = int(stats.get("last_retrain_total_rows", 0) or 0)
    last_retrain_settled_rows = int(stats.get("last_retrain_settled_rows", 0) or 0)
    last_retrain_full_feature_settled = int(stats.get("last_retrain_full_feature_settled", 0) or 0)

    new_rows_since_retrain = max(0, total_rows - last_retrain_total_rows)
    new_settled_since_retrain = max(0, settled_rows - last_retrain_settled_rows)
    new_full_feature_settled_since_retrain = max(0, full_feature_settled_rows - last_retrain_full_feature_settled)

    lines = [
        "<b>ML STATUS</b>",
        "",
        f"Dataset: <code>{html.escape(TRAINER_DATA_FILE)}</code>",
        f"Total rows: <b>{total_rows}</b>",
        f"Settled WIN/LOSS rows: <b>{settled_rows}</b>",
        f"Full-feature rows: <b>{full_feature_rows}</b>",
        f"Full-feature settled rows: <b>{full_feature_settled_rows}</b>",
        f"Candidate threshold: <b>{MIN_CANDIDATE_ROWS}</b>",
        f"Production threshold: <b>{MIN_PRODUCTION_ROWS}</b>",
        f"Candidate model present: <b>{'YES' if candidate_exists else 'NO'}</b>",
        f"Production model present: <b>{'YES' if production_exists else 'NO'}</b>",
        f"Active runtime model: <code>{html.escape(active_model)}</code>",
        f"Retrain running: <b>{'YES' if state.retrain_running else 'NO'}</b>",
        "",
        "<b>Dataset mix</b>",
        f"Migrated historical rows: <b>{migrated_rows}</b> | settled: <b>{migrated_settled_rows}</b>",
        f"New live-format rows: <b>{live_format_rows}</b> | settled: <b>{live_format_settled_rows}</b>",
        "",
        "<b>Since last retrain</b>",
        f"New rows: <b>{new_rows_since_retrain}</b>",
        f"New settled rows: <b>{new_settled_since_retrain}</b>",
        f"New full-feature settled rows: <b>{new_full_feature_settled_since_retrain}</b>",
    ]

    if missing_features:
        lines.extend([
            "",
            "Missing dataset features:",
            ", ".join(missing_features),
        ])
    elif total_rows:
        coverage_parts = []
        for column in TRAINER_FEATURE_COLUMNS:
            non_null = int(df[column].notna().sum())
            coverage = (non_null / total_rows) * 100 if total_rows else 0.0
            coverage_parts.append(f"{column} {coverage:.0f}%")
        lines.extend([
            "",
            "Feature coverage:",
            " | ".join(coverage_parts),
        ])

    if state.last_retrain_result:
        lines.extend([
            "",
            "Last retrain:",
            html.escape(state.last_retrain_result),
        ])

    return "\n".join(lines)

def run_retrain_from_bot() -> str:

    try:
        with live_training_lock:
            result = train_oracle()
    except Exception as exc:
        logger.exception("RETRAIN_ERROR | error=%s", exc)
        state.last_retrain_result = f"Error: {exc}"
        return (
            "<b>RETRAIN</b>\n\n"
            f"Retrain failed: <code>{html.escape(str(exc))}</code>"
        )

    status = result.get("status", "error")
    if status != "ok":
        state.last_retrain_result = result.get("message", "Retrain failed.")
        return (
            "<b>RETRAIN</b>\n\n"
            f"{html.escape(result.get('message', 'Retrain failed.'))}\n"
            f"Settled rows available: <b>{int(result.get('rows', 0))}</b>"
        )

    mode = result.get("mode", "none")
    model_path = result.get("model_path", "")
    rows = int(result.get("rows", 0))
    validation = result.get("validation", {}) or {}

    try:
        with live_training_lock:
            df_metrics = pd.read_csv(TRAINER_DATA_FILE)
        retrain_total_rows = len(df_metrics)
        retrain_settled_rows = int(df_metrics["Outcome"].isin(["WIN", "LOSS"]).sum()) if "Outcome" in df_metrics.columns else 0
        retrain_full_feature_settled = 0
        if all(column in df_metrics.columns for column in TRAINER_FEATURE_COLUMNS) and "Outcome" in df_metrics.columns:
            retrain_full_feature_settled = int((df_metrics[TRAINER_FEATURE_COLUMNS].notna().all(axis=1) & df_metrics["Outcome"].isin(["WIN", "LOSS"])).sum())
    except Exception:
        retrain_total_rows = rows
        retrain_settled_rows = rows
        retrain_full_feature_settled = 0

    if mode == "production":
        try:
            state.oracle_brain = joblib.load(MODEL_PATH)
        except Exception as exc:
            logger.exception("RETRAIN_RELOAD_ERROR | error=%s", exc)
            state.last_retrain_result = f"Production saved but reload failed: {exc}"
            return (
                "<b>RETRAIN</b>\n\n"
                f"Production retrain completed, but reload failed: <code>{html.escape(str(exc))}</code>\n"
                f"Saved model: <code>{html.escape(model_path)}</code>"
            )

    sorted_features = sorted(
        result.get("feature_importances", {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    top_features = ", ".join(f"{name} {value:.2f}" for name, value in sorted_features[:4]) or "n/a"
    validation_line = ""
    if validation:
        validation_line = (
            f" | val acc {validation.get('accuracy', 0.0):.2f}"
            f" | val logloss {validation.get('log_loss', 0.0):.2f}"
        )
    state.last_retrain_result = f"{mode.upper()} | {rows} rows | {top_features}{validation_line}"
    with state_lock:
        stats["last_retrain_total_rows"] = retrain_total_rows
        stats["last_retrain_settled_rows"] = retrain_settled_rows
        stats["last_retrain_full_feature_settled"] = retrain_full_feature_settled
    salva_dati_web()
    logger.info(
        "RETRAIN_OK | mode=%s rows=%s model=%s top_features=%s validation=%s",
        mode,
        rows,
        model_path,
        top_features,
        validation,
    )

    validation_block = ""
    if validation:
        validation_block = (
            f"\n<b>Validation:</b> accuracy {validation.get('accuracy', 0.0):.3f}"
            f" | log loss {validation.get('log_loss', 0.0):.3f}"
            f" | rows {validation.get('rows', 0)}"
        )

    return (
        "<b>RETRAIN COMPLETED</b>\n\n"
        f"Mode: <b>{html.escape(mode.upper())}</b>\n"
        f"Settled rows used: <b>{rows}</b>\n"
        f"Saved model: <code>{html.escape(model_path)}</code>\n"
        f"{html.escape(result.get('message', ''))}\n"
        f"<b>Top features:</b> {html.escape(top_features)}"
        f"{validation_block}"
    )

def start_retrain_job(chat_id: int, starter_text: str = "ML retrain started in background. I will send the result here as soon as it finishes.") -> str:

    with state_lock:
        if state.retrain_running:
            return "Retrain already running. Please wait for the final message."
        state.retrain_running = True

    def retrain_worker():
        try:
            outcome_message = run_retrain_from_bot()
            bot.send_message(chat_id, outcome_message, parse_mode="HTML")
        except Exception as exc:
            logger.exception("RETRAIN_THREAD_ERROR | error=%s", exc)
            bot.send_message(chat_id, f"Retrain thread error: {exc}")
        finally:
            with state_lock:
                state.retrain_running = False

    thread = threading.Thread(target=retrain_worker, daemon=True, name="oracle-retrain")
    thread.start()
    return starter_text


def maybe_trigger_auto_retrain() -> None:
    step = max(0, AUTO_RETRAIN_EVERY_N_SETTLED)
    if step <= 0:
        return

    settled_total = get_total_settled_count()
    if settled_total < step:
        return

    with state_lock:
        last_auto_total = int(stats.get("last_auto_retrain_total", 0) or 0)
    if settled_total - last_auto_total < step:
        return

    started_message = start_retrain_job(
        CHAT_ID,
        f"Auto ML retrain started after {settled_total} settled signals.",
    )
    if started_message.startswith("Retrain already running"):
        return

    with state_lock:
        stats["last_auto_retrain_total"] = settled_total
    salva_dati_web()
    log_event("AUTO_RETRAIN_START", f"settled_total={settled_total} step={step}")
    if CHAT_ID:
        bot.send_message(CHAT_ID, started_message)


def predict_titan_pressure_prob(dna: float, minute_value: int, score_diff: int, total_goals: int, stats_payload: dict):
    if state.titan_pressure_brain is None or not isinstance(stats_payload, dict):
        return None
    try:
        model_feature_columns = list(getattr(state.titan_pressure_brain, "feature_names_in_", TITAN_PRESSURE_FEATURE_COLUMNS))
        feature_values = {
            "DNAxG": dna,
            "Minute": minute_value,
            "ScoreDiff": score_diff,
            "TotalGoalsAtSignal": total_goals,
            "TotalShots": float(stats_payload.get("total_shots", 0.0) or 0.0),
            "ShotsOnGoal": float(stats_payload.get("shots_on_goal", 0.0) or 0.0),
            "DangerousAttacks": float(stats_payload.get("dangerous_attacks", 0.0) or 0.0),
            "Corners": float(stats_payload.get("corners", 0.0) or 0.0),
            "PossessionDiff": float(stats_payload.get("possession_diff", 0.0) or 0.0),
            "RedCardsHome": float(stats_payload.get("red_cards_home", 0.0) or 0.0),
            "RedCardsAway": float(stats_payload.get("red_cards_away", 0.0) or 0.0),
        }
        x_input = pd.DataFrame([[feature_values.get(column, 0.0) for column in model_feature_columns]], columns=model_feature_columns)
        return float(state.titan_pressure_brain.predict_proba(x_input)[0][1])
    except Exception as exc:
        logger.exception("TITAN_PRESSURE_PREDICT_ERROR | error=%s", exc)
        return None

def evaluate_titan_soft_layer(stats_payload: dict, market: str, minute_value: int, total_goals: int) -> dict:
    if not isinstance(stats_payload, dict):
        return {"promote": False, "label": "", "score": 0}

    red_cards = float(stats_payload.get("red_cards", 0.0) or 0.0)
    shots_on_goal = float(stats_payload.get("shots_on_goal", 0.0) or 0.0)
    total_shots = float(stats_payload.get("total_shots", 0.0) or 0.0)
    corners = float(stats_payload.get("corners", 0.0) or 0.0)

    score = 0
    promote = False
    if market == MARKET_OVER05_HT:
        if shots_on_goal >= 2:
            score += 1
        if total_shots >= 7:
            score += 1
        if corners >= 2:
            score += 1
        if minute_value <= 20 and total_shots >= 5:
            score += 1
        promote = red_cards == 0 and score >= 3
    elif market == MARKET_OVER15_HT:
        if total_goals != 1:
            return {"promote": False, "label": "", "score": 0}
        if shots_on_goal >= 3:
            score += 1
        if total_shots >= 9:
            score += 1
        if corners >= 3:
            score += 1
        if minute_value <= 25 and shots_on_goal >= 2:
            score += 1
        promote = red_cards == 0 and score >= 3

    label = f"titan pressure {int(score)}/4 | sog {int(shots_on_goal)} | shots {int(total_shots)} | corners {int(corners)}"
    return {"promote": promote, "label": label, "score": score}


def has_live_pressure_data(stats_payload: dict) -> bool:
    if not isinstance(stats_payload, dict):
        return False
    return any(float(stats_payload.get(key, 0.0) or 0.0) > 0 for key in ["shots_on_goal", "total_shots", "corners", "dangerous_attacks"])

def get_xg_rate(stats_payload: dict, minute_value: int) -> float:
    if not isinstance(stats_payload, dict) or minute_value <= 0:
        return 0.0
    xg_h = float(stats_payload.get("xg_home", 0.0) or 0.0)
    xg_a = float(stats_payload.get("xg_away", 0.0) or 0.0)
    return round((xg_h + xg_a) / max(1, minute_value), 4)
