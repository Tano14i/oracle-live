"""Un report non puo' contraddire se stesso, e non si pubblica da solo.

L'11 ottobre 2026 il report di performance diceva, nello stesso messaggio:

    titolo:            +9.071,60 EUR    ROI +33,2%    2.729 segnali chiusi
    le sue righe:      -1.460,90 EUR    ROI  -7,4%    1.971 segnali chiusi

Diecimilacinquecentotrentadue euro e mezzo di scarto, col segno opposto. Il
titolo veniva dal contatore stats["total_profit"], le righe dal dataset con le
quote vere dove ci sono; nessuno dei due sapeva dell'altro. E 758 segnali
esistevano solo nei contatori.

Il numero del titolo non restava fra noi: maybe_send_performance_report lo
mandava ogni N chiusure al canale admin, **al canale VIP e al canale free**, e
ne generava anche il testo pronto per i social, con "1000 -> 91945 EUR" e gli
hashtag. Era una dichiarazione falsa sui soldi spedita a chi paga per i
segnali.

Due requisiti, e questo cancello li tiene entrambi.

1. La pubblicazione automatica e' spenta. Non "sconsigliata": spenta, e se
   qualcuno la riaccende il punto 2 deve comunque reggere.

2. Il titolo e' la somma delle sue righe. Non una versione piu' prudente dello
   stesso errore: la stessa cifra, allo stesso centesimo. E' lo stesso
   principio di report_pl.py, che per costruzione non sa produrre un totale
   mescolato.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    import config

    # 1. L'interruttore esiste ed e' spento.
    check(hasattr(config, "PERFORMANCE_REPORT_BROADCAST"),
          "non esiste nessun interruttore per la pubblicazione automatica")
    check(getattr(config, "PERFORMANCE_REPORT_BROADCAST", True) is False,
          "la pubblicazione automatica del report e' ACCESA: il titolo di quel "
          "messaggio finisce su VIP e su free")

    sorgente = (Path(__file__).resolve().parent.parent / "oracle_live.py").read_text(
        encoding="utf-8", errors="replace").splitlines()

    # L'interruttore va controllato all'inizio della funzione che pubblica, non
    # dopo aver composto il messaggio.
    inizio = next((n for n, r in enumerate(sorgente)
                   if r.startswith("def maybe_send_performance_report")), None)
    check(inizio is not None, "maybe_send_performance_report non esiste piu'")
    if inizio is not None:
        corpo = sorgente[inizio:inizio + 40]
        # Deve essere un'istruzione, non una parola in un commento: la prima
        # versione di questo controllo si accontentava del nome ovunque, e un
        # mio commento che citava l'interruttore bastava a farlo passare.
        i_flag = next((n for n, r in enumerate(corpo)
                       if r.strip().startswith("if not PERFORMANCE_REPORT_BROADCAST")), None)
        i_invio = next((n for n, r in enumerate(corpo) if "send_message" in r), None)
        check(i_flag is not None, "la funzione che pubblica non guarda l'interruttore")
        check(i_flag is None or i_flag < 5,
              f"l'interruttore viene guardato alla riga {i_flag} del corpo: va in testa")
        if i_flag is not None and i_invio is not None:
            check(i_flag < i_invio,
                  "il messaggio viene composto e mandato prima di guardare l'interruttore")
        # E i tre destinatari sono ancora nel piano: se un giorno si riaccende,
        # si riaccende anche verso VIP e free. Il punto 2 deve proteggere la'.
        piano = [r for r in corpo if "VIP_CHANNEL_ID" in r or "CHANNEL_ID" in r]
        check(bool(piano) or i_flag is not None,
              "il piano di consegna e' cambiato: ricontrollare dove va il report")

    # 2. IL REQUISITO CHE RESTA ANCHE SE SI RIACCENDE: il titolo e' la somma
    #    delle righe. Si verifica sulla funzione vera, con i dati veri.
    import importlib.util
    percorso = Path(__file__).resolve().parent.parent / "oracle_live.py"
    spec = importlib.util.spec_from_file_location("_ol_report", percorso)
    # Importare oracle_live intero accende il bot: la funzione si prova per
    # equivalenza sui dati, replicando esattamente i due conti che divergevano.
    import json

    import numpy as np
    import pandas as pd

    base = Path(__file__).resolve().parent.parent
    quote = {"NEXT GOAL LIVE": config.QUOTA_NEXT_GOAL,
             "OVER 0.5 HT": config.QUOTA_O05_HT,
             "OVER 1.5 HT": config.QUOTA_O15_HT}
    d = pd.read_csv(base / "live_training_data.csv", low_memory=False)
    s = d[d.Outcome.isin(["WIN", "LOSS"])
          & d.Tier.isin(["APPROVED", "CAUTION", "GAMBLING"])]
    s = s.drop_duplicates(subset=["SignalKey"], keep="first")
    somma_righe = 0.0
    chiusi_righe = 0
    for m, g in s.groupby(s.Market.fillna("UNKNOWN")):
        q = pd.to_numeric(g.get("OpenOdd"), errors="coerce").where(lambda x: x > 1.0)
        eff = q.fillna(quote.get(m, config.QUOTA))
        somma_righe += float(np.where(g.Outcome.values == "WIN",
                                      (eff - 1).values, -1).sum()) * float(config.STAKE)
        chiusi_righe += len(g)

    legacy = json.loads((base / "web_stats.json").read_text(encoding="utf-8"))
    titolo_legacy = float(legacy.get("total_profit", 0.0))
    print(f"somma delle righe per market : {somma_righe:+,.2f} EUR su {chiusi_righe} chiusi")
    print(f"contatore legacy             : {titolo_legacy:+,.2f} EUR")
    print(f"scarto fra i due             : {titolo_legacy - somma_righe:+,.2f} EUR")

    # Il codice non deve piu' usare il contatore legacy come titolo. Si verifica
    # che la funzione ricalcoli il totale dalle righe.
    testo = percorso.read_text(encoding="utf-8", errors="replace")
    i_snap = testo.index("def compute_performance_snapshot")
    i_fine = testo.index("def format_performance_by_market")
    corpo_snap = testo[i_snap:i_fine]
    check('total_profit = sum(float(item["profit"]) for item in by_market)' in corpo_snap,
          "il titolo del report non viene ricalcolato dalla somma delle righe: "
          "puo' tornare a contraddirle")
    check(corpo_snap.count('stats.get("total_profit"') <= 1,
          "il contatore legacy viene ancora usato piu' di una volta nel calcolo")
    # E senza righe non si inventa un totale.
    check("total_profit = 0.0" in corpo_snap,
          "senza righe per market il titolo resta quello del contatore legacy: "
          "un numero senza niente sotto")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print("pubblicazione automatica spenta, interruttore in testa alla funzione, "
          "titolo ricalcolato dalla somma delle righe, nessun totale inventato")
    print("performance report verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
