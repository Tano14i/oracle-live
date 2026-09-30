"""Tiene vivo oracle_live.py: se il processo muore, lo rimette in piedi.

Nato dopo un crash del PC che ha lasciato il bot fermo 21 ore su una macchina
accesa: il problema non era il PC spento, era che nessuno lo riavviava.

Distingue l'uscita pulita dal crash. oracle_live.py esce con codice 0 sia
quando lo fermi tu, sia quando trova il lock gia' preso da un'altra istanza:
in entrambi i casi riavviare sarebbe sbagliato, quindi il supervisore si ferma.
"""
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(BASE_DIR, "oracle_live.py")
PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
SUPERVISOR_LOG = os.path.join(BASE_DIR, "supervisor.log")

BACKOFF_START = 5
BACKOFF_MAX = 300
STABLE_SECONDS = 300      # oltre questa durata il tentativo conta come riuscito
MAX_RAPID_FAILURES = 10   # crash immediati di fila prima di arrendersi

child = None
stopping = False


def log(message: str) -> None:
    line = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") + " | " + message
    print(line, flush=True)
    try:
        with open(SUPERVISOR_LOG, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def stop(signum, frame):
    global stopping
    stopping = True
    log("SUPERVISOR_STOP | richiesto arresto, chiudo il bot")
    if child and child.poll() is None:
        try:
            child.terminate()
            child.wait(timeout=30)
        except Exception:
            child.kill()
    raise SystemExit(0)


def main() -> int:
    global child
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, stop)
        except (ValueError, OSError):
            pass

    python = PYTHON if os.path.exists(PYTHON) else sys.executable
    if not os.path.exists(BOT_SCRIPT):
        log("SUPERVISOR_FAIL | script non trovato: " + BOT_SCRIPT)
        return 1

    env = os.environ.copy()
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")

    log("SUPERVISOR_START | python=" + python)
    backoff = BACKOFF_START
    rapid_failures = 0
    restarts = 0

    while not stopping:
        started = time.time()
        try:
            child = subprocess.Popen([python, BOT_SCRIPT], cwd=BASE_DIR, env=env)
        except Exception as exc:
            log("SUPERVISOR_SPAWN_FAIL | " + str(exc))
            return 1
        log("BOT_STARTED | pid=" + str(child.pid) + " riavvii=" + str(restarts))

        code = child.wait()
        uptime = time.time() - started

        if stopping:
            break

        if code == 0:
            # uscita pulita: fermato a mano, oppure lock gia' preso.
            log("BOT_EXIT_CLEAN | codice=0 durata=" + str(int(uptime))
                + "s | non riavvio (arresto voluto o altra istanza attiva)")
            return 0

        restarts += 1
        if uptime >= STABLE_SECONDS:
            backoff = BACKOFF_START
            rapid_failures = 0
            log("BOT_CRASH | codice=" + str(code) + " dopo " + str(int(uptime))
                + "s | riavvio fra " + str(backoff) + "s")
        else:
            rapid_failures += 1
            log("BOT_CRASH_RAPID | codice=" + str(code) + " dopo " + str(int(uptime))
                + "s | consecutivi=" + str(rapid_failures) + " | riavvio fra "
                + str(backoff) + "s")
            if rapid_failures >= MAX_RAPID_FAILURES:
                log("SUPERVISOR_GIVE_UP | " + str(rapid_failures)
                    + " crash immediati di fila: c'e' un problema che il riavvio non risolve")
                return 1

        for _ in range(backoff):
            if stopping:
                break
            time.sleep(1)
        backoff = min(backoff * 2, BACKOFF_MAX)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
