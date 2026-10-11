"""Il modello seleziona, non indovina: e quello che non sa riconoscere tace.

Fabio: "come facciamo selezione delle partite che hanno la probabilita' piu'
alta del gol al secondo tempo?" Il modello di modello_2t.py risponde - 67.953
partite, sei feature, calibrato entro un punto in tutti e dieci i decili fuori
campione - e l'osservatore lo usa per suonare solo sul decile alto.

Tre cose possono andare storte, e sono quelle che questo cancello guarda.

La prima: una squadra riconosciuta male. Il modello lavora su nomi, e un
abbinamento sbagliato produce una probabilita' sbagliata con l'aspetto di una
misura - lo stesso difetto di "dangerous attacks" a 0,00. Quindi senza
identificazione certa la probabilita' e' None, e un segnale senza probabilita'
non suona: si registra e tace.

La seconda: la soglia che si scolla dal modello. Se qualcuno la scrivesse a
mano nel codice, un riaddestramento la lascerebbe indietro senza che nessuno
lo noti. Deve venire dal modello stesso, e coincidere con quella registrata in
regola_modello_2t.md.

La terza: suonare per tutti di nuovo. L'osservatore deve registrare ogni 0-0 -
la misura ne ha bisogno - e mandare il messaggio solo per i selezionati.
Registrare tutto e suonare per tutto era il comportamento di prima: 265
messaggi in un giorno.
"""
import hashlib
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

import modello_2t as mod  # noqa: E402
import second_half as sh  # noqa: E402
import second_half_observer as obs  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
REGOLA = BASE / "regola_modello_2t.md"
ANCORA = "## La regola, fissata adesso"
IMPRONTA = "3d02c622ddd4b1fc0505e724f2cb81c0ca1c5d2ffcf0ee29e4a0c6d0d81d62e8"
SOGLIA_REGISTRATA = 0.7915793918550821
CONGELAMENTO = "2026-10-11T15:19:43.695524+00:00"

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
    def __init__(self, casa, fuori):
        self.casa, self.fuori = casa, fuori

    def get(self, url, **kw):
        if "statistics" in url or "events" in url:
            return Risposta({"errors": [], "response": []})
        return Risposta({"errors": [], "response": [{
            "fixture": {"id": 4711, "status": {"short": "2H", "elapsed": 47}},
            "league": {"id": 71, "name": "Serie A", "country": "Brazil", "season": 2026},
            "teams": {"home": {"name": self.casa}, "away": {"name": self.fuori}},
            "goals": {"home": 0, "away": 0},
            "score": {"halftime": {"home": 0, "away": 0}},
        }]})


def main() -> int:
    # 1. Il modello si carica e la soglia viene da lui, non da una costante.
    check(mod.carica(), "il modello non si carica: senza, l'osservatore tornerebbe muto su tutto")
    soglia = mod.soglia_decile_alto()
    check(abs(soglia - SOGLIA_REGISTRATA) < 1e-12,
          f"la soglia del modello ({soglia!r}) non e' quella registrata "
          f"({SOGLIA_REGISTRATA!r}): modello e regola si sono scollati")
    sorgente = (BASE / "modello_2t.py").read_text(encoding="utf-8")
    check('soglie"] or {}).get("d9"' in sorgente or 'get("d9"' in sorgente,
          "la soglia non viene letta dal modello: scritta a mano si scolla al "
          "primo riaddestramento")
    check(str(SOGLIA_REGISTRATA)[:8] not in sorgente,
          "la soglia e' scritta a mano dentro modello_2t.py")

    # 2. La registrazione non e' stata ritoccata.
    check(REGOLA.exists(), "la registrazione della regola non c'e' piu'")
    if REGOLA.exists():
        testo = REGOLA.read_text(encoding="utf-8")
        check(ANCORA in testo, "la sezione vincolata non si trova piu'")
        if ANCORA in testo:
            impronta = hashlib.sha256(testo[testo.index(ANCORA):].encode("utf-8")).hexdigest()
            check(impronta == IMPRONTA,
                  f"la regola e' stata modificata dopo la registrazione "
                  f"(attesa {IMPRONTA[:16]}..., trovata {impronta[:16]}...): "
                  f"una variante richiede una registrazione nuova")
        check(CONGELAMENTO in testo, "l'istante di congelamento non e' quello registrato")
        for pezzo in ("80,8%", "1,178", "1,238", "non si gioca"):
            check(pezzo in testo,
                  f"la registrazione non dice piu' che il prezzo si mangia il "
                  f"vantaggio: manca '{pezzo}'")

    # 3. IL PUNTO CHE PROTEGGE LA MISURA: una squadra che non si identifica
    #    non produce una probabilita' inventata.
    for casa, fuori in (("Squadra Inesistente XYZ", "Altra Inesistente XYZ"),
                        ("Vila Nova", "Squadra Inesistente XYZ"), ("", ""), (None, None)):
        p, perche = mod.probabilita(casa, fuori)
        check(p is None, f"probabilita' inventata per '{casa}' vs '{fuori}': {p}")
        check(not mod.selezionato(p), f"segnale selezionato senza probabilita': {casa}")
    # ...e una squadra vera la produce.
    p, perche = mod.probabilita("Vila Nova", "Cuiaba")
    check(p is not None and 0.0 < p < 1.0, f"probabilita' non calcolata su squadre note: {p}")
    check("precedenti" in perche, f"il motivo non dice su quanti precedenti si basa: {perche}")
    # Un nome con rumore attorno deve trovare la stessa squadra.
    p2, _ = mod.probabilita("Vila Nova FC", "Cuiaba")
    check(p2 is not None and abs(p2 - p) < 1e-9,
          f"'Vila Nova FC' non viene riconosciuta come 'Vila Nova': {p2} vs {p}")
    # Ma un nome soltanto somigliante NON deve passare per quella squadra.
    p3, _ = mod.probabilita("Vila Verde", "Cuiaba")
    check(p3 is None or abs(p3 - p) > 1e-9,
          "'Vila Verde' viene confusa con 'Vila Nova': un abbinamento sbagliato "
          "produce una probabilita' sbagliata")

    # 4. L'osservatore registra tutti e suona solo per i selezionati.
    cartella = tempfile.mkdtemp(prefix="oracle_mod_")
    veri = (obs.requests, obs.append_row, obs.PENDING_PATH)
    obs.PENDING_PATH = os.path.join(cartella, "attesa.json")
    righe, inviati = [], []
    obs.append_row = lambda row: righe.append(dict(row))
    coperta = lambda lid, s: {"stats": False, "events": True}   # noqa: E731
    try:
        # Una partita sotto soglia: registrata, muta.
        obs._seen.clear(); obs._scartati.clear()
        obs.requests = Api("Vila Nova", "Cuiaba")
        p_bassa, _ = mod.probabilita("Vila Nova", "Cuiaba")
        check(p_bassa < soglia, f"il caso di prova non e' sotto soglia: {p_bassa}")
        aperti = obs.observe_once({}, lambda t: inviati.append(t) or 1, None, coverage=coperta)
        check(aperti == 1, f"il segnale sotto soglia non viene aperto: {aperti}")
        check(len(righe) == 1, f"il segnale sotto soglia non viene registrato: {righe}")
        check(inviati == [],
              f"suona anche sotto soglia: tornerebbero 265 messaggi al giorno ({len(inviati)})")
        check(righe and righe[0].get("ModelP") not in (None, ""),
              f"la probabilita' non finisce nel registro: {righe}")
        check("ModelP" in obs.COLUMNS, "la colonna ModelP non e' nel registro")
        # Lo snapshot resta in attesa anche se muto: l'esito serve alla misura.
        check(4711 in obs._seen,
              "un segnale muto non viene seguito: si perderebbe il suo esito")

        # Una partita sopra soglia: suona.
        casa, fuori = cerca_coppia_sopra_soglia(soglia)
        check(casa is not None, "nessuna coppia sopra soglia trovata per la prova")
        if casa:
            obs._seen.clear(); obs._scartati.clear(); righe.clear(); inviati.clear()
            obs.requests = Api(casa, fuori)
            obs.observe_once({}, lambda t: inviati.append(t) or 1, None, coverage=coperta)
            check(len(inviati) == 1,
                  f"una partita del decile alto ({casa} vs {fuori}) non suona: {inviati}")
            check(len(righe) == 1, "la partita selezionata non viene registrata")
    finally:
        obs.requests, obs.append_row, obs.PENDING_PATH = veri
        obs._seen.clear(); obs._scartati.clear()
        import shutil
        shutil.rmtree(cartella, ignore_errors=True)

    # 5. E la selezione deve essere selettiva: il decile alto, non meta' del mondo.
    import json
    squadre = json.loads((BASE / "squadre_2t.json").read_text(encoding="utf-8"))
    nomi = list(squadre)[:120]
    sopra = 0
    for i in range(0, len(nomi) - 1, 2):
        p, _ = mod.probabilita(nomi[i], nomi[i + 1])
        if mod.selezionato(p):
            sopra += 1
    quota = sopra / max(1, len(nomi) // 2)
    check(quota <= 0.30,
          f"la soglia seleziona il {quota:.0%} delle coppie: non e' un decile alto")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"soglia {soglia:.4f} letta dal modello e uguale alla registrata; squadra "
          f"ignota -> nessuna probabilita' e nessun messaggio; registrati tutti, "
          f"suonano i selezionati; selezione al {quota:.0%} delle coppie di prova")
    print("modello 2t verification passed")
    return 0


def cerca_coppia_sopra_soglia(soglia):
    """Due squadre vere la cui partita sta nel decile alto."""
    import json
    squadre = json.loads((BASE / "squadre_2t.json").read_text(encoding="utf-8"))
    migliori = sorted(squadre.items(), key=lambda kv: -kv[1]["r2"])[:40]
    for i in range(len(migliori)):
        for j in range(i + 1, len(migliori)):
            p, _ = mod.probabilita(migliori[i][0], migliori[j][0])
            if p is not None and p >= soglia:
                return migliori[i][0], migliori[j][0]
    return None, None


if __name__ == "__main__":
    raise SystemExit(main())
