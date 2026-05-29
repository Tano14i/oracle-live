from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

import requests

from oracle_prematch.loader import parse_datetime


MATCH_WINNER_NAMES = {"match winner", "fulltime result"}
TOTAL_GOALS_NAMES = {"goals over/under", "match goals"}


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


def _extract_match_winner(bets: list[dict]) -> tuple[float | None, float | None, float | None]:
    for bet in bets:
        bet_name = str(bet.get("name", "")).strip().lower()
        if bet_name not in MATCH_WINNER_NAMES:
            continue
        home_price = None
        draw_price = None
        away_price = None
        for value in bet.get("values", []):
            label = str(value.get("value", "")).strip().lower()
            odd = _safe_float(value.get("odd"))
            if label == "home":
                home_price = odd
            elif label == "draw":
                draw_price = odd
            elif label == "away":
                away_price = odd
        if any(item is not None for item in (home_price, draw_price, away_price)):
            return home_price, draw_price, away_price
    return None, None, None


def _extract_totals_25(bets: list[dict]) -> tuple[float | None, float | None]:
    for bet in bets:
        bet_name = str(bet.get("name", "")).strip().lower()
        if bet_name not in TOTAL_GOALS_NAMES:
            continue
        over_price = None
        under_price = None
        for value in bet.get("values", []):
            label = str(value.get("value", "")).strip().lower()
            handicap = str(value.get("handicap", "")).strip()
            odd = _safe_float(value.get("odd"))
            if label == "over" and handicap == "2.5":
                over_price = odd
            elif label == "under" and handicap == "2.5":
                under_price = odd
            elif label == "over 2.5":
                over_price = odd
            elif label == "under 2.5":
                under_price = odd
        if over_price is not None or under_price is not None:
            return over_price, under_price
    return None, None


class ApiFootballOddsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("Missing PREMATCH_API_FOOTBALL_KEY or API_KEY.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})

    def _get(self, endpoint: str, params: dict) -> dict:
        response = self.session.get(f"{self.base_url}{endpoint}", params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"API-FOOTBALL error on {endpoint}: {errors}")
        return payload

    def list_bookmakers(self) -> list[dict]:
        payload = self._get("/odds/bookmakers", {})
        return payload.get("response", [])

    def fetch_odds(self, date_value: str, league_ids: list[int] | None = None, season: int | None = None, page_limit: int | None = None) -> list[dict]:
        rows: list[dict] = []
        league_filter = set(league_ids or [])
        pages_fetched = 0
        page = 1
        while True:
            params: dict[str, str | int] = {"date": date_value, "page": page}
            if season is not None:
                params["season"] = season
            if league_ids and len(league_ids) == 1:
                params["league"] = league_ids[0]
            payload = self._get("/odds", params)
            page_rows = payload.get("response", [])
            if league_filter and len(league_filter) > 1:
                page_rows = [row for row in page_rows if int((row.get("league") or {}).get("id") or 0) in league_filter]
            rows.extend(page_rows)
            current = int(((payload.get("paging") or {}).get("current")) or page)
            total = int(((payload.get("paging") or {}).get("total")) or current)
            pages_fetched += 1
            if current >= total:
                break
            if page_limit is not None and pages_fetched >= page_limit:
                break
            page += 1
            time.sleep(0.2)
        return rows

    def fetch_fixtures_for_date(
        self,
        date_value: str,
        fixture_ids: list[str],
        league_ids: list[int] | None = None,
        season: int | None = None,
        page_limit: int | None = None,
    ) -> dict[str, dict]:
        wanted_ids = set(str(item) for item in fixture_ids if str(item).strip())
        if not wanted_ids:
            return {}
        fixtures: dict[str, dict] = {}
        league_filter = set(league_ids or [])
        params: dict[str, str | int] = {"date": date_value}
        if season is not None:
            params["season"] = season
        if league_filter and len(league_filter) == 1:
            params["league"] = next(iter(league_filter))
        payload = self._get("/fixtures", params)
        page_rows = payload.get("response", [])
        for row in page_rows:
            current_id = str(((row.get("fixture") or {}).get("id")) or "").strip()
            if not current_id or current_id not in wanted_ids:
                continue
            if league_filter and len(league_filter) > 1:
                current_league_id = int(((row.get("league") or {}).get("id")) or 0)
                if current_league_id not in league_filter:
                    continue
            fixtures[current_id] = row
        return fixtures

    def normalize_events(self, odds_rows: list[dict], fixtures_by_id: dict[str, dict]) -> list[NormalizedEvent]:
        captured_at_utc = datetime.now(timezone.utc)
        normalized: list[NormalizedEvent] = []

        for row in odds_rows:
            fixture_info = row.get("fixture") or {}
            fixture_id = str(fixture_info.get("id") or "").strip()
            fixture_payload = fixtures_by_id.get(fixture_id)
            if not fixture_id or not fixture_payload:
                continue

            teams = fixture_payload.get("teams") or {}
            home_team = str(((teams.get("home") or {}).get("name")) or "").strip()
            away_team = str(((teams.get("away") or {}).get("name")) or "").strip()
            if not home_team or not away_team:
                continue

            league = row.get("league") or {}
            bookmaker_count = len(row.get("bookmakers") or [])
            if bookmaker_count == 0:
                continue

            home_prices: list[float | None] = []
            draw_prices: list[float | None] = []
            away_prices: list[float | None] = []
            over_prices: list[float | None] = []
            under_prices: list[float | None] = []

            for bookmaker in row.get("bookmakers", []):
                bets = bookmaker.get("bets") or []
                home_price, draw_price, away_price = _extract_match_winner(bets)
                over_price, under_price = _extract_totals_25(bets)
                home_prices.append(home_price)
                draw_prices.append(draw_price)
                away_prices.append(away_price)
                over_prices.append(over_price)
                under_prices.append(under_price)

            country = str(league.get("country") or "").strip()
            league_name = str(league.get("name") or "").strip()
            season = str(league.get("season") or "").strip()
            normalized.append(
                NormalizedEvent(
                    fixture_id=fixture_id,
                    sport="football",
                    country=country,
                    league=league_name,
                    home_team=home_team,
                    away_team=away_team,
                    kickoff_utc=parse_datetime(str(fixture_info.get("date"))),
                    captured_at_utc=captured_at_utc,
                    bookmaker_count=bookmaker_count,
                    home_odds=_median_or_none(home_prices),
                    draw_odds=_median_or_none(draw_prices),
                    away_odds=_median_or_none(away_prices),
                    over25_odds=_median_or_none(over_prices),
                    under25_odds=_median_or_none(under_prices),
                    tags=[country.lower(), league_name.lower(), f"season-{season}"] if country and league_name else [f"season-{season}"],
                    notes=["source api-football", f"bookmakers {bookmaker_count}", f"api update {row.get('update')}"],
                    raw_payload={"odds": row, "fixture": fixture_payload},
                )
            )
        return normalized
