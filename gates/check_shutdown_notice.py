"""Chi spegne il bot deve sapere che non si riaccende da solo.

L'8 ottobre 2026 un /shutdown e' arrivato un secondo dopo un riavvio
automatico. Il bot si e' spento, e con lui il supervisore: per lui un'uscita
con codice 0 vale come arresto voluto, quindi non riavvia. Il messaggio di
allora - "Shutdown completed. The process will now close." - era vero e
inutile: non diceva che nessuno avrebbe rimesso in piedi niente, e il bot e'
rimasto giu' finche' qualcuno non e' andato a guardare i log.

La verifica pretende tre cose dal messaggio: che dichiari che si ferma anche il
supervisore, che porti il comando per riaccenderlo, e che quel comando punti a
file che esistono davvero. Un'istruzione di recupero sbagliata e' peggio che
nessuna istruzione, perche' la leggi quando il bot e' giu'.

Poi pretende che l'avviso venga mandato PRIMA dello spegnimento: request_shutdown
ferma il polling, e un avviso spedito dopo puo' non partire.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# supervisor.py non fa niente all'import: tutto sta sotto __main__.
import supervisor  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    acceso = supervisor.shutdown_notice(True)
    pausa = supervisor.shutdown_notice(False)

    # 1. Dice che si ferma anche il supervisore. E' il fatto che sorprende.
    for testo in (acceso, pausa):
        check("supervisore" in testo.lower(),
              f"il messaggio non nomina il supervisore:{chr(10)}{testo}")
        check("da solo" in testo or "nessuno" in testo.lower(),
              f"il messaggio non dice che nessuno riaccende il bot:{chr(10)}{testo}")

    # 2. Porta il comando per riaccendere, e il comando e' eseguibile: i due
    #    percorsi che contiene devono esistere.
    comando = supervisor.restart_command()
    check(comando in acceso, f"il comando di riavvio non compare nel messaggio:{chr(10)}{acceso}")
    percorsi = re.findall('"([^"]+)"', comando)
    check(len(percorsi) == 2, f"il comando non contiene due percorsi citati: {comando}")
    for percorso in percorsi:
        check(os.path.exists(percorso), f"il comando di riavvio punta a un file che non c'e': {percorso}")
    check(any(p.endswith("supervisor.py") for p in percorsi),
          f"il comando non avvia il supervisore: {comando}")
    check(any(p.endswith("pythonw.exe") or p.endswith("python.exe") for p in percorsi),
          f"il comando non usa l'interprete del progetto: {comando}")
    # Un comando con percorsi relativi funziona solo da una cartella precisa.
    for percorso in percorsi:
        check(os.path.isabs(percorso),
              f"percorso relativo nel comando di recupero: {percorso}")

    # 3. Lo stato del radar e' riportato, e i due casi sono distinti: dopo il
    #    riavvio il radar torna com'era, e saperlo cambia cosa fai dopo.
    check("acceso" in acceso, f"con radar acceso non lo dice:{chr(10)}{acceso}")
    check("pausa" in pausa, f"con radar in pausa non lo dice:{chr(10)}{pausa}")
    check(acceso != pausa, "il messaggio e' identico con il radar acceso e in pausa")

    # CONTROLLO NEGATIVO: il vecchio messaggio non deve passare queste prove.
    vecchio = "Shutdown completed. The process will now close."
    check("supervisore" not in vecchio.lower() and supervisor.restart_command() not in vecchio,
          "il controllo negativo e' rotto: il vecchio messaggio passerebbe")

    # 4. Nel gestore, l'avviso precede lo spegnimento.
    sorgente = (Path(__file__).resolve().parent.parent / "oracle_live.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    inizio = next((n for n, r in enumerate(sorgente) if "def shutdown_cmd(" in r), None)
    check(inizio is not None, "shutdown_cmd non trovato in oracle_live.py")
    if inizio is not None:
        corpo = sorgente[inizio:inizio + 25]
        i_avviso = next((n for n, r in enumerate(corpo) if "shutdown_notice(" in r), None)
        i_spegni = next((n for n, r in enumerate(corpo) if "request_shutdown()" in r), None)
        check(i_avviso is not None, "shutdown_cmd non manda l'avviso nuovo")
        check(i_spegni is not None, "shutdown_cmd non chiama request_shutdown")
        if i_avviso is not None and i_spegni is not None:
            check(i_avviso < i_spegni,
                  "lo spegnimento precede l'avviso: il polling si ferma e l'avviso puo' non partire")
        check(any("except" in r for r in corpo[:(i_spegni or len(corpo))]),
              "un avviso che non parte impedirebbe lo spegnimento: manca la protezione")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"il messaggio nomina il supervisore, porta un comando assoluto verso file "
          f"esistenti, distingue radar acceso e in pausa, e parte prima dello spegnimento")
    print("shutdown notice verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
