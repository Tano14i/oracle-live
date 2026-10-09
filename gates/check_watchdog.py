"""Il bot non deve restare giu' perche' chi lo ha avviato e' morto.

Misurato il 9 ottobre 2026: bot morto alle 23:49:59Z, nessuno in piedi per
cinque ore e cinquanta, e il supervisore - che esiste per riavviarlo - morto
con lui senza scrivere una riga. Windows non si era spento ne' sospeso: uptime
73,6 ore. Il supervisore viveva nell'albero di processi della sessione che
l'aveva avviato, e quando quella e' finita e' finito anche lui. Codice di
uscita 0xC000013A, CTRL_C_EXIT.

Da qui due requisiti, e questo cancello verifica entrambi.

Uno: riconoscere se il bot c'e' senza indovinare nomi di processi, usando lo
stesso lock con cui il bot impedisce a se stesso di partire due volte. E nel
dubbio - lock non apribile - rispondere "sta girando", perche' far partire una
seconda istanza e' peggio che non fare niente.

Due: avviarlo STACCATO. Senza CREATE_BREAKAWAY_FROM_JOB il processo nuovo resta
nel job object di chi lo ha avviato e muore con lui: e' esattamente il difetto
che ha causato il buco di stanotte, quindi e' il flag che va verificato.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import watchdog as wd  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


class PopenFinta:
    """Registra come sarebbe stato avviato il supervisore, senza avviarlo."""

    chiamate = []

    def __init__(self, comando, **kw):
        PopenFinta.chiamate.append({"comando": comando, **kw})
        self.pid = 4242


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="oracle_wd_")
    veri = (wd.LOCK_PATH, wd.LOG_PATH, wd.subprocess.Popen)
    wd.LOCK_PATH = os.path.join(cartella, "prova.lock")
    wd.LOG_PATH = os.path.join(cartella, "prova.log")
    wd.subprocess.Popen = PopenFinta
    try:
        return verifica(cartella)
    finally:
        wd.LOCK_PATH, wd.LOG_PATH, wd.subprocess.Popen = veri
        PopenFinta.chiamate.clear()
        shutil.rmtree(cartella, ignore_errors=True)


def verifica(cartella) -> int:
    check("oracle_wd_" in wd.LOCK_PATH,
          "il cancello sta usando il lock del bot vivo: potrebbe avviarne un secondo")

    # 1. Lock libero: il bot non c'e', e il watchdog lo avvia.
    PopenFinta.chiamate.clear()
    check(wd.bot_is_running() is False,
          "con il lock libero il watchdog crede che il bot stia girando: non lo riavvierebbe mai")
    check(wd.main() == 0, "con il bot assente main() torna un errore")
    check(len(PopenFinta.chiamate) == 1,
          f"il supervisore non viene avviato una volta sola: {len(PopenFinta.chiamate)} avvii")

    # 2. IL FLAG CHE CONTA: staccato dal job di chi lo avvia.
    if PopenFinta.chiamate:
        c = PopenFinta.chiamate[0]
        flag = c.get("creationflags", 0)
        check(flag & wd.CREATE_BREAKAWAY_FROM_JOB,
              "manca CREATE_BREAKAWAY_FROM_JOB: il bot morirebbe di nuovo con la "
              "sessione che lo ha avviato, che e' il difetto di stanotte")
        check(flag & wd.DETACHED_PROCESS,
              "manca DETACHED_PROCESS: resta attaccato alla console del chiamante")
        check(flag & wd.CREATE_NEW_PROCESS_GROUP,
              "manca CREATE_NEW_PROCESS_GROUP: un CTRL+C al chiamante arriverebbe anche a lui")
        check(c.get("cwd") == wd.BASE_DIR,
              f"avviato nella cartella sbagliata: {c.get('cwd')}")
        check(str(c["comando"][-1]).endswith("supervisor.py"),
              f"non avvia il supervisore: {c['comando']}")
        check("pythonw" in str(c["comando"][0]).lower(),
              f"non usa pythonw, quindi lascerebbe una finestra aperta: {c['comando'][0]}")
        check(c.get("stdin") is not None and c.get("stdout") is not None,
              "stdin/stdout non reindirizzati: ereditando la console morirebbe con lei")

    # 3. Lock tenuto da qualcun altro: il watchdog NON deve avviare niente.
    #    Un secondo handle, anche nello stesso processo, non riesce a prenderlo:
    #    i lock di Windows sono per handle, quindi la prova e' fedele.
    tenuto = open(wd.LOCK_PATH, "a+")
    tenuto.seek(0)
    wd._lock_mod.locking(tenuto.fileno(), wd._lock_mod.LK_NBLCK, 1)
    try:
        PopenFinta.chiamate.clear()
        check(wd.bot_is_running() is True,
              "con il lock tenuto il watchdog crede che il bot sia morto")
        check(wd.main() == 0, "main() segnala un errore mentre il bot sta girando")
        check(PopenFinta.chiamate == [],
              f"avvia una SECONDA istanza del bot mentre la prima gira: {PopenFinta.chiamate}")
    finally:
        wd._lock_mod.locking(tenuto.fileno(), wd._lock_mod.LK_UNLCK, 1)
        tenuto.close()

    # 4. Dopo il rilascio il lock risulta di nuovo libero: il watchdog non si
    #    tiene in mano il lock che il bot dovra' prendere.
    check(wd.bot_is_running() is False,
          "il watchdog resta attaccato al lock e impedisce al bot di prenderlo")

    # 5. Nel dubbio non si avvia niente: lock non apribile -> "sta girando".
    wd.LOCK_PATH = cartella          # una cartella non si apre come file
    PopenFinta.chiamate.clear()
    check(wd.bot_is_running() is True,
          "con il lock illeggibile il watchdog decide che il bot e' morto e ne avvia un altro")
    check(PopenFinta.chiamate == [], f"avvio nel dubbio: {PopenFinta.chiamate}")
    wd.LOCK_PATH = os.path.join(cartella, "prova.lock")

    # 6. Un supervisore che non esiste viene segnalato, non ignorato.
    vero_sup = wd.SUPERVISOR
    wd.SUPERVISOR = os.path.join(cartella, "non_esiste.py")
    PopenFinta.chiamate.clear()
    try:
        check(wd.main() == 1, "un supervisore mancante non viene segnalato come errore")
        check(PopenFinta.chiamate == [], "prova ad avviare un file che non c'e'")
    finally:
        wd.SUPERVISOR = vero_sup

    # 7. Quando agisce lo scrive, quando tutto va bene tace: un watchdog che
    #    scrive una riga ogni dieci minuti riempie il log di niente.
    righe = Path(wd.LOG_PATH).read_text(encoding="utf-8").splitlines() if os.path.exists(wd.LOG_PATH) else []
    check(any("WATCHDOG_AVVIATO" in r for r in righe),
          f"l'avvio non viene registrato: {righe}")
    PopenFinta.chiamate.clear()
    tenuto = open(wd.LOCK_PATH, "a+")
    tenuto.seek(0)
    wd._lock_mod.locking(tenuto.fileno(), wd._lock_mod.LK_NBLCK, 1)
    try:
        prima = len(Path(wd.LOG_PATH).read_text(encoding="utf-8").splitlines())
        wd.main()
        dopo = len(Path(wd.LOG_PATH).read_text(encoding="utf-8").splitlines())
        check(dopo == prima, f"scrive nel log anche quando non fa niente ({dopo - prima} righe)")
    finally:
        wd._lock_mod.locking(tenuto.fileno(), wd._lock_mod.LK_UNLCK, 1)
        tenuto.close()

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print("il bot si riconosce dal suo lock, mai una seconda istanza, avvio staccato "
          "dal job del chiamante, silenzio quando non c'e' niente da fare")
    print("watchdog verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
