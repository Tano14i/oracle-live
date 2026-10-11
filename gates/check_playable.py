"""Le partite che non si possono giocare non si aprono. Le altre, tutte.

Fabio: "escludiamo le partite U19 che in ogni caso sulla mia piattaforma di
betting non si possono giocare". Giusto - un segnale su una partita che non
esiste nel suo book e' rumore in canale e una riga inutile nel registro, piu'
tre chiamate all'API sprecate.

Perche' questo filtro e' legittimo e non e' scegliere i risultati comodi:
separa per giocabilita', che e' una proprieta' della competizione e non dipende
da come la partita e' finita. Misurato al momento dell'introduzione, sui
ventinove segnali chiusi: le cinque escluse non avevano quota, quindi il conto
del margine - i quattordici su cui una scommessa esisteva - non si muove di un
centesimo. Cambia il canale, non la misura.

La parte che puo' fare danno e' il riconoscimento dei nomi. Nel registro ci
sono "Plaza Colonia vs Juventud" (Uruguay, prima squadra, vinta a 1,36),
"Akademiya Ontustik" (Kazakhstan, prima squadra, vinta) e "Kahta 02 Spor"
(Turchia, vinta): un filtro su "juven", su "akadem" o su due cifre le
butterebbe via. Per questo i controlli positivi di questo cancello contano
piu' di quelli negativi.
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

# Devono essere ESCLUSE. Le prime cinque sono quelle vere del registro.
DA_ESCLUDERE = [
    ("Copa do Brasil U20", "Ceará U20 vs Ferroviario U20"),
    ("Reserve League", "Ferro 2 vs Independiente Res."),
    ("Friendlies Women", "Scotland U19 W vs Croatia U19 W"),
    ("Friendlies Women", "Finland U19 W vs Belgium U19 W"),
    ("Nasjonal U19 Champions League", "Rosenborg U19 vs Lillestrøm U19"),
    ("Premier League", "Arsenal U21 vs Chelsea U21"),
    ("Campeonato Brasileiro Sub-20", "Santos vs Palmeiras"),
    ("Primavera 1", "Milan vs Roma"),
    ("Youth League", "Porto vs Benfica"),
    ("Campionato Juniores", "Vicenza vs Padova"),
    ("Liga", "Real Madrid U-19 vs Barcelona U-19"),
    ("Reserves Cup", "Celtic vs Rangers"),
]

# Devono PASSARE. Sono prime squadre con nomi che un filtro ingenuo prende.
DA_TENERE = [
    ("Copa Uruguay", "Plaza Colonia vs Juventud"),
    ("1. Division", "Shakhter Karagandy vs Akademiya Ontustik"),
    ("Türkiye Kupası", "Talasgücü Belediyespor vs Kahta 02 Spor"),
    ("Copa Chile", "Antofagasta vs Universidad de Chile"),
    ("Serie A", "Juventus vs Inter"),
    ("Primera División", "Independiente vs Racing Club"),
    ("Serie B", "Resende FC vs Bangu"),
    ("Ligue 1", "Jeunesse Sportive de Kabylie vs CR Belouizdad"),
    ("Premier League", "Shabab Al Sahel vs Tadamon Sour"),
    ("Serie B", "Vila Nova vs Cuiaba"),
    ("League Cup", "Al Ittihad vs Wadi Degla"),
    ("Liga 3", "WIT Georgia vs Gonio"),
    ("Primera División RFEF - Group 2", "FC Cartagena vs Real Murcia"),
    ("Eerste Divisie", "Jong Ajax vs Jong PSV"),
]


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
    def __init__(self, partita):
        self.partita = partita
        self.chiamati = []

    def get(self, url, **kw):
        self.chiamati.append("statistics" if "statistics" in url
                             else "events" if "events" in url else "fixtures")
        if "statistics" in url or "events" in url:
            return Risposta({"errors": [], "response": []})
        return Risposta({"errors": [], "response": [self.partita]})


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


def partita(lega, casa, fuori):
    return {
        "fixture": {"id": 5555, "status": {"short": "2H", "elapsed": 47}},
        "league": {"id": 999, "name": lega, "country": "X", "season": 2026},
        "teams": {"home": {"name": casa}, "away": {"name": fuori}},
        "goals": {"home": 0, "away": 0},
        "score": {"halftime": {"home": 0, "away": 0}},
    }


def main() -> int:
    # 1. Quelle da escludere vengono escluse, con un motivo leggibile.
    for lega, incontro in DA_ESCLUDERE:
        ok, motivo = sh.playable(lega, incontro)
        check(not ok, f"NON esclusa: {lega} | {incontro}")
        if not ok:
            check("giovanili o riserve" in motivo,
                  f"motivo poco chiaro per {incontro}: {motivo}")

    # 2. IL CONTROLLO CHE CONTA: le prime squadre con nomi insidiosi passano.
    #    Una di queste - Juventud a 1,36 - e' una vittoria vera del registro.
    for lega, incontro in DA_TENERE:
        ok, motivo = sh.playable(lega, incontro)
        check(ok, f"ESCLUSA per errore: {lega} | {incontro} -> {motivo}")

    # 3. Nomi vuoti o assenti non devono far cadere nulla ne' escludere tutto.
    for lega, incontro in ((None, None), ("", ""), ("Serie A", None)):
        ok, _ = sh.playable(lega, incontro)
        check(ok, f"esclusa una partita senza nome: lega={lega} incontro={incontro}")

    # 4. observe_once non apre, non registra e NON CHIAMA l'API su una partita
    #    non giocabile: tre chiamate sprecate per un messaggio che non serve.
    righe, inviati = [], []
    veri = (obs.append_row, obs.requests, obs.PENDING_PATH, obs.modello_2t)
    obs.modello_2t = ModelloFinto
    obs.append_row = lambda row: righe.append(dict(row))
    obs.PENDING_PATH = str(Path(__file__).resolve().parent / "_attesa_playable.json")
    coperta = lambda lid, s: {"stats": True, "events": True}  # noqa: E731
    try:
        api = Api(partita("Nasjonal U19 Champions League",
                          "Rosenborg U19", "Lillestrøm U19"))
        obs.requests = api
        obs._seen.clear()
        obs._scartati.clear()
        aperti = obs.observe_once({}, lambda t: inviati.append(t) or 1, None,
                                  coverage=coperta)
        check(aperti == 0, f"una partita U19 viene aperta: {aperti}")
        check(righe == [], f"riga registrata per una partita U19: {righe}")
        check(inviati == [], f"messaggio inviato per una partita U19: {inviati}")
        check(obs._seen == {}, "la partita U19 resta in attesa di esito")
        check("statistics" not in api.chiamati and "events" not in api.chiamati,
              f"chiamate sprecate su una partita non giocabile: {api.chiamati}")

        # Il filtro si registra una volta, non a ogni scansione: la finestra
        # 46-48 dura tre minuti, cioe' quattro giri.
        check(5555 in obs._scartati, "lo scarto non viene ricordato")
        for _ in range(3):
            obs.observe_once({}, lambda t: inviati.append(t) or 1, None, coverage=coperta)
        check(inviati == [], "dopo tre giri in piu' qualcosa e' stato inviato")

        # CONTROLLO POSITIVO: la stessa partita con nomi di prima squadra si apre.
        api2 = Api(partita("Copa Uruguay", "Plaza Colonia", "Juventud"))
        obs.requests = api2
        obs._seen.clear()
        obs._scartati.clear()
        righe.clear()
        inviati.clear()
        aperti = obs.observe_once({}, lambda t: inviati.append(t) or 1, None,
                                  coverage=coperta)
        check(aperti == 1,
              "Plaza Colonia - Juventud non viene piu' aperta: il filtro mangia "
              "una vittoria vera del registro")
        check(len(righe) == 1, f"la partita giocabile non viene registrata: {righe}")
        check(len(inviati) == 1, f"la partita giocabile non viene inviata: {inviati}")
    finally:
        obs.append_row, obs.requests, obs.PENDING_PATH, obs.modello_2t = veri
        obs._seen.clear()
        obs._scartati.clear()
        temporanea = Path(__file__).resolve().parent / "_attesa_playable.json"
        if temporanea.exists():
            temporanea.unlink()

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(DA_ESCLUDERE)} competizioni non giocabili escluse, "
          f"{len(DA_TENERE)} prime squadre con nomi insidiosi conservate, "
          f"nessuna chiamata spesa su una partita che non si puo' giocare")
    print("playable verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
