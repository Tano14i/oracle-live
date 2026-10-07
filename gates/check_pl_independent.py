"""La cifra misurata deve reggere a un calcolo fatto per un'altra strada.

Un report che calcola male e si auto-conferma e' peggio di nessun report. Qui il
P/L misurato e il conteggio W-L vengono ricalcolati dal dataset senza passare da
report_pl, e confrontati.

Include un controllo negativo: lo stesso confronto su una cifra deliberatamente
sbagliata deve fallire, altrimenti l'uguaglianza non sta verificando niente.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import report_pl  # noqa: E402
from config import LIVE_TRAINING_DATA_PATH, STAKE  # noqa: E402

FAIL = []
TOLL = 0.011  # arrotondamento a due decimali


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def indipendente(stake: float) -> dict:
    """Ricalcolo diretto, senza toccare report_pl."""
    df = pd.read_csv(LIVE_TRAINING_DATA_PATH, low_memory=False)
    df = df.drop_duplicates(subset="SignalKey", keep="first")
    df["OpenOdd"] = pd.to_numeric(df["OpenOdd"], errors="coerce")
    df = df[df["Tier"].isin(["APPROVED", "CAUTION", "GAMBLING"])]
    df = df[df["Outcome"].isin(["WIN", "LOSS"])]
    vinte = int((df["Outcome"] == "WIN").sum())
    perse = int((df["Outcome"] == "LOSS").sum())
    prezzati = df[df["OpenOdd"] > 1.0]
    pl = 0.0
    for row in prezzati.itertuples():
        pl += (row.OpenOdd - 1.0) if row.Outcome == "WIN" else -1.0
    return {"wins": vinte, "losses": perse,
            "measured_pl": round(pl * stake, 2), "priced": len(prezzati)}


def main() -> int:
    report = report_pl.build_report()
    mio = indipendente(float(STAKE))

    check(report["wins"] == mio["wins"],
          f"vinte: report {report['wins']} contro ricalcolo {mio['wins']}")
    check(report["losses"] == mio["losses"],
          f"perse: report {report['losses']} contro ricalcolo {mio['losses']}")
    check(report["priced_count"] == mio["priced"],
          f"prezzati: report {report['priced_count']} contro ricalcolo {mio['priced']}")
    check(abs(report["measured_pl"] - mio["measured_pl"]) <= TOLL,
          f"P/L misurato: report {report['measured_pl']} contro ricalcolo {mio['measured_pl']}")

    # CONTROLLO NEGATIVO: lo stesso confronto su una cifra sbagliata deve
    # fallire. Se passasse, l'uguaglianza qui sopra non proverebbe niente.
    sbagliato = mio["measured_pl"] + 1.0
    check(abs(report["measured_pl"] - sbagliato) > TOLL,
          "il confronto accetta anche una cifra sbagliata di 1 EUR: non verifica niente")

    # Il conteggio W-L non puo' mai mancare ne' sballare.
    check(report["wins"] + report["losses"] == report["published"],
          f"W+L ({report['wins']}+{report['losses']}) non torna con i pubblicati"
          f" ({report['published']})")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"W-L {report['wins']}-{report['losses']} e P/L misurato "
          f"{report['measured_pl']:+.2f} EUR confermati per via indipendente su "
          f"{report['priced_count']} prezzati")
    print("pl independent verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
