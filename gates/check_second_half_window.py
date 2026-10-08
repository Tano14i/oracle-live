"""Il segnale del 47' si apre solo nella finestra giusta e solo a 0-0.

La regola e' quella di Ten: colpo al 9' sul gol del primo tempo, e se la partita
e' 0-0 all'intervallo un secondo colpo al 47'. Se la finestra si allargasse, il
market diventerebbe "gol da qui alla fine" aperto a qualunque minuto - un'altra
scommessa, con un altro tasso base e un altro prezzo.

La verifica prova sia i casi che devono passare sia quelli che devono essere
rifiutati: una finestra che accetta tutto passerebbe un controllo solo positivo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import second_half as sh  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    check(sh.WINDOW_START == 46 and sh.WINDOW_END == 48,
          f"finestra {sh.WINDOW_START}-{sh.WINDOW_END}: attesa 46-48")

    # Devono passare: 0-0 dentro la finestra, con la partita in corso.
    for minuto in range(sh.WINDOW_START, sh.WINDOW_END + 1):
        ok, motivo = sh.second_half_gate(minuto, 0, "2H")
        check(ok, f"minuto {minuto} a 0-0 rifiutato: {motivo}")

    # Devono essere rifiutati, uno per ragione.
    casi_no = [
        (45, 0, "2H", "minuto prima della finestra"),
        (49, 0, "2H", "minuto dopo la finestra"),
        (60, 0, "2H", "minuto molto dopo la finestra"),
        (47, 1, "2H", "punteggio non 0-0"),
        (47, 3, "2H", "punteggio con tre gol"),
        (47, 0, "HT", "partita all'intervallo"),
        (47, 0, "FT", "partita finita"),
        (47, 0, "SUSP", "partita sospesa"),
        (None, 0, "2H", "minuto sconosciuto"),
        (47, None, "2H", "punteggio sconosciuto"),
    ]
    for minuto, gol, stato, perche in casi_no:
        ok, _ = sh.second_half_gate(minuto, gol, stato)
        check(not ok, f"accettato un caso da rifiutare ({perche}): minuto={minuto} gol={gol} stato={stato}")

    # La regola di Ten e' "0-0 ALL'INTERVALLO". Il punteggio live al 46' puo'
    # essere in ritardo: su Petare-Atletico Avila, l'8 ottobre 2026, goals e
    # score dicevano 0-0 e gli eventi un gol al 42'. Con l'intervallo noto
    # comanda quello.
    ok, motivo = sh.second_half_gate(47, 0, "2H", 0)
    check(ok, f"0-0 all'intervallo e 0-0 adesso rifiutato: {motivo}")
    check("intervallo" in motivo, f"il motivo non dice da dove viene il punteggio: {motivo}")
    ok, motivo = sh.second_half_gate(47, 0, "2H", 1)
    check(not ok, "accettata una partita che all'intervallo non era 0-0, "
                  "con il punteggio live in ritardo a 0-0")
    check("intervallo" in motivo, f"il rifiuto non spiega l'intervallo: {motivo}")
    ok, _ = sh.second_half_gate(47, 1, "2H", 0)
    check(not ok, "accettata una partita dove il gol e' gia' arrivato: la scommessa e' chiusa")

    # CONTROLLO NEGATIVO sul ripiego: intervallo ignoto non deve bloccare tutto,
    # altrimenti un fornitore che non manda score.halftime zittirebbe il market.
    ok, motivo = sh.second_half_gate(47, 0, "2H", None)
    check(ok, f"con l'intervallo ignoto non si apre piu' niente: {motivo}")
    check("ignoto" in motivo,
          f"il ripiego sul punteggio live non viene dichiarato nel motivo: {motivo}")

    # in_window da solo, con i bordi.
    check(not sh.in_window(sh.WINDOW_START - 1), "in_window accetta il minuto prima")
    check(not sh.in_window(sh.WINDOW_END + 1), "in_window accetta il minuto dopo")
    check(not sh.in_window(None), "in_window accetta un minuto nullo")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"finestra {sh.WINDOW_START}-{sh.WINDOW_END} a 0-0: "
          f"{sh.WINDOW_END - sh.WINDOW_START + 1} casi accettati, "
          f"{len(casi_no)} rifiutati per la ragione giusta")
    print("second half window verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
