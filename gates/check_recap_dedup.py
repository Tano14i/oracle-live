"""Il recap deve deduplicare come tutto il resto.

Lo storico ha 26.748 righe duplicate su 30.260: lo stesso segnale riaccodato a
ogni scansione finche' restava pendente. La prima riga e' quella scritta al
momento della decisione; le copie successive portano uno stato a partita
avanzata sotto colonne che si chiamano "AtOpen".

compute_performance_snapshot usa keep="first", compute_daily_snapshot usava
keep="last". Oggi non cambia i conteggi - l'esito viene scritto su tutte le
copie - ma e' una incoerenza latente: basta che un domani il recap legga una
colonna di stato perche' i due rapporti divergano senza preavviso.

La verifica include un controllo positivo: la stessa regola applicata a una riga
con keep="last" deve bocciarla, altrimenti non sta controllando niente.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SORGENTE = ROOT / "oracle_live.py"

FAIL = []
ATTESO = 'keep="first"'
MARCATORE = 'drop_duplicates(subset=["SignalKey"]'


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def giudica(riga: str) -> bool:
    """True se la riga deduplica nel modo giusto."""
    return ATTESO in riga


def main() -> int:
    testo = SORGENTE.read_text(encoding="utf-8", errors="replace")
    trovate = [(n + 1, r.strip()) for n, r in enumerate(testo.splitlines())
               if MARCATORE in r]

    check(bool(trovate), f"nessun {MARCATORE} trovato in oracle_live.py")
    for numero, riga in trovate:
        check(giudica(riga), f"riga {numero} non usa {ATTESO}: {riga}")

    # CONTROLLO POSITIVO: la regola deve bocciare una riga sbagliata.
    finta = 'df = df.drop_duplicates(subset=["SignalKey"], keep="last")'
    if giudica(finta):
        FAIL.append("la regola APPROVA una riga con keep=last: non controlla niente")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(trovate)} punti di deduplicazione, tutti con {ATTESO}: "
          + ", ".join(f"riga {n}" for n, _ in trovate))
    print("recap dedup verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
