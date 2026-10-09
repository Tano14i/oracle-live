"""Se il bot non sta girando, lo rimette in piedi. Indipendente da chi lo chiama.

Perche' esiste, misurato il 9 ottobre 2026.

Il bot e' morto alle 23:49:59Z e nessuno se ne e' accorto per cinque ore e
cinquanta. Il supervisore, che esiste proprio per riavviarlo, non ha scritto
una riga: e' morto con lui. E Windows non si era ne' spento ne' sospeso -
uptime 73,6 ore, ultimo avvio il 6 ottobre.

La causa non era la macchina: era che il supervisore l'avevo avviato io, dalla
sessione di Claude Code. Viveva nell'albero di processi di quella sessione, e
quando la sessione e' finita Windows ha chiuso l'albero. La firma e' il codice
di uscita 0xC000013A (CTRL_C_EXIT), lo stesso che si e' visto al riavvio di
stamattina quando il mio wrapper di PowerShell e' uscito portandosi dietro il
bot appena avviato.

Quindi un avvio "al login" non basta: stanotte nessuno ha fatto login. Serve
qualcosa che controlli ogni tanto se il bot c'e', e che lo avvii STACCATO da
chi ha lanciato il controllo. E' quello che fa questo file.

Come riconosce se il bot gira: prova a prendere oracle_live.lock, lo stesso
lock con cui il bot impedisce a se stesso di partire due volte. Se riesce a
prenderlo, nessuno lo teneva, quindi il bot non c'e'. Nessun elenco di
processi da interpretare, nessun nome da indovinare: la stessa verita' che usa
il bot.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

if os.name == "nt":
    import msvcrt as _lock_mod
    _PLATFORM = "win32"
else:
    import fcntl as _lock_mod
    _PLATFORM = "posix"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BASE_DIR, "oracle_live.lock")
SUPERVISOR = os.path.join(BASE_DIR, "supervisor.py")
PYTHONW = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
LOG_PATH = os.path.join(BASE_DIR, "supervisor.log")

# Flag di creazione Windows. DETACHED_PROCESS stacca la console,
# CREATE_NEW_PROCESS_GROUP evita che un CTRL+C al gruppo del chiamante arrivi
# anche a lui, CREATE_BREAKAWAY_FROM_JOB lo fa uscire dal job object di chi lo
# avvia - ed e' quello che mancava: senza, muore quando muore la sessione.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def log(message: str) -> None:
    riga = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") + " | " + message
    print(riga, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(riga + "\n")
    except OSError:
        pass


def bot_is_running() -> bool:
    """True se qualcuno tiene il lock del bot.

    Se il file non si riesce nemmeno ad aprire si risponde "sta girando": un
    dubbio non deve far partire una seconda istanza.
    """
    try:
        handle = open(LOCK_PATH, "a+")
    except OSError as exc:
        log(f"WATCHDOG_DUBBIO | lock non apribile ({exc}), non faccio niente")
        return True
    try:
        handle.seek(0)
        try:
            if _PLATFORM == "win32":
                _lock_mod.locking(handle.fileno(), _lock_mod.LK_NBLCK, 1)
            else:
                _lock_mod.flock(handle.fileno(), _lock_mod.LOCK_EX | _lock_mod.LOCK_NB)
        except OSError:
            return True          # lo tiene il bot: sta girando
        # L'ho preso io, quindi era libero. Lo rilascio subito: il bot che sto
        # per avviare deve poterlo prendere lui.
        try:
            if _PLATFORM == "win32":
                _lock_mod.locking(handle.fileno(), _lock_mod.LK_UNLCK, 1)
            else:
                _lock_mod.flock(handle.fileno(), _lock_mod.LOCK_UN)
        except OSError:
            pass
        return False
    finally:
        handle.close()


def start_supervisor() -> int:
    """Avvia il supervisore staccato da chi ha chiamato il watchdog.

    Torna il pid, o 0 se non ce l'ha fatta. Prova prima con il breakaway dal
    job object: se il sistema non lo permette, riprova senza, perche' un bot
    avviato in modo imperfetto e' meglio di nessun bot.
    """
    eseguibile = PYTHONW if os.path.exists(PYTHONW) else (
        PYTHON if os.path.exists(PYTHON) else sys.executable)
    if not os.path.exists(SUPERVISOR):
        log(f"WATCHDOG_FALLITO | supervisor.py non trovato in {BASE_DIR}")
        return 0
    comando = [eseguibile, SUPERVISOR]
    for flag, descrizione in ((DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                               | CREATE_BREAKAWAY_FROM_JOB, "staccato dal job"),
                              (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, "staccato")):
        try:
            processo = subprocess.Popen(
                comando, cwd=BASE_DIR, close_fds=True,
                creationflags=flag if os.name == "nt" else 0,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log(f"WATCHDOG_AVVIATO | supervisore pid={processo.pid} ({descrizione})")
            return processo.pid
        except OSError as exc:
            log(f"WATCHDOG_RITENTA | {descrizione} non riuscito: {exc}")
    return 0


def main() -> int:
    if bot_is_running():
        return 0        # tutto a posto: silenzio, cosi' il log non si gonfia
    log("WATCHDOG_ASSENTE | il bot non tiene il lock, lo riavvio")
    return 0 if start_supervisor() else 1


if __name__ == "__main__":
    raise SystemExit(main())
