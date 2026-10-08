"""Il registro deve dire da dove viene un buco, e non disallinearsi mai.

Due difetti, trovati lo stesso giorno.

Il primo: observe_once trattava "la chiamata e' fallita" e "l'API non ha quel
dato" nello stesso modo, un payload vuoto, senza scrivere niente. Quando Fabio
ha chiesto perche' mancavano le statistiche ho dovuto rifare le chiamate a mano
il giorno dopo, perche' il registro non sapeva dirlo. Ora ogni riga porta la
provenienza: dati, vuoto, copertura, errore:...

Il secondo: append_row scrive i valori nell'ordine di COLUMNS sotto
l'intestazione che e' sul disco. Cambiare COLUMNS senza riscrivere
l'intestazione mette ogni valore nuovo sotto l'etichetta sbagliata - un
registro che sembra buono e non lo e'. Il modo peggiore di rompere una misura.
"""
import csv
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import second_half_observer as obs  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


class Risposta:
    def __init__(self, codice=200, payload=None, rompi_json=False):
        self.status_code = codice
        self._payload = payload if payload is not None else {"errors": [], "response": []}
        self._rompi = rompi_json

    def json(self):
        if self._rompi:
            raise ValueError("non e' json")
        return self._payload


class Api:
    def __init__(self, risposta):
        self.risposta = risposta

    def get(self, url, **kw):
        if isinstance(self.risposta, Exception):
            raise self.risposta
        return self.risposta


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_log_")
    log_vero, req_vero = obs.LOG_PATH, obs.requests
    obs.LOG_PATH = os.path.join(cartella, "registro.csv")
    try:
        return verifica()
    finally:
        obs.LOG_PATH, obs.requests = log_vero, req_vero
        obs._header_checked = False
        shutil.rmtree(cartella, ignore_errors=True)


def verifica() -> int:
    check("oracle_log_" in obs.LOG_PATH, "il cancello sta scrivendo sul registro del bot vivo")

    # 1. Le tre provenienze sono tre cose diverse.
    casi = [
        ("dati", Risposta(200, {"errors": [], "response": [{"statistics": []}]})),
        ("vuoto", Risposta(200, {"errors": [], "response": []})),
        ("errore:http429", Risposta(429, {})),
        ("errore:http500", Risposta(500, {})),
        ("errore:rispostaillegibile", Risposta(200, rompi_json=True)),
        ("errore:ConnectionError", ConnectionError("rete giu'")),
    ]
    for atteso, risposta in casi:
        obs.requests = Api(risposta)
        _, provenienza = obs.fetch_stats(1, {})
        check(provenienza == atteso,
              f"provenienza '{provenienza}' invece di '{atteso}'")

    # Un errore dichiarato dall'API nel corpo non e' una risposta vuota.
    obs.requests = Api(Risposta(200, {"errors": {"token": "chiave non valida"}, "response": []}))
    _, provenienza = obs.fetch_stats(1, {})
    check(provenienza.startswith("errore:"),
          f"un errore dichiarato nel corpo passa per risposta vuota: '{provenienza}'")
    check("chiave non valida" in provenienza,
          f"l'errore dell'API non viene riportato: '{provenienza}'")

    # IL PUNTO: vuoto ed errore non devono coincidere. Senza questa differenza
    # non si sa se il dato non c'e' o se non siamo riusciti a chiederlo.
    obs.requests = Api(Risposta(200, {"errors": [], "response": []}))
    _, vuoto = obs.fetch_stats(1, {})
    obs.requests = Api(Risposta(503, {}))
    _, errore = obs.fetch_stats(1, {})
    check(vuoto != errore, "vuoto ed errore sono ancora la stessa cosa")

    # 2. La provenienza finisce nella riga del registro.
    fixture = {"fixture": {"id": 7, "status": {"elapsed": 47}},
               "league": {"id": 72, "name": "Serie B", "country": "Brazil", "season": 2026},
               "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
               "score": {"halftime": {"home": 0, "away": 0}}}
    row = obs.build_row(fixture, {"totals": {}}, None, "2026-10-08T12:00:00+00:00",
                        stats_coperte=False, stats_source="copertura", events_source="dati")
    check(row.get("StatsSource") == "copertura", f"provenienza non registrata: {row}")
    check(row.get("EventsSource") == "dati", f"provenienza degli eventi non registrata: {row}")
    check(row.get("StatsCovered") is False, f"copertura non registrata: {row}")
    check(row.get("LeagueId") == 72, f"id della lega non registrato: {row}")
    for colonna in ("StatsSource", "EventsSource", "StatsCovered", "LeagueId", "GoalMinute"):
        check(colonna in obs.COLUMNS, f"la colonna {colonna} non e' nel registro")
    # I due campi inesistenti non devono tornare nel registro.
    for morto in ("Attacks", "DangerousAttacks"):
        check(morto not in obs.COLUMNS,
              f"la colonna {morto} e' tornata: due colonne sempre vuote invitano "
              f"a leggerle come zeri")

    # 3. La migrazione dell'intestazione: le righe restano, i valori non slittano.
    vecchie = ["ObservedAtUTC", "FixtureId", "LeagueName", "Country", "MatchUp",
               "Minute", "Corners", "Attacks", "DangerousAttacks", "ShotsOnGoal",
               "ShotsOffGoal", "YellowCards", "RedCards", "PossessionHome",
               "PossessionAway", "LiveOdd", "MissingFields", "Outcome",
               "CloseScore", "SettledTimeUTC"]
    with open(obs.LOG_PATH, "w", newline="", encoding="utf-8") as handle:
        scrittore = csv.DictWriter(handle, fieldnames=vecchie)
        scrittore.writeheader()
        scrittore.writerow({"ObservedAtUTC": "2026-10-07T20:03:45+00:00", "FixtureId": 1560841,
                            "LeagueName": "Copa Venezuela", "Country": "Venezuela",
                            "MatchUp": "Petare vs Avila", "Minute": 46, "Corners": "",
                            "Attacks": "", "DangerousAttacks": "", "ShotsOnGoal": "",
                            "Outcome": "LOSS", "CloseScore": "0-0", "LiveOdd": ""})
        scrittore.writerow({"ObservedAtUTC": "2026-10-08T09:00:00+00:00", "FixtureId": 1520919,
                            "LeagueName": "Serie B", "Country": "Brazil",
                            "MatchUp": "Vila Nova vs Cuiaba", "Minute": 47, "Corners": 4,
                            "ShotsOnGoal": 0, "LiveOdd": 1.40, "Outcome": "LOSS",
                            "CloseScore": "0-0", "Attacks": "", "DangerousAttacks": ""})

    esito = obs.migrate_log()
    check(esito == "migrato", f"la migrazione non avviene: {esito}")
    with open(obs.LOG_PATH, newline="", encoding="utf-8") as handle:
        lettore = csv.DictReader(handle)
        check(list(lettore.fieldnames) == obs.COLUMNS,
              f"intestazione non allineata dopo la migrazione: {lettore.fieldnames}")
        righe = list(lettore)
    check(len(righe) == 2, f"righe perse nella migrazione: {len(righe)} invece di 2")
    check(righe[1]["Corners"] == "4" and righe[1]["LiveOdd"] == "1.4",
          f"i valori sono slittati di colonna: {righe[1]}")
    check(righe[0]["Outcome"] == "LOSS" and righe[1]["MatchUp"] == "Vila Nova vs Cuiaba",
          f"righe rimescolate: {righe}")
    check(os.path.exists(obs.LOG_PATH + ".bak"),
          "la migrazione non lascia una copia: non si potrebbe annullare")
    check(obs.migrate_log() == "allineato",
          "la migrazione si ripete su un registro gia' allineato")

    # 4. E dopo la migrazione una scrittura nuova finisce sotto le etichette giuste.
    obs._header_checked = True
    obs.append_row(dict(row, Outcome="WIN", CloseScore="1-0", GoalMinute=50))
    import pandas as pd
    d = pd.read_csv(obs.LOG_PATH)
    ultima = d.iloc[-1]
    check(int(ultima["GoalMinute"]) == 50, f"GoalMinute finisce altrove: {dict(ultima)}")
    check(ultima["StatsSource"] == "copertura", f"StatsSource finisce altrove: {dict(ultima)}")
    check(int(ultima["FixtureId"]) == 7, f"FixtureId finisce altrove: {dict(ultima)}")

    # 5. CONTROLLO NEGATIVO: una colonna che sparisce CON dei dati dentro blocca
    #    la migrazione. Meglio un'intestazione vecchia di una perdita silenziosa.
    with open(obs.LOG_PATH, "w", newline="", encoding="utf-8") as handle:
        scrittore = csv.DictWriter(handle, fieldnames=vecchie)
        scrittore.writeheader()
        scrittore.writerow({"ObservedAtUTC": "x", "FixtureId": 1, "Attacks": 42})
    esito = obs.migrate_log()
    check(esito == "rifiutato",
          f"una colonna con dati viene cancellata in silenzio: esito {esito}")
    with open(obs.LOG_PATH, newline="", encoding="utf-8") as handle:
        check(list(csv.DictReader(handle).fieldnames) == vecchie,
              "il registro e' stato riscritto nonostante il rifiuto")

    # 6. Un registro assente non e' un errore: primo avvio.
    os.remove(obs.LOG_PATH)
    check(obs.migrate_log() == "assente", "un registro assente viene trattato come un guasto")
    obs._header_checked = False
    obs.ensure_log()
    with open(obs.LOG_PATH, newline="", encoding="utf-8") as handle:
        check(list(csv.DictReader(handle).fieldnames) == obs.COLUMNS,
              "un registro nuovo nasce con l'intestazione sbagliata")

    # 7. E la diagnostica deve ARRIVARE da qualche parte. Il bot gira sotto
    #    pythonw, che non ha una console: un print() finisce nel nulla, cioe'
    #    la riga che spiega perche' un dato manca non esiste.
    verifica_diagnostica()

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(casi)} provenienze distinte fra dati, vuoto ed errore; registro migrato "
          f"senza slittamenti, con copia; migrazione rifiutata se perderebbe dati; "
          f"diagnostica nel log del bot e non in una console che non esiste")
    print("log provenance verification passed")
    return 0


def verifica_diagnostica() -> None:
    import logging
    import api_coverage as cov

    # Nessun print nei due moduli: sotto pythonw non lo legge nessuno.
    for modulo in (obs, cov):
        sorgente = Path(modulo.__file__).read_text(encoding="utf-8").splitlines()
        colpevoli = [(n + 1, r.strip()) for n, r in enumerate(sorgente)
                     if r.strip().startswith("print(")]
        check(not colpevoli,
              f"{Path(modulo.__file__).name} usa print(), che sotto pythonw non arriva "
              f"in nessun log: righe {colpevoli}")
        # E il logger deve essere figlio di quello del bot, altrimenti le righe
        # non raggiungono oracle_live.log.
        check(modulo.logger.name.startswith("oracle_live."),
              f"{Path(modulo.__file__).name}: logger '{modulo.logger.name}' non e' figlio "
              f"di 'oracle_live': le righe non arriverebbero nel log del bot")

    # PROVA DI ARRIVO: un handler sul logger del bot deve vedere la riga.
    righe = []

    class Finto(logging.Handler):
        def emit(self, record):
            righe.append(record.getMessage())

    padre = logging.getLogger("oracle_live")
    handler = Finto()
    livello = padre.level
    padre.setLevel(logging.INFO)
    padre.addHandler(handler)
    try:
        # Un percorso di errore vero, non una chiamata a diario().
        pending_vero = obs.PENDING_PATH
        obs.PENDING_PATH = obs.LOG_PATH + ".attesarotta.json"
        with open(obs.PENDING_PATH, "w", encoding="utf-8") as handle:
            handle.write("{rotto")
        try:
            obs.load_pending()
        finally:
            os.remove(obs.PENDING_PATH)
            obs.PENDING_PATH = pending_vero
        check(any("OSSERVATORE47" in r and "illeggibile" in r for r in righe),
              f"un'attesa corrotta non lascia traccia nel log del bot: {righe}")
        cov.diario("prova")
        check(any(r.startswith("COPERTURA") for r in righe),
              f"la copertura non scrive nel log del bot: {righe}")
    finally:
        padre.removeHandler(handler)
        padre.setLevel(livello)


if __name__ == "__main__":
    raise SystemExit(main())
