"""La cattura conserva ogni campo che l'API manda, non solo quelli previsti.

Il vecchio fetch_fixture_stats mappava la risposta su un dizionario a dodici
chiavi fisse: tutto il resto veniva scartato, e un campo cercato con il nome
sbagliato restava zero senza che nulla lo segnalasse. E' cosi' che
"dangerous attacks" e' stato letto come misurato e valeva zero.

Qui si pretende il contrario: un campo che arriva viene conservato anche se
nessuno lo ha previsto, cosi' quando l'API ne aggiunge uno non serve ricordarsi
di aggiungerlo al codice.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import second_half as sh  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def squadra(coppie):
    return {"statistics": [{"type": k, "value": v} for k, v in coppie]}


def main() -> int:
    # Campi veri di /fixtures/statistics piu' uno inventato che nessuno prevede.
    risposta = [
        squadra([("Shots on Goal", 6), ("Total Shots", 12), ("Corner Kicks", 3),
                 ("Ball Possession", "42%"), ("Total passes", 457),
                 ("expected_goals", 1.62), ("Campo Inventato", 7)]),
        squadra([("Shots on Goal", 4), ("Total Shots", 9), ("Corner Kicks", 5),
                 ("Ball Possession", "58%"), ("Total passes", 512),
                 ("expected_goals", 0.91), ("Campo Inventato", 2)]),
    ]
    c = sh.capture_fields(risposta)

    # Niente viene buttato, nemmeno quello che non serve al messaggio.
    for atteso in ("shots on goal", "total shots", "corner kicks", "ball possession",
                   "total passes", "expected goals", "campo inventato"):
        check(atteso in c["types"], f"campo perso dalla cattura: {atteso}")
    check("campo inventato" in c["totals"],
          "un campo non previsto non finisce nei totali: la cattura e' a chiavi fisse")
    check(c["totals"]["campo inventato"] == 9.0,
          f"somma sbagliata sul campo non previsto: {c['totals'].get('campo inventato')}")

    # Per squadra, cosi' il possesso resta leggibile.
    check(c["home"].get("ball possession") == 42.0,
          f"possesso casa sbagliato: {c['home'].get('ball possession')}")
    check(c["away"].get("ball possession") == 58.0,
          f"possesso ospiti sbagliato: {c['away'].get('ball possession')}")

    # I nomi vengono normalizzati come in oracle_live, altrimenti i due lati
    # cercherebbero chiavi diverse sullo stesso dato.
    check(sh.normalize_type("Shots on Goal") == "shots on goal",
          "normalizzazione dei nomi diversa dall'attesa")
    check(sh.normalize_type("expected_goals") == "expected goals",
          "underscore non normalizzato")

    # None resta None: un campo che l'API manda vuoto non e' uno zero.
    convuoto = sh.capture_fields([squadra([("Red Cards", None), ("Corner Kicks", 2)])])
    check(convuoto["totals"].get("red cards") is None,
          f"un campo vuoto diventa zero: {convuoto['totals'].get('red cards')}")
    check(convuoto["totals"].get("corner kicks") == 2.0,
          "un campo valorizzato accanto a uno vuoto si perde")
    check(sh.parse_value(None) is None, "parse_value trasforma None in un numero")
    check(sh.parse_value("") is None, "parse_value trasforma la stringa vuota in un numero")
    check(sh.parse_value("58%") == 58.0, "parse_value non legge le percentuali")
    check(sh.parse_value(0) == 0.0, "parse_value perde lo zero misurato")

    # CONTROLLO POSITIVO: con una risposta vuota la cattura non inventa campi.
    vuota = sh.capture_fields([])
    check(vuota["types"] == [] and vuota["totals"] == {},
          f"la cattura inventa campi da una risposta vuota: {vuota}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(c['types'])} campi conservati compreso uno non previsto; "
          "vuoto resta vuoto, zero resta zero")
    print("stats capture verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
