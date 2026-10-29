"""L'osservatore del 47esimo minuto: segnale con statistiche, e misura.

Fa due cose insieme.

Per te: al minuto 46-48, su una partita 0-0 all'intervallo, manda un messaggio
con corner, tiri totali, tiri in area, tiri in porta, tiri fuori porta,
cartellini e possesso. I campi che l'API non fornisce vengono dichiarati
"non disponibile" invece di stampati a zero - e' il difetto che ha tenuto
"dangerous attacks" a 0,00 per mesi facendolo sembrare misurato.

Dove l'API dichiara di non raccogliere le statistiche di quella competizione
(api_coverage) il messaggio lo dice in una riga sola, invece di elencare sette
"non disponibile" che sembrano un guasto nostro. I cartellini si recuperano
comunque da /fixtures/events, che quelle leghe le copre.

Per la misura: registra ogni snapshot in second_half_log.csv e poi l'esito, cosi'
la domanda di Ten - i tiri al 45' spostano il 74,2%? - diventa verificabile sui
tuoi dati invece che sulla sua impressione o sulla mia. Oggi non e' verificabile:
il bot nel secondo tempo non valuta nulla, quindi non ha un solo dato dopo il 45'.

Perche' e' un modulo separato e non un market nel radar loop.

Il tasso base misurato su 164.590 partite 0-0 all'intervallo e' 74,2%, cioe' un
pareggio a quota 1,348; su "gol nel secondo tempo" il book paga 1,08-1,15, che
vuol dire perdere il 18% per scommessa. Pubblicare questo market sui canali
free e VIP a quelle quote sarebbe spedire una perdita misurata a chi paga.
Quindi l'osservatore manda solo al canale admin, registra la quota live quando
c'e', e la decisione di pubblicarlo resta tua - informata dai dati che questo
stesso modulo raccoglie.
"""
import csv
import json
import logging
import os
import threading
import time
from typing import Optional

import requests

import api_coverage
import modello_2t
from config import API_KEY, CHAT_ID
from second_half import (LINE_BREAK, MIN_QUOTA, NOTE_EMPTY_STATS, NOTE_NO_STATS,
                         capture_fields, format_stats_block, missing_fields,
                         playable, second_half_gate)

FIXTURES_URL = "https://v3.football.api-sports.io/fixtures"
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"
EVENTS_URL = "https://v3.football.api-sports.io/fixtures/events"

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "second_half_log.csv")
# "Attacks" e "DangerousAttacks" non ci sono piu': l'API non li manda, verificato
# sei volte, e due colonne sempre vuote in un registro sono un invito a leggerle
# come zeri. Al loro posto i campi che esistono e misurano la stessa pressione.
# StatsSource ed EventsSource esistono perche' ho dovuto rifare a mano le
# chiamate per sapere se una risposta vuota era un rifiuto dell'API o un nostro
# errore di rete: il registro non sapeva dirlo.
COLUMNS = [
    "ObservedAtUTC", "FixtureId", "LeagueId", "LeagueName", "Country", "MatchUp", "Minute",
    "Corners", "TotalShots", "ShotsInsidebox", "ShotsOnGoal", "ShotsOffGoal",
    "YellowCards", "RedCards", "PossessionHome", "PossessionAway",
    "LiveOdd", "MissingFields", "StatsCovered", "StatsSource", "EventsSource",
    "ModelP", "Outcome", "CloseScore", "GoalMinute", "DetectedMinute", "SettledTimeUTC",
    "RowType",
]

# Campi grezzi -> colonne del registro. Quelli assenti restano vuoti, non zero.
FIELD_COLUMNS = [
    ("Corners", ("corner kicks",)),
    ("TotalShots", ("total shots",)),
    ("ShotsInsidebox", ("shots insidebox",)),
    ("ShotsOnGoal", ("shots on goal",)),
    ("ShotsOffGoal", ("shots off goal",)),
    ("YellowCards", ("yellow cards",)),
    ("RedCards", ("red cards",)),
]

# Il tipo "Goal" dell'API comprende i rigori sbagliati. Un rigore fallito non
# e' un gol, e preso per tale sposterebbe il minuto del gol all'indietro.
NON_GOL = {"missed penalty"}
# Oltre il 45' si e' nel secondo tempo: i recuperi del primo restano a 45 con
# il minuto extra a parte.
SECOND_HALF_FROM = 46

SCAN_SECONDS = 40

# Riga di separazione e righe di esito. Il file e' UTF-8 e gli emoji stanno
# qui come caratteri: raccolti in costanti perche' il messaggio li usa due
# volte, all'apertura e alla modifica, e devono coincidere.
SEP = "━" * 20
OUTCOME_LINES = {
    "WIN": "✅ VINTO - gol nel secondo tempo",
    "LOSS": "❌ PERSO - finita senza gol",
    # L'API non ha mai chiuso la partita: meglio dirlo che lasciare "in corso"
    # su una gara di tre giorni fa.
    "UNSETTLED": "❓ ESITO IGNOTO - partita non chiusa dall'API",
}
PENDING_LINE = "⏳ IN CORSO - esito da chiudere"

# Gli snapshot in attesa su disco. _seen vive in memoria e il bot viene
# riavviato: il supervisore lo ha ripreso due volte nelle ultime
# ventiquattr'ore. Senza questo file un segnale aperto al 47' prima di un
# riavvio resterebbe "in corso" nel canale per sempre, e senza esito nel
# registro - cioe' perso per la misura, che e' il motivo per cui esiste.
PENDING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "second_half_pending.json")
# Oltre questo tempo uno snapshot non chiuso viene archiviato come ignoto,
# altrimenti l'osservatore lo interrogherebbe a ogni giro per sempre.
STALE_HOURS = 12

# Due fasi per uno stesso snapshot. L'API aggiorna il punteggio prima di
# pubblicare l'evento del gol: su Port FC - Persib Bandung, l'8 ottobre 2026,
# il punteggio era 1-0 alle 13:22:30 e l'evento "66' Goal Penalty" e' comparso
# minuti dopo. Chiudere entro 40 secondi vuol dire perdere la gara. Quindi
# l'esito si registra subito e il minuto esatto si inseguie dopo.
FASE_ESITO = "esito"      # si aspetta di sapere come finisce
FASE_MINUTO = "minuto"    # esito noto, manca il minuto del gol
# Oltre questi tentativi si rinuncia al minuto esatto e resta il limite
# superiore: inseguire per sempre un evento che non arriva costa una chiamata
# a ogni giro e non porta niente.
MAX_TENTATIVI_MINUTO = 15

# I fixture scartati perche' non giocabili: solo per non ripetere la riga di
# log quattro volte, una per scansione, mentre la partita e' nella finestra.
_scartati = set()

_lock = threading.Lock()
# fixture_id -> {"row": riga, "capture": statistiche, "message_id": id Telegram}
# La cattura e l'id servono alla chiusura: il messaggio di apertura viene
# riscritto con l'esito, e per riscriverlo serve ricostruire lo stesso testo.
_seen = {}
# fid del segnale attualmente inviato su Telegram e non ancora chiuso.
# Un nuovo segnale selezionato non viene inviato finche' questo e' aperto:
# due segnali aperti insieme confondono su quale scommettere.
_attivo_fid = None
# fid dei segnali selezionati ma in attesa di invio.
_coda = []

# Coda e segnale attivo vivono su disco separato dal pending, cosi' il gate
# check_second_half_restart non deve cambiare (legge pending con .values()).
QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "second_half_queue.json")
# Oltre questo minuto il segnale attivo sblocca la coda anche senza gol:
# al 75' senza rete il segnale e' quasi certamente perso, tenere la coda
# ferma fino alla fine ufficiale costa un segnale che vale ancora qualcosa.
MINUTO_TIMEOUT_CODA = 75


# I messaggi di diagnostica finiscono nel log del bot: il suo logger si chiama
# "oracle_live" e un figlio ci propaga dentro. Con print() non finivano da
# nessuna parte, perche' il bot gira sotto pythonw e non ha una console - cioe'
# proprio la diagnostica aggiunta per sapere perche' un dato manca era muta.
logger = logging.getLogger("oracle_live.osservatore47")


def diario(message: str) -> None:
    """Una riga nel log del bot, nella forma degli altri eventi."""
    logger.info(f"OSSERVATORE47 | {message}")


_header_checked = False


def migrate_log() -> str:
    """Allinea l'intestazione del registro a COLUMNS, conservando le righe.

    append_row scrive i valori nell'ordine di COLUMNS. Se le colonne cambiano e
    l'intestazione sul disco resta quella vecchia, ogni riga nuova finisce
    sotto l'etichetta sbagliata e il registro diventa falso senza che niente
    protesti: il modo peggiore di rompere una misura.

    Una colonna che sparisce e che contiene dati blocca la migrazione: meglio
    un registro con l'intestazione vecchia che una perdita silenziosa. Le
    colonne tolte qui - Attacks, DangerousAttacks - sono vuote su tutte le
    righe, perche' l'API non le ha mai mandate.
    """
    if not os.path.exists(LOG_PATH):
        return "assente"
    try:
        with open(LOG_PATH, newline="", encoding="utf-8") as handle:
            lettore = csv.DictReader(handle)
            vecchie = list(lettore.fieldnames or [])
            righe = list(lettore)
    except OSError as exc:
        diario(f"registro non leggibile ({exc})")
        return "errore"
    if vecchie == COLUMNS:
        return "allineato"

    persi = [c for c in vecchie if c not in COLUMNS]
    con_dati = [c for c in persi
                if any(str(r.get(c) or "").strip() for r in righe)]
    if con_dati:
        diario(f"migrazione rifiutata, colonne con dati che sparirebbero: {con_dati}")
        return "rifiutato"

    temporaneo = LOG_PATH + ".tmp"
    try:
        with open(temporaneo, "w", newline="", encoding="utf-8") as handle:
            scrittore = csv.DictWriter(handle, fieldnames=COLUMNS)
            scrittore.writeheader()
            for r in righe:
                scrittore.writerow({k: r.get(k, "") for k in COLUMNS})
        # L'originale resta accanto: una migrazione si deve poter annullare.
        os.replace(LOG_PATH, LOG_PATH + ".bak")
        os.replace(temporaneo, LOG_PATH)
    except OSError as exc:
        diario(f"migrazione fallita ({exc})")
        return "errore"
    aggiunte = [c for c in COLUMNS if c not in vecchie]
    diario(f"registro migrato, {len(righe)} righe, colonne tolte {persi}, aggiunte {aggiunte}")
    return "migrato"


def ensure_log() -> None:
    global _header_checked
    if not os.path.exists(LOG_PATH):
        with _lock:
            with open(LOG_PATH, "w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=COLUMNS).writeheader()
        _header_checked = True
        return
    # Una volta per processo: l'intestazione sul disco deve corrispondere a
    # COLUMNS prima della prima scrittura, non dopo.
    if not _header_checked:
        _header_checked = True
        migrate_log()


def append_row(row: dict) -> None:
    ensure_log()
    with _lock:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=COLUMNS).writerow(
                {k: row.get(k, "") for k in COLUMNS})


def save_pending() -> None:
    """Scrive su disco gli snapshot in attesa di esito.

    Scrive su un file temporaneo e poi rinomina: se il processo muore a meta'
    scrittura resta la versione precedente, non mezzo JSON illeggibile.
    """
    with _lock:
        try:
            temporaneo = PENDING_PATH + ".tmp"
            with open(temporaneo, "w", encoding="utf-8") as handle:
                json.dump({str(k): v for k, v in _seen.items()}, handle)
            os.replace(temporaneo, PENDING_PATH)
        except OSError as exc:
            diario(f"attesa non salvata: {exc}")


def save_queue() -> None:
    """Scrive su disco la coda e il segnale attivo."""
    try:
        temporaneo = QUEUE_PATH + ".tmp"
        with open(temporaneo, "w", encoding="utf-8") as handle:
            json.dump({"coda": _coda, "attivo": _attivo_fid}, handle)
        os.replace(temporaneo, QUEUE_PATH)
    except OSError as exc:
        diario(f"coda non salvata: {exc}")


def load_queue() -> None:
    """Ripristina coda e segnale attivo dopo un riavvio.

    Chiamata dopo load_pending: usa _seen per validare i fid.
    Un fid che non e' piu' in _seen (gia' chiuso prima del riavvio) viene
    scartato silenziosamente.
    """
    global _coda, _attivo_fid
    if not os.path.exists(QUEUE_PATH):
        return
    try:
        with open(QUEUE_PATH, encoding="utf-8") as handle:
            dati = json.load(handle)
    except (OSError, ValueError):
        return
    _coda = [f for f in (dati.get("coda") or []) if f in _seen]
    candidato = dati.get("attivo")
    _attivo_fid = candidato if candidato in _seen else None


def load_pending() -> int:
    """Rimette in memoria gli snapshot non chiusi. Torna quanti ne ha ripresi.

    Un file corrotto o illeggibile non deve impedire l'avvio: in quel caso si
    riparte vuoti, perdendo le modifiche ai messaggi aperti ma non il bot.
    """
    if not os.path.exists(PENDING_PATH):
        return 0
    try:
        with open(PENDING_PATH, encoding="utf-8") as handle:
            dati = json.load(handle)
    except (OSError, ValueError) as exc:
        diario(f"attesa illeggibile ({exc}), riparto vuoto")
        return 0
    ripresi = 0
    for chiave, voce in (dati or {}).items():
        if not isinstance(voce, dict) or not isinstance(voce.get("row"), dict):
            continue
        try:
            fid = int(chiave)
        except (TypeError, ValueError):
            continue
        _seen[fid] = {
            "row": voce["row"],
            "capture": voce.get("capture") or {},
            "message_id": voce.get("message_id"),
            # La fase deve sopravvivere: senza, uno snapshot che aspettava solo
            # il minuto del gol tornerebbe nel giro delle chiusure e scriverebbe
            # un secondo esito per lo stesso segnale.
            "fase": voce.get("fase") or FASE_ESITO,
            "tentativi": int(voce.get("tentativi") or 0),
        }
        ripresi += 1
    return ripresi


def observed_at(voce: dict):
    """Quando lo snapshot e' stato aperto, o None se la data non si legge.

    Torna sempre un orario con fuso: una data senza fuso non si puo'
    sottrarre da adesso, e il confronto sull'eta' morirebbe di TypeError.
    """
    from datetime import datetime, timezone
    testo = (voce.get("row") or {}).get("ObservedAtUTC")
    if not testo:
        return None
    try:
        quando = datetime.fromisoformat(str(testo))
    except ValueError:
        return None
    return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def total_from(fields: dict, names: tuple) -> Optional[float]:
    trovati = [fields[n] for n in names if fields.get(n) is not None]
    return float(sum(trovati)) if trovati else None


def call_api(url: str, params: dict, headers: dict) -> tuple:
    """(lista, provenienza). La provenienza distingue tre cose diverse.

    "dati" l'API ha risposto con contenuto, "vuoto" ha risposto 200 senza
    contenuto - cioe' quel dato non ce l'ha - "errore:..." la chiamata non e'
    arrivata. Prima erano la stessa cosa, e per sapere quale fosse ho dovuto
    rifare le chiamate a mano il giorno dopo.
    """
    try:
        risposta = requests.get(url, headers=headers, params=params, timeout=20)
    except Exception as exc:
        return [], f"errore:{type(exc).__name__}"
    if risposta.status_code != 200:
        return [], f"errore:http{risposta.status_code}"
    try:
        payload = risposta.json()
    except ValueError:
        return [], "errore:rispostaillegibile"
    errori = payload.get("errors")
    # L'API usa [] per "nessun errore" e un dizionario per dirne uno.
    if isinstance(errori, dict) and errori:
        return [], f"errore:{list(errori.values())[0]}"[:60]
    contenuto = payload.get("response") or []
    return contenuto, ("dati" if contenuto else "vuoto")


def fetch_stats(fid, headers: dict) -> tuple:
    return call_api(STATS_URL, {"fixture": fid}, headers)


def fetch_events(fid, headers: dict) -> tuple:
    return call_api(EVENTS_URL, {"fixture": fid}, headers)


def cards_from_events(eventi) -> tuple:
    """(gialli, rossi) contati dagli eventi, o (None, None) senza eventi.

    E' l'unico dei sette campi che si recupera dove le statistiche non sono
    raccolte: events=True su tutte le competizioni del registro. Una lista
    vuota torna None e non zero: nessun evento registrato non vuol dire
    nessun cartellino.
    """
    if not eventi:
        return None, None
    gialli = rossi = 0
    for evento in eventi:
        if evento.get("type") != "Card":
            continue
        dettaglio = str(evento.get("detail") or "").lower()
        # Prima il rosso: "Second Yellow card" porta all'espulsione ma l'API lo
        # conta fra i gialli, come fa la colonna Yellow Cards delle statistiche.
        if "red" in dettaglio:
            rossi += 1
        elif "yellow" in dettaglio:
            gialli += 1
    return gialli, rossi


def merge_cards(capture: dict, gialli, rossi) -> dict:
    """Mette i cartellini degli eventi nella cattura, solo dove mancano.

    Un dato misurato dalle statistiche non viene sovrascritto da uno dedotto
    dagli eventi: se i due disaccordano vince quello della fonte dichiarata.
    """
    if gialli is None and rossi is None:
        return capture
    totali = capture.setdefault("totals", {})
    if totali.get("yellow cards") is None and gialli is not None:
        totali["yellow cards"] = float(gialli)
    if totali.get("red cards") is None and rossi is not None:
        totali["red cards"] = float(rossi)
    return capture


def first_second_half_goal(eventi) -> Optional[int]:
    """Il minuto del primo gol del secondo tempo, o None.

    E' il dato che manca per sapere se conviene entrare al 47' o aspettare:
    finora sapevamo che un gol era arrivato, non quando.
    """
    minuti = []
    for evento in (eventi or []):
        if evento.get("type") != "Goal":
            continue
        if str(evento.get("detail") or "").lower() in NON_GOL:
            continue
        minuto = (evento.get("time") or {}).get("elapsed")
        if minuto is not None and int(minuto) >= SECOND_HALF_FROM:
            minuti.append(int(minuto))
    return min(minuti) if minuti else None


def halftime_total(fixture: dict) -> Optional[int]:
    """I gol all'intervallo secondo score.halftime, o None se non lo dice."""
    intervallo = ((fixture.get("score") or {}).get("halftime") or {})
    casa, fuori = intervallo.get("home"), intervallo.get("away")
    if casa is None and fuori is None:
        return None
    return (casa or 0) + (fuori or 0)


def chiedi_quota(fetch_odd, fid, minuto):
    """La quota live, passando il minuto a chi lo accetta.

    Il minuto conta: fetch_live_market_odd lo gira a record_live_odd, che
    scrive la riga in odds_history.csv. Finche' l'osservatore passava 47 fisso,
    ogni quota del secondo tempo finiva registrata come se fosse del 47esimo e
    la curva dei prezzi non esisteva - 328 osservazioni, una per partita, tutte
    allo stesso minuto.

    Un fornitore che accetta un solo argomento resta valido: i cancelli ne
    usano di finti, e non devono rompersi per questo.
    """
    if fetch_odd is None:
        return None
    try:
        import inspect
        quanti = len(inspect.signature(fetch_odd).parameters)
    except (TypeError, ValueError):
        quanti = 1
    return fetch_odd(fid, minuto) if quanti >= 2 else fetch_odd(fid)


def stats_covered_in(row: dict) -> bool:
    """Se le statistiche risultavano coperte per quella partita.

    Un valore mancante o illeggibile vale "coperte": il messaggio torna a
    elencare i campi come prima, che e' il comportamento prudente.
    """
    return row.get("StatsCovered") not in (False, "False", "false", "no", 0, "0")


def stats_note(row: dict) -> Optional[str]:
    """Perche' i numeri non ci sono, quando lo sappiamo.

    Tre casi distinti, e tenerli distinti e' il punto: la competizione non e'
    coperta, oppure e' coperta e per questa partita l'API non ha mandato
    niente, oppure ne ha mandata una parte - e allora l'elenco completo con le
    assenze dichiarate dice piu' di qualunque frase.
    """
    if not stats_covered_in(row):
        return NOTE_NO_STATS
    if row.get("StatsSource") == "vuoto":
        return NOTE_EMPTY_STATS
    return None


def build_row(fixture: dict, capture: dict, live_odd: Optional[float], now_iso: str,
              stats_coperte: bool = True, stats_source: str = "",
              events_source: str = "", model_p=None) -> dict:
    totals = capture.get("totals", {})
    row = {
        "ObservedAtUTC": now_iso,
        "FixtureId": fixture["fixture"]["id"],
        "LeagueId": (fixture.get("league") or {}).get("id", ""),
        "LeagueName": fixture["league"]["name"],
        "Country": fixture["league"]["country"],
        "MatchUp": f'{fixture["teams"]["home"]["name"]} vs {fixture["teams"]["away"]["name"]}',
        "Minute": fixture["fixture"]["status"].get("elapsed"),
        "PossessionHome": capture.get("home", {}).get("ball possession", ""),
        "PossessionAway": capture.get("away", {}).get("ball possession", ""),
        "LiveOdd": "" if live_odd is None else live_odd,
        "MissingFields": "|".join(missing_fields(capture)),
        "StatsCovered": stats_coperte,
        "StatsSource": stats_source,
        "EventsSource": events_source,
        "ModelP": "" if model_p is None else round(float(model_p), 4),
    }
    for colonna, names in FIELD_COLUMNS:
        valore = total_from(totals, names)
        row[colonna] = "" if valore is None else valore
    return row


def message_id_of(esito):
    """L'id del messaggio inviato, qualunque cosa torni il mittente.

    telebot torna un oggetto Message; un mittente finto puo' tornare un numero
    o niente. Senza id non si puo' modificare nulla, e None lo dice.
    """
    if esito is None:
        return None
    if isinstance(esito, int):
        return esito
    return getattr(esito, "message_id", None)


def format_message(row: dict, capture: dict) -> str:
    """Il messaggio per il canale admin.

    Lo stesso testo serve due volte: all'apertura, e alla chiusura con Outcome
    valorizzato. Finche' l'esito non c'e' il messaggio lo dichiara in corso,
    cosi' nessuna riga resta ambigua se la modifica non arriva mai.
    """
    quota = row.get("LiveOdd")
    if quota in (None, ""):
        riga_quota = "💰 QUOTA LIVE: non disponibile"
    else:
        giudizio = "sopra il pareggio" if float(quota) >= MIN_QUOTA else "SOTTO il pareggio"
        riga_quota = f"💰 QUOTA LIVE: {float(quota):.2f} ({giudizio} di {MIN_QUOTA:.2f})"

    esito = str(row.get("Outcome") or "").upper()
    if esito in OUTCOME_LINES:
        punteggio = row.get("CloseScore") or ""
        minuto_gol = row.get("GoalMinute")
        minuto_visto = row.get("DetectedMinute")
        if esito == "WIN" and minuto_gol not in (None, ""):
            # Il minuto del gol e' il dato che dice se conveniva entrare al 47'
            # o aspettare: quando c'e', prende il posto della frase generica.
            riga_esito = f"✅ VINTO - gol al {int(float(minuto_gol))}'"
        elif esito == "WIN" and minuto_visto not in (None, ""):
            # L'evento non e' ancora pubblicato: questo e' il minuto in cui il
            # punteggio era cambiato, cioe' un limite superiore. Detto come
            # tale, non spacciato per il minuto del gol.
            riga_esito = f"✅ VINTO - gol entro il {int(float(minuto_visto))}'"
        else:
            riga_esito = OUTCOME_LINES[esito]
        if punteggio:
            riga_esito += f" ({punteggio})"
    else:
        riga_esito = PENDING_LINE

    parti = [
        "⚽ SEGNALE 47' - GOL NEL SECONDO TEMPO",
        riga_esito,
        SEP,
        f"🆚 MATCH: {row['MatchUp']}",
        f"🏆 {row['Country']} - {row['LeagueName']}",
        f"⏱ MINUTO: {row['Minute']}' | 0-0 all'intervallo",
        SEP,
        format_stats_block(capture, stats_note(row)),
        SEP,
        riga_quota,
        "📊 TASSO BASE: 74,2% su 164.590 partite 0-0 all'intervallo",
        f"⚖️ PAREGGIO RICHIESTO: quota {1 / 0.742:.3f}",
        SEP,
        "👁️ Solo osservazione: non pubblicato su free/VIP.",
    ]
    return LINE_BREAK.join(parti)


def _invia_da_coda(send, edit, avviso: str = "") -> None:
    """Invia il primo segnale in coda, se ce n'e' uno valido.

    Salta i fixture scaduti (oltre STALE_HOURS) o gia' usciti da _seen.
    Se la coda e' vuota azzera _attivo_fid.
    `avviso` e' una riga di contesto preposta al messaggio (es. timeout 75').
    """
    global _attivo_fid
    from datetime import datetime, timezone
    adesso = datetime.now(timezone.utc)
    while _coda:
        fid = _coda.pop(0)
        voce = _seen.get(fid)
        if voce is None:
            continue
        aperto = observed_at(voce)
        if aperto and (adesso - aperto).total_seconds() > STALE_HOURS * 3600:
            diario(f"coda: {fid} scaduto ({STALE_HOURS}h), saltato")
            continue
        row = voce.get("row") or {}
        capture = voce.get("capture") or {}
        testo = format_message(row, capture)
        if avviso:
            testo = avviso + LINE_BREAK + testo
        try:
            voce["message_id"] = message_id_of(send(testo))
        except Exception as exc:
            diario(f"coda: invio fallito su {fid}: {exc}")
        _attivo_fid = fid
        save_pending()
        save_queue()
        diario(f"coda: inviato {row.get('MatchUp', fid)} "
               f"(residuo coda: {len(_coda)})")
        return
    _attivo_fid = None
    save_queue()


def observe_once(headers: dict, send, fetch_odd=None, coverage=None) -> int:
    """Un giro: cerca le partite nella finestra, manda e registra. Torna quante.

    `coverage(league_id, season)` dice cosa l'API dichiara di raccogliere per
    quella competizione; serve iniettabile per provare senza rete.
    """
    global _attivo_fid, _coda
    # Se _seen e' stato svuotato esternamente (test o riavvio parziale),
    # l'attivo e la coda punterebbero a fixture spariti: meglio ripartire puliti.
    if _attivo_fid is not None and _attivo_fid not in _seen:
        _attivo_fid = None
    _coda = [f for f in _coda if f in _seen]
    if coverage is None:
        def coverage(lid, season):
            return api_coverage.coverage_for(lid, season, headers=headers)

    fixtures, provenienza = call_api(FIXTURES_URL, {"live": "all"}, headers)
    if provenienza.startswith("errore:"):
        # Prima questo giro tornava zero in silenzio: un osservatore che non
        # vede niente e un osservatore che non riesce a guardare si somigliano
        # troppo, ed e' la somiglianza che ha fatto sembrare vivo un bot morto.
        diario(f"elenco partite non arrivato ({provenienza})")

    from datetime import datetime, timezone
    aperti = 0
    for fixture in fixtures:
        fid = fixture["fixture"]["id"]
        stato = fixture["fixture"]["status"]
        goals = fixture.get("goals") or {}
        total_goals = (goals.get("home") or 0) + (goals.get("away") or 0)
        ok, _ = second_half_gate(stato.get("elapsed"), total_goals,
                                 stato.get("short", ""), halftime_total(fixture))
        if not ok or fid in _seen:
            continue

        lega = fixture.get("league") or {}
        squadre = fixture.get("teams") or {}
        incontro = (f'{(squadre.get("home") or {}).get("name", "")} vs '
                    f'{(squadre.get("away") or {}).get("name", "")}')
        giocabile, perche = playable(lega.get("name"), incontro)
        if not giocabile:
            # Prima di qualunque chiamata: su una partita che non si puo'
            # giocare, statistiche, eventi e quota sarebbero tre chiamate
            # spese per un messaggio che non serve a nessuno.
            if fid not in _scartati:
                _scartati.add(fid)
                diario(f"saltata {incontro}: {perche}")
            continue

        copertura = coverage(lega.get("id"), lega.get("season")) or {}
        if api_coverage.stats_hopeless(copertura):
            # L'API dichiara di non raccoglierle: la chiamata sarebbe HTTP 200
            # con results=0, cioe' un giro a vuoto. Risparmiata, e dichiarata.
            payload, stats_source, stats_coperte = [], "copertura", False
        else:
            payload, stats_source = fetch_stats(fid, headers)
            stats_coperte = True
        capture = capture_fields(payload)

        eventi, events_source = fetch_events(fid, headers)
        capture = merge_cards(capture, *cards_from_events(eventi))

        live_odd = None
        try:
            live_odd = chiedi_quota(fetch_odd, fid, stato.get("elapsed"))
        except Exception as exc:
            diario(f"quota non letta su {fid}: {exc}")
        # La probabilita' di gol nel secondo tempo, dal modello storico. Il
        # segnale si registra sempre - serve alla misura - ma suona solo se sta
        # nel decile alto. Prima apriva su ogni 0-0 senza selezione, che era
        # giusto finche' misuravo e sbagliato dal giorno in cui la misura era
        # finita: cinquantotto messaggi in un'ora.
        model_p, perche_p = modello_2t.probabilita(
            (squadre.get("home") or {}).get("name"),
            (squadre.get("away") or {}).get("name"))
        now_iso = datetime.now(timezone.utc).isoformat()
        row = build_row(fixture, capture, live_odd, now_iso,
                        stats_coperte=stats_coperte, stats_source=stats_source,
                        events_source=events_source, model_p=model_p)
        row["RowType"] = "open"
        voce = {"row": row, "capture": capture, "message_id": None}
        _seen[fid] = voce
        append_row(row)
        if modello_2t.selezionato(model_p):
            if _attivo_fid is None:
                try:
                    voce["message_id"] = message_id_of(send(format_message(row, capture)))
                except Exception:
                    pass
                _attivo_fid = fid
                save_queue()
            else:
                _coda.append(fid)
                save_queue()
                diario(f"coda: {incontro} accodato "
                       f"(attivo: {_attivo_fid}, coda={len(_coda)})")
        elif fid not in _scartati:
            _scartati.add(fid)
            diario(f"muto {incontro}: p={'n/d' if model_p is None else format(model_p, '.3f')} "
                   f"sotto la soglia {modello_2t.soglia_decile_alto():.4f} ({perche_p})")
        # Dopo l'invio, non prima: l'id del messaggio deve finire su disco,
        # altrimenti un riavvio lascia il messaggio senza nessuno che lo chiuda.
        save_pending()
        aperti += 1
    return aperti


def registra_esito(fid, voce: dict, esito: str, punteggio: str, edit, adesso,
                   minuto_gol=None, minuto_visto=None) -> dict:
    """Scrive la riga chiusa e poi riscrive il messaggio, in quest'ordine.

    Il registro non deve dipendere da Telegram: se la modifica fallisce resta
    un messaggio vecchio, se la scrittura fallisse resterebbe una misura in
    meno - e la misura e' il motivo per cui l'osservatore esiste.

    `minuto_visto` e' il minuto della partita quando abbiamo visto il gol: un
    limite superiore che non dipende da nessuna gara con l'API, perche' viene
    dallo stesso fixture che ci ha detto il punteggio. `minuto_gol` e' quello
    esatto, dagli eventi, quando c'e'. Torna la riga scritta.
    """
    row = dict(voce.get("row") or {})
    row["Outcome"] = esito
    row["CloseScore"] = punteggio
    row["GoalMinute"] = "" if minuto_gol is None else minuto_gol
    row["DetectedMinute"] = "" if minuto_visto is None else minuto_visto
    row["SettledTimeUTC"] = adesso.isoformat()
    row["RowType"] = "settle"
    append_row(row)
    if edit is not None and voce.get("message_id"):
        try:
            edit(voce["message_id"], format_message(row, voce.get("capture") or {}))
        except Exception as exc:
            diario(f"modifica fallita su {fid}: {exc}")
    return row


def settle_once(headers: dict, edit=None, fetch_odd=None, send=None) -> int:
    """Chiude gli snapshot in attesa: WIN al primo gol, LOSS a fine partita.

    Alla chiusura riscrive il messaggio di apertura con l'esito, come fa il bot
    sui suoi segnali: altrimenti nel canale resta un messaggio che dice "in
    corso" su una partita finita ore prima. La riga del registro viene scritta
    prima della modifica, cosi' un errore di Telegram non porta via il dato.
    """
    global _attivo_fid
    from datetime import datetime, timezone
    adesso = datetime.now(timezone.utc)
    chiusi = 0
    for fid in list(_seen):
        voce = _seen[fid]
        if voce.get("fase", FASE_ESITO) != FASE_ESITO:
            # L'esito e' gia' registrato: di questo si cerca solo il minuto, e
            # lo fa backfill_once. Chiuderlo due volte scriverebbe due esiti.
            continue
        items, _ = call_api(FIXTURES_URL, {"id": fid}, headers)

        esito = None
        punteggio = ""
        minuto_visto = None
        if items:
            fixture = items[0]
            goals = fixture.get("goals") or {}
            casa = goals.get("home") or 0
            fuori = goals.get("away") or 0
            punteggio = f"{casa}-{fuori}"
            stato = fixture["fixture"]["status"].get("short", "")
            minuto_visto = fixture["fixture"]["status"].get("elapsed")
            if casa + fuori > 0:
                esito = "WIN"
            elif stato in {"FT", "AET", "PEN"}:
                esito = "LOSS"

        if esito is None:
            # Ancora aperto: questo e' il momento per leggere il prezzo. Il
            # minuto lo sappiamo dal fixture che abbiamo appena interrogato,
            # quindi la curva del book diventa confrontabile con quella equa
            # ricavata dai minuti dei gol. Senza questo punto non si puo'
            # sapere se aspettare che la quota salga a 1,40 convenga.
            if minuto_visto is not None:
                try:
                    chiedi_quota(fetch_odd, fid, minuto_visto)
                except Exception as exc:
                    diario(f"quota non letta su {fid} al {minuto_visto}': {exc}")
            # Se e' aperto da troppo tempo - API muta, partita
            # rinviata, fixture sparito - lo si archivia come ignoto: restare
            # in coda per sempre vorrebbe dire una chiamata a ogni giro e un
            # messaggio che dice "in corso" su una partita di tre giorni fa.
            # Sblocca la coda al timeout: al 75' senza gol il segnale attivo
            # blocca qualcosa che vale ancora. L'attivo resta tracciato fino
            # alla fine, ma smette di bloccare il prossimo in coda.
            if (send is not None and _coda
                    and fid == _attivo_fid
                    and minuto_visto is not None
                    and int(minuto_visto) >= MINUTO_TIMEOUT_CODA):
                incontro_at = (voce.get("row") or {}).get("MatchUp", str(fid))
                avviso = (f"⏰ Segnale precedente ancora aperto al {minuto_visto}' "
                          f"senza gol ({incontro_at})\n"
                          f"⚠️ Statistiche al minuto di apertura — quota potrebbe "
                          f"essere cambiata")
                _attivo_fid = None
                _invia_da_coda(send, edit, avviso=avviso)
                diario(f"coda sbloccata al {minuto_visto}' su {fid} ({incontro_at})")
            aperto = observed_at(voce)
            if aperto is None or (adesso - aperto).total_seconds() <= STALE_HOURS * 3600:
                continue
            esito = "UNSETTLED"

        # Il minuto del gol si chiede solo quando un gol c'e' stato: una
        # chiamata in piu' per segnale vinto, non una per giro.
        minuto_gol = None
        if esito == "WIN":
            eventi, _ = fetch_events(fid, headers)
            minuto_gol = first_second_half_goal(eventi)

        row = registra_esito(fid, voce, esito, punteggio, edit, adesso,
                             minuto_gol, minuto_visto if esito == "WIN" else None)
        if esito == "WIN" and minuto_gol is None:
            # L'evento non c'era ancora. L'esito e' registrato e il messaggio
            # aggiornato; lo snapshot resta in coda solo per il minuto esatto.
            voce["fase"] = FASE_MINUTO
            voce["tentativi"] = 0
            voce["row"] = row
        else:
            _seen.pop(fid, None)
        # Quando il segnale attivo si chiude (qualunque esito), sblocca la coda.
        if fid == _attivo_fid:
            _attivo_fid = None
            if send is not None:
                _invia_da_coda(send, edit)
            else:
                save_queue()
        chiusi += 1
    if chiusi:
        save_pending()
    return chiusi


def backfill_once(headers: dict, edit=None) -> int:
    """Insegue il minuto esatto del gol sugli esiti gia' registrati.

    Perche' esiste: l'API aggiorna il punteggio prima di pubblicare l'evento.
    Su Port FC - Persib Bandung il punteggio era 1-0 alle 13:22:30 e l'evento
    "66' Goal Penalty" e' comparso minuti dopo. Chiedere una volta al momento
    della chiusura vuol dire perdere la gara quasi sempre.

    Quando il minuto arriva, scrive una riga nuova con quel minuto e riscrive
    il messaggio con il dato esatto. Dopo MAX_TENTATIVI_MINUTO si rinuncia, e
    resta il limite superiore gia' registrato in DetectedMinute.
    """
    from datetime import datetime, timezone
    completati = 0
    for fid in list(_seen):
        voce = _seen[fid]
        if voce.get("fase") != FASE_MINUTO:
            continue
        voce["tentativi"] = int(voce.get("tentativi") or 0) + 1
        eventi, _ = fetch_events(fid, headers)
        minuto = first_second_half_goal(eventi)
        if minuto is None:
            if voce["tentativi"] >= MAX_TENTATIVI_MINUTO:
                diario(f"minuto del gol non trovato su {fid} dopo "
                       f"{voce['tentativi']} tentativi, resta il limite superiore")
                _seen.pop(fid, None)
                completati += 1
            continue
        row = dict(voce.get("row") or {})
        row["GoalMinute"] = minuto
        row["SettledTimeUTC"] = datetime.now(timezone.utc).isoformat()
        row["RowType"] = "backfill"
        append_row(row)
        if edit is not None and voce.get("message_id"):
            try:
                edit(voce["message_id"], format_message(row, voce.get("capture") or {}))
            except Exception as exc:
                diario(f"modifica fallita su {fid}: {exc}")
        diario(f"minuto del gol trovato su {fid}: {minuto}' "
               f"al tentativo {voce['tentativi']}")
        _seen.pop(fid, None)
        completati += 1
    if completati:
        save_pending()
    return completati


def observer_loop(send, fetch_odd=None, stop=None, edit=None) -> None:
    """Il ciclo: apre, chiude, e insegue il minuto del gol.

    `send` manda il messaggio e torna il suo id, `edit` lo riscrive quando si
    sa di piu', `stop()` dice quando smettere.
    """
    headers = {"x-apisports-key": API_KEY}
    ensure_log()
    ripresi = load_pending()
    load_queue()
    if ripresi:
        diario(f"{ripresi} snapshot ripresi dopo il riavvio")
    while not (stop() if stop else False):
        try:
            observe_once(headers, send, fetch_odd)
            settle_once(headers, edit, fetch_odd, send=send)
            backfill_once(headers, edit)
        except Exception as exc:
            diario(f"giro fallito: {exc}")
        time.sleep(SCAN_SECONDS)


def default_sender(bot):
    """Manda solo al canale admin: il market non e' validato per free/VIP.

    Torna l'id del messaggio, che serve per riscriverlo quando l'esito arriva.
    """
    def send(text: str):
        if not CHAT_ID:
            return None
        return message_id_of(bot.send_message(CHAT_ID, text))
    return send


def default_editor(bot):
    """Riscrive il messaggio di apertura con l'esito, sempre e solo sull'admin.

    Se la modifica non passa - messaggio troppo vecchio, id non piu' valido -
    manda il testo nuovo, come fa edit_signal_message in oracle_live: meglio un
    messaggio in piu' che un esito che non arriva.
    """
    def edit(message_id, text: str) -> None:
        if not CHAT_ID or not message_id:
            return
        try:
            bot.edit_message_text(text=text, chat_id=CHAT_ID, message_id=message_id)
        except Exception as exc:
            diario(f"edit {message_id} fallita ({exc}), mando il testo")
            bot.send_message(CHAT_ID, text)
    return edit
