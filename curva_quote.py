"""La curva del book contro la curva equa: conviene aspettare che la quota salga?

Fabio: "io aspetto che la quota live salga a 1.40".

Il ragionamento e' giusto in aritmetica. A quota 1,40 il pareggio chiede il
71,4%, e un 0-0 all'intervallo qualunque vede un gol nel secondo tempo nel
74,2% dei casi: se il book offrisse 1,40 su una partita media sarebbe un
regalo da quasi quattro punti.

Il problema e' che la quota non sale da sola: sale perche' il tempo passa e la
probabilita' scende. Sui nostri 505 segnali chiusi, restando 0-0:

    47'  ->  77,7% di gol    quota equa 1,287
    56'  ->  70,6%           quota equa 1,417      <- qui l'equo vale 1,40
    60'  ->  66,4%           quota equa 1,507
    70'  ->  54,4%           quota equa 1,838

Quindi la domanda diventa una sola, e si misura: **il book arriva a 1,40 prima
o dopo il minuto in cui 1,40 e' il prezzo giusto?** Se arriva prima, aspettare
e' un margine vero. Se arriva dopo, aspettare e' pagare il tempo.

Questo script risponde, appena ci sono abbastanza punti di curva. Li registra
l'osservatore: a ogni giro, su ogni segnale ancora aperto, legge la quota e il
minuto e li lascia in odds_history.csv. Prima passava 47 fisso, quindi di
curve non ce n'erano: 328 osservazioni, una per partita, tutte allo stesso
minuto.

Uso:  .venv\\Scripts\\python.exe curva_quote.py
"""
import os
import re

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(BASE_DIR, "second_half_log.csv")
QUOTE = os.path.join(BASE_DIR, "odds_history.csv")
MERCATO = "NEXT GOAL LIVE"
SOGLIA = 1.40
# Le stesse giovanili che l'osservatore salta: restano nelle righe vecchie.
NON_GIOCABILI = re.compile(
    r"\bu-?(?:1[4-9]|2[0-3])\b|\bsub-?(?:1[4-9]|2[0-3])\b|\byouth\b|\bjuniores\b"
    r"|\bprimavera\b|\breserves?\b|\bres\.", re.IGNORECASE)


def segnali() -> pd.DataFrame:
    d = pd.read_csv(REGISTRO)
    d["ordine"] = range(len(d))
    u = d.sort_values("ordine").drop_duplicates("FixtureId", keep="last")
    sporche = (u.LeagueName.fillna("") + " | " + u.MatchUp.fillna(""))
    u = u[~sporche.str.contains(NON_GIOCABILI)]
    return u[u.Outcome.isin(["WIN", "LOSS"])].copy()


def curva_equa(chiusi: pd.DataFrame) -> pd.Series:
    """Probabilita' di gol restando 0-0 fino al minuto m, minuto per minuto."""
    vinte = chiusi[chiusi.Outcome == "WIN"].copy()
    vinte["minuto"] = vinte.GoalMinute.fillna(vinte.DetectedMinute)
    vinte = vinte[vinte.minuto.notna()]
    perse = int((chiusi.Outcome == "LOSS").sum())
    fuori = {}
    for m in range(46, 91):
        ancora = int((vinte.minuto > m).sum())
        totale = ancora + perse
        fuori[m] = ancora / totale if totale >= 20 else np.nan
    return pd.Series(fuori, name="prob_vera")


def main() -> int:
    chiusi = segnali()
    equa = curva_equa(chiusi)
    print(f"segnali chiusi usati per la curva equa: {len(chiusi)}")

    if not os.path.exists(QUOTE):
        print("odds_history.csv assente: nessuna curva del book")
        return 0
    q = pd.read_csv(QUOTE)
    q = q[(q.Market == MERCATO) & q.Minute.notna() & q.Odd.notna()]
    q = q[q.FixtureId.isin(set(chiusi.FixtureId))]
    q["Minute"] = pd.to_numeric(q.Minute, errors="coerce")
    q = q[q.Minute >= 46]
    print(f"punti di curva sui nostri segnali: {len(q)} su {q.FixtureId.nunique()} partite")
    per_partita = q.groupby("FixtureId").size()
    print(f"punti per partita: mediana {per_partita.median():.0f}, massimo {per_partita.max()}"
          if len(per_partita) else "nessun punto")
    if len(q) < 50 or per_partita.median() < 2:
        print()
        print("Troppo pochi punti per confrontare le curve: serve che l'osservatore")
        print("giri qualche sera con la registrazione del minuto attiva.")
        print()

    print()
    print("=== il book contro l'equo, minuto per minuto ===")
    print(" minuto    n   quota book   quota equa   scarto    chi paga meglio")
    for a, b in ((46, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 80), (80, 91)):
        s = q[(q.Minute >= a) & (q.Minute < b)]
        if len(s) < 5:
            continue
        p = equa.loc[a:b - 1].mean()
        eq = 1 / p if p and not np.isnan(p) else np.nan
        book = s.Odd.mean()
        scarto = book - eq
        chi = "IL BOOK (margine per noi)" if scarto > 0 else "l'equo (paghiamo il tempo)"
        print(f" {a:2}-{b-1:2}'  {len(s):4}     {book:6.3f}       {eq:6.3f}   {scarto:+6.3f}   {chi}")

    print()
    print(f"=== la strategia: entrare quando il book mostra {SOGLIA:.2f} ===")
    esiti = chiusi.set_index("FixtureId").Outcome.to_dict()
    righe = []
    for fid, g in q.sort_values("Minute").groupby("FixtureId"):
        arrivata = g[g.Odd >= SOGLIA]
        if arrivata.empty:
            continue
        prima = arrivata.iloc[0]
        righe.append((fid, prima.Minute, prima.Odd, esiti.get(fid)))
    t = pd.DataFrame(righe, columns=["FixtureId", "Minute", "Odd", "Outcome"]).dropna()
    if len(t) < 10:
        print(f" solo {len(t)} partite hanno raggiunto {SOGLIA:.2f} nei dati registrati:")
        print(" il verdetto non esiste ancora.")
        return 0
    pl = np.where(t.Outcome == "WIN", t.Odd - 1, -1)
    boot = [np.random.default_rng(i).choice(pl, len(pl), replace=True).mean()
            for i in range(6000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f" partite che arrivano a {SOGLIA:.2f}: {len(t)} su {q.FixtureId.nunique()} "
          f"({len(t)/q.FixtureId.nunique():.0%})")
    print(f" minuto in cui ci arrivano: mediana {t.Minute.median():.0f}'  "
          f"(l'equo vale {SOGLIA:.2f} al 56')")
    print(f" esiti: {(t.Outcome=='WIN').sum()}W-{(t.Outcome=='LOSS').sum()}L = "
          f"{(t.Outcome=='WIN').mean():.1%}  (il pareggio a {SOGLIA:.2f} chiede {100/SOGLIA:.1f}%)")
    print(f" ROI {pl.sum()/len(pl):+.1%}   IC95 {lo:+.1%}/{hi:+.1%}"
          + ("   ZERO FUORI: margine" if lo > 0 else "   lo zero e' dentro: non dimostrato"))
    print()
    print(" confronto con l'entrare subito al 47' sulle stesse partite:")
    subito = chiusi[chiusi.FixtureId.isin(set(t.FixtureId)) & chiusi.LiveOdd.notna()]
    if len(subito):
        pls = np.where(subito.Outcome == "WIN", subito.LiveOdd - 1, -1)
        print(f"  n={len(subito)}  quota media {subito.LiveOdd.mean():.3f}  "
              f"ROI {pls.sum()/len(pls):+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
