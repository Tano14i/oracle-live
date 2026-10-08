"""Cosa l'API dichiara di raccogliere, competizione per competizione.

Nasce da una domanda di Fabio: perche' non abbiamo le statistiche su partite
che lui vede su Sofascore. La risposta non era un guasto nostro. Per quelle
competizioni /fixtures/statistics risponde HTTP 200, errors=[], results=0, con
il piano Ultra attivo e 2.700 chiamate su 75.000 usate: semplicemente l'API
non raccoglie quel dato la'. Lo dichiara lei stessa in /leagues, nel campo
coverage.fixtures.statistics_fixtures.

Verificato sulle quindici partite del registro dell'8 ottobre 2026: dove la
bandiera dice False arrivano zero campi, dove dice True arrivano sedici.
Quindici previsioni su quindici, nessun errore. Quindi la bandiera si puo'
leggere prima di chiamare: risparmia la chiamata e, soprattutto, permette di
scrivere "questa competizione non ha statistiche" invece di sette righe
"non disponibile" che sembrano un guasto.

La copertura e' per lega e stagione e non cambia durante la stagione, quindi
si chiede una volta e si tiene su disco. Una copertura ignota - chiamata
fallita - NON viene salvata come False: sarebbe un "non ci sono dati" inventato
da un errore di rete, lo stesso scambio fra assente e misurato che ha tenuto
"dangerous attacks" a zero per mesi.
"""
import json
import logging
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COVERAGE_PATH = os.path.join(BASE_DIR, "api_coverage.json")
LEAGUES_URL = "https://v3.football.api-sports.io/leagues"

# Chiavi che leggiamo dal blocco coverage. Nostro nome -> nome dell'API.
FIELDS = {
    "stats": "statistics_fixtures",
    "stats_players": "statistics_players",
    "events": "events",
    "lineups": "lineups",
}

logger = logging.getLogger("oracle_live.copertura")


def diario(message: str) -> None:
    logger.info(f"COPERTURA | {message}")


IGNOTA = {"stats": None, "events": None, "odds": None, "source": "ignota"}

_lock = threading.Lock()
_cache = {}
_loaded = False


def chiave(league_id, season) -> str:
    return f"{league_id}:{season}"


def load() -> int:
    """Rilegge la copertura salvata. Torna quante voci ha trovato."""
    global _loaded
    with _lock:
        _loaded = True
        if not os.path.exists(COVERAGE_PATH):
            return 0
        try:
            with open(COVERAGE_PATH, encoding="utf-8") as handle:
                dati = json.load(handle)
        except (OSError, ValueError) as exc:
            diario(f"file illeggibile ({exc}), riparto vuoto")
            return 0
        if isinstance(dati, dict):
            for k, v in dati.items():
                if isinstance(v, dict):
                    _cache[k] = v
        return len(_cache)


def save() -> None:
    with _lock:
        try:
            temporaneo = COVERAGE_PATH + ".tmp"
            with open(temporaneo, "w", encoding="utf-8") as handle:
                json.dump(_cache, handle, indent=1, sort_keys=True)
            os.replace(temporaneo, COVERAGE_PATH)
        except OSError as exc:
            diario(f"non salvata: {exc}")


def parse_response(payload, season) -> dict:
    """Estrae la copertura della stagione richiesta dalla risposta di /leagues."""
    for item in (payload or {}).get("response", []) or []:
        for stagione in item.get("seasons", []) or []:
            if stagione.get("year") != season:
                continue
            coperture = stagione.get("coverage") or {}
            fixtures = coperture.get("fixtures") or {}
            letta = {nostro: fixtures.get(loro) for nostro, loro in FIELDS.items()}
            letta["odds"] = coperture.get("odds")
            letta["league_name"] = (item.get("league") or {}).get("name")
            letta["source"] = "api"
            return letta
    return dict(IGNOTA)


def coverage_for(league_id, season, headers=None, fetch=None) -> dict:
    """La copertura di quella lega in quella stagione.

    `fetch(league_id)` permette di provare senza rete. Una risposta che non
    arriva torna IGNOTA e non viene messa in cache: la prossima volta si
    richiede, invece di portarsi dietro un falso "non coperta".
    """
    if not _loaded:
        load()
    if league_id is None or season is None:
        return dict(IGNOTA)
    k = chiave(league_id, season)
    if k in _cache:
        voce = dict(_cache[k])
        voce["source"] = "cache"
        return voce

    if fetch is None:
        if headers is None:
            return dict(IGNOTA)

        def fetch(lid):
            import requests
            risposta = requests.get(LEAGUES_URL, headers=headers,
                                    params={"id": lid}, timeout=20)
            if risposta.status_code != 200:
                return None
            return risposta.json()

    try:
        payload = fetch(league_id)
    except Exception as exc:
        diario(f"lega {league_id} non interrogabile: {exc}")
        return dict(IGNOTA)

    letta = parse_response(payload, season)
    if letta.get("stats") is None and letta.get("events") is None:
        return dict(IGNOTA)       # non la salvo: non so niente
    with _lock:
        _cache[k] = {kk: vv for kk, vv in letta.items() if kk != "source"}
    save()
    return letta


def has_stats(copertura: dict) -> bool:
    """True solo se l'API dichiara di raccogliere le statistiche.

    Una copertura ignota non e' un no: in quel caso si chiama e si vede, come
    si faceva prima di questo modulo.
    """
    return bool((copertura or {}).get("stats"))


def stats_hopeless(copertura: dict) -> bool:
    """True solo quando sappiamo per certo che non ci sono statistiche."""
    return (copertura or {}).get("stats") is False
