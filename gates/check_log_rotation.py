"""Il log non puo' crescere senza limite.

Il 30 settembre oracle_live.log era arrivato a 191 MB, per il 99% righe
POLLING_RESTART identiche. L'ho svuotato a mano: non e' una correzione, e'
un rinvio. Questa verifica misura il comportamento, non la presenza di una
costante: scrive abbastanza da superare il limite e controlla che il file
abbia davvero ruotato e che il totale su disco resti dentro il tetto
dichiarato.
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_setup import LOG_BACKUP_COUNT, LOG_MAX_BYTES, build_file_handler  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    check(LOG_MAX_BYTES > 0, f"LOG_MAX_BYTES deve essere positivo, e' {LOG_MAX_BYTES}")
    check(LOG_BACKUP_COUNT > 0, f"LOG_BACKUP_COUNT deve essere positivo, e' {LOG_BACKUP_COUNT}")
    cap = LOG_MAX_BYTES * (LOG_BACKUP_COUNT + 1)
    check(cap < 200 * 1024 * 1024, f"il tetto complessivo {cap} byte non evita il caso da 191 MB")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "probe.log"
        handler = build_file_handler(str(target))
        logger = logging.getLogger("gate_rotation_probe")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False

        # Abbastanza da superare il limite piu' volte, con messaggi diversi
        # cosi' la soppressione dei duplicati non interferisce con la misura.
        payload = "x" * 512
        written = 0
        i = 0
        while written < LOG_MAX_BYTES * (LOG_BACKUP_COUNT + 2):
            logger.info("riga %d %s", i, payload)
            written += 540
            i += 1
        handler.flush()
        handler.close()

        files = sorted(p for p in Path(tmp).iterdir() if p.name.startswith("probe.log"))
        total = sum(p.stat().st_size for p in files)
        check(len(files) > 1, f"nessuna rotazione avvenuta: {[p.name for p in files]}")
        check(len(files) <= LOG_BACKUP_COUNT + 1,
              f"{len(files)} file contro un massimo di {LOG_BACKUP_COUNT + 1}")
        check(total <= cap * 1.05,
              f"totale su disco {total} byte oltre il tetto {cap}")
        check(target.stat().st_size <= LOG_MAX_BYTES * 1.05,
              f"il file attivo {target.stat().st_size} byte supera {LOG_MAX_BYTES}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"tetto complessivo {cap / 1024 / 1024:.0f} MB su {LOG_BACKUP_COUNT + 1} file")
    print("log rotation verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
