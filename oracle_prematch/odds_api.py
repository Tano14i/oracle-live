from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

import requests

from oracle_prematch.loader import parse_datetime


@dataclass(slots=True)
class NormalizedEvent:
    fixture_id: str
    sport: str
    country: str
    league: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    captured_at_utc: datetime
    bookmaker_count: int
    home_odds: float | None
    draw_odds: float | None
    away_odds: float | None
    over25_odds: float | None
    under25_odds: float | None
    tags: list[str]
    notes: list[str]
    raw_payload: dict


def _safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median_or_none(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(float(median(usable)), 4)


def _normalize_country(sport_key: str) -> str:
    parts = sport_key.split("_")
    if len(parts) >= 2 and parts[0] == "soccer":
        return parts[1].replace("-", " ").title()
    return ""


def _select_total_prices(market_payload: dict) -> tuple[float | None, float | None]:
    exact_over = None
    exact_under = None
    fallback_pairs: list[tuple[float, float | None, float | None]] = []
    over_map: dict[float, float] = {}
    under_map: dict[float, float] = {}

    for outcome in market_payload.get("outcomes", []):
        point = _safe_float(outcome.get("point"))
        price = _safe_float(outcome.get("price"))
        if point is None or price is None:
            continue
        name = str(outcome.get("name", "")).strip().lower()
        if name == "over":
            over_map[point] = price
        elif name == "under":
            under_map[point] = price

    if 2.5 in over_map and 2.5 in under_map:
        exact_over = over_map[2.5]
        exact_under = under_map[2.5]
        return exact_over, exact_under

    for point, over_price in over_map.items():
        fallback_pairs.append((abs(point - 2.5), over_price, under_map.get(point)))
    if not fallback_pairs:
        return None, None

    fallback_pairs.sort(key=lambda item: item[0])
    _, fallback_over, fallback_under = fallback_pairs[0]
    return fallback_over, fallback_under


class TheOddsApiClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("Missing PREMATCH_ODDS_API_KEY.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def list_sports(self, all_sports: bool = False) -> list[dict]:
        response = self.session.get(
            f"{self.base_url}/v4/sports",
            params={"apiKey": self.api_key, "all": str(all_sports).lower()},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_odds(self, sport_key: str, regions: str, markets: str, odds_format: str = "decimal", date_format: str = "iso") -> list[dict]:
        response = self.session.get(
            f"{self.base_url}/v4/sports/{sport_key}/odds",
            params={
                "apiKey": self.api_key,
                "regions": regions,
                "markets": markets,
                "oddsFormat": odds_format,
                "dateFormat": date_format,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def normalize_events(self, payload: list[dict], sport_key: str) -> list[NormalizedEvent]:
        captured_at_utc = datetime.now(timezone.utc)
        normalized: list[NormalizedEvent] = []

        for event in payload:
            home_team = str(event.get("home_team", "")).strip()
            away_team = str(event.get("away_team", "")).strip()
            if not home_team or not away_team:
                continue

            home_prices: list[float | None] = []
            draw_prices: list[float | None] = []
            away_prices: list[float | None] = []
            over_prices: list[float | None] = []
            under_prices: list[float | None] = []

            bookmakers = event.get("bookmakers") or []
            for bookmaker in bookmakers:
                h2h_market = None
                totals_market = None
                for market in bookmaker.get("markets", []):
                    key = str(market.get("key", "")).strip().lower()
                    if key == "h2h":
                        h2h_market = market
                    elif key == "totals":
                        totals_market = market

                if h2h_market:
                    for outcome in h2h_market.get("outcomes", []):
                        name = str(outcome.get("name", "")).strip()
                        price = _safe_float(outcome.get("price"))
                        lowered = name.lower()
                        if name == home_team:
                            home_prices.append(price)
                        elif name == away_team:
                            away_prices.append(price)
                        elif lowered == "draw":
                            draw_prices.append(price)

                if totals_market:
                    over_price, under_price = _select_total_prices(totals_market)
                    over_prices.append(over_price)
                    under_prices.append(under_price)

            bookmaker_count = len(bookmakers)
            if bookmaker_count == 0:
                continue

            league = str(event.get("sport_title") or sport_key).strip()
            country = _normalize_country(str(event.get("sport_key") or sport_key))
            tags = [str(event.get("sport_key") or sport_key)]
            if country:
                tags.append(country.lower())
            normalized.append(
                NormalizedEvent(
                    fixture_id=str(event.get("id")),
                    sport=str(sport_key.split("_", 1)[0]).strip().lower(),
                    country=country,
                    league=league,
                    home_team=home_team,
                    away_team=away_team,
                    kickoff_utc=parse_datetime(event["commence_time"]),
                    captured_at_utc=captured_at_utc,
                    bookmaker_count=bookmaker_count,
                    home_odds=_median_or_none(home_prices),
                    draw_odds=_median_or_none(draw_prices),
                    away_odds=_median_or_none(away_prices),
                    over25_odds=_median_or_none(over_prices),
                    under25_odds=_median_or_none(under_prices),
                    tags=tags,
                    notes=[f"source the-odds-api", f"bookmakers {bookmaker_count}"],
                    raw_payload=event,
                )
            )
        return normalized
