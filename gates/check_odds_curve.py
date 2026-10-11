"""Il minuto deve arrivare fino alla riga registrata, o la curva non esiste.

Fabio aspetta che la quota live salga a 1,40 prima di entrare. Per sapere se
conviene serve confrontare due curve: quella del book e quella equa, cioe' la
probabilita' di gol restando 0-0 minuto per minuto. Sui nostri 505 segnali
chiusi l'equo vale 1,40 al 56'. Se il book ci arriva prima, aspettare e' un
margine; se ci arriva dopo, si paga il tempo.

La curva del book non c'era, e il motivo era una riga sola: l'osservatore
chiedeva la quota con `minute=47` fisso. fetch_live_market_odd gira quel
minuto a record_live_odd, che scrive odds_history.csv - quindi ogni quota del
secondo tempo risultava letta al 47esimo. Risultato: 328 osservazioni, una per
partita, tutte allo stesso minuto, e nessuna curva.

Questo cancello pretende quattro cose: che il minuto vero arrivi a chi
registra, che la quota venga letta a ogni giro finche' il segnale e' aperto e
non dopo, che un fornitore di quote a un solo argomento continui a funzionare
- i cancelli ne usano di finti - e che un errore nella lettura della quota non
porti via l'esito, perche' il registro non deve dipendere dalle quote.

In piu' verifica una proprieta' della curva equa: non puo' salire. Se salisse,
la conclusione sul "conviene aspettare" sarebbe invertita da un bug.
"""
import os
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
    """Partita ferma sullo 0-0 al minuto che gli si dice."""

    def __init__(self, minuto, stato="2H"):
        self.minuto = minuto
        self.stato = stato

    def get(self, url, **kw):
        if "statistics" in url or "events" in url:
            return Risposta({"errors": [], "response": []})
        return Risposta({"errors": [], "response": [{
            "fixture": {"id": 808, "status": {"short": self.stato, "elapsed": self.minuto}},
            "league": {"id": 1, "name": "Serie B", "country": "Brazil", "season": 2026},
            "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
            "goals": {"home": 0, "away": 0},
            "score": {"halftime": {"home": 0, "away": 0}},
        }]})


def snapshot():
    return {"row": {"ObservedAtUTC": datetime.now(timezone.utc).isoformat(),
                    "FixtureId": 808, "MatchUp": "A vs B", "Country": "Brazil",
                    "LeagueName": "Serie B", "Minute": 47, "LiveOdd": 1.25},
            "capture": sh.capture_fields([]), "message_id": 1,
            "fase": obs.FASE_ESITO, "tentativi": 0}


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_curva_")
    veri = (obs.requests, obs.append_row, obs.PENDING_PATH)
    obs.PENDING_PATH = os.path.join(cartella, "attesa.json")
    righe = []
    obs.append_row = lambda row: righe.append(dict(row))
    try:
        return verifica(righe)
    finally:
        obs.requests, obs.append_row, obs.PENDING_PATH = veri
        obs._seen.clear()
        import shutil
        shutil.rmtree(cartella, ignore_errors=True)


def verifica(righe) -> int:
    # 1. chiedi_quota passa il minuto a chi lo accetta.
    visti = []
    due = lambda fid, minuto: visti.append((fid, minuto)) or 1.33   # noqa: E731
    check(obs.chiedi_quota(due, 808, 63) == 1.33, "la quota non torna al chiamante")
    check(visti == [(808, 63)], f"il minuto non arriva al fornitore: {visti}")

    # ...e un fornitore a un solo argomento continua a funzionare.
    uno_visti = []
    uno = lambda fid: uno_visti.append(fid) or 1.22                 # noqa: E731
    check(obs.chiedi_quota(uno, 808, 63) == 1.22,
          "un fornitore a un argomento si rompe: i cancelli ne usano di finti")
    check(uno_visti == [808], f"chiamata sbagliata al fornitore a un argomento: {uno_visti}")
    check(obs.chiedi_quota(None, 808, 63) is None, "senza fornitore non torna None")

    # 2. Finche' il segnale e' aperto, la quota si legge a OGNI giro, col minuto
    #    vero della partita - non con il 47 fisso che ha cancellato la curva.
    visti.clear()
    obs._seen.clear()
    obs._seen[808] = snapshot()
    for minuto in (52, 58, 66):
        obs.requests = Api(minuto)
        chiusi = obs.settle_once({}, None, due)
        check(chiusi == 0, f"una partita 0-0 al {minuto}' viene chiusa")
    check([m for _, m in visti] == [52, 58, 66],
          f"i minuti registrati sono {[m for _, m in visti]} invece di [52, 58, 66]: "
          f"senza il minuto vero la curva del book non esiste")
    check(all(f == 808 for f, _ in visti), f"fixture sbagliato nelle letture: {visti}")

    # 3. Quando il segnale si chiude, la quota non si chiede piu'.
    visti.clear()
    righe.clear()
    obs.requests = Api(90, stato="FT")
    chiusi = obs.settle_once({}, None, due)
    check(chiusi == 1, f"la partita finita 0-0 non viene chiusa: {chiusi}")
    check(righe and righe[0].get("Outcome") == "LOSS", f"esito sbagliato: {righe}")
    check(visti == [],
          f"la quota viene chiesta anche su un segnale chiuso: {visti} (chiamate sprecate)")

    # 4. IL PUNTO CHE PROTEGGE LA MISURA: se la lettura della quota fallisce,
    #    l'esito si registra comunque. Il registro non dipende dalle quote.
    def quota_che_muore(fid, minuto):
        raise RuntimeError("odds/live non risponde")

    obs._seen.clear()
    obs._seen[808] = snapshot()
    obs.requests = Api(70)

    def chiudi(atteso, descrizione):
        """settle_once senza lasciar passare eccezioni: un cancello che si
        schianta non diagnostica niente, dice solo che qualcosa e' rotto."""
        try:
            return obs.settle_once({}, None, quota_che_muore) == atteso
        except Exception as exc:
            FAIL.append(f"{descrizione}: l'errore sulla quota arriva fino al "
                        f"chiamante e porterebbe via l'esito ({exc!r})")
            return False

    check(chiudi(0, "partita ancora in corso"),
          "un errore sulla quota chiude il segnale per sbaglio")
    check(808 in obs._seen, "un errore sulla quota butta via lo snapshot")
    righe.clear()
    obs.requests = Api(90, stato="FT")
    check(chiudi(1, "partita finita"), "un errore sulla quota impedisce la chiusura")
    check(righe and righe[0].get("Outcome") == "LOSS",
          f"un errore sulla quota porta via l'esito: {righe}")

    # 5. observe_once legge la quota al minuto vero dell'apertura, non a 47 fisso.
    visti.clear()
    obs._seen.clear()
    obs.requests = Api(48)
    obs.observe_once({}, lambda t: 1, due, coverage=lambda lid, s: {"stats": False, "events": True})
    check([m for _, m in visti] == [48],
          f"all'apertura il minuto registrato e' {[m for _, m in visti]} invece di [48]")

    # 6. La curva equa non puo' salire: se salisse, la conclusione si invertirebbe.
    import curva_quote as cq
    chiusi_veri = cq.segnali()
    curva = cq.curva_equa(chiusi_veri).dropna()
    check(len(curva) > 10, f"la curva equa ha solo {len(curva)} punti")
    salite = [(m, curva[m]) for m, p in zip(curva.index[1:], curva.values[1:])
              if p > curva.loc[m - 1] + 1e-9]
    check(not salite,
          f"la probabilita' di gol SALE col passare dei minuti in {len(salite)} punti: "
          f"{salite[:3]} - con una curva cosi' il confronto col book direbbe il contrario")
    check(curva.iloc[0] > curva.iloc[-1],
          "la curva equa non scende fra il primo e l'ultimo minuto")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"minuto vero fino al registratore (52, 58, 66 e 48 all'apertura), nessuna "
          f"lettura sui segnali chiusi, esito salvo se la quota fallisce, curva equa "
          f"monotona su {len(curva)} minuti")
    print("odds curve verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
