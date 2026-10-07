"""Il blocco statistiche mostra i sette campi, e dice quali l'API non manda.

Questo cancello esiste per un errore durato mesi. fetch_fixture_stats cercava
"dangerous attacks" con un nome che /fixtures/statistics non usa: il campo e'
rimasto a 0,00 in 89 casi su 89, il modello lo pesava 0.0000, e io avevo letto
quel peso come "le statistiche live non servono" invece che "il campo e' vuoto".
Un numero mancante stampato come zero e' indistinguibile da una misura.

La verifica pretende che un campo assente venga dichiarato assente, e che uno
presente a zero venga mostrato come zero. Sono due cose diverse e il messaggio
deve distinguerle.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import second_half as sh  # noqa: E402

FAIL = []

CHIESTI = ["Corner", "Attacchi", "Attacchi pericolosi", "Tiri in porta",
           "Tiri fuori porta", "Cartellini", "Possesso"]


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def squadra(**campi):
    return {"statistics": [{"type": k, "value": v} for k, v in campi.items()]}


def main() -> int:
    etichette = [e for e, _ in sh.STAT_FIELDS]
    for chiesto in CHIESTI:
        check(chiesto in etichette, f"campo chiesto non previsto dal modulo: {chiesto}")
    check(len(sh.STAT_FIELDS) == len(CHIESTI),
          f"il modulo prevede {len(sh.STAT_FIELDS)} campi, chiesti {len(CHIESTI)}")

    # Caso completo: tutti i campi presenti e valorizzati.
    pieno = sh.capture_fields([
        squadra(**{"Corner Kicks": 4, "Attacks": 60, "Dangerous Attacks": 25,
                   "Shots on Goal": 3, "Shots off Goal": 2, "Yellow Cards": 1,
                   "Red Cards": 0, "Ball Possession": "58%"}),
        squadra(**{"Corner Kicks": 2, "Attacks": 40, "Dangerous Attacks": 15,
                   "Shots on Goal": 1, "Shots off Goal": 4, "Yellow Cards": 2,
                   "Red Cards": 0, "Ball Possession": "42%"}),
    ])
    testo = sh.format_stats_block(pieno)
    for etichetta in CHIESTI:
        check(etichetta in testo, f"{etichetta} assente dal blocco quando il dato c'e'")
    check("non disponibile" not in testo,
          f"dichiarato non disponibile un campo presente:\n{testo}")
    check("Corner: 6" in testo, f"i corner non sono sommati fra le squadre:\n{testo}")
    check("Possesso: 58% - 42%" in testo,
          f"il possesso va mostrato per squadra, non sommato:\n{testo}")
    check(not sh.missing_fields(pieno),
          f"campi dichiarati mancanti quando ci sono: {sh.missing_fields(pieno)}")

    # Caso reale dell'API verificata: attacchi e attacchi pericolosi assenti.
    parziale = sh.capture_fields([
        squadra(**{"Corner Kicks": 3, "Shots on Goal": 2, "Shots off Goal": 1,
                   "Yellow Cards": 0, "Ball Possession": "50%"}),
        squadra(**{"Corner Kicks": 1, "Shots on Goal": 0, "Shots off Goal": 2,
                   "Yellow Cards": 0, "Ball Possession": "50%"}),
    ])
    testo2 = sh.format_stats_block(parziale)
    check("Attacchi: non disponibile" in testo2,
          f"un campo assente non e' dichiarato assente:\n{testo2}")
    check("Attacchi pericolosi: non disponibile" in testo2,
          f"attacchi pericolosi assenti non dichiarati:\n{testo2}")
    mancanti = sh.missing_fields(parziale)
    check(set(mancanti) == {"Attacchi", "Attacchi pericolosi"},
          f"elenco dei mancanti sbagliato: {mancanti}")

    # LA DISTINZIONE CHE CONTA: presente e uguale a zero non e' "non disponibile".
    check("Cartellini: 0" in testo2,
          f"uno zero misurato va mostrato come zero, non come assente:\n{testo2}")
    check("Tiri in porta: 2" in testo2,
          "uno zero in una squadra non deve azzerare il totale: " + testo2)

    # CONTROLLO POSITIVO: con nessun campo, tutti e sette devono risultare assenti.
    vuoto = sh.capture_fields([])
    check(len(sh.missing_fields(vuoto)) == len(CHIESTI),
          f"senza dati solo {len(sh.missing_fields(vuoto))} campi su {len(CHIESTI)} risultano assenti")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(CHIESTI)} campi; con dati completi nessun 'non disponibile'; "
          f"con l'API reale mancano {mancanti}; uno zero misurato resta zero")
    print("stats block verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
