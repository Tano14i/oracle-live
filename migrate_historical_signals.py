import html
import json
import os
import re
from typing import Dict, List

import pandas as pd

WEB_DATA_PATH = "web_stats.json"
OUTPUT_PATH = "live_training_data.csv"

LIVE_TRAINING_COLUMNS = [
    "SignalKey",
    "OpenTimeUTC",
    "FixtureId",
    "Country",
    "LeagueName",
    "FilterMode",
    "MarketMode",
    "Market",
    "Minute",
    "MinuteBucket",
    "StartScore",
    "TotalGoalsAtOpen",
    "DNA",
    "Prob",
    "Tier",
    "Reason",
    "AvgTotalGoals",
    "AvgHTGoals",
    "HomeAvgTotalGoals",
    "AwayAvgTotalGoals",
    "HomeAvgHTGoals",
    "AwayAvgHTGoals",
    "Status",
    "Outcome",
    "CloseScore",
    "SettledTimeUTC",
]


def get_minute_bucket(minute_value: int) -> str:
    if minute_value <= 20:
        return "15-20"
    if minute_value <= 25:
        return "21-25"
    if minute_value <= 30:
        return "26-30"
    if minute_value <= 35:
        return "31-35"
    return "36-43"


def ensure_output() -> pd.DataFrame:
    if os.path.exists(OUTPUT_PATH):
        try:
            df = pd.read_csv(OUTPUT_PATH)
        except Exception:
            df = pd.DataFrame(columns=LIVE_TRAINING_COLUMNS)
    else:
        df = pd.DataFrame(columns=LIVE_TRAINING_COLUMNS)
    for col in LIVE_TRAINING_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[LIVE_TRAINING_COLUMNS]


def parse_prob(value) -> float:
    text = str(value or "").replace("%", "").strip()
    try:
        return round(float(text) / 100.0, 4)
    except Exception:
        return 0.0


def parse_tier(value) -> str:
    text = str(value or "")
    if "APPROVED" in text:
        return "APPROVED"
    if "CAUTION" in text:
        return "CAUTION"
    if "GAMBLING" in text:
        return "GAMBLING"
    return text.strip()


def parse_outcome(value) -> str:
    text = str(value or "").upper()
    if "WIN" in text:
        return "WIN"
    if "LOSS" in text or "PERSO" in text:
        return "LOSS"
    return ""


def parse_original_text(original_text: str) -> Dict[str, object]:
    if not original_text:
        return {}
    text = html.unescape(str(original_text))
    cleaned = re.sub(r"<[^>]+>", "", text)
    result: Dict[str, object] = {}

    patterns = {
        "country": r"NAZIONE:\s*(.+)",
        "match": r"MATCH:\s*(.+)",
        "market": r"MARKET:\s*(.+)",
        "dna_conf": r"DNA:\s*`?([0-9]+(?:\.[0-9]+)?)`?\s*\|\s*.*?CONF:\s*([0-9]+(?:\.[0-9]+)?)%",
        "minute_score": r"MINUTO:\s*([0-9]+)'\s*\|\s*([0-9]+-[0-9]+)",
    }

    country_match = re.search(patterns["country"], cleaned)
    market_match = re.search(patterns["market"], cleaned)
    dna_match = re.search(patterns["dna_conf"], cleaned)
    minute_match = re.search(patterns["minute_score"], cleaned)

    if country_match:
        result["Country"] = country_match.group(1).strip()
    if market_match:
        result["Market"] = market_match.group(1).strip()
    if dna_match:
        result["DNA"] = float(dna_match.group(1))
        result["Prob"] = round(float(dna_match.group(2)) / 100.0, 4)
    if minute_match:
        minute_value = int(minute_match.group(1))
        score = minute_match.group(2)
        result["Minute"] = minute_value
        result["MinuteBucket"] = get_minute_bucket(minute_value)
        result["StartScore"] = score
        try:
            goals = score.split("-")
            result["TotalGoalsAtOpen"] = int(goals[0]) + int(goals[1])
        except Exception:
            result["TotalGoalsAtOpen"] = 0
    return result


def build_row_from_recent(signal: dict) -> Dict[str, object]:
    signal_key = str(signal.get("SignalKey") or "").strip()
    market = str(signal.get("Market") or "").strip()
    if not signal_key:
        base_match = str(signal.get("Match") or "UNKNOWN").replace(" ", "_")
        base_time = str(signal.get("Ora") or "00:00").replace(":", "")
        signal_key = f"legacy:{base_match}:{base_time}:{market or 'UNKNOWN'}"
    return {
        "SignalKey": signal_key,
        "OpenTimeUTC": "",
        "FixtureId": "",
        "Country": "",
        "LeagueName": str(signal.get("Campionato") or ""),
        "FilterMode": str(signal.get("Filtro") or ""),
        "MarketMode": str(signal.get("Mode") or ""),
        "Market": market,
        "Minute": 0,
        "MinuteBucket": "",
        "StartScore": "",
        "TotalGoalsAtOpen": 0,
        "DNA": float(signal.get("DNA") or 0),
        "Prob": parse_prob(signal.get("Prob")),
        "Tier": parse_tier(signal.get("Tier")),
        "Reason": "historic_recent_signal",
        "AvgTotalGoals": "",
        "AvgHTGoals": "",
        "HomeAvgTotalGoals": "",
        "AwayAvgTotalGoals": "",
        "HomeAvgHTGoals": "",
        "AwayAvgHTGoals": "",
        "Status": "settled" if parse_outcome(signal.get("Esito")) else "pending",
        "Outcome": parse_outcome(signal.get("Esito")),
        "CloseScore": "",
        "SettledTimeUTC": "",
    }


def build_row_from_monitor(signal_key: str, item: dict) -> Dict[str, object]:
    parsed = parse_original_text(item.get("original_text", ""))
    return {
        "SignalKey": signal_key,
        "OpenTimeUTC": "",
        "FixtureId": item.get("fixture_id", ""),
        "Country": parsed.get("Country", ""),
        "LeagueName": item.get("league_name", ""),
        "FilterMode": "",
        "MarketMode": "",
        "Market": item.get("market", parsed.get("Market", "")),
        "Minute": parsed.get("Minute", ""),
        "MinuteBucket": item.get("minute_bucket", parsed.get("MinuteBucket", "")),
        "StartScore": item.get("start_score", parsed.get("StartScore", "")),
        "TotalGoalsAtOpen": parsed.get("TotalGoalsAtOpen", ""),
        "DNA": parsed.get("DNA", ""),
        "Prob": parsed.get("Prob", ""),
        "Tier": parse_tier(item.get("tier", "")),
        "Reason": "historic_monitor_entry",
        "AvgTotalGoals": "",
        "AvgHTGoals": "",
        "HomeAvgTotalGoals": "",
        "AwayAvgTotalGoals": "",
        "HomeAvgHTGoals": "",
        "AwayAvgHTGoals": "",
        "Status": item.get("status", "pending"),
        "Outcome": parse_outcome(item.get("edited_outcome", "")),
        "CloseScore": "",
        "SettledTimeUTC": "",
    }


def migrate() -> None:
    if not os.path.exists(WEB_DATA_PATH):
        print(f"Errore: {WEB_DATA_PATH} non trovato.")
        return

    with open(WEB_DATA_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    output_df = ensure_output()
    existing_keys = set(output_df["SignalKey"].astype(str).tolist()) if not output_df.empty else set()
    rows: List[Dict[str, object]] = []
    imported_recent = 0
    imported_monitor = 0

    for signal in data.get("recent_signals", []):
        row = build_row_from_recent(signal)
        if row["SignalKey"] in existing_keys:
            continue
        rows.append(row)
        existing_keys.add(row["SignalKey"])
        imported_recent += 1

    monitor = data.get("monitor_risultati", {}) or {}
    for signal_key, item in monitor.items():
        if not isinstance(item, dict):
            continue
        row = build_row_from_monitor(str(signal_key), item)
        if row["SignalKey"] in existing_keys:
            continue
        if not row["Market"] and not row["Outcome"] and not row["DNA"]:
            continue
        rows.append(row)
        existing_keys.add(row["SignalKey"])
        imported_monitor += 1

    if not rows:
        print("Nessun nuovo segnale storico recuperabile da migrare.")
        return

    recovered_df = pd.DataFrame(rows, columns=LIVE_TRAINING_COLUMNS)
    if output_df.empty:
        final_df = recovered_df.copy()
    else:
        final_df = pd.concat([output_df, recovered_df], ignore_index=True)
    final_df.to_csv(OUTPUT_PATH, index=False)

    settled_with_outcome = int(final_df["Outcome"].isin(["WIN", "LOSS"]).sum())
    print("Migrazione completata.")
    print(f"- Recent signals importati: {imported_recent}")
    print(f"- Monitor entries importate: {imported_monitor}")
    print(f"- Totale righe dataset: {len(final_df)}")
    print(f"- Righe allenabili (WIN/LOSS): {settled_with_outcome}")


if __name__ == "__main__":
    migrate()