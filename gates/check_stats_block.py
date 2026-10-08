"""Il blocco statistiche mostra i sette campi, e dice quali l'API non manda.

Questo cancello esiste per un errore durato mesi. fetch_fixture_stats cercava
"dangerous attacks" con un nome che /fixtures/statistics non usa: il campo e'
rimasto a 0,00 in 89 casi su 89, il modello lo pesava 0.0000, e io avevo letto
quel peso come "le statistiche live non servono" invece che "il campo e' vuoto".
Un numero mancante stampato come zero e' indistinguibile da una misura.

Dall'8 ottobre 2026 i campi chiesti sono quelli che l'API manda davvero.
"Attacks" e "Dangerous Attacks" non esistono in quella risposta: su una partita
coperta arrivano sedici campi e non sono fra loro. Al loro posto "Total Shots"
e "Shots insidebox", che misurano la stessa pressione ed esistono.

La verifica pretende che un campo assente venga dichiarato assente, che uno
presente a zero venga mostrato come zero, e che dove l'API dichiara di non
raccogliere le statistiche il blocco dica la ragione una volta invece di
elencare sette "non disponibile" che sembrano un guasto nostro.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Il blocco contiene emoji: su una console a codepagina 1252 un print di
# diagnostica morirebbe di UnicodeEncodeError, nascondendo il guasto vero.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import second_half as sh  # noqa: E402

FAIL = []

CHIESTI = ["Corner", "Tiri totali", "Tiri in area", "Tiri in porta",
           "Tiri fuori porta", "Cartellini", "Possesso"]

# I nomi veri, letti dalla risposta di /fixtures/statistics su Brasile Serie B
# l'8 ottobre 2026. Se un'etichetta del messaggio cercasse un nome che l'API
# non usa, tornerebbe l'errore di "dangerous attacks".
NOMI_API = {"Passes accurate", "Shots insidebox", "Shots outsidebox",
            "Blocked Shots", "Free Kicks", "Shots on Goal", "Goalkeeper Saves",
            "Shots off Goal", "Offsides", "Total passes", "Total Shots",
            "Yellow Cards", "Corner Kicks", "Fouls", "Red Cards",
            "Ball Possession"}


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

    # Ogni nome cercato deve esistere nella risposta reale dell'API.
    normalizzati = {sh.normalize_type(n) for n in NOMI_API}
    for etichetta, nomi in sh.STAT_FIELDS:
        for nome in nomi:
            check(nome in normalizzati,
                  f"{etichetta} cerca '{nome}', che l'API non manda: "
                  f"e' l'errore di dangerous attacks")
    # E i due campi inesistenti non devono tornare.
    for morto in ("attacks", "dangerous attacks"):
        cercati = [n for _, nomi in sh.STAT_FIELDS for n in nomi]
        check(morto not in cercati, f"il modulo cerca ancora '{morto}', che non esiste")

    # Caso completo: tutti i campi presenti e valorizzati.
    pieno = sh.capture_fields([
        squadra(**{"Corner Kicks": 4, "Total Shots": 9, "Shots insidebox": 5,
                   "Shots on Goal": 3, "Shots off Goal": 2, "Yellow Cards": 1,
                   "Red Cards": 0, "Ball Possession": "58%"}),
        squadra(**{"Corner Kicks": 2, "Total Shots": 6, "Shots insidebox": 2,
                   "Shots on Goal": 1, "Shots off Goal": 4, "Yellow Cards": 2,
                   "Red Cards": 0, "Ball Possession": "42%"}),
    ])
    testo = sh.format_stats_block(pieno)
    for etichetta in CHIESTI:
        check(etichetta in testo, f"{etichetta} assente dal blocco quando il dato c'e'")
    check("non disponibile" not in testo,
          f"dichiarato non disponibile un campo presente:\n{testo}")
    check("Corner: 6" in testo, f"i corner non sono sommati fra le squadre:\n{testo}")
    check("Tiri totali: 15" in testo, f"i tiri totali non sono sommati:\n{testo}")
    check("Tiri in area: 7" in testo, f"i tiri in area non sono sommati:\n{testo}")
    check("Possesso: 58% - 42%" in testo,
          f"il possesso va mostrato per squadra, non sommato:\n{testo}")
    check(not sh.missing_fields(pieno),
          f"campi dichiarati mancanti quando ci sono: {sh.missing_fields(pieno)}")
    check(sh.NOTE_NO_STATS not in testo,
          "il blocco dichiara non raccolte statistiche che ha ricevuto")

    # Caso parziale: l'API manda alcuni campi e non altri.
    parziale = sh.capture_fields([
        squadra(**{"Corner Kicks": 3, "Shots on Goal": 2, "Shots off Goal": 1,
                   "Yellow Cards": 0, "Ball Possession": "50%"}),
        squadra(**{"Corner Kicks": 1, "Shots on Goal": 0, "Shots off Goal": 2,
                   "Yellow Cards": 0, "Ball Possession": "50%"}),
    ])
    testo2 = sh.format_stats_block(parziale)
    mancanti = sh.missing_fields(parziale)
    check(set(mancanti) == {"Tiri totali", "Tiri in area"},
          f"elenco dei mancanti sbagliato: {mancanti}")
    # I mancanti stanno in UNA riga, non una per campo: sette righe identiche
    # che dicono "no" rendono il messaggio illeggibile.
    righe_mancanti = [r for r in testo2.splitlines() if r.startswith(sh.NOTE_MISSING_PREFIX)]
    check(len(righe_mancanti) == 1,
          f"i campi mancanti non stanno in una riga sola ({len(righe_mancanti)} righe): "
          f"senza quella riga un campo assente torna indistinguibile da uno zero")
    # Niente accessi all'indice senza rete: un cancello che si schianta con un
    # IndexError non diagnostica nulla, dice solo che qualcosa e' andato storto.
    riga_mancanti = righe_mancanti[0] if righe_mancanti else ""
    for assente in mancanti:
        check(assente in riga_mancanti,
              f"{assente} manca e non viene nominato fra i senza dato: '{riga_mancanti}'")
    check("non disponibile" not in testo2,
          f"tornano le righe 'non disponibile':\n{testo2}")
    # Una riga per ogni campo presente, piu' quella dei mancanti.
    check(len(testo2.splitlines()) == len(CHIESTI) - len(mancanti) + 1,
          f"il blocco ha {len(testo2.splitlines())} righe invece di "
          f"{len(CHIESTI) - len(mancanti) + 1}:\n{testo2}")
    # E un campo presente non deve finire fra i mancanti.
    for presente in ("Corner", "Possesso"):
        check(presente not in riga_mancanti,
              f"{presente} c'e' ed e' elencato fra i senza dato: '{riga_mancanti}'")

    # LA DISTINZIONE CHE CONTA: presente e uguale a zero resta uno zero mostrato,
    # e non finisce fra i campi senza dato.
    zero_misurato = sh.capture_fields([
        squadra(**{"Corner Kicks": 0, "Yellow Cards": 0, "Red Cards": 0}),
        squadra(**{"Corner Kicks": 0, "Yellow Cards": 0, "Red Cards": 0}),
    ])
    testo3 = sh.format_stats_block(zero_misurato)
    check("Corner: 0" in testo3,
          f"uno zero misurato non viene mostrato come zero:\n{testo3}")
    check("Cartellini: 0" in testo3,
          f"uno zero misurato sui cartellini sparisce:\n{testo3}")
    riga3 = next((r for r in testo3.splitlines()
                  if r.startswith(sh.NOTE_MISSING_PREFIX)), "")
    check("Corner" not in riga3,
          f"uno zero misurato viene elencato fra i campi senza dato:\n{testo3}")
    check("Tiri in porta: 2" in testo2,
          "uno zero in una squadra non deve azzerare il totale: " + testo2)

    # CONTROLLO POSITIVO: con nessun campo, tutti e sette devono risultare assenti.
    vuoto = sh.capture_fields([])
    check(len(sh.missing_fields(vuoto)) == len(CHIESTI),
          f"senza dati solo {len(sh.missing_fields(vuoto))} campi su {len(CHIESTI)} risultano assenti")

    # Competizione senza copertura: la ragione una volta, non sette righe vuote.
    scoperto = sh.format_stats_block(vuoto, sh.NOTE_NO_STATS)
    check(sh.NOTE_NO_STATS in scoperto,
          f"non viene dichiarato che l'API non raccoglie le statistiche:\n{scoperto}")
    check("non disponibile" not in scoperto,
          f"sette 'non disponibile' su una competizione senza copertura:\n{scoperto}")
    check(len(scoperto.splitlines()) == 1,
          f"il blocco senza copertura occupa {len(scoperto.splitlines())} righe invece di una")

    # Ma i numeri che abbiamo comunque - i cartellini dagli eventi - si vedono.
    solo_cartellini = sh.capture_fields([])
    solo_cartellini.setdefault("totals", {})["yellow cards"] = 2.0
    con_eventi = sh.format_stats_block(solo_cartellini, sh.NOTE_NO_STATS)
    check("Cartellini: 2" in con_eventi,
          f"un dato recuperato dagli eventi non viene mostrato:\n{con_eventi}")
    check(sh.NOTE_NO_STATS in con_eventi,
          "la ragione sparisce appena arriva un numero")
    check("Corner: non disponibile" not in con_eventi,
          f"tornano le righe vuote accanto al dato recuperato:\n{con_eventi}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(CHIESTI)} campi, tutti con nomi che l'API manda davvero; "
          f"con dati completi nessun 'non disponibile'; mancanti dichiarati {mancanti}; "
          f"uno zero misurato resta zero; senza copertura una riga sola")
    print("stats block verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
