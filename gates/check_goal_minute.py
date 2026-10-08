"""Il minuto del gol non deve dipendere da una gara con l'API.

Port FC - Persib Bandung, 8 ottobre 2026. Segnale aperto al 46', chiuso alle
13:22:30 perche' /fixtures diceva 1-0. L'evento "66' Goal Penalty" e' comparso
nella risposta di /fixtures/events minuti dopo: l'API aggiorna il punteggio
prima di pubblicare l'evento. Chiedendo una volta sola al momento della
chiusura si perde quella gara quasi sempre, e il messaggio e' arrivato con
"gol nel secondo tempo" invece del minuto.

Due rimedi, e questo cancello verifica entrambi.

Il limite superiore: il minuto della partita quando abbiamo visto il punteggio
cambiato, che viene dallo stesso fixture e quindi c'e' sempre. Nel messaggio
va detto come limite - "gol entro il 67'" - non spacciato per il minuto esatto.

L'inseguimento: lo snapshot resta in coda in una seconda fase, solo per il
minuto. Quando l'evento compare, una riga nuova porta il minuto esatto e il
messaggio viene riscritto. Dopo un tetto di tentativi si rinuncia, perche'
inseguire per sempre un evento che non arriva costa una chiamata a ogni giro.

E l'esito non si registra due volte: un segnale in attesa di minuto non deve
tornare nel giro delle chiusure.
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
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


class Risposta:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Api:
    """Il fornitore come si e' comportato davvero: punteggio prima, evento poi."""

    def __init__(self, minuto_partita=67, con_evento=False):
        self.minuto_partita = minuto_partita
        self.con_evento = con_evento
        self.chiamate_eventi = 0

    def get(self, url, **kw):
        if "events" in url:
            self.chiamate_eventi += 1
            if not self.con_evento:
                return Risposta({"errors": [], "response": [
                    {"time": {"elapsed": 41}, "type": "Card", "detail": "Yellow Card",
                     "team": {"name": "Persib Bandung"}}]})
            return Risposta({"errors": [], "response": [
                {"time": {"elapsed": 41}, "type": "Card", "detail": "Yellow Card",
                 "team": {"name": "Persib Bandung"}},
                {"time": {"elapsed": 66}, "type": "Goal", "detail": "Penalty",
                 "team": {"name": "Port FC"}}]})
        if "statistics" in url:
            return Risposta({"errors": [], "response": []})
        return Risposta({"errors": [], "response": [{
            "fixture": {"id": 1551233,
                        "status": {"short": "2H", "elapsed": self.minuto_partita}},
            "league": {"id": 1130, "name": "ASEAN Club Championship",
                       "country": "World", "season": 2026},
            "teams": {"home": {"name": "Port FC"}, "away": {"name": "Persib Bandung"}},
            "goals": {"home": 1, "away": 0},
            "score": {"halftime": {"home": 0, "away": 0}},
        }]})


def snapshot():
    return {
        "row": {"ObservedAtUTC": datetime.now(timezone.utc).isoformat(),
                "FixtureId": 1551233, "MatchUp": "Port FC vs Persib Bandung",
                "Country": "World", "LeagueName": "ASEAN Club Championship",
                "Minute": 46, "LiveOdd": 1.33, "StatsCovered": False,
                "StatsSource": "copertura"},
        "capture": obs.merge_cards(sh.capture_fields([]), 1, 0),
        "message_id": 9100,
    }


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_minuto_")
    veri = (obs.LOG_PATH, obs.PENDING_PATH, obs.requests, obs.append_row)
    obs.LOG_PATH = os.path.join(cartella, "registro.csv")
    obs.PENDING_PATH = os.path.join(cartella, "attesa.json")
    try:
        return verifica()
    finally:
        obs.LOG_PATH, obs.PENDING_PATH, obs.requests, obs.append_row = veri
        obs._seen.clear()
        obs._header_checked = False
        shutil.rmtree(cartella, ignore_errors=True)


def verifica() -> int:
    check("oracle_minuto_" in obs.LOG_PATH, "il cancello scrive sul registro del bot vivo")

    righe, modifiche = [], []
    obs.append_row = lambda row: righe.append(dict(row))
    edit = lambda mid, testo: modifiche.append((mid, testo))  # noqa: E731

    # 1. Chiusura con l'evento non ancora pubblicato: l'esito si registra
    #    subito, con il limite superiore, e il messaggio lo dice come limite.
    obs._seen.clear()
    api = Api(minuto_partita=67, con_evento=False)
    obs.requests = api
    obs._seen[1551233] = snapshot()
    chiusi = obs.settle_once({}, edit)
    check(chiusi == 1, f"la chiusura non avviene: {chiusi}")
    check(len(righe) == 1 and righe[0].get("Outcome") == "WIN",
          f"esito non registrato subito: {righe}")
    check(righe and righe[0].get("GoalMinute") == "",
          f"minuto esatto inventato quando l'evento non c'e': {righe[0].get('GoalMinute')}")
    check(righe and righe[0].get("DetectedMinute") == 67,
          f"limite superiore non registrato: {righe[0].get('DetectedMinute')}")
    check(modifiche and "entro il 67'" in modifiche[0][1],
          f"il messaggio non dichiara il minuto come limite:\n{modifiche}")
    check(modifiche and "gol al 67'" not in modifiche[0][1],
          f"un limite superiore viene spacciato per il minuto del gol:\n{modifiche}")
    check("DetectedMinute" in obs.COLUMNS, "la colonna DetectedMinute non e' nel registro")

    # 2. Lo snapshot resta in coda SOLO per il minuto, e non viene richiuso.
    # Nessun accesso diretto alla chiave: un cancello che si schianta con un
    # KeyError non diagnostica nulla. E' il modo in cui questo stesso cancello
    # mi e' sfuggito al primo controllo negativo.
    in_coda = obs._seen.get(1551233)
    check(in_coda is not None,
          "lo snapshot sparisce dopo la chiusura e il minuto esatto non arrivera' mai")
    check((in_coda or {}).get("fase") == obs.FASE_MINUTO,
          f"fase sbagliata: {(in_coda or {}).get('fase')}")
    righe.clear()
    modifiche.clear()
    check(obs.settle_once({}, edit) == 0,
          "un segnale in attesa di minuto viene richiuso: due esiti per un segnale")
    check(righe == [], f"secondo esito registrato per lo stesso segnale: {righe}")

    # 3. Quando l'evento compare: riga nuova col minuto esatto, messaggio riscritto.
    api.con_evento = True
    completati = obs.backfill_once({}, edit)
    check(completati == 1, f"il minuto non viene recuperato: {completati}")
    check(len(righe) == 1 and righe[0].get("GoalMinute") == 66,
          f"minuto esatto non registrato: {righe}")
    check(righe and righe[0].get("Outcome") == "WIN",
          f"la riga di completamento perde l'esito: {righe}")
    check(righe and righe[0].get("DetectedMinute") == 67,
          "la riga di completamento perde il limite superiore")
    check(modifiche and "gol al 66'" in modifiche[0][1],
          f"il messaggio non viene riscritto col minuto esatto:\n{modifiche}")
    check(modifiche and modifiche[0][0] == 9100,
          f"la modifica non usa il messaggio di apertura: {modifiche}")
    check(1551233 not in obs._seen, "lo snapshot completato resta in coda per sempre")

    # 4. Si rinuncia dopo il tetto di tentativi, senza inventare il minuto.
    obs._seen.clear()
    righe.clear()
    modifiche.clear()
    obs.requests = Api(minuto_partita=67, con_evento=False)
    obs._seen[1551233] = dict(snapshot(), fase=obs.FASE_MINUTO, tentativi=0)
    obs._seen[1551233]["row"] = dict(obs._seen[1551233]["row"], Outcome="WIN",
                                     CloseScore="1-0", DetectedMinute=67)
    giri = 0
    while 1551233 in obs._seen and giri < obs.MAX_TENTATIVI_MINUTO * 3:
        obs.backfill_once({}, edit)
        giri += 1
    check(giri == obs.MAX_TENTATIVI_MINUTO,
          f"si rinuncia dopo {giri} giri invece di {obs.MAX_TENTATIVI_MINUTO}")
    check(righe == [], f"rinunciando si scrive una riga con un minuto inventato: {righe}")
    check(modifiche == [], f"rinunciando si riscrive il messaggio: {modifiche}")

    # CONTROLLO NEGATIVO: col minuto esatto disponibile alla chiusura non si
    # entra affatto nella seconda fase, e non si spreca nessuna chiamata.
    obs._seen.clear()
    righe.clear()
    modifiche.clear()
    api = Api(minuto_partita=67, con_evento=True)
    obs.requests = api
    obs._seen[1551233] = snapshot()
    obs.settle_once({}, edit)
    check(righe and righe[0].get("GoalMinute") == 66,
          f"il minuto esatto disponibile non viene usato: {righe}")
    check(1551233 not in obs._seen,
          "si entra nella fase del minuto anche avendolo gia': chiamate sprecate")
    check(modifiche and "gol al 66'" in modifiche[0][1],
          f"il messaggio non porta il minuto esatto:\n{modifiche}")
    prima = api.chiamate_eventi
    check(obs.backfill_once({}, edit) == 0, "backfill_once lavora su niente")
    check(api.chiamate_eventi == prima,
          "backfill_once chiama gli eventi senza avere niente da completare")

    # 5. La fase sopravvive al riavvio: un minuto inseguito a cavallo di un
    #    riavvio non deve ripartire come una chiusura.
    obs._seen.clear()
    obs._seen[1551233] = dict(snapshot(), fase=obs.FASE_MINUTO, tentativi=3)
    obs.save_pending()
    obs._seen.clear()
    obs.load_pending()
    ripreso = obs._seen.get(1551233) or {}
    check(ripreso.get("fase") == obs.FASE_MINUTO,
          f"dopo il riavvio la fase e' {ripreso.get('fase')}: il segnale verrebbe richiuso")
    check(ripreso.get("tentativi") == 3,
          f"i tentativi non sopravvivono: {ripreso.get('tentativi')}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"esito registrato subito col limite superiore e dichiarato come limite; "
          f"minuto esatto inseguito e riscritto; nessun doppio esito; resa dopo "
          f"{obs.MAX_TENTATIVI_MINUTO} tentativi senza inventare niente")
    print("goal minute verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
