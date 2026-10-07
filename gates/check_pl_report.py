"""Il report sul P/L non puo' produrre una cifra mescolata.

L'errore che questo cancello impedisce: il 7 ottobre ho riportato "+7,90 EUR"
sommando 4,90 misurati su 5 segnali prezzati e 3,00 stimati su 20 che non erano
giocabili da nessuna parte. Il numero sembrava cassa.

La verifica non si fida del fatto che il report sia scritto bene adesso:
controlla che il guardrail RIFIUTI una struttura mescolata, con un controllo
positivo. Senza quello, un validatore che non valida niente passerebbe.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import report_pl  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    report = report_pl.build_report()

    # Il report deve tenere separate le due cifre...
    for key in ("measured_pl", "estimated_pl", "priced_count", "unpriced_count",
                "wins", "losses", "unplayable_count"):
        check(key in report, f"campo mancante nel report: {key}")

    # ...e non deve avere nessun campo che rappresenti un totale unico.
    presenti = sorted(k for k in report if str(k).lower() in report_pl.FORBIDDEN_KEYS)
    check(not presenti, f"il report contiene cifre mescolate: {presenti}")

    # CONTROLLO POSITIVO: il validatore deve rifiutare una struttura mescolata.
    # Senza questo, un validatore vuoto passerebbe la verifica.
    for chiave in ("total_pl", "profit", "totale"):
        finto = dict(report)
        finto[chiave] = 1.23
        try:
            report_pl.validate_report(finto)
            FAIL.append(f"il validatore ha ACCETTATO un report con {chiave}: non valida niente")
        except report_pl.BlendedTotalError:
            pass

    # Il testo non deve contenere una riga che somma le due cifre.
    testo = report_pl.format_report(report)
    somma = report["measured_pl"] + report["estimated_pl"]
    for forma in (f"{somma:+.2f}", f"{somma:.2f}"):
        check(forma not in testo,
              f"il testo contiene la somma {forma}: misurato e stimato vanno separati")
    check("MISURATO" in testo and "STIMATO" in testo,
          "il testo non distingue esplicitamente misurato da stimato")
    check("non giocabili" in testo,
          "il testo non dichiara quanti segnali non erano giocabili a nessun prezzo")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"campi separati, validatore rifiuta 3 forme di totale, testo senza somma "
          f"({report['priced_count']} prezzati / {report['unpriced_count']} stimati / "
          f"{report['unplayable_count']} non giocabili)")
    print("pl report verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
