"""Un timestamp etichettato Z deve essere UTC.

Il formatter scriveva "%(asctime)sZ" con asctime in ora LOCALE: ogni riga del
log portava una Z su un orario sbagliato di due ore. Mi ha fatto perdere tempo
il 30 settembre, quando ho creduto che il bot avesse smesso di scansionare
mentre era il log a mentire sull'ora, e falsa qualunque correlazione con i log
dell'API.

La verifica confronta il timestamp emesso con l'ora UTC vera. Include un
controllo negativo: se il fuso locale e' diverso da UTC, il timestamp NON deve
coincidere con l'ora locale - altrimenti la verifica passerebbe anche su un
formatter sbagliato in una macchina configurata su UTC.
"""
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_setup import build_file_handler  # noqa: E402

FAIL = []
TOLERANZA = timedelta(seconds=90)


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "utc.log"
        handler = build_file_handler(str(target))
        logger = logging.getLogger("gate_utc_probe")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
        logger.info("SONDA | riga di prova")
        handler.flush()
        handler.close()
        riga = target.read_text(encoding="utf-8").strip().splitlines()[-1]

    testo = riga.split(" | ")[0]
    check(testo.endswith("Z"), f"il timestamp non e' etichettato Z: {testo!r}")
    try:
        emesso = datetime.strptime(testo.rstrip("Z"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        print("FALLITO: timestamp illeggibile", testo, exc)
        return 1

    ora_utc = datetime.now(timezone.utc)
    scarto_utc = abs(emesso - ora_utc)
    check(scarto_utc <= TOLERANZA,
          f"il timestamp dista {scarto_utc} dall'ora UTC vera ({testo} contro {ora_utc:%H:%M:%S})")

    # Controllo negativo: su una macchina non-UTC il timestamp deve NON
    # coincidere con l'ora locale, altrimenti la Z resta una bugia.
    offset = -time.timezone if (time.daylight == 0) else -time.altzone
    if offset == 0:
        print("nota: fuso locale uguale a UTC, controllo negativo non applicabile")
    else:
        ora_locale_come_utc = datetime.now().replace(tzinfo=timezone.utc)
        scarto_locale = abs(emesso - ora_locale_come_utc)
        check(scarto_locale > TOLERANZA,
              f"il timestamp coincide con l'ora LOCALE ({testo}): la Z e' falsa")
        print(f"controllo negativo attivo: offset locale {offset / 3600:+.0f}h, "
              f"distanza dall'ora locale {scarto_locale}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"timestamp {testo} contro UTC {ora_utc:%Y-%m-%d %H:%M:%S}Z, scarto {scarto_utc}")
    print("log utc verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
