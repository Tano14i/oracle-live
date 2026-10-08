"""Un riavvio non deve lasciare un segnale del 47' per sempre "in corso".

Il supervisore ha ripreso il bot due volte nelle ventiquattr'ore del 7 ottobre
2026 (BOT_CRASH codice -1 dopo 27h, poi dopo 10h). Gli snapshot in attesa
vivevano solo in memoria: un segnale aperto al 47' e chiuso da un riavvio
restava con il messaggio fermo su "in corso" e senza riga di esito nel
registro - cioe' perso per la misura, che e' il motivo per cui l'osservatore
esiste.

Qui si pretende che l'attesa sopravviva al riavvio, che un riavvio chiuda
davvero cio' che era aperto, e che uno snapshot che l'API non chiude mai non
resti in coda in eterno.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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


class RispostaFinta:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class ApiFinta:
    def __init__(self, payload):
        self.payload = payload
        self.chiamate = 0

    def get(self, url, **kw):
        self.chiamate += 1
        return RispostaFinta(self.payload)


def capture_finta():
    def squadra(**campi):
        return {"statistics": [{"type": k, "value": v} for k, v in campi.items()]}
    return sh.capture_fields([
        squadra(**{"Corner Kicks": 3, "Shots on Goal": 2, "Ball Possession": "58%"}),
        squadra(**{"Corner Kicks": 1, "Shots on Goal": 0, "Ball Possession": "42%"}),
    ])


def voce_finta(ore_fa=0.0, message_id=4242):
    quando = datetime.now(timezone.utc) - timedelta(hours=ore_fa)
    return {
        "row": {"ObservedAtUTC": quando.isoformat(), "FixtureId": 777,
                "MatchUp": "Vila Nova vs Cuiaba", "Country": "Brazil",
                "LeagueName": "Serie B", "Minute": 47, "LiveOdd": 1.40},
        "capture": capture_finta(),
        "message_id": message_id,
    }


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_pending_")
    pending_vero = obs.PENDING_PATH
    append_vero = obs.append_row
    requests_vero = obs.requests
    # Il cancello non deve toccare l'attesa del bot vivo: scrivere sul file
    # vero mentre l'osservatore gira vorrebbe dire cancellargli gli snapshot.
    obs.PENDING_PATH = os.path.join(cartella, "pending.json")
    try:
        return verifica()
    finally:
        obs.PENDING_PATH = pending_vero
        obs.append_row = append_vero
        obs.requests = requests_vero
        obs._seen.clear()
        shutil.rmtree(cartella, ignore_errors=True)


def verifica() -> int:
    check(obs.PENDING_PATH != os.path.join(
        os.path.dirname(os.path.abspath(obs.__file__)), "second_half_pending.json"),
        "il cancello sta scrivendo sull'attesa del bot vivo")

    righe = []
    obs.append_row = lambda row: righe.append(dict(row))

    # 1. Salvataggio e ripresa: riga, statistiche e id del messaggio tornano
    #    identici. Senza l'id non ci sarebbe niente da modificare.
    obs._seen.clear()
    obs._seen[777] = voce_finta()
    obs.save_pending()
    atteso = dict(obs._seen[777])
    obs._seen.clear()                      # questo e' il riavvio
    ripresi = obs.load_pending()
    check(ripresi == 1, f"ripresi {ripresi} snapshot invece di 1")
    ripreso = obs._seen.get(777)
    check(ripreso is not None, "lo snapshot non torna con la chiave numerica del fixture")
    if ripreso:
        check(ripreso.get("message_id") == 4242,
              f"l'id del messaggio non sopravvive al riavvio: {ripreso.get('message_id')}")
        check(ripreso.get("row") == atteso["row"],
              "la riga torna diversa da come era stata salvata")
        check(ripreso.get("capture", {}).get("totals", {}).get("corner kicks") == 4.0,
              f"le statistiche non sopravvivono: {ripreso.get('capture', {}).get('totals')}")

    # 2. Dopo il riavvio la chiusura funziona: registra e modifica il messaggio
    #    aperto prima del riavvio, con l'id giusto.
    modifiche = []
    obs.requests = ApiFinta({"response": [{"fixture": {"id": 777, "status": {"short": "FT"}},
                                           "goals": {"home": 1, "away": 0}}]})
    righe.clear()
    chiusi = obs.settle_once({}, lambda mid, text: modifiche.append((mid, text)))
    check(chiusi == 1, f"dopo il riavvio la chiusura non avviene: {chiusi}")
    check(len(righe) == 1 and righe[0].get("Outcome") == "WIN",
          f"esito non registrato dopo il riavvio: {righe}")
    check([m for m, _ in modifiche] == [4242],
          f"la modifica non usa l'id salvato prima del riavvio: {modifiche}")
    if modifiche:
        check("VINTO" in modifiche[0][1], "il messaggio modificato non dichiara l'esito")
    # Un vinto senza il minuto del gol resta in coda solo per il minuto: cio'
    # che non deve restare e' un'attesa di esito, che il riavvio richiuderebbe.
    residuo = obs._seen.get(777)
    check(residuo is None or residuo.get("fase") == obs.FASE_MINUTO,
          f"lo snapshot chiuso resta in attesa di esito: {residuo}")
    salvata = json.load(open(obs.PENDING_PATH, encoding="utf-8"))
    check(all(v.get("fase") == obs.FASE_MINUTO for v in salvata.values()),
          f"l'attesa su disco conserva un'attesa di esito dopo la chiusura: {salvata}")

    # 3. Uno snapshot che l'API non chiude mai non resta in coda in eterno:
    #    oltre STALE_HOURS viene archiviato come ignoto, e il messaggio lo dice.
    obs._seen.clear()
    obs._seen[777] = voce_finta(ore_fa=obs.STALE_HOURS + 1)
    obs.requests = ApiFinta({"response": []})
    righe.clear()
    modifiche.clear()
    chiusi = obs.settle_once({}, lambda mid, text: modifiche.append((mid, text)))
    check(chiusi == 1, f"uno snapshot vecchio e muto non viene archiviato: {chiusi}")
    check(len(righe) == 1 and righe[0].get("Outcome") == "UNSETTLED",
          f"l'archiviazione non e' marcata come ignota: {righe}")
    check(bool(modifiche) and obs.PENDING_LINE not in modifiche[0][1],
          f"il messaggio resta 'in corso' su una partita archiviata: {modifiche}")
    check(777 not in obs._seen, "lo snapshot archiviato resta in coda")

    # CONTROLLO NEGATIVO: uno snapshot appena aperto che l'API non chiude NON
    # va archiviato. Altrimenti la soglia chiuderebbe tutto subito.
    obs._seen.clear()
    obs._seen[777] = voce_finta(ore_fa=1)
    obs.requests = ApiFinta({"response": []})
    righe.clear()
    chiusi = obs.settle_once({}, None)
    check(chiusi == 0, f"uno snapshot di un'ora viene archiviato: {chiusi}")
    check(777 in obs._seen, "uno snapshot ancora valido viene buttato")
    check(righe == [], f"archiviazione scritta su uno snapshot vivo: {righe}")

    # CONTROLLO NEGATIVO: con una partita 0-0 ancora in corso non si chiude.
    obs.requests = ApiFinta({"response": [{"fixture": {"id": 777, "status": {"short": "2H"}},
                                           "goals": {"home": 0, "away": 0}}]})
    righe.clear()
    check(obs.settle_once({}, None) == 0,
          "una partita ancora in corso viene chiusa come persa")
    check(777 in obs._seen, "snapshot buttato mentre la partita e' in corso")

    # 4. Un file corrotto non impedisce l'avvio: si riparte vuoti, non si muore.
    obs._seen.clear()
    with open(obs.PENDING_PATH, "w", encoding="utf-8") as handle:
        handle.write('{"777": {"row": ')      # JSON tagliato a meta'
    try:
        ripresi = obs.load_pending()
        check(ripresi == 0, f"un file corrotto riporta {ripresi} snapshot")
        check(obs._seen == {}, "un file corrotto lascia stato inventato in memoria")
    except Exception as exc:
        FAIL.append(f"un file di attesa corrotto impedisce l'avvio: {exc}")

    # Voci malformate vengono scartate una per una, non fanno cadere il resto.
    with open(obs.PENDING_PATH, "w", encoding="utf-8") as handle:
        json.dump({"nonunnumero": {"row": {}}, "12": "stringa", "34": {"row": {"FixtureId": 34}}},
                  handle)
    obs._seen.clear()
    check(obs.load_pending() == 1,
          f"le voci malformate non vengono scartate come si deve: {obs._seen}")
    check(list(obs._seen) == [34], f"ripresa sbagliata: {list(obs._seen)}")

    # 5. Il salvataggio non lascia file temporanei in giro e resta leggibile.
    obs._seen.clear()
    obs._seen[777] = voce_finta()
    obs.save_pending()
    check(not os.path.exists(obs.PENDING_PATH + ".tmp"),
          "il salvataggio lascia un file temporaneo: il prossimo avvio potrebbe leggerlo")
    try:
        json.load(open(obs.PENDING_PATH, encoding="utf-8"))
    except ValueError as exc:
        FAIL.append(f"l'attesa salvata non e' JSON valido: {exc}")

    # 6. Un'attesa assente non e' un errore: primo avvio in assoluto.
    os.remove(obs.PENDING_PATH)
    obs._seen.clear()
    check(obs.load_pending() == 0, "il primo avvio senza file di attesa non e' pulito")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"attesa salvata e ripresa con id e statistiche, chiusura dopo riavvio, "
          f"archiviazione oltre {obs.STALE_HOURS}h, file corrotto non blocca l'avvio")
    print("second half restart verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
