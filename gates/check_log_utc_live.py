"""L'esito vero: il log IN PRODUZIONE scrive l'ora giusta.

check_log_utc.py prova che il modulo sa scrivere in UTC. Non prova che il
processo in esecuzione lo faccia: la correzione del formatter vale solo al
riavvio, e un bot avviato prima continua a scrivere l'ora locale con la Z
appiccicata. E' la differenza fra "il codice e' giusto" e "il sistema fa la
cosa giusta", che in questa sessione ho confuso piu' di una volta.

Legge l'ultima riga datata del log reale e la confronta con l'UTC vero, con
lo stesso controllo negativo contro l'ora locale.
"""
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "oracle_live.log"
# Una scansione ogni ~50 secondi; dieci minuti coprono anche le ore con poche
# partite senza rendere il cancello cieco.
TOLERANZA = timedelta(minutes=10)
RIGA = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})Z \|")

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    if not LOG.exists():
        print("FALLITO: oracle_live.log assente")
        return 1
    ultimo = None
    with LOG.open(encoding="utf-8", errors="replace") as handle:
        for riga in handle:
            m = RIGA.match(riga)
            if m:
                ultimo = m.group(1)
    if not ultimo:
        print("FALLITO: nessuna riga datata nel log")
        return 1

    emesso = datetime.strptime(ultimo, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    ora_utc = datetime.now(timezone.utc)
    scarto_utc = abs(emesso - ora_utc)
    check(scarto_utc <= TOLERANZA,
          f"l'ultima riga ({ultimo}Z) dista {scarto_utc} dall'UTC vero"
          f" ({ora_utc:%Y-%m-%d %H:%M:%S}Z): il processo in esecuzione non scrive UTC")

    offset = -time.timezone if (time.daylight == 0) else -time.altzone
    if offset == 0:
        print("nota: fuso locale uguale a UTC, controllo negativo non applicabile")
    else:
        locale_come_utc = datetime.now().replace(tzinfo=timezone.utc)
        scarto_locale = abs(emesso - locale_come_utc)
        check(scarto_locale > TOLERANZA,
              f"l'ultima riga coincide con l'ora LOCALE ({ultimo}Z): la Z resta falsa")
        print(f"controllo negativo attivo: offset locale {offset / 3600:+.0f}h,"
              f" distanza dall'ora locale {scarto_locale}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"ultima riga {ultimo}Z contro UTC {ora_utc:%Y-%m-%d %H:%M:%S}Z, scarto {scarto_utc}")
    print("log utc live verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
