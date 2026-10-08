"""Dove le statistiche non ci sono, gli eventi ci sono: cartellini e minuto del gol.

Su tutte le competizioni del registro dell'8 ottobre 2026 - comprese le dodici
senza statistiche - l'API dichiara events=True, e un endpoint che non
chiamavamo mai. Sulla partita del Kazakhstan /fixtures/events risponde:

    20'  Card  Red Card      Akademiya Ontustik
    50'  Goal  Normal Goal   Shakhter Karagandy

Da la' vengono due cose. I cartellini, l'unico dei sette campi chiesti che si
recupera anche dove le statistiche non sono raccolte. E il minuto del gol, che
e' il dato mancante per sapere se al 47' conviene entrare o aspettare: finora
sapevamo che un gol era arrivato, non quando.

Il cancello pretende che nessuna delle due deduzioni inventi numeri: una lista
di eventi vuota non e' "zero cartellini", un rigore sbagliato non e' un gol, un
gol del primo tempo non e' un gol del secondo, e un dato misurato dalle
statistiche non viene sovrascritto da uno dedotto.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import second_half as sh  # noqa: E402
import second_half_observer as obs  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def evento(minuto, tipo, dettaglio, squadra="A", extra=None):
    return {"time": {"elapsed": minuto, "extra": extra}, "type": tipo,
            "detail": dettaglio, "team": {"name": squadra}}


# Gli eventi veri di Shakhter Karagandy - Akademiya Ontustik.
KAZAKHSTAN = [evento(20, "Card", "Red Card", "Akademiya Ontustik"),
              evento(50, "Goal", "Normal Goal", "Shakhter Karagandy")]


def main() -> int:
    # 1. Cartellini dagli eventi.
    gialli, rossi = obs.cards_from_events(KAZAKHSTAN)
    check((gialli, rossi) == (0, 1), f"cartellini del Kazakhstan letti male: {gialli}G {rossi}R")

    misti = [evento(10, "Card", "Yellow Card"), evento(30, "Card", "Yellow Card"),
             evento(44, "Card", "Second Yellow card"), evento(70, "Card", "Red Card"),
             evento(55, "subst", "Substitution 1"), evento(60, "Goal", "Normal Goal")]
    gialli, rossi = obs.cards_from_events(misti)
    check(gialli == 3, f"gialli contati male: {gialli} invece di 3 (il secondo giallo e' un giallo)")
    check(rossi == 1, f"rossi contati male: {rossi} invece di 1")

    # IL PUNTO: nessun evento non e' zero cartellini.
    check(obs.cards_from_events([]) == (None, None),
          "una lista vuota diventa zero cartellini: un numero inventato")
    check(obs.cards_from_events(None) == (None, None),
          "eventi assenti diventano zero cartellini")
    # Ma eventi senza cartellini SONO zero cartellini: e' una misura.
    check(obs.cards_from_events([evento(60, "Goal", "Normal Goal")]) == (0, 0),
          "una partita con eventi e senza cartellini non viene misurata come zero")

    # 2. I cartellini dedotti entrano nella cattura solo dove mancano.
    vuota = sh.capture_fields([])
    unita = obs.merge_cards(vuota, 2, 1)
    check(unita["totals"].get("yellow cards") == 2.0,
          f"cartellini degli eventi non uniti alla cattura: {unita['totals']}")
    testo = sh.format_stats_block(unita, sh.NOTE_NO_STATS)
    check("Cartellini: 3" in testo, f"i cartellini dedotti non arrivano nel messaggio:\n{testo}")

    # Un dato misurato non si sovrascrive con uno dedotto.
    misurata = sh.capture_fields([
        {"statistics": [{"type": "Yellow Cards", "value": 5},
                        {"type": "Red Cards", "value": 0}]}])
    dopo = obs.merge_cards(misurata, 99, 99)
    check(dopo["totals"].get("yellow cards") == 5.0,
          f"un dato delle statistiche viene sovrascritto da quello degli eventi: {dopo['totals']}")
    check(dopo["totals"].get("red cards") == 0.0,
          f"uno zero misurato viene sovrascritto da un dedotto: {dopo['totals']}")
    # E senza niente da unire la cattura non cambia.
    prima = sh.capture_fields([{"statistics": [{"type": "Corner Kicks", "value": 3}]}])
    check(obs.merge_cards(prima, None, None)["totals"] == {"corner kicks": 3.0},
          "merge_cards tocca la cattura anche senza cartellini da unire")

    # 3. Minuto del primo gol del secondo tempo.
    check(obs.first_second_half_goal(KAZAKHSTAN) == 50,
          f"minuto del gol sbagliato: {obs.first_second_half_goal(KAZAKHSTAN)}")
    due = [evento(80, "Goal", "Normal Goal"), evento(52, "Goal", "Penalty")]
    check(obs.first_second_half_goal(due) == 52,
          f"non viene preso il primo dei due gol: {obs.first_second_half_goal(due)}")

    # Un rigore sbagliato ha type Goal nell'API: non e' un gol.
    sbagliato = [evento(48, "Goal", "Missed Penalty"), evento(77, "Goal", "Normal Goal")]
    check(obs.first_second_half_goal(sbagliato) == 77,
          f"un rigore sbagliato viene contato come gol: "
          f"{obs.first_second_half_goal(sbagliato)}")

    # Un gol del primo tempo non e' un gol del secondo, nemmeno nei recuperi.
    primo = [evento(42, "Goal", "Normal Goal"), evento(45, "Goal", "Normal Goal", extra=2)]
    check(obs.first_second_half_goal(primo) is None,
          f"un gol del primo tempo viene preso per uno del secondo: "
          f"{obs.first_second_half_goal(primo)}")
    check(obs.first_second_half_goal([]) is None, "senza eventi viene inventato un minuto")
    check(obs.first_second_half_goal([evento(None, "Goal", "Normal Goal")]) is None,
          "un gol senza minuto diventa un minuto")

    # 4. Il minuto del gol finisce nel messaggio modificato.
    base = {"MatchUp": "A vs B", "Country": "X", "LeagueName": "Y", "Minute": 47,
            "LiveOdd": 1.30, "Outcome": "WIN", "CloseScore": "1-0"}
    con = obs.format_message(dict(base, GoalMinute=50), vuota)
    check("gol al 50'" in con, f"il minuto del gol non compare nel messaggio:\n{con}")
    senza = obs.format_message(dict(base), vuota)
    check("VINTO" in senza and "gol al" not in senza,
          f"senza minuto il messaggio ne inventa uno:\n{senza}")

    # 5. Il punteggio dell'intervallo si legge da score.halftime.
    fixture = {"score": {"halftime": {"home": 0, "away": 1},
                         "fulltime": {"home": 0, "away": 0}}}
    check(obs.halftime_total(fixture) == 1,
          f"punteggio dell'intervallo letto male: {obs.halftime_total(fixture)}")
    check(obs.halftime_total({"score": {"halftime": {"home": 0, "away": 0}}}) == 0,
          "uno 0-0 all'intervallo non viene letto come zero")
    check(obs.halftime_total({"score": {"halftime": {"home": None, "away": None}}}) is None,
          "un intervallo non ancora noto diventa zero gol")
    check(obs.halftime_total({}) is None, "un fixture senza score diventa 0-0")

    # 6. E observe_once lo passa davvero al cancello: una funzione giusta
    #    chiamata senza il parametro non protegge niente.
    verifica_cablaggio()

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print("cartellini dedotti dagli eventi senza inventare zeri, dato misurato mai "
          "sovrascritto, rigore sbagliato e gol del primo tempo esclusi, minuto nel messaggio")
    print("events fallback verification passed")
    return 0


class Risposta:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Api:
    def __init__(self, partita):
        self.partita = partita

    def get(self, url, **kw):
        if "statistics" in url or "events" in url:
            return Risposta({"errors": [], "response": []})
        return Risposta({"errors": [], "response": [self.partita]})


def partita_con(halftime, live):
    return {
        "fixture": {"id": 4242, "status": {"short": "2H", "elapsed": 47}},
        "league": {"id": 1113, "name": "Copa Venezuela", "country": "Venezuela",
                   "season": 2026},
        "teams": {"home": {"name": "Petare FC"}, "away": {"name": "Atletico Avila FC"}},
        "goals": {"home": live, "away": 0},
        "score": {"halftime": {"home": halftime, "away": 0}},
    }


def verifica_cablaggio() -> None:
    """observe_once deve passare score.halftime al cancello.

    Il caso vero: Petare-Atletico Avila, 7 ottobre 2026. goals e score dicevano
    0-0, gli eventi un gol al 42'. Se il punteggio dell'intervallo dice che 0-0
    non era, il segnale non si apre, qualunque cosa dica il punteggio live.
    """
    import os
    righe = []
    append_vero, requests_vero, pending_vero = obs.append_row, obs.requests, obs.PENDING_PATH
    obs.append_row = lambda row: righe.append(dict(row))
    obs.PENDING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "_attesa_di_prova.json")
    coperta = lambda lid, s: {"stats": True, "events": True}  # noqa: E731
    try:
        # 0-1 all'intervallo con il punteggio live in ritardo a 0-0: niente.
        obs._seen.clear()
        obs.requests = Api(partita_con(halftime=1, live=0))
        aperti = obs.observe_once({}, lambda t: 1, None, coverage=coperta)
        check(aperti == 0,
              "observe_once apre un segnale su una partita che all'intervallo non era 0-0: "
              "il punteggio dell'intervallo non arriva al cancello")
        check(righe == [], f"riga registrata per un segnale che non va aperto: {righe}")

        # CONTROLLO POSITIVO: 0-0 all'intervallo e 0-0 adesso si apre.
        obs._seen.clear()
        obs.requests = Api(partita_con(halftime=0, live=0))
        check(obs.observe_once({}, lambda t: 1, None, coverage=coperta) == 1,
              "una partita 0-0 all'intervallo non viene piu' aperta")
    finally:
        obs.append_row, obs.requests = append_vero, requests_vero
        if os.path.exists(obs.PENDING_PATH):
            os.remove(obs.PENDING_PATH)
        obs.PENDING_PATH = pending_vero
        obs._seen.clear()


if __name__ == "__main__":
    raise SystemExit(main())
