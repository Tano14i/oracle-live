"""Una risposta vuota dell'API non e' un nostro guasto, e va distinta.

Fabio vedeva su Sofascore le statistiche di partite su cui il nostro messaggio
scriveva sette "non disponibile". La verifica, fatta l'8 ottobre 2026:
/fixtures/statistics risponde HTTP 200, errors=[], results=0, con piano Ultra
attivo e 2.700 chiamate su 75.000. Non un errore: l'API dichiara in /leagues,
nel campo coverage.fixtures.statistics_fixtures, di non raccogliere quel dato
per quelle competizioni. Su quindici partite del registro la bandiera ha
previsto il risultato quindici volte - False -> zero campi, True -> sedici.

Questo cancello pretende tre cose. Che la copertura venga letta dalla forma
reale della risposta. Che una copertura ignota - chiamata fallita - NON venga
registrata come "non coperta": sarebbe un "non ci sono dati" inventato da un
errore di rete, lo stesso scambio fra assente e misurato che ha tenuto
"dangerous attacks" a zero per mesi. E che una copertura nota venga chiesta una
volta sola, perche' una chiamata per partita su un dato che cambia una volta
all'anno e' spreco.
"""
import json
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

import api_coverage as cov  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


# La risposta reale di /leagues?id=72 (Brasile Serie B), ridotta ai campi che
# leggiamo. Le stagioni sono piu' di una di proposito: va presa quella giusta.
RISPOSTA_SERIE_B = {
    "errors": [],
    "results": 1,
    "response": [{
        "league": {"id": 72, "name": "Serie B", "type": "League"},
        "country": {"name": "Brazil"},
        "seasons": [
            {"year": 2025, "coverage": {"fixtures": {"statistics_fixtures": False,
                                                     "statistics_players": False,
                                                     "events": True, "lineups": True},
                                        "odds": False}},
            {"year": 2026, "coverage": {"fixtures": {"statistics_fixtures": True,
                                                     "statistics_players": True,
                                                     "events": True, "lineups": True},
                                        "odds": True}},
        ],
    }],
}

# La risposta reale di /leagues?id=388 (Kazakhstan 1. Division).
RISPOSTA_KAZAKHSTAN = {
    "errors": [],
    "results": 1,
    "response": [{
        "league": {"id": 388, "name": "1. Division"},
        "seasons": [
            {"year": 2026, "coverage": {"fixtures": {"statistics_fixtures": False,
                                                     "statistics_players": False,
                                                     "events": True, "lineups": True},
                                        "odds": True}},
        ],
    }],
}


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_cov_")
    vero = cov.COVERAGE_PATH
    cov.COVERAGE_PATH = os.path.join(cartella, "coverage.json")
    cov._cache.clear()
    cov._loaded = True
    try:
        return verifica()
    finally:
        cov.COVERAGE_PATH = vero
        cov._cache.clear()
        cov._loaded = False
        shutil.rmtree(cartella, ignore_errors=True)


def verifica() -> int:
    check(cov.COVERAGE_PATH.endswith("coverage.json") and "oracle_cov_" in cov.COVERAGE_PATH,
          "il cancello sta scrivendo sulla copertura del bot vivo")

    # 1. La forma reale della risposta viene letta, e la stagione conta.
    chiamate = []

    def fetch_serie_b(lid):
        chiamate.append(lid)
        return RISPOSTA_SERIE_B

    c = cov.coverage_for(72, 2026, fetch=fetch_serie_b)
    check(c.get("stats") is True, f"copertura 2026 letta male: {c}")
    check(c.get("events") is True, f"events letto male: {c}")
    check(c.get("odds") is True, f"odds letto male: {c}")
    check(c.get("league_name") == "Serie B", f"nome della lega perso: {c}")
    check(cov.has_stats(c), "has_stats dice no su una lega coperta")
    check(not cov.stats_hopeless(c), "stats_hopeless dice si su una lega coperta")

    cov._cache.clear()
    c2025 = cov.coverage_for(72, 2025, fetch=fetch_serie_b)
    check(c2025.get("stats") is False,
          f"viene letta la stagione sbagliata: 2025 risulta {c2025.get('stats')}")

    # 2. Il caso che ha aperto tutto: bandiera False, e si sa prima di chiamare.
    cov._cache.clear()
    k = cov.coverage_for(388, 2026, fetch=lambda lid: RISPOSTA_KAZAKHSTAN)
    check(k.get("stats") is False, f"Kazakhstan: statistiche date per coperte: {k}")
    check(cov.stats_hopeless(k),
          "la copertura negativa non viene riconosciuta: la chiamata inutile resta")
    check(k.get("events") is True,
          "events dato per non coperto: i cartellini si perderebbero anche la'")

    # 3. Si chiede una volta sola.
    cov._cache.clear()
    chiamate.clear()
    for _ in range(5):
        cov.coverage_for(72, 2026, fetch=fetch_serie_b)
    check(len(chiamate) == 1,
          f"la copertura viene richiesta {len(chiamate)} volte invece di una")

    # ...e sopravvive al riavvio, altrimenti ogni riavvio rifa' le chiamate.
    salvato = json.load(open(cov.COVERAGE_PATH, encoding="utf-8"))
    check("72:2026" in salvato, f"copertura non salvata su disco: {list(salvato)}")
    cov._cache.clear()
    cov._loaded = False
    check(cov.load() == 1, "la copertura salvata non viene ripresa")
    chiamate.clear()
    ripresa = cov.coverage_for(72, 2026, fetch=fetch_serie_b)
    check(chiamate == [], "dopo il riavvio la copertura viene richiesta di nuovo")
    check(ripresa.get("stats") is True, f"copertura ripresa sbagliata: {ripresa}")
    check(ripresa.get("source") == "cache", f"provenienza non dichiarata: {ripresa}")

    # 4. IL PUNTO CHE CONTA: una chiamata fallita non diventa "non coperta".
    for descrizione, rotto in (
        ("chiamata che solleva", "alza"),
        ("risposta vuota", {"errors": [], "response": []}),
        ("risposta None", None),
        ("lega sconosciuta", {"errors": {"id": "non esiste"}, "response": []}),
        ("stagione assente", RISPOSTA_KAZAKHSTAN),   # chiesta 2030
    ):
        cov._cache.clear()
        stagione = 2030 if descrizione == "stagione assente" else 2026

        def fetch(lid, payload=rotto):
            if payload == "alza":
                raise RuntimeError("rete giu'")
            return payload

        r = cov.coverage_for(999, stagione, fetch=fetch)
        check(r.get("stats") is None,
              f"{descrizione}: copertura inventata {r.get('stats')} invece di ignota")
        check(not cov.stats_hopeless(r),
              f"{descrizione}: una copertura ignota viene trattata come un rifiuto, "
              f"e la chiamata alle statistiche non verrebbe piu' fatta")
        check(cov.chiave(999, stagione) not in cov._cache,
              f"{descrizione}: l'ignoto viene messo in cache e non si riprova piu'")

    # 5. Senza lega o stagione non si inventa niente.
    for lid, season in ((None, 2026), (72, None), (None, None)):
        r = cov.coverage_for(lid, season, fetch=lambda x: RISPOSTA_SERIE_B)
        check(r.get("stats") is None, f"copertura inventata per lega={lid} stagione={season}")

    # 6. Un file di copertura corrotto non impedisce l'avvio.
    with open(cov.COVERAGE_PATH, "w", encoding="utf-8") as handle:
        handle.write("{non json")
    cov._cache.clear()
    cov._loaded = False
    try:
        check(cov.load() == 0, "un file corrotto porta dentro voci inventate")
    except Exception as exc:
        FAIL.append(f"un file di copertura corrotto impedisce l'avvio: {exc}")

    # 7. La copertura serve a qualcosa: dove dice no, la chiamata alle
    #    statistiche non si fa, e il messaggio dice la ragione invece di
    #    elencare sette "non disponibile".
    verifica_osservatore()

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print("copertura letta dalla forma reale per stagione, chiesta una volta e "
          "ripresa dopo il riavvio, ignota mai scambiata per 'non coperta'; "
          "dove dice no la chiamata non si fa e il messaggio spiega perche'")
    print("api coverage verification passed")
    return 0


class RispostaFinta:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class ApiContata:
    """Conta quali endpoint vengono chiamati davvero."""

    def __init__(self, partita):
        self.chiamati = []
        self.partita = partita
        self.vuote = False      # imita la Liga 3 georgiana: coperta e senza dati

    def get(self, url, **kw):
        self.chiamati.append(url.rsplit("/fixtures", 1)[-1] or "/fixtures")
        if "statistics" in url:
            if self.vuote:
                return RispostaFinta({"errors": [], "response": []})
            return RispostaFinta({"errors": [], "response": [
                {"statistics": [{"type": "Corner Kicks", "value": 3}]}]})
        if "events" in url:
            return RispostaFinta({"errors": [], "response": [
                {"time": {"elapsed": 20}, "type": "Card", "detail": "Red Card",
                 "team": {"name": "Akademiya Ontustik"}}]})
        return RispostaFinta({"errors": [], "response": [self.partita]})


class ModelloFinto:
    """Modello iniettato: le squadre di prova non stanno nello storico, quindi
    il modello vero non le riconosce e il segnale resterebbe muto. Qui si prova
    l'invio, non la selezione - quella ha il suo cancello (G31)."""

    @staticmethod
    def probabilita(casa, fuori):
        return 0.95, "modello finto"

    @staticmethod
    def selezionato(p):
        return True

    @staticmethod
    def soglia_decile_alto():
        return 0.7915793918550821


def verifica_osservatore() -> None:
    import second_half as sh
    import second_half_observer as obs

    partita = {
        "fixture": {"id": 1534867, "status": {"short": "2H", "elapsed": 46}},
        "league": {"id": 388, "name": "1. Division", "country": "Kazakhstan", "season": 2026},
        "teams": {"home": {"name": "Shakhter Karagandy"},
                  "away": {"name": "Akademiya Ontustik"}},
        "goals": {"home": 0, "away": 0},
        "score": {"halftime": {"home": 0, "away": 0}},
    }

    righe, inviati = [], []
    append_vero, requests_vero, pending_vero = obs.append_row, obs.requests, obs.PENDING_PATH
    modello_vero = obs.modello_2t
    obs.modello_2t = ModelloFinto
    obs.append_row = lambda row: righe.append(dict(row))
    obs.PENDING_PATH = cov.COVERAGE_PATH + ".attesa"
    api = ApiContata(partita)
    obs.requests = api
    obs._seen.clear()
    try:
        aperti = obs.observe_once({}, lambda t: inviati.append(t) or 1, None,
                                  coverage=lambda lid, s: {"stats": False, "events": True})
        check(aperti == 1, f"la partita non viene aperta: {aperti}")
        check("/statistics" not in api.chiamati,
              f"le statistiche vengono chieste a una lega che non le ha: {api.chiamati}")
        check("/events" in api.chiamati,
              f"gli eventi non vengono chiesti: {api.chiamati}")
        check(righe and righe[0].get("StatsSource") == "copertura",
              f"provenienza non registrata come copertura: {righe}")
        check(righe and righe[0].get("StatsCovered") is False,
              f"copertura non registrata nella riga: {righe}")
        # Il cartellino rosso degli eventi arriva comunque nel messaggio.
        check(inviati and "Cartellini: 1" in inviati[0],
              f"il cartellino dagli eventi non arriva nel messaggio:\n{inviati}")
        check(inviati and sh.NOTE_NO_STATS in inviati[0],
              f"il messaggio non spiega perche' le statistiche mancano:\n{inviati}")
        check(inviati and "non disponibile" not in inviati[0].split("QUOTA")[0],
              f"il messaggio elenca ancora i campi vuoti:\n{inviati}")

        # CONTROLLO NEGATIVO: con la copertura ignota le statistiche SI chiedono.
        api.chiamati.clear()
        obs._seen.clear()
        obs.observe_once({}, lambda t: 1, None, coverage=lambda lid, s: cov.IGNOTA)
        check("/statistics" in api.chiamati,
              f"con copertura ignota la chiamata non viene piu' fatta: {api.chiamati}")

        # IL TERZO CASO, trovato su WIT Georgia - Gonio l'8 ottobre 2026: la
        # competizione e' dichiarata coperta e per quella partita l'API non
        # manda niente. Non e' la stessa cosa di una lega senza copertura, e il
        # messaggio non deve dire la frase sbagliata.
        tre = [
            ({"StatsCovered": False, "StatsSource": "copertura"}, sh.NOTE_NO_STATS,
             "competizione non coperta"),
            ({"StatsCovered": True, "StatsSource": "vuoto"}, sh.NOTE_EMPTY_STATS,
             "coperta ma senza dati per questa partita"),
            ({"StatsCovered": True, "StatsSource": "dati"}, None,
             "dati arrivati: nessuna nota, elenco completo"),
        ]
        for riga, atteso, descrizione in tre:
            check(obs.stats_note(riga) == atteso,
                  f"{descrizione}: nota '{obs.stats_note(riga)}' invece di '{atteso}'")
        check(sh.NOTE_NO_STATS != sh.NOTE_EMPTY_STATS,
              "le due ragioni dicono la stessa frase: tornano indistinguibili")

        api_vuota = ApiContata(partita)
        api_vuota.vuote = True
        obs.requests = api_vuota
        obs._seen.clear()
        inviati.clear()
        righe.clear()
        obs.observe_once({}, lambda t: inviati.append(t) or 1, None,
                         coverage=lambda lid, s: {"stats": True, "events": True})
        check(righe and righe[0].get("StatsSource") == "vuoto",
              f"una risposta vuota su lega coperta non viene registrata come vuota: {righe}")
        check(inviati and sh.NOTE_EMPTY_STATS in inviati[0],
              f"il messaggio non distingue 'coperta ma senza dati':\n{inviati}")
        check(inviati and sh.NOTE_NO_STATS not in inviati[0],
              f"il messaggio incolpa la copertura di una lega che e' coperta:\n{inviati}")
    finally:
        obs.append_row, obs.requests, obs.PENDING_PATH = append_vero, requests_vero, pending_vero
        obs.modello_2t = modello_vero
        obs._seen.clear()
        if os.path.exists(cov.COVERAGE_PATH + ".attesa"):
            os.remove(cov.COVERAGE_PATH + ".attesa")


if __name__ == "__main__":
    raise SystemExit(main())
