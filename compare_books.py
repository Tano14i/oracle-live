"""Il tuo book paga meglio di quello che il bot vede?

E' la leva piu' promettente che l'analisi ha trovato. Al win rate misurato dei
segnali pubblicati (62.4%) il pareggio sta a quota 1.60; il bot ne ottiene 1.50.
Manca il 6-7% di prezzo, non quattro punti di bravura del modello.

Sono due problemi di difficolta' molto diversa: migliorare il modello di quattro
punti su mille righe e' improbabile, trovare un book che paga 1.60 dove
l'aggregatore segna 1.50 e' ordinaria amministrazione. API-Football da' UNA
quota media; i book reali differiscono fra loro del 5-10% sulla stessa linea, e
nel live differiscono di piu'.

Come si usa, in due passaggi.

1. Esporta i segnali da controllare:

       python compare_books.py --export 20

   Scrive book_comparison.csv con una riga per segnale e la colonna MiaQuota
   vuota. Apri il file, e per ogni segnale scrivi la quota che trovi TU sul tuo
   book nel momento in cui lo ricevi. Lascia vuoto quello che non trovi.

2. Leggi il verdetto:

       python compare_books.py

   Confronta le due colonne, dice se il divario e' sistematico, e ricalcola il
   ROI alla tua quota invece che a quella del bot.

Venti righe bastano per vedere un divario del 6%: serve riempirle nel momento
giusto, non a partita finita, perche' una quota live di dieci minuti dopo non e'
la quota che avresti preso.
"""
import argparse
import math
import os

import numpy as np
import pandas as pd

OUT_PATH = "book_comparison.csv"
COLUMNS = ["SignalKey", "OpenTimeUTC", "Match", "LeagueName", "Market",
           "Minute", "Tier", "QuotaBot", "MiaQuota", "Esito"]


def load_signals(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    if "SignalKey" in df.columns:
        df = df.drop_duplicates(subset="SignalKey", keep="first")
    for column in ["OpenOdd", "Minute"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    # Solo quello che il bot pubblica davvero: gli shadow non li ricevi.
    return df[df["Tier"].isin(["APPROVED", "CAUTION", "GAMBLING"])].copy()


def export(csv_path: str, limit: int) -> int:
    signals = load_signals(csv_path)
    if signals.empty:
        print("Nessun segnale pubblicato nel dataset.")
        return 1
    # Le righe migrate dallo storico non hanno OpenTimeUTC: ordinare senza
    # escluderle fa finire in coda proprio quelle, ed e' la coda che si esporta.
    signals["_t"] = pd.to_datetime(signals["OpenTimeUTC"], errors="coerce", utc=True)
    signals = signals.dropna(subset=["_t"]).sort_values("_t").tail(limit)

    # Il dataset non porta i nomi delle squadre, web_stats.json si': senza quelli
    # il file non si riesce a riempire guardando Telegram.
    names = {}
    try:
        import json
        with open("web_stats.json", encoding="utf-8") as handle:
            monitor = json.load(handle).get("monitor_risultati") or {}
        names = {str(key): value.get("match_up", "") for key, value in monitor.items()
                 if isinstance(value, dict)}
    except Exception:
        pass

    rows = pd.DataFrame({
        "SignalKey": signals["SignalKey"],
        "OpenTimeUTC": signals["OpenTimeUTC"],
        # monitor_risultati tiene solo gli ultimi 200 chiusi: per i piu' vecchi
        # resta l'id partita, che basta a ritrovare il segnale su Telegram.
        "Match": signals["SignalKey"].astype(str).map(
            lambda k: names.get(k) or f"fixture {k.split(':')[0]}"),
        "LeagueName": signals.get("LeagueName", ""),
        "Market": signals["Market"],
        "Minute": signals["Minute"],
        "Tier": signals["Tier"],
        "QuotaBot": signals["OpenOdd"],
        "MiaQuota": "",
        "Esito": signals["Outcome"],
    })[COLUMNS]

    if os.path.exists(OUT_PATH):
        # Non si sovrascrive il lavoro gia' fatto: si aggiungono le righe nuove.
        old = pd.read_csv(OUT_PATH)
        already = set(old["SignalKey"].astype(str))
        rows = rows[~rows["SignalKey"].astype(str).isin(already)]
        if rows.empty:
            print(f"{OUT_PATH} e' gia' aggiornato: nessun segnale nuovo da aggiungere.")
            return 0
        rows = pd.concat([old, rows], ignore_index=True)
        print(f"Aggiunte {len(rows) - len(old)} righe nuove a {OUT_PATH}.")
    else:
        print(f"Scritto {OUT_PATH} con {len(rows)} segnali.")

    rows.to_csv(OUT_PATH, index=False)
    print()
    print("Riempi la colonna MiaQuota con il prezzo che trovi sul tuo book,")
    print("nel momento in cui ricevi il segnale. Poi lancia: python compare_books.py")
    return 0


def report(stake: float) -> int:
    if not os.path.exists(OUT_PATH):
        print(f"{OUT_PATH} non esiste. Prima: python compare_books.py --export 20")
        return 1
    df = pd.read_csv(OUT_PATH)
    for column in ["QuotaBot", "MiaQuota"]:
        df[column] = pd.to_numeric(df.get(column), errors="coerce")

    filled = df[df["MiaQuota"] > 1.0].copy()
    print(f"righe nel file: {len(df)}  |  con la tua quota: {len(filled)}")
    if filled.empty:
        print()
        print("Nessuna quota tua inserita: non c'e' niente da confrontare.")
        return 0

    both = filled[filled["QuotaBot"] > 1.0].copy()
    print(f"confrontabili (entrambe le quote): {len(both)}")
    print()

    if not both.empty:
        both["divario"] = both["MiaQuota"] / both["QuotaBot"] - 1.0
        media = both["divario"].mean()
        mediana = both["divario"].median()
        meglio = int((both["divario"] > 0).sum())
        print("=== il tuo book contro quello che vede il bot ===")
        print(f"  divario medio   : {100 * media:+.1f}%")
        print(f"  divario mediano : {100 * mediana:+.1f}%")
        print(f"  tua quota migliore in {meglio} casi su {len(both)}")
        if len(both) >= 10:
            # Significativita' del divario: se l'intervallo contiene lo zero, il
            # divario non e' distinguibile dal rumore delle singole rilevazioni.
            se = both["divario"].std(ddof=1) / math.sqrt(len(both))
            lo, hi = media - 1.96 * se, media + 1.96 * se
            print(f"  IC95 del divario: {100 * lo:+.1f}% / {100 * hi:+.1f}%")
            if lo > 0:
                print("  -> il tuo book paga sistematicamente di piu'")
            elif hi < 0:
                print("  -> il tuo book paga sistematicamente di meno")
            else:
                print("  -> divario non distinguibile dal caso, servono piu' righe")
        else:
            print(f"  (servono almeno 10 confronti per dire se e' sistematico, ne hai {len(both)})")
        print()

    settled = filled[filled["Esito"].isin(["WIN", "LOSS"])].copy()
    if settled.empty:
        print("Nessun segnale ancora chiuso fra quelli che hai riempito.")
        return 0

    settled["win"] = (settled["Esito"] == "WIN").astype(int)
    print("=== il conto, alla TUA quota ===")
    wr = settled["win"].mean()
    pl_mine = np.where(settled["win"] == 1, settled["MiaQuota"] - 1.0, -1.0)
    print(f"  segnali chiusi    : {len(settled)}  ({int(settled['win'].sum())}W"
          f" - {len(settled) - int(settled['win'].sum())}L, WR {100 * wr:.1f}%)")
    print(f"  quota tua mediana : {settled['MiaQuota'].median():.2f}")
    print(f"  pareggio richiesto: {100 / settled['MiaQuota'].median():.1f}% di win rate")
    print(f"  ROI alla tua quota: {100 * pl_mine.mean():+.1f}%")
    print(f"  P/L con stake {stake:.0f}: {stake * pl_mine.sum():+.2f} EUR")

    paired = settled[settled["QuotaBot"] > 1.0]
    if not paired.empty:
        pl_bot = np.where(paired["win"] == 1, paired["QuotaBot"] - 1.0, -1.0)
        pl_you = np.where(paired["win"] == 1, paired["MiaQuota"] - 1.0, -1.0)
        print()
        print(f"  sugli stessi {len(paired)} segnali:")
        print(f"    ROI alla quota del bot : {100 * pl_bot.mean():+.1f}%")
        print(f"    ROI alla quota tua     : {100 * pl_you.mean():+.1f}%")
        print(f"    differenza             : {100 * (pl_you.mean() - pl_bot.mean()):+.1f} punti")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="live_training_data.csv")
    parser.add_argument("--export", type=int, metavar="N",
                        help="prepara il file con gli ultimi N segnali pubblicati")
    parser.add_argument("--stake", type=float, default=10.0)
    args = parser.parse_args()
    if args.export:
        return export(args.csv, args.export)
    return report(args.stake)


if __name__ == "__main__":
    raise SystemExit(main())
