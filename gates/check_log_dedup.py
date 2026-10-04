"""Una dipendenza che fallisce in loop non deve riempire il disco.

Il caso reale: api.telegram.org irraggiungibile per 29 giorni ha prodotto una
riga POLLING_RESTART identica ogni 5 secondi, cioe' 191 MB di log in cui le
poche righe utili erano introvabili. La rotazione limita lo spazio ma butta via
proprio le righe buone; serve anche non scrivere mille volte la stessa.

La verifica emette lo stesso messaggio molte volte e controlla che il file ne
contenga meno, con un conteggio delle ripetizioni soppresse. Poi emette
messaggi diversi e controlla che quelli NON vengano soppressi: senza questo
secondo controllo un filtro che scarta tutto passerebbe la verifica.
"""
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_setup import build_file_handler  # noqa: E402

FAIL = []
RIPETIZIONI = 200


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def emetti(target: Path, messaggi) -> list:
    handler = build_file_handler(str(target))
    logger = logging.getLogger("gate_dedup_probe")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    for m in messaggi:
        logger.info(m)
    handler.flush()
    handler.close()
    return [r for r in target.read_text(encoding="utf-8").splitlines() if r.strip()]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        uguali = emetti(Path(tmp) / "a.log",
                        ["POLLING_RESTART | host non raggiungibile"] * RIPETIZIONI)
        diversi = emetti(Path(tmp) / "b.log",
                         [f"RADAR_SUMMARY | scansione {i}" for i in range(RIPETIZIONI)])

    check(len(uguali) < RIPETIZIONI / 2,
          f"{len(uguali)} righe su {RIPETIZIONI} identiche: la soppressione non agisce")
    check(any("soppress" in r.lower() or "ripetiz" in r.lower() for r in uguali),
          "nessuna riga segnala quante ripetizioni sono state soppresse")
    # Controllo positivo: i messaggi diversi non devono essere toccati.
    check(len(diversi) == RIPETIZIONI,
          f"soppresse anche righe diverse fra loro: {len(diversi)} su {RIPETIZIONI}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{RIPETIZIONI} righe identiche -> {len(uguali)} scritte; "
          f"{RIPETIZIONI} righe diverse -> {len(diversi)} scritte")
    print("log dedup verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
