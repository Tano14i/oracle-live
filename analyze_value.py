"""L'esperimento decisivo: il modello batte il prezzo, o lo paga?

Un segnale e' redditizio solo se il suo win rate reale supera la probabilita'
implicita nella quota offerta. Tutto il resto - win rate, tier, lift del modello -
misura quanto spesso si indovina, non se si guadagna.

Questo script risponde a quattro domande, in ordine di importanza:

1. Dove stiamo rispetto al prezzo? (WR reale contro probabilita' implicita)
2. Quando modello e book non sono d'accordo, chi ha ragione? E' la scommessa
   che il bot fa ogni volta che pubblica.
3. Esiste un segmento con margine positivo? Per market, tier, minuto, fascia
   di quota, campionato.
4. Abbiamo abbastanza dati per crederci?

Uso:
    python analyze_value.py
    python analyze_value.py --csv live_training_data.csv --min-n 10
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervallo di confidenza su una proporzione.

    Serve perche' un win rate su 30 segnali e un win rate su 3.000 non sono la
    stessa affermazione, e trattarli uguale e' il modo piu' rapido di inseguire
    rumore.
    """
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - margin), min(1.0, centre + margin)


def sample_needed(edge: float, p: float = 0.6, z: float = 1.96) -> int:
    """Quante scommesse prezzate servono per distinguere un margine dal caso."""
    return math.ceil((z ** 2) * p * (1 - p) / edge ** 2)


def load(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)

    # Un segnale, una riga. Finche' i pendenti venivano riaperti a ogni scansione
    # lo stesso segnale lasciava fino a 135 copie, e le copie pesano i perdenti:
    # chi vince subito si chiude alla prima scansione e ne lascia una sola.
    if "SignalKey" in df.columns:
        df = df.drop_duplicates(subset="SignalKey", keep="first")

    for column in ["OpenOdd", "Prob", "Minute"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    df["win"] = (df["Outcome"] == "WIN").astype(int)

    priced = df[df["OpenOdd"] > 1.0].copy()
    priced["implied"] = 1.0 / priced["OpenOdd"]
    priced["pl"] = np.where(priced["win"] == 1, priced["OpenOdd"] - 1.0, -1.0)
    priced["edge"] = priced["win"] - priced["implied"]
    priced["model_edge"] = priced["Prob"] - priced["implied"]
    return df, priced


def block(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def table(groups, min_n: int) -> None:
    print(f"  {'segmento':<34}{'n':>5}{'WR%':>8}{'implicita%':>12}{'margine':>9}{'ROI%':>9}")
    shown = 0
    for label, g in groups:
        n = len(g)
        if n < min_n:
            continue
        shown += 1
        wr = g["win"].mean()
        imp = g["implied"].mean()
        print(f"  {str(label)[:34]:<34}{n:>5}{100 * wr:>8.1f}{100 * imp:>12.1f}"
              f"{100 * (wr - imp):>+9.1f}{100 * g['pl'].mean():>9.1f}")
    if not shown:
        print(f"  (nessun segmento con almeno {min_n} segnali prezzati)")


def trajectories(csv_path: str, min_n: int) -> None:
    """L'effetto dell'attesa, per singolo segnale invece che per mediane.

    La domanda e': se entro W minuti dopo il segnale, prendo un prezzo migliore
    ma perdo i vincenti il cui gol e' arrivato prima. Il saldo si misura solo
    appaiando, sullo STESSO segnale, la quota a quel momento e l'esito finale.

    Stimarlo con una quota mediana e un rincaro uniforme - come e' stato fatto
    la prima volta - mescola popolazioni diverse e da' un numero che sembra
    preciso e non lo e'.

    La chiave del segnale e' FixtureId + Market, quindi odds_history.csv si
    appaia al dataset senza bisogno di una colonna in piu'.
    """
    if not os.path.exists("odds_history.csv"):
        print("  odds_history.csv non trovato: niente traiettorie.")
        return
    signals = pd.read_csv(csv_path, low_memory=False)
    if "SignalKey" in signals.columns:
        signals = signals.drop_duplicates(subset="SignalKey", keep="first")
    signals = signals[signals["Outcome"].isin(["WIN", "LOSS"])].copy()
    # Un solo market: OVER 1.5 HT sta intorno a 2.40 e OVER 0.5 HT a 1.50,
    # mediarli in una riga sola da' un numero che non significa niente. Qui
    # interessa il market che viene pubblicato.
    signals = signals[signals["Market"] == "OVER 0.5 HT"]
    signals["FixtureId"] = pd.to_numeric(signals["FixtureId"], errors="coerce")
    signals["t0"] = pd.to_datetime(signals["OpenTimeUTC"], errors="coerce", utc=True)
    signals["t1"] = pd.to_datetime(signals["SettledTimeUTC"], errors="coerce", utc=True)
    signals = signals.dropna(subset=["FixtureId", "t0", "t1"])
    signals["win"] = (signals["Outcome"] == "WIN").astype(int)

    odds = pd.read_csv("odds_history.csv")
    odds["FixtureId"] = pd.to_numeric(odds["FixtureId"], errors="coerce")
    odds["Odd"] = pd.to_numeric(odds["Odd"], errors="coerce")
    odds["t"] = pd.to_datetime(odds["ObservedAtUTC"], errors="coerce", utc=True)
    odds = odds.dropna(subset=["FixtureId", "Odd", "t"])

    # Una riga per (segnale, osservazione), tenendo solo le letture dentro la
    # finestra in cui il segnale era pendente: una quota di prima o di dopo non
    # e' un prezzo che avresti potuto prendere.
    merged = signals.merge(odds, on=["FixtureId", "Market"], suffixes=("", "_odd"))
    merged = merged[(merged["t"] >= merged["t0"]) & (merged["t"] <= merged["t1"])]
    merged["attesa"] = (merged["t"] - merged["t0"]).dt.total_seconds() / 60.0
    if merged.empty:
        print("  nessuna quota osservata dentro la finestra dei segnali.")
        return

    per_signal = merged.groupby("SignalKey")["attesa"].size()
    print(f"  segnali con almeno una quota nella finestra: {merged['SignalKey'].nunique()}")
    print(f"  di cui con due o piu letture a tempi diversi: {int((per_signal >= 2).sum())}")
    print()
    print(f"  {'entrata':<12}{'n':>5}{'WR%':>8}{'quota med':>12}{'ROI%':>9}")
    for lo, hi, label in [(0, 1, "subito"), (2, 4, "+2-4 min"), (5, 7, "+5-7 min"),
                          (8, 12, "+8-12 min"), (13, 20, "+13-20 min")]:
        window = merged[merged["attesa"].between(lo, hi)]
        # Una lettura per segnale: la prima dentro la finestra, cioe' il prezzo
        # che avresti preso entrando in quel momento.
        window = window.sort_values("attesa").drop_duplicates(subset="SignalKey", keep="first")
        if len(window) < min_n:
            print(f"  {label:<12}{len(window):>5}   (sotto il minimo di {min_n})")
            continue
        pl = np.where(window["win"] == 1, window["Odd"] - 1.0, -1.0)
        print(f"  {label:<12}{len(window):>5}{100 * window['win'].mean():>8.1f}"
              f"{window['Odd'].median():>12.2f}{100 * pl.mean():>+9.1f}")
    print()
    print("  i vincenti il cui gol arriva prima della finestra non compaiono nella")
    print("  riga di quella finestra: e' il costo dell'attesa, ed e' cosi' che va")
    print("  contato invece di stimarlo a parte.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="live_training_data.csv")
    parser.add_argument("--min-n", type=int, default=5,
                        help="segnali minimi perche' un segmento venga mostrato")
    args = parser.parse_args()

    try:
        settled, priced = load(args.csv)
    except Exception as exc:
        print(f"Impossibile leggere {args.csv}: {exc}")
        return 1

    print(f"segnali chiusi: {len(settled)}")
    print(f"di cui con quota reale registrata: {len(priced)}"
          f" ({100 * len(priced) / max(1, len(settled)):.1f}%)")
    if priced.empty:
        print()
        print("Senza quote reali non si puo' dire niente sul margine.")
        print("La quota si registra all'apertura e, se il book non la espone ancora,")
        print("al primo ciclo utile dopo: vedi LIVE_ODDS_LATE nel log.")
        return 0

    block("1. Dove stiamo rispetto al prezzo")
    print("  margine positivo = il book sottovaluta l'evento = guadagno per noi")
    print("  margine negativo = stiamo pagando il margine del book")
    print()
    table([(m, g) for m, g in priced.groupby("Market")], args.min_n)

    block("2. Quando modello e book non sono d'accordo, chi ha ragione?")
    print("  il bot scommette che abbia ragione il modello, ogni volta che pubblica")
    for market, g in priced.groupby("Market"):
        if len(g) < args.min_n:
            continue
        print()
        print(f"  --- {market} (n={len(g)}) ---")
        table([
            ("modello piu' ottimista del book", g[g["model_edge"] > 0.03]),
            ("sostanzialmente d'accordo", g[g["model_edge"].abs() <= 0.03]),
            ("modello piu' pessimista del book", g[g["model_edge"] < -0.03]),
        ], 1)

    block("3. Esiste un segmento con margine positivo?")
    for name, keys in [
        ("per tier", "Tier"),
        ("per campionato", "LeagueName"),
        ("per fascia di minuto", None),
        ("per fascia di quota", None),
    ]:
        print()
        print(f"  {name}:")
        if keys == "Tier" or keys == "LeagueName":
            groups = [(k, g) for k, g in priced.groupby(keys)]
        elif name == "per fascia di minuto":
            bands = pd.cut(priced["Minute"], [0, 5, 8, 12, 20, 45],
                           labels=["1-5", "6-8", "9-12", "13-20", "21+"])
            groups = [(k, g) for k, g in priced.groupby(bands, observed=True)]
        else:
            bands = pd.cut(priced["OpenOdd"], [1.0, 1.25, 1.4, 1.6, 2.0, 100],
                           labels=["<1.25", "1.25-1.40", "1.40-1.60", "1.60-2.00", ">2.00"])
            groups = [(k, g) for k, g in priced.groupby(bands, observed=True)]
        table(sorted(groups, key=lambda kv: -kv[1]["pl"].mean()), args.min_n)

    block("4. Abbiamo abbastanza dati per crederci?")
    wins = int(priced["win"].sum())
    lo, hi = wilson_interval(wins, len(priced))
    imp = priced["implied"].mean()
    print(f"  complessivo: n={len(priced)}  WR {100 * priced['win'].mean():.1f}%"
          f"  (IC95 {100 * lo:.1f}% - {100 * hi:.1f}%)")
    print(f"  probabilita' implicita media: {100 * imp:.1f}%")
    print(f"  ROI misurato: {100 * priced['pl'].mean():+.1f}%")
    print()
    # Niente verdetti binari su un confronto che puo' stare sul filo: si dice
    # dove cade l'intervallo rispetto al prezzo e si lascia leggere.
    if lo > imp:
        verdict = "l'intero intervallo sta SOPRA il prezzo: margine positivo"
    elif hi < imp:
        verdict = "l'intero intervallo sta SOTTO il prezzo: margine negativo"
    else:
        verdict = (f"l'intervallo ({100 * lo:.1f}%-{100 * hi:.1f}%) contiene il prezzo "
                   f"({100 * imp:.1f}%): indistinguibile dal caso")
    print(f"  dove cade: {verdict}")
    print()
    for edge in (0.08, 0.05, 0.03, 0.02):
        need = sample_needed(edge)
        state = "raggiunto" if len(priced) >= need else f"mancano {need - len(priced)}"
        print(f"  per rilevare un margine del {100 * edge:.0f}%: ~{need} prezzate  ({state})")

    block("5. Aspettare conviene? (per singolo segnale)")
    trajectories(args.csv, args.min_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
