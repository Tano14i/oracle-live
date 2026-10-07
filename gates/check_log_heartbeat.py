"""Il log non deve tacere a lungo mentre il processo lavora.

La soppressione delle ripetizioni, com'era, lasciava passare una riga ogni 50.
Con il bot inattivo ogni scansione scrive un RADAR_SUMMARY byte per byte
identico, e 50 scansioni da 50 secondi fanno piu' di mezz'ora: misurati 21 buchi
oltre i 10 minuti, il piu' grande di 35. Un log muto tornava ad avere due
significati, ripetizioni soppresse oppure processo morto, che e' l'ambiguita' che
la soppressione doveva togliere.

La verifica usa un orologio finto, cosi' e' deterministica e non aspetta cinque
minuti veri. Include il controllo opposto: senza far passare il tempo, le stesse
righe devono restare soppresse - altrimenti un filtro che non sopprime niente
passerebbe questa verifica.
"""
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_setup import REPEAT_NOTICE_SECONDS, RepeatSuppressor, build_formatter  # noqa: E402

FAIL = []
IDENTICHE = 30          # meno della soglia di conteggio, cosi' decide solo il tempo
NOTICE_EVERY = 50
NOTICE_SECONDS = 300.0


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


class OrologioFinto:
    def __init__(self) -> None:
        self.adesso = 0.0

    def __call__(self) -> float:
        return self.adesso

    def avanza(self, secondi: float) -> None:
        self.adesso += secondi


def emetti(messaggi_con_attesa) -> list:
    """Scrive su un file temporaneo con orologio controllato, torna le righe."""
    orologio = OrologioFinto()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hb.log"
        handler = logging.FileHandler(str(target), encoding="utf-8")
        handler.setFormatter(build_formatter())
        handler.addFilter(RepeatSuppressor(NOTICE_EVERY, NOTICE_SECONDS, clock=orologio))
        logger = logging.getLogger("gate_heartbeat_probe")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
        for messaggio, attesa in messaggi_con_attesa:
            orologio.avanza(attesa)
            logger.info(messaggio)
        handler.flush()
        handler.close()
        return [r for r in target.read_text(encoding="utf-8").splitlines() if r.strip()]


def main() -> int:
    check(REPEAT_NOTICE_SECONDS <= 600,
          f"il battito a {REPEAT_NOTICE_SECONDS}s lascia buchi troppo lunghi")

    identico = "RADAR_SUMMARY | fixtures=0 league_filtered=0"

    # Con il tempo che passa: il battito deve uscire anche se il conteggio
    # (30) non raggiunge la soglia (50).
    con_tempo = emetti([(identico, 60.0)] * IDENTICHE)
    check(len(con_tempo) > 1,
          f"nessun battito in {IDENTICHE} righe identiche distanziate di 60s:"
          " il log tace mentre il processo lavora")
    check(any("ripetizione" in r for r in con_tempo[1:]),
          "il battito non dice che sono ripetizioni soppresse")

    # CONTROLLO OPPOSTO: senza far passare il tempo, le stesse righe devono
    # restare soppresse. Se passassero, il filtro non sopprimerebbe niente.
    senza_tempo = emetti([(identico, 0.0)] * IDENTICHE)
    check(len(senza_tempo) == 1,
          f"{len(senza_tempo)} righe scritte senza che passasse tempo:"
          " la soppressione non agisce")

    # Il battito non deve essere piu' frequente del necessario.
    atteso_max = IDENTICHE * 60.0 / NOTICE_SECONDS + 2
    check(len(con_tempo) <= atteso_max,
          f"{len(con_tempo)} battiti dove ne bastavano {atteso_max:.0f}:"
          " il filtro scrive troppo")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"battito ogni {NOTICE_SECONDS:.0f}s: {IDENTICHE} righe identiche a 60s di"
          f" distanza -> {len(con_tempo)} scritte; senza tempo -> {len(senza_tempo)}")
    print("log heartbeat verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
