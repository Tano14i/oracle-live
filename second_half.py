"""Il segnale del 47esimo minuto, con le statistiche in chiaro.

L'idea e' di Ten: un colpo al 9' sul gol del primo tempo e, se la partita e'
0-0 all'intervallo, un secondo colpo al 47' sul gol del secondo tempo, con le
statistiche della partita in modo da "regolarsi meglio".

Due cose misurate che questo modulo porta con se'.

La prima e' il tasso base, su 164.590 partite finite 0-0 all'intervallo: un gol
nel secondo tempo arriva nel 74,2% dei casi (IC95 73,9-74,4%). Non l'86% che
circolava, che veniva da 764 partite selezionate. Il 74,2% vuol dire che la
quota di pareggio e' 1,348, e su "gol nel secondo tempo" a 0-0 il book paga
1,08-1,15. Per questo il market nasce con un minimo di quota: pubblicare a 1,10
significa perdere il 18% per scommessa, misurato.

La seconda riguarda le statistiche. Il vecchio fetch_fixture_stats mappava la
risposta dell'API su un dizionario a campi fissi, e cercava "dangerous attacks"
con un nome che quell'API non usa: il campo e' rimasto a zero in 89 casi su 89
per mesi, e il modello lo pesava 0.0000 - cosa che io avevo letto come "i tiri
non servono" invece che come "il campo e' vuoto". Qui la cattura conserva TUTTI
i campi che arrivano, e il messaggio dichiara quelli assenti invece di stamparli
a zero. Un numero mancante deve sembrare mancante.
"""
import re
from typing import Optional

# Finestra di apertura. Il secondo tempo comincia al 46': 46-48 lascia due
# scansioni di margine senza sconfinare nel gioco vero.
WINDOW_START = 46
WINDOW_END = 48

# Quota minima: il pareggio misurato, arrotondato per eccesso ai 5 centesimi.
MIN_QUOTA = 1.35

# I sette campi del messaggio: etichetta che leggi, e i "type" normalizzati da
# cercare nella risposta dell'API.
#
# "attacks" e "dangerous attacks" NON ESISTONO in /fixtures/statistics. Non e'
# un'ipotesi: su una partita coperta (Brasile Serie B, 8 ottobre 2026) l'API
# manda sedici campi, e non sono fra quelli.
#
#   Shots on Goal · Shots off Goal · Total Shots · Shots insidebox
#   Shots outsidebox · Blocked Shots · Corner Kicks · Ball Possession
#   Fouls · Offsides · Goalkeeper Saves · Free Kicks · Total passes
#   Passes accurate · Yellow Cards · Red Cards
#
# Per sei volte di fila quei due campi sono risultati assenti - a fine partita
# su Fulham, in diretta su Vila Nova, su quattordici righe di registro, e qui.
# Chiedevano gli attacchi pericolosi per capire la pressione: i campi che
# misurano la stessa cosa e che esistono sono "total shots" e "shots insidebox",
# cioe' i tiri tentati e quelli da dentro l'area. Quelli stanno qui.
STAT_FIELDS = [
    ("Corner", ("corner kicks",)),
    ("Tiri totali", ("total shots",)),
    ("Tiri in area", ("shots insidebox",)),
    ("Tiri in porta", ("shots on goal",)),
    ("Tiri fuori porta", ("shots off goal",)),
    ("Cartellini", ("yellow cards", "red cards")),
    ("Possesso", ("ball possession",)),
]

# Sette righe "non disponibile" sembrano un guasto nostro. Lo sono state per
# una sera: Fabio vedeva quei numeri su Sofascore e il messaggio non diceva
# perche' noi no. Le ragioni sono due e vanno distinte, perche' portano a cose
# diverse - la prima e' definitiva per quella competizione, la seconda puo'
# riguardare solo quella partita.
NOTE_NO_STATS = "📊 Statistiche: non raccolte dall'API per questa competizione"
# WIT Georgia - Gonio, 8 ottobre 2026: Liga 3 georgiana dichiara
# statistics_fixtures=True e /fixtures/statistics risponde HTTP 200 con
# results=0. La bandiera dice cosa raccolgono per la competizione, non cosa
# esiste per la singola partita.
NOTE_EMPTY_STATS = "📊 Statistiche: l'API le copre ma non ne ha per questa partita"
# Quando non sappiamo perche': niente di arrivato e nessuna provenienza. E' il
# caso delle righe aperte prima che la provenienza esistesse.
NOTE_NO_DATA = "📊 Statistiche: nessun dato per questa partita"
# I campi assenti in una riga sola. Restano nominati - un campo che manca deve
# sembrare mancante, mai uno zero - ma non occupano sette righe per dire "no".
NOTE_MISSING_PREFIX = "➖ Senza dato: "

PERCENT_FIELDS = {"Possesso"}

# Un'icona per riga, solo per leggibilita'. Le etichette restano quelle di
# STAT_FIELDS: sono chiavi usate da missing_fields e dai cancelli, e un emoji
# davanti non le cambia.
STAT_ICONS = {
    "Corner": "🚩",             # bandierina
    "Tiri totali": "⚔️",        # spade incrociate
    "Tiri in area": "🔥",       # fuoco
    "Tiri in porta": "🎯",      # bersaglio
    "Tiri fuori porta": "💨",   # soffio
    "Cartellini": "🟨",         # quadrato giallo
    "Possesso": "🔄",           # frecce circolari
}

# Separatore di riga, definito come costante per non passare da un literal
# con backslash: due livelli di escaping lo hanno gia' trasformato una volta.
LINE_BREAK = chr(10)


# Competizioni che non si possono giocare: giovanili e squadre riserve. Sulla
# piattaforma di Fabio quelle partite non esistono, quindi un segnale la' e'
# rumore in canale e una riga inutile nel registro.
#
# Perche' questo filtro e' legittimo e non e' "scegliere i risultati che mi
# piacciono": separa per GIOCABILITA', una proprieta' della competizione che
# non dipende da come e' finita. Verificato sui ventinove segnali al momento
# dell'introduzione: le cinque escluse non avevano quota, quindi la misura del
# margine - gli unici segnali su cui una scommessa esisteva - non si muove di
# un centesimo. Cambia il canale, non il conto.
#
# I nomi sono la parte delicata. "Juventud" (Uruguay), "Akademiya Ontustik"
# (Kazakhstan), "Juventus", "Independiente", "Resende", "Kahta 02 Spor" sono
# squadre di prima squadra: un filtro su "juven", "akadem" o su due cifre le
# ucciderebbe. Per questo si cercano marcatori di eta' con i confini di parola.
UNPLAYABLE_PATTERNS = (
    r"\bu-?(?:1[4-9]|2[0-3])\b",      # U19, U-20, U23
    r"\bsub-?(?:1[4-9]|2[0-3])\b",    # Sub-20, come lo scrive il Brasile
    r"\byouth\b",
    r"\bjuniores\b",
    r"\bprimavera\b",
    r"\breserves?\b",
    r"\bres\.",                        # "Independiente Res."
)
_unplayable = re.compile("|".join(UNPLAYABLE_PATTERNS), re.IGNORECASE)


def playable(league_name: str, matchup: str) -> tuple:
    """(giocabile, motivo). Cerca i marcatori in lega E nomi delle squadre.

    Servono entrambi: "Friendlies Women" non dice niente, ma "Scotland U19 W
    vs Croatia U19 W" si'; e "Reserve League" non lo dicono i nomi delle
    squadre ma la competizione.
    """
    for testo in (league_name or "", matchup or ""):
        trovato = _unplayable.search(str(testo))
        if trovato:
            return False, f"giovanili o riserve ({trovato.group(0)} in '{testo}')"
    return True, "competizione giocabile"


def in_window(minute_value: Optional[int]) -> bool:
    """True solo nella finestra di apertura del secondo tempo."""
    if minute_value is None:
        return False
    return WINDOW_START <= int(minute_value) <= WINDOW_END


def second_half_gate(minute_value: Optional[int], total_goals: Optional[int],
                     status_short: str = "",
                     halftime_goals: Optional[int] = None) -> tuple:
    """(apribile, motivo). La regola di Ten: 0-0 all'intervallo, colpo al 47'.

    Lo stato della partita conta: a 0-0 al 47' ma con la gara sospesa o finita
    non si apre niente.

    `halftime_goals` e' il punteggio dell'intervallo, da score.halftime. E' la
    regola di Ten alla lettera, e serve perche' il punteggio live puo' essere
    in ritardo: un gol al 44' non ancora propagato farebbe sembrare 0-0 al 46'
    una partita che all'intervallo era 0-1. Visto sul fornitore l'8 ottobre
    2026, su Petare-Atletico Avila: goals e score dicevano 0-0, gli eventi un
    gol al 42'.

    Se l'intervallo e' ignoto - None - si ricade sul punteggio live, come prima
    di questo parametro: meglio la regola approssimata che nessun segnale.
    """
    if str(status_short or "").upper() in {"HT", "FT", "AET", "PEN", "PST", "CANC", "ABD", "SUSP"}:
        return False, f"partita in stato {status_short}"
    if not in_window(minute_value):
        return False, f"minuto {minute_value} fuori dalla finestra {WINDOW_START}-{WINDOW_END}"
    if halftime_goals is not None and int(halftime_goals) != 0:
        return False, f"all'intervallo non era 0-0 ({halftime_goals} gol)"
    if total_goals is None or int(total_goals) != 0:
        return False, f"punteggio non 0-0 ({total_goals} gol)"
    quale = "0-0 all'intervallo" if halftime_goals is not None else "0-0 live (intervallo ignoto)"
    return True, f"{quale}, finestra del secondo tempo"


def normalize_type(name) -> str:
    """Nome del campo come lo cerchiamo noi. Deve restare allineato a
    normalize_stat_key in oracle_live.py."""
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def parse_value(value):
    """Il valore numerico, o None se il campo non porta un numero.

    None e zero sono cose diverse: un campo che l'API non valorizza non e' una
    partita senza corner, e il messaggio deve poterlo dire.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    testo = str(value).strip().replace("%", "")
    if not testo:
        return None
    try:
        return float(testo)
    except ValueError:
        return None


def capture_fields(api_response) -> dict:
    """Conserva OGNI campo che l'API manda, per squadra e in totale.

    Il vecchio fetch_fixture_stats mappava su un dizionario a campi fissi:
    tutto quello che non era previsto veniva buttato, e un campo cercato con il
    nome sbagliato restava zero in silenzio. Qui si tiene tutto, cosi' un campo
    nuovo compare da solo e uno assente si vede.
    """
    squadre = []
    for team in (api_response or []):
        campi = {}
        for stat in (team.get("statistics") or []):
            campi[normalize_type(stat.get("type"))] = parse_value(stat.get("value"))
        squadre.append(campi)

    totali = {}
    for campi in squadre:
        for chiave, valore in campi.items():
            if valore is None:
                totali.setdefault(chiave, None)
                continue
            totali[chiave] = (totali.get(chiave) or 0.0) + valore
    return {
        "totals": totali,
        "home": squadre[0] if len(squadre) > 0 else {},
        "away": squadre[1] if len(squadre) > 1 else {},
        "types": sorted({k for c in squadre for k in c}),
    }


def pick_stat(fields: dict, names: tuple):
    """Somma i campi richiesti, o None se nessuno porta un numero."""
    trovati = [fields[n] for n in names if fields.get(n) is not None]
    if not trovati:
        return None
    return float(sum(trovati))


def format_stats_block(capture: dict, nota: Optional[str] = None) -> str:
    """Solo i numeri che ci sono. Quelli che mancano, in una riga sola.

    Prima elencava tutti e sette i campi con "non disponibile" accanto agli
    assenti: su una competizione senza statistiche erano sette righe identiche
    che dicevano solo "no", e il messaggio diventava illeggibile.

    La regola che non cambia: un campo assente resta DICHIARATO assente, mai
    stampato come zero. E' il difetto che ha tenuto "dangerous attacks" a 0,00
    per mesi facendolo sembrare una misura. Cambia la forma - una riga invece
    di sette - non la regola.

    Tre casi. Niente di arrivato: resta solo la ragione (`nota`, oppure
    NOTE_NO_DATA se non la sappiamo). Qualcosa di arrivato e qualcosa no: i
    numeri, piu' una riga che nomina i mancanti. Tutto arrivato: i sette campi.
    """
    totali = capture.get("totals", {})
    casa = capture.get("home", {})
    ospiti = capture.get("away", {})
    righe = []
    for etichetta, names in STAT_FIELDS:
        icona = STAT_ICONS.get(etichetta, "")
        capo = f"{icona} {etichetta}" if icona else etichetta
        if etichetta in PERCENT_FIELDS:
            # Il possesso non si somma: 50 e 50 non fanno 100 di possesso.
            c = pick_stat(casa, names)
            o = pick_stat(ospiti, names)
            if c is None and o is None:
                continue
            righe.append(f"{capo}: {0 if c is None else c:.0f}% - "
                         f"{0 if o is None else o:.0f}%")
            continue
        valore = pick_stat(totali, names)
        if valore is None:
            continue
        if float(valore).is_integer():
            righe.append(f"{capo}: {int(valore)}")
        else:
            righe.append(f"{capo}: {valore:.1f}")

    if not righe:
        return nota or NOTE_NO_DATA
    if nota:
        return LINE_BREAK.join([nota] + righe)
    mancanti = missing_fields(capture)
    if mancanti:
        righe.append(NOTE_MISSING_PREFIX + ", ".join(mancanti))
    return LINE_BREAK.join(righe)


def missing_fields(capture: dict) -> list:
    """Quali dei sette campi l'API non ha mandato. Serve al log, non al lettore."""
    totali = capture.get("totals", {})
    casa = capture.get("home", {})
    ospiti = capture.get("away", {})
    mancanti = []
    for etichetta, names in STAT_FIELDS:
        if etichetta in PERCENT_FIELDS:
            if pick_stat(casa, names) is None and pick_stat(ospiti, names) is None:
                mancanti.append(etichetta)
        elif pick_stat(totali, names) is None:
            mancanti.append(etichetta)
    return mancanti
