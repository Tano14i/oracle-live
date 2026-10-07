"""L'unica fonte per qualunque affermazione sul P/L.

Nasce da un errore mio del 7 ottobre. Avevo riportato "25 segnali dal 1 ottobre,
profitto da 9.071,40 a 9.079,30 (+7,90)" omettendo che sette erano perse, e
senza dire che quel +7,90 era in gran parte aritmetica: 20 dei 25 segnali non
avevano una quota reale, quindi il loro P/L veniva calcolato sul fallback di
config. Peggio: di quei 20 nessuno era giocabile, perche' per quelle partite non
esisteva un prezzo live su nessun book. Il numero non era falso, era selettivo -
che in un rapporto e' peggio, perche' non si puo' controllare.

Due giorni prima avevo criticato il recap del bot per la stessa contabilita', e
poi ho letto `total_profit` da web_stats.json - che usa lo stesso fallback - e
l'ho riportato come cassa.

La correzione non e' ricordarsi di stare attenti. E' rendere il numero mescolato
impossibile da produrre: `build_report` non ha un campo totale, e
`validate_report` rifiuta qualunque struttura che ne contenga uno. Chi volesse
sommare misurato e stimato deve farlo a mano e assumersene la responsabilita'.

Uso:
    python report_pl.py
    python report_pl.py --since 2026-10-01
"""
import argparse
import os
from typing import Optional

import numpy as np
import pandas as pd

from config import LIVE_TRAINING_DATA_PATH, STAKE

ODDS_HISTORY = "odds_history.csv"
PUBLIC_TIERS = {"APPROVED", "CAUTION", "GAMBLING"}

# Quota usata per stimare il P/L dei segnali senza prezzo reale. Mai sopra la
# mediana misurata, cosi' la stima non lusinga: vedi la regola in config.py.
FALLBACK_QUOTA = 1.45

# Nomi che rappresenterebbero una cifra unica mescolata. Un report che ne
# contiene uno viene rifiutato: sommare una misura e una stima produce un numero
# che sembra cassa e non lo e'.
FORBIDDEN_KEYS = {
    "total", "totale", "total_pl", "total_profit", "net", "net_pl",
    "profit", "pl", "blended", "combined", "overall",
}


class BlendedTotalError(ValueError):
    """Sollevata quando un report contiene una cifra unica mescolata."""


def validate_report(report: dict) -> None:
    """Rifiuta qualunque report che mescoli misurato e stimato in un numero.

    E' il guardrail che rende la disciplina meccanica invece di una promessa:
    non basta che io mi ricordi di separare le due cifre, deve essere il codice
    a non permettere di unirle.
    """
    offending = sorted(k for k in report if str(k).lower() in FORBIDDEN_KEYS)
    if offending:
        raise BlendedTotalError(
            "il report contiene cifre mescolate: " + ", ".join(offending)
            + ". Misurato e stimato vanno riportati separati."
        )


def _unplayable_keys(frame: pd.DataFrame) -> set:
    """Segnali per cui nessun prezzo live e' mai esistito.

    Non sono "senza quota registrata per sfortuna": sono partite che nessun book
    prezzava, quindi non erano giocabili a nessuna condizione. Contarle nel P/L,
    anche come stima, descrive scommesse impossibili da piazzare.
    """
    if not os.path.exists(ODDS_HISTORY):
        return set()
    try:
        odds = pd.read_csv(ODDS_HISTORY)
    except Exception:
        return set()
    if "FixtureId" not in odds.columns or "Market" not in odds.columns:
        return set()
    odds["FixtureId"] = pd.to_numeric(odds["FixtureId"], errors="coerce")
    seen = set(zip(odds["FixtureId"].dropna().astype(int), odds["Market"]))
    out = set()
    for row in frame.itertuples():
        fixture = int(row.FixtureId) if pd.notna(row.FixtureId) else None
        if fixture is None or (fixture, row.Market) not in seen:
            out.add(row.SignalKey)
    return out


def build_report(since: Optional[str] = None,
                 stake: Optional[float] = None,
                 csv_path: Optional[str] = None) -> dict:
    """Il report, con misurato e stimato tenuti separati per costruzione."""
    stake = float(STAKE if stake is None else stake)
    path = csv_path or LIVE_TRAINING_DATA_PATH
    frame = pd.read_csv(path, low_memory=False)

    # keep="first": la prima riga di un segnale e' quella scritta al momento
    # della decisione. Le copie successive portano uno stato a partita avanzata.
    if "SignalKey" in frame.columns:
        frame = frame.drop_duplicates(subset="SignalKey", keep="first")
    for column in ("OpenOdd", "FixtureId"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["Tier"].isin(PUBLIC_TIERS)]
    frame = frame[frame["Outcome"].isin(["WIN", "LOSS"])].copy()
    if since:
        opened = pd.to_datetime(frame["OpenTimeUTC"], errors="coerce", utc=True)
        frame = frame[opened >= pd.Timestamp(since, tz="UTC")]

    frame["win"] = (frame["Outcome"] == "WIN").astype(int)
    priced = frame[frame["OpenOdd"] > 1.0]
    unpriced = frame[~(frame["OpenOdd"] > 1.0)]

    measured = float(np.where(priced["win"] == 1, priced["OpenOdd"] - 1.0, -1.0).sum()) * stake
    estimated = float(np.where(unpriced["win"] == 1, FALLBACK_QUOTA - 1.0, -1.0).sum()) * stake

    report = {
        "since": since or "tutto lo storico",
        "stake": stake,
        "published": int(len(frame)),
        "wins": int(frame["win"].sum()),
        "losses": int(len(frame) - frame["win"].sum()),
        "win_rate": float(frame["win"].mean()) if len(frame) else 0.0,
        "priced_count": int(len(priced)),
        "measured_pl": round(measured, 2),
        "priced_median_odd": float(priced["OpenOdd"].median()) if len(priced) else 0.0,
        "unpriced_count": int(len(unpriced)),
        "estimated_pl": round(estimated, 2),
        "estimate_quota": FALLBACK_QUOTA,
        "unplayable_count": len(_unplayable_keys(frame) & set(frame["SignalKey"])),
    }
    validate_report(report)
    return report


def format_report(report: dict) -> str:
    """Testo del report. Nessuna riga somma misurato e stimato."""
    validate_report(report)
    rate = 100 * report["win_rate"]
    lines = [
        f"P/L — periodo: {report['since']}  (stake {report['stake']:.0f} EUR)",
        "-" * 62,
        f"  pubblicati        {report['published']:>6}",
        f"  esiti             {report['wins']:>6}W - {report['losses']}L"
        f"   (win rate {rate:.1f}%)",
        "",
        f"  con quota reale   {report['priced_count']:>6}"
        f"   quota mediana {report['priced_median_odd']:.2f}",
        f"  P/L MISURATO      {report['measured_pl']:>+9.2f} EUR",
        "",
        f"  senza quota       {report['unpriced_count']:>6}",
        f"  P/L STIMATO       {report['estimated_pl']:>+9.2f} EUR"
        f"   al fallback {report['estimate_quota']:.2f} — aritmetica, non cassa",
        "",
        f"  non giocabili     {report['unplayable_count']:>6}"
        "   nessun book esponeva un prezzo: il loro P/L,",
        "                            misurato o stimato, descrive scommesse"
        " impossibili da piazzare",
        "-" * 62,
        "  Misurato e stimato restano separati per costruzione: sommarli produce",
        "  un numero che sembra cassa e non lo e'.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="solo i segnali aperti da questa data (YYYY-MM-DD)")
    parser.add_argument("--stake", type=float)
    parser.add_argument("--csv")
    args = parser.parse_args()
    print(format_report(build_report(args.since, args.stake, args.csv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
