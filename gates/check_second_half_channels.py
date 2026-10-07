"""Il segnale del 47' non deve raggiungere i canali a pagamento.

Il tasso base misurato su 164.590 partite 0-0 all'intervallo e' 74,2%: pareggio
a quota 1,348. Su "gol nel secondo tempo" il book paga 1,08-1,15, cioe' una
perdita del 18% per scommessa. Finche' questo non e' validato sui dati raccolti
dall'osservatore stesso, mandarlo su free o VIP significa spedire una perdita
misurata a chi paga.

La verifica controlla tre cose: che il mittente di default scriva solo al canale
admin, che il messaggio dichiari la quota contro il pareggio invece di
presentarla nuda, e che l'osservatore registri la riga anche quando l'invio
fallisce - altrimenti un errore di rete farebbe perdere il dato oltre al
messaggio.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import second_half as sh  # noqa: E402
import second_half_observer as obs  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


class BotFinto:
    def __init__(self) -> None:
        self.inviati = []

    def send_message(self, chat_id, text, **kw):
        self.inviati.append((chat_id, text))


def main() -> int:
    import config

    # 1. Il mittente di default scrive a un solo destinatario: l'admin.
    bot = BotFinto()
    obs.default_sender(bot)("prova")
    destinatari = [c for c, _ in bot.inviati]
    check(len(destinatari) == 1, f"il mittente scrive a {len(destinatari)} destinatari")
    if destinatari:
        check(str(destinatari[0]) == str(config.CHAT_ID),
              f"destinatario {destinatari[0]} invece del canale admin")
        for nome, valore in (("CHANNEL_ID", getattr(config, "CHANNEL_ID", None)),
                             ("VIP_CHANNEL_ID", getattr(config, "VIP_CHANNEL_ID", None))):
            if valore:
                check(str(destinatari[0]) != str(valore),
                      f"il mittente scrive su {nome}: e' un canale a pagamento")

    # 2. Il codice non nomina i canali pubblici da nessuna parte.
    sorgente = Path(obs.__file__).read_text(encoding="utf-8")
    for vietato in ("CHANNEL_ID", "VIP_CHANNEL_ID"):
        check(vietato not in sorgente,
              f"{vietato} compare in second_half_observer: puo' finire sui canali")

    # 3. Il messaggio dichiara la quota contro il pareggio, non nuda.
    capture = sh.capture_fields([
        {"statistics": [{"type": "Corner Kicks", "value": 3},
                        {"type": "Shots on Goal", "value": 2},
                        {"type": "Ball Possession", "value": "55%"}]},
        {"statistics": [{"type": "Corner Kicks", "value": 1},
                        {"type": "Shots on Goal", "value": 1},
                        {"type": "Ball Possession", "value": "45%"}]},
    ])
    base = {"MatchUp": "A vs B", "Country": "X", "LeagueName": "Y", "Minute": 47}

    sotto = obs.format_message(dict(base, LiveOdd=1.10), capture)
    check("SOTTO il pareggio" in sotto,
          f"una quota sotto il pareggio non viene segnalata come tale:\n{sotto}")
    sopra = obs.format_message(dict(base, LiveOdd=1.50), capture)
    check("sopra il pareggio" in sopra,
          f"una quota sopra il pareggio non viene riconosciuta:\n{sopra}")
    ignota = obs.format_message(dict(base, LiveOdd=""), capture)
    check("non disponibile" in ignota,
          f"una quota assente non viene dichiarata:\n{ignota}")
    for testo in (sotto, sopra, ignota):
        check("74,2%" in testo, "il messaggio non riporta il tasso base misurato")
        check("Solo osservazione" in testo,
              "il messaggio non dichiara di non essere pubblicato")

    # 4. Se l'invio fallisce, la riga deve essere comunque registrata.
    sorgente_righe = sorgente.splitlines()
    i_append = [n for n, r in enumerate(sorgente_righe) if "append_row(row)" in r]
    i_send = [n for n, r in enumerate(sorgente_righe) if r.strip() == "send(format_message(row, capture))"]
    check(bool(i_append) and bool(i_send) and min(i_append) < min(i_send),
          "l'invio precede la registrazione: un errore di rete perderebbe il dato")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"un solo destinatario (admin), nessun riferimento ai canali pubblici, "
          f"quota giudicata contro il pareggio {1 / 0.742:.3f}, registrazione prima dell'invio")
    print("second half channels verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
