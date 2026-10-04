"""La raccolta quote a ogni scansione ha funzionato in produzione?

Il 4 ottobre ho committato la modifica che chiede la quota a ogni scansione
mentre un segnale e' pendente, e l'ho riportata come fatta avendo osservato
solo "odds_tracked=0" - cioe' il contatore comparire, non funzionare. Lo stesso
errore che mi e' costato il tabellone sull'attesa.

Questa verifica legge il log reale e pretende la prova: almeno una scansione
con odds_tracked positivo, e almeno un segnale con due letture di quota a
minuti diversi dentro la propria finestra di pendenza - che e' il dato che
prima mancava del tutto (zero su OVER 0.5 HT).

Puo' fallire legittimamente: se da quando la modifica e' attiva non si sono
aperti segnali, la prova non c'e'. In quel caso il cancello resta non
soddisfatto, che e' l'esito onesto.
"""
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "oracle_live.log"
ODDS = ROOT / "odds_history.csv"

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    if not LOG.exists():
        print("FALLITO: oracle_live.log assente")
        return 1

    massimo = 0
    scansioni = 0
    scansioni_con_contatore = 0
    pendenti_visti = 0
    with LOG.open(encoding="utf-8", errors="replace") as handle:
        for riga in handle:
            if "RADAR_SUMMARY" not in riga:
                continue
            scansioni += 1
            # Solo le scansioni successive alla modifica portano il contatore:
            # contare anche le precedenti diluirebbe la misura e renderebbe
            # il fallimento meno leggibile di quanto deve essere.
            m = re.search(r"odds_tracked=(\d+)", riga)
            if not m:
                continue
            scansioni_con_contatore += 1
            massimo = max(massimo, int(m.group(1)))
            p = re.search(r"pending_or_sent=(\d+)", riga)
            if p:
                pendenti_visti += int(p.group(1))
    check(scansioni > 0, "nessuna scansione nel log")
    check(scansioni_con_contatore > 0,
          "nessuna scansione porta odds_tracked: la modifica non e' in esecuzione")
    check(massimo > 0,
          f"odds_tracked mai positivo in {scansioni_con_contatore} scansioni con il contatore"
          f" (pendenti incontrati: {pendenti_visti}): la modifica e' attiva ma non ha"
          " ancora avuto un segnale pendente su cui agire")

    # La prova strutturale: due letture della stessa partita e market a minuti
    # diversi. Prima della modifica era zero su OVER 0.5 HT.
    coppie = 0
    if ODDS.exists():
        visti = {}
        with ODDS.open(encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                chiave = (row.get("FixtureId"), row.get("Market"))
                minuto = row.get("Minute")
                if not chiave[0] or minuto in (None, ""):
                    continue
                visti.setdefault(chiave, set()).add(minuto)
        coppie = sum(1 for minuti in visti.values() if len(minuti) >= 2)
    check(coppie > 0, "nessuna partita con due letture di quota a minuti diversi")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        print(f"(misurato: scansioni={scansioni} con_contatore={scansioni_con_contatore}"
              f" odds_tracked_max={massimo} partite_con_traiettoria={coppie})")
        return 1
    print(f"scansioni={scansioni} con_contatore={scansioni_con_contatore}"
          f" odds_tracked_max={massimo} partite_con_traiettoria={coppie}")
    print("odds tracking verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
