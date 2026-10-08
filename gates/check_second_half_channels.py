"""Il segnale del 47' non deve raggiungere i canali a pagamento, e deve dire
come e' finito.

Il tasso base misurato su 164.590 partite 0-0 all'intervallo e' 74,2%: pareggio
a quota 1,348. Le prime quote raccolte dall'osservatore stanno fra 1,18 e 1,40,
mediana 1,28: sotto il pareggio in 5 casi su 7. Finche' questo non e' validato
sui dati raccolti dall'osservatore stesso, mandarlo su free o VIP significa
spedire una perdita misurata a chi paga.

La verifica controlla quattro cose, e le ultime due le controlla eseguendo il
codice invece di leggerlo:

1. il mittente di default scrive solo al canale admin, e torna l'id del
   messaggio - senza id non esiste modifica;
2. il messaggio dichiara la quota contro il pareggio invece di presentarla
   nuda, e dichiara l'esito: in corso finche' non si sa, vinto o perso dopo;
3. all'apertura la riga viene registrata PRIMA dell'invio, e un invio che
   fallisce non porta via il dato;
4. alla chiusura la riga viene registrata PRIMA della modifica, e una modifica
   che fallisce non porta via l'esito.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# I messaggi contengono emoji: su una console Windows a codepagina 1252 un
# print di diagnostica morirebbe di UnicodeEncodeError, nascondendo il guasto
# vero dietro a un errore di stampa.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import second_half as sh  # noqa: E402
import second_half_observer as obs  # noqa: E402

FAIL = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


class BotFinto:
    """Un telebot che registra invece di parlare. edit_fallisce imita il caso
    reale del messaggio troppo vecchio per essere modificato."""

    def __init__(self, edit_fallisce: bool = False) -> None:
        self.inviati = []
        self.modificati = []
        self.edit_fallisce = edit_fallisce
        self._prossimo_id = 500

    def send_message(self, chat_id, text, **kw):
        self._prossimo_id += 1
        self.inviati.append((chat_id, text))
        return type("Msg", (), {"message_id": self._prossimo_id})()

    def edit_message_text(self, text=None, chat_id=None, message_id=None, **kw):
        if self.edit_fallisce:
            raise RuntimeError("message is not modified / too old")
        self.modificati.append((chat_id, message_id, text))


class RispostaFinta:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def coverage_finta(league_id=None, season=None):
    """Copertura iniettata. api_coverage viene reso velenoso: se un giorno
    qualcuno smette di iniettarla, il cancello fallisce invece di fare una
    chiamata di rete vera dentro una verifica."""
    return {"stats": True, "events": True, "odds": True, "source": "finta"}


def vieta_rete(*a, **kw):
    raise AssertionError("copertura non iniettata: il cancello starebbe chiamando la rete")


class ApiFinta:
    """requests finto: accoppia un frammento di URL a una risposta. L'ordine
    conta, perche' 'fixtures' e' contenuto in 'fixtures/statistics'."""

    def __init__(self, coppie):
        self.coppie = coppie

    def get(self, url, **kw):
        for frammento, payload in self.coppie:
            if frammento in url:
                return RispostaFinta(payload)
        return RispostaFinta({"response": []})


STATISTICHE = [
    {"statistics": [{"type": "Corner Kicks", "value": 3},
                    {"type": "Shots on Goal", "value": 2},
                    {"type": "Ball Possession", "value": "55%"}]},
    {"statistics": [{"type": "Corner Kicks", "value": 1},
                    {"type": "Shots on Goal", "value": 1},
                    {"type": "Ball Possession", "value": "45%"}]},
]

EVENTI = [
    {"time": {"elapsed": 20}, "type": "Card", "detail": "Yellow Card",
     "team": {"name": "Vila Nova"}},
]

PARTITA_47 = {
    "fixture": {"id": 777, "status": {"short": "2H", "elapsed": 47}},
    "league": {"name": "Serie B", "country": "Brazil"},
    "teams": {"home": {"name": "Vila Nova"}, "away": {"name": "Cuiaba"}},
    "goals": {"home": 0, "away": 0},
}


def partita_chiusa(casa, fuori, stato):
    return {"response": [{"fixture": {"id": 777, "status": {"short": stato}},
                          "goals": {"home": casa, "away": fuori}}]}


def apparecchia(monkey_append):
    """Isola l'osservatore: niente rete, niente CSV, niente stato residuo."""
    obs._seen.clear()
    obs.append_row = monkey_append


def main() -> int:
    import config
    import shutil
    import tempfile

    append_vero = obs.append_row
    requests_vero = obs.requests
    pending_vero = obs.PENDING_PATH
    # L'osservatore salva l'attesa su disco. Il cancello non deve scrivere sul
    # file del bot vivo: gli cancellerebbe gli snapshot aperti.
    cartella = tempfile.mkdtemp(prefix="oracle_pending_")
    obs.PENDING_PATH = str(Path(cartella) / "pending.json")
    coverage_vera = obs.api_coverage.coverage_for
    obs.api_coverage.coverage_for = vieta_rete
    try:
        return verifica(config)
    finally:
        obs.append_row = append_vero
        obs.requests = requests_vero
        obs.PENDING_PATH = pending_vero
        obs.api_coverage.coverage_for = coverage_vera
        obs._seen.clear()
        shutil.rmtree(cartella, ignore_errors=True)


def verifica(config) -> int:
    # 1. Il mittente di default scrive a un solo destinatario: l'admin.
    bot = BotFinto()
    esito_invio = obs.default_sender(bot)("prova")
    destinatari = [c for c, _ in bot.inviati]
    check(len(destinatari) == 1, f"il mittente scrive a {len(destinatari)} destinatari")
    check(esito_invio is not None,
          "il mittente non torna l'id del messaggio: la modifica a esito noto e' impossibile")
    if destinatari:
        check(str(destinatari[0]) == str(config.CHAT_ID),
              f"destinatario {destinatari[0]} invece del canale admin")
        for nome, valore in (("CHANNEL_ID", getattr(config, "CHANNEL_ID", None)),
                             ("VIP_CHANNEL_ID", getattr(config, "VIP_CHANNEL_ID", None))):
            if valore:
                check(str(destinatari[0]) != str(valore),
                      f"il mittente scrive su {nome}: e' un canale a pagamento")

    # Anche la modifica va solo all'admin, e se non passa ricade su un invio.
    bot_edit = BotFinto()
    obs.default_editor(bot_edit)(42, "testo nuovo")
    check([c for c, _, _ in bot_edit.modificati] == [config.CHAT_ID],
          f"la modifica non va al solo canale admin: {bot_edit.modificati}")
    bot_rotto = BotFinto(edit_fallisce=True)
    obs.default_editor(bot_rotto)(42, "testo nuovo")
    check([c for c, _ in bot_rotto.inviati] == [config.CHAT_ID],
          "se la modifica fallisce l'esito non arriva da nessuna parte")

    # 2. Il codice non nomina i canali pubblici da nessuna parte.
    sorgente = Path(obs.__file__).read_text(encoding="utf-8")
    for vietato in ("CHANNEL_ID", "VIP_CHANNEL_ID"):
        check(vietato not in sorgente,
              f"{vietato} compare in second_half_observer: puo' finire sui canali")

    # 3. Il messaggio dichiara la quota contro il pareggio, non nuda.
    capture = sh.capture_fields(STATISTICHE)
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

    # 4. L'esito si legge dal messaggio: in corso, vinto o perso col punteggio.
    check(obs.PENDING_LINE in sotto,
          f"un segnale aperto non dichiara di essere in corso:\n{sotto}")
    vinto = obs.format_message(dict(base, LiveOdd=1.28, Outcome="WIN", CloseScore="1-0"), capture)
    check("VINTO" in vinto and "1-0" in vinto,
          f"un segnale vinto non dice di essere vinto, o perde il punteggio:\n{vinto}")
    check(obs.PENDING_LINE not in vinto,
          f"un segnale chiuso continua a dirsi in corso:\n{vinto}")
    perso = obs.format_message(dict(base, LiveOdd=1.40, Outcome="LOSS", CloseScore="0-0"), capture)
    check("PERSO" in perso and "0-0" in perso,
          f"un segnale perso non dice di essere perso:\n{perso}")
    check(obs.PENDING_LINE not in perso,
          f"un segnale chiuso continua a dirsi in corso:\n{perso}")
    # Le statistiche restano nel messaggio modificato: l'esito non le cancella.
    check("Corner: 4" in vinto, f"la modifica perde le statistiche:\n{vinto}")

    # 5. All'apertura: prima si registra, poi si manda. Anche se l'invio muore.
    cronologia = []
    righe = []

    def append_finto(row):
        righe.append(dict(row))
        cronologia.append("registra")

    apparecchia(append_finto)
    obs.requests = ApiFinta([("fixtures/statistics", {"response": STATISTICHE}),
                             ("fixtures/events", {"response": EVENTI}),
                             ("fixtures", {"response": [PARTITA_47]})])

    def send_che_muore(text):
        cronologia.append("manda")
        raise RuntimeError("Telegram non risponde")

    aperti = obs.observe_once({}, send_che_muore, None, coverage=coverage_finta)
    check(aperti == 1, f"la partita al 47' non viene aperta: {aperti}")
    check(cronologia == ["registra", "manda"],
          f"l'invio precede la registrazione: un errore di rete perderebbe il dato ({cronologia})")
    check(len(righe) == 1 and righe[0].get("FixtureId") == 777,
          f"invio fallito e riga perduta: {righe}")
    check(777 in obs._seen and obs._seen[777].get("message_id") is None,
          f"un invio fallito lascia un id inventato: {obs._seen.get(777)}")

    # L'id torna nello stato quando l'invio riesce: serve alla modifica.
    cronologia.clear()
    righe.clear()
    apparecchia(append_finto)
    obs.observe_once({}, lambda text: 9001, None, coverage=coverage_finta)
    check(obs._seen.get(777, {}).get("message_id") == 9001,
          f"l'id del messaggio non viene conservato: {obs._seen.get(777)}")
    check(obs._seen.get(777, {}).get("capture", {}).get("totals"),
          "le statistiche non vengono conservate: la modifica non potrebbe ricostruire il testo")

    # 6. Alla chiusura: prima si registra l'esito, poi si modifica. Anche se la
    #    modifica muore.
    for punteggio, stato, atteso in ((1, "2H", "WIN"), (0, "FT", "LOSS")):
        cronologia.clear()
        righe.clear()
        apparecchia(append_finto)
        obs.requests = ApiFinta([("fixtures/statistics", {"response": STATISTICHE}),
                                 ("fixtures/events", {"response": EVENTI}),
                                 ("fixtures", {"response": [PARTITA_47]})])
        obs.observe_once({}, lambda text: 9001, None, coverage=coverage_finta)
        cronologia.clear()
        righe.clear()
        obs.requests = ApiFinta([("fixtures", partita_chiusa(punteggio, 0, stato))])

        def edit_che_muore(message_id, text):
            cronologia.append(f"modifica:{message_id}")
            raise RuntimeError("messaggio troppo vecchio")

        chiusi = obs.settle_once({}, edit_che_muore)
        check(chiusi == 1, f"la chiusura {atteso} non avviene: {chiusi}")
        check(len(righe) == 1 and righe[0].get("Outcome") == atteso,
              f"esito {atteso} non registrato: {righe}")
        check(cronologia == ["registra", "modifica:9001"],
              f"esito {atteso}: la riga va registrata e poi il messaggio modificato "
              f"con l'id dell'apertura, invece la sequenza e' {cronologia}")
        # Un vinto senza il minuto del gol resta in coda, ma SOLO per il
        # minuto: quello che non deve succedere e' un secondo esito.
        residuo = obs._seen.get(777)
        check(residuo is None or residuo.get("fase") == obs.FASE_MINUTO,
              f"lo snapshot chiuso resta in attesa di esito: verrebbe chiuso "
              f"due volte (fase {residuo.get('fase') if residuo else None})")
        righe.clear()
        obs.settle_once({}, edit_che_muore)
        check(righe == [],
              f"un secondo giro registra un altro esito per lo stesso segnale: {righe}")

    # CONTROLLO NEGATIVO: senza la funzione di modifica la chiusura non si
    # rompe, registra e tace. E' il caso di un avvio senza editor.
    cronologia.clear()
    righe.clear()
    apparecchia(append_finto)
    obs.requests = ApiFinta([("fixtures/statistics", {"response": STATISTICHE}),
                             ("fixtures/events", {"response": EVENTI}),
                             ("fixtures", {"response": [PARTITA_47]})])
    obs.observe_once({}, lambda text: 9001, None, coverage=coverage_finta)
    righe.clear()
    cronologia.clear()
    obs.requests = ApiFinta([("fixtures", partita_chiusa(2, 1, "FT"))])
    check(obs.settle_once({}, None) == 1, "senza editor la chiusura non avviene")
    check(cronologia == ["registra"], f"senza editor viene chiamato qualcosa: {cronologia}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"un solo destinatario (admin) per invio e modifica, nessun riferimento ai "
          f"canali pubblici, quota giudicata contro il pareggio {1 / 0.742:.3f}, "
          f"esito scritto nel messaggio, registrazione prima di invio e modifica")
    print("second half channels verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
