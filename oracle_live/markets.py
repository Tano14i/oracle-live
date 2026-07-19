from oracle_live.constants import (
    AUTO_MARKET_SWITCH_ENABLED,
    DEFAULT_MARKET_MODE,
    MARKET_NEXT_GOAL,
    MARKET_OVER05_HT,
    MARKET_OVER15_HT,
    MARKET_PRESETS,
)
from oracle_live.state import salva_dati_web, state_lock, stats

def get_minute_bucket(minute_value: int) -> str:
    if minute_value <= 20:
        return "15-20"
    if minute_value <= 25:
        return "21-25"
    if minute_value <= 30:
        return "26-30"
    if minute_value <= 35:
        return "31-35"
    return "36-44"


def get_market_mode() -> str:
    mode = stats.get("market_mode", DEFAULT_MARKET_MODE)
    return mode if mode in MARKET_PRESETS else DEFAULT_MARKET_MODE


def get_market_label() -> str:
    return MARKET_PRESETS[get_market_mode()]["label"]


def get_active_markets():
    return MARKET_PRESETS[get_market_mode()]["markets"]


def get_routed_active_markets():
    markets = list(dict.fromkeys(get_active_markets()))
    if not AUTO_MARKET_SWITCH_ENABLED:
        return markets
    mode = get_market_mode()
    if mode in {"NEXT_GOAL", "HT_NEXT"}:
        return [MARKET_OVER05_HT, MARKET_OVER15_HT, MARKET_NEXT_GOAL]
    return markets


def get_market_router_score(market: str, minute_value: int, total_goals: int) -> float:
    if market == MARKET_OVER05_HT:
        if total_goals != 0:
            return -1.0
        if minute_value <= 10:
            return 1.30
        if minute_value <= 25:
            return 1.10
        if minute_value <= 35:
            return 0.85
        return 0.35
    if market == MARKET_OVER15_HT:
        if total_goals > 1:
            return -1.0
        if total_goals == 1:
            if minute_value <= 10:
                return 0.60
            if minute_value <= 25:
                return 1.05
            if minute_value <= 35:
                return 1.20
            return 0.55
        if minute_value <= 10:
            return 0.35
        if minute_value <= 25:
            return 0.55
        if minute_value <= 35:
            return 0.70
        return 0.20
    if market == MARKET_NEXT_GOAL:
        if minute_value <= 5:
            return 0.30
        if minute_value <= 10:
            return 0.45
        if minute_value <= 25:
            return 0.90
        if minute_value <= 35:
            return 1.00
        return 1.20
    return 0.0


def prioritize_markets(markets, minute_value: int, total_goals: int):
    return sorted(
        list(dict.fromkeys(markets)),
        key=lambda market_name: (get_market_router_score(market_name, minute_value, total_goals), market_name == MARKET_NEXT_GOAL),
        reverse=True,
    )


def set_market_mode(mode: str) -> str:
    if mode not in MARKET_PRESETS:
        return get_market_label()
    with state_lock:
        stats["market_mode"] = mode
    salva_dati_web()
    return MARKET_PRESETS[mode]["label"]


def is_market_window(market: str, minute_value: int, total_goals: int) -> bool:
    if market == MARKET_NEXT_GOAL:
        return 1 <= minute_value <= 85
    if market == MARKET_OVER15_HT:
        # Disabilitato: WR storico 28.3% — market strutturalmente in perdita
        return False
    if not 1 <= minute_value <= 44:
        return False
    if market == MARKET_OVER05_HT:
        # Limitato al minuto <= 20: WR crolla a 6-20% dopo
        return total_goals == 0 and minute_value <= 20
    return False


def is_market_winner(market: str, total_goals: int) -> bool:
    if market == MARKET_OVER05_HT:
        return total_goals >= 1
    if market == MARKET_OVER15_HT:
        return total_goals >= 2
    if market == MARKET_NEXT_GOAL:
        return False
    return False


def is_first_half_closed(status_short: str, minute_value: int) -> bool:
    status_short = str(status_short or "").upper()
    return status_short in {"HT", "BT", "FT", "AET", "PEN"} or minute_value >= 45


def get_min_quota_for_tier(tier: str) -> float:
    return {"APPROVED": 1.90, "CAUTION": 1.70, "GAMBLING": 1.75, "LEARNING": 1.75}.get(tier, 1.75)
