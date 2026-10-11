"""La regola dei corner non deve poter essere ritoccata dopo aver visto i dati.

L'11 ottobre 2026, sui 103 segnali del 47' con statistiche, ho provato quattro
campi e uno e' passato: corner > 4 da' +17,1 punti di gol nel secondo tempo,
z=+2,26, e sui 43 con quota un ROI di +14,5% con l'intervallo bootstrap sopra
lo zero.

Non e' una scoperta, per tre ragioni scritte in regola_corner.md: quattro campi
provati (p corretto 0,095), tre sole perdite su 43 - lo stesso difetto che l'8
ottobre mi aveva mostrato un intervallo sopra lo zero su 13W-1L, sparito due
giorni dopo - e soglia scelta dopo aver guardato i dati.

L'unico modo di saperlo e' misurarla su dati che non l'hanno suggerita. Perche'
quella misura valga, due cose devono restare vere, e sono quelle che questo
cancello protegge:

1. La regola, l'istante di congelamento e il criterio di successo non sono
   cambiati da quando li ho scritti. Se qualcuno sposta la soglia da 4 a 3
   perche' "cosi' viene meglio", il cancello se ne accorge: dell'impronta
   della parte vincolata.

2. La valutazione usa SOLO i segnali osservati dopo il congelamento. I 43 che
   hanno suggerito la regola non possono rientrare nel conto che la giudica.

Il cancello non pretende che la regola sia confermata: pretende che il metodo
sia onesto. Stampa anche a che punto siamo, cosi' il progresso si vede senza
dover rifare i conti a mano.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
REGOLA = BASE / "regola_corner.md"
REGISTRO = BASE / "second_half_log.csv"

# Impronta della parte vincolata, presa quando la regola e' stata registrata.
# Cambiarla a mano per far passare il cancello e' esattamente la cosa che il
# cancello esiste per rendere visibile.
ANCORA = "## La regola, fissata adesso"
IMPRONTA = "558d92bb51552071a70bac487e92169d48b049fa913dfd6cf1b5294dd91616b3"
CONGELAMENTO = "2026-10-11T14:14:45.689079+00:00"
SOGLIA_CORNER = 4
N_RICHIESTI = 40

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    check(REGOLA.exists(), f"la registrazione non c'e' piu': {REGOLA.name}")
    if not REGOLA.exists():
        print("FALLITO:", FAIL[0])
        return 1
    testo = REGOLA.read_text(encoding="utf-8")

    # 1. La parte vincolata non e' cambiata.
    check(ANCORA in testo, f"la sezione vincolata '{ANCORA}' non si trova piu'")
    if ANCORA in testo:
        vincolata = testo[testo.index(ANCORA):]
        impronta = hashlib.sha256(vincolata.encode("utf-8")).hexdigest()
        check(impronta == IMPRONTA,
              f"la regola e' stata modificata dopo la registrazione.\n"
              f"         attesa {IMPRONTA}\n         trovata {impronta}\n"
              f"         Se la modifica e' voluta, serve una registrazione NUOVA con "
              f"un campione nuovo: ritoccare questa annulla la prova.")

    # 2. I numeri usati dal codice coincidono con quelli scritti nella regola.
    check(CONGELAMENTO in testo,
          f"l'istante di congelamento {CONGELAMENTO} non e' quello scritto nella regola")
    check(f"Corners > {SOGLIA_CORNER}" in testo,
          f"la soglia {SOGLIA_CORNER} non e' quella scritta nella regola")
    check(f"**{N_RICHIESTI} segnali nuovi**" in testo,
          f"il numero richiesto {N_RICHIESTI} non e' quello scritto nella regola")
    # E le tre ragioni per cui non e' ancora una scoperta devono restare scritte.
    for ragione in ("quattro campi", "0,095", "13W-1L"):
        check(ragione in testo,
              f"la registrazione non dice piu' perche' la regola non e' provata: "
              f"manca '{ragione}'")

    # 3. La valutazione guarda solo i segnali nuovi.
    if not REGISTRO.exists():
        print("FALLITO: registro assente")
        return 1
    d = pd.read_csv(REGISTRO)
    d["ordine"] = range(len(d))
    u = d.sort_values("ordine").drop_duplicates("FixtureId", keep="last")
    nuovi = u[u.ObservedAtUTC > CONGELAMENTO]
    vecchi = u[u.ObservedAtUTC <= CONGELAMENTO]
    check(len(vecchi) > 0, "il congelamento non separa niente: nessun segnale lo precede")

    idonei = nuovi[(nuovi.StatsSource == "dati") & nuovi.Corners.notna()
                   & (nuovi.Corners > SOGLIA_CORNER) & nuovi.LiveOdd.notna()
                   & nuovi.Outcome.isin(["WIN", "LOSS"])]
    # CONTROLLO: nessuno dei segnali che hanno suggerito la regola entra nel conto.
    check(not set(idonei.FixtureId) & set(vecchi.FixtureId),
          "nel conto che giudica la regola entrano segnali che l'hanno suggerita")

    print(f"regola congelata al {CONGELAMENTO}, impronta verificata")
    print(f"segnali idonei dopo il congelamento: {len(idonei)} su {N_RICHIESTI} richiesti")
    if len(idonei):
        pl = np.where(idonei.Outcome == "WIN", idonei.LiveOdd - 1, -1)
        vinte = int((idonei.Outcome == "WIN").sum())
        riga = (f"  parziale: {vinte}W-{len(idonei)-vinte}L, quota media "
                f"{idonei.LiveOdd.mean():.3f}, ROI {pl.sum()/len(pl):+.1%}")
        if len(idonei) >= N_RICHIESTI:
            b = [np.random.default_rng(i).choice(pl, len(pl), replace=True).mean()
                 for i in range(4000)]
            lo, hi = np.percentile(b, [2.5, 97.5])
            verdetto = "CONFERMATA" if lo > 0 else "RESPINTA"
            riga += f"\n  IC95 {lo:+.1%}/{hi:+.1%}  ->  {verdetto} secondo il criterio registrato"
        else:
            riga += f"  (ancora {N_RICHIESTI - len(idonei)}: nessun verdetto)"
        print(riga)
    else:
        print("  nessun segnale idoneo ancora: il verdetto non esiste")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print("corner preregistration verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
