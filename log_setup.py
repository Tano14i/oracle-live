"""Configurazione del log: tetto allo spazio, ora vera, niente righe ripetute.

Tre difetti reali, tutti visti in questa settimana.

Il primo: `logging.FileHandler` non ruota. Il 30 settembre oracle_live.log era
a 191 MB perche' api.telegram.org era irraggiungibile da 29 giorni e il bot
scriveva la stessa riga ogni cinque secondi. Svuotarlo a mano non e' una
correzione, e' un rinvio.

Il secondo: il formatter scriveva `"%(asctime)sZ"` con asctime in ora LOCALE.
Ogni riga portava una Z su un orario sbagliato di due ore. Mi ha fatto credere
che il bot avesse smesso di scansionare quando era il log a mentire sull'ora, e
rende impossibile correlare il log con quello dell'API.

Il terzo: la rotazione da sola limita lo spazio ma butta via le righe buone.
Con 191 MB di POLLING_RESTART identici, le poche righe utili erano
introvabili - e con la sola rotazione sarebbero state le prime a sparire.

Il modulo sta separato da oracle_live.py perche' cosi' la configurazione del
log si puo' verificare senza importare il bot intero (modello, pandas, telebot).
"""
import logging
import threading
import time
from logging.handlers import RotatingFileHandler

# 10 MB per file, 5 file: tetto di 50 MB contro i 191 MB osservati. Tiene
# settimane di log normale e rende impossibile il caso patologico.
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 4

# Ogni quante ripetizioni identiche consecutive lasciar passare una riga di
# riepilogo. Abbastanza raro da non riempire il disco, abbastanza frequente da
# accorgersi che qualcosa gira a vuoto.
REPEAT_NOTICE_EVERY = 50

# E anche: ogni quanti secondi, a prescindere dal conteggio.
#
# Serve perche' il solo conteggio ha prodotto buchi da 35 minuti. Quando il bot
# e' inattivo ogni scansione scrive un RADAR_SUMMARY byte per byte identico, e
# una riga ogni 50 scansioni da 50 secondi vuol dire piu' di mezz'ora di
# silenzio. Cosi' il log muto tornava ad avere due significati - ripetizioni
# soppresse oppure processo morto - che e' esattamente l'ambiguita' che la
# soppressione doveva togliere.
REPEAT_NOTICE_SECONDS = 300

LOG_FORMAT = "%(asctime)sZ | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class RepeatSuppressor(logging.Filter):
    """Prima riga di una serie identica, poi una ogni N ripetizioni O ogni T secondi.

    Non e' un filtro generico sul volume: sopprime solo ripetizioni
    CONSECUTIVE dello stesso messaggio. Messaggi diversi passano sempre, anche
    a raffica, perche' sono informazione.

    Il rilascio a tempo e' il battito: senza di esso il solo conteggio ha
    prodotto buchi da 35 minuti con il bot inattivo, e un log muto tornava ad
    avere due significati.
    """

    def __init__(self, notice_every: int = REPEAT_NOTICE_EVERY,
                 notice_seconds: float = REPEAT_NOTICE_SECONDS,
                 clock=time.monotonic) -> None:
        super().__init__()
        self._notice_every = max(2, int(notice_every))
        self._notice_seconds = max(1.0, float(notice_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._last = None
        self._repeats = 0
        self._last_emitted = clock()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True

        with self._lock:
            if message != self._last:
                soppresse = self._repeats
                self._last = message
                self._repeats = 0
                self._last_emitted = self._clock()
                if soppresse >= self._notice_every:
                    # La serie precedente si e' chiusa: si dice quante righe
                    # sono state soppresse, altrimenti il buco e' invisibile.
                    record.msg = (f"[{soppresse} righe identiche soppresse prima di questa] "
                                  f"{message}")
                    record.args = ()
                return True

            self._repeats += 1
            scaduto = (self._clock() - self._last_emitted) >= self._notice_seconds
            if self._repeats % self._notice_every == 0 or scaduto:
                # Il battito: si lascia passare una riga anche solo perche' e'
                # passato troppo tempo, cosi' un log muto significa una cosa sola.
                record.msg = (f"{message} | ripetizione {self._repeats},"
                              " righe identiche soppresse")
                record.args = ()
                self._last_emitted = self._clock()
                return True
            return False


def build_formatter() -> logging.Formatter:
    """Formatter con l'ora in UTC, cosi' la Z finale dice la verita'."""
    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    formatter.converter = time.gmtime
    return formatter


def build_file_handler(path: str,
                       max_bytes: int = LOG_MAX_BYTES,
                       backup_count: int = LOG_BACKUP_COUNT,
                       notice_every: int = REPEAT_NOTICE_EVERY,
                       notice_seconds: float = REPEAT_NOTICE_SECONDS) -> RotatingFileHandler:
    """Handler su file: ruota, scrive in UTC, sopprime le ripetizioni."""
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=False,
    )
    handler.setFormatter(build_formatter())
    handler.addFilter(RepeatSuppressor(notice_every, notice_seconds))
    return handler
