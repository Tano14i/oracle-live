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

# I sette campi chiesti, con i nomi che l'API puo' usare per ognuno. La chiave
# e' l'etichetta nel messaggio; i valori sono i "type" normalizzati da cercare.
#
# "attacks" e "dangerous attacks" NON sono presenti nella risposta di
# /fixtures/statistics verificata su una partita conclusa di Premier League.
# Restano qui perche' se l'API li esponesse in diretta vanno raccolti - ma il
# messaggio li marchera' come non disponibili invece di scrivere 0.
STAT_FIELDS = [
    ("Corner", ("corner kicks",)),
    ("Attacchi", ("attacks",)),
    ("Attacchi pericolosi", ("dangerous attacks",)),
    ("Tiri in porta", ("shots on goal",)),
    ("Tiri fuori porta", ("shots off goal",)),
    ("Cartellini", ("yellow cards", "red cards")),
    ("Possesso", ("ball possession",)),
]

PERCENT_FIELDS = {"Possesso"}

# Separatore di riga, definito come costante per non passare da un literal
# con backslash: due livelli di escaping lo hanno gia' trasformato una volta.
LINE_BREAK = chr(10)


def in_window(minute_value: Optional[int]) -> bool:
    """True solo nella finestra di apertura del secondo tempo."""
    if minute_value is None:
        return False
    return WINDOW_START <= int(minute_value) <= WINDOW_END


def second_half_gate(minute_value: Optional[int], total_goals: Optional[int],
                     status_short: str = "") -> tuple:
    """(apribile, motivo). La regola di Ten: 0-0 all'intervallo, colpo al 47'.

    Lo stato della partita conta: a 0-0 al 47' ma con la gara sospesa o finita
    non si apre niente.
    """
    if str(status_short or "").upper() in {"HT", "FT", "AET", "PEN", "PST", "CANC", "ABD", "SUSP"}:
        return False, f"partita in stato {status_short}"
    if not in_window(minute_value):
        return False, f"minuto {minute_value} fuori dalla finestra {WINDOW_START}-{WINDOW_END}"
    if total_goals is None or int(total_goals) != 0:
        return False, f"punteggio non 0-0 ({total_goals} gol)"
    return True, "0-0 all'intervallo, finestra del secondo tempo"


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


def format_stats_block(capture: dict) -> str:
    """Le sette statistiche chieste, con i mancanti dichiarati."""
    totali = capture.get("totals", {})
    casa = capture.get("home", {})
    ospiti = capture.get("away", {})
    righe = []
    for etichetta, names in STAT_FIELDS:
        if etichetta in PERCENT_FIELDS:
            # Il possesso non si somma: 50 e 50 non fanno 100 di possesso.
            c = pick_stat(casa, names)
            o = pick_stat(ospiti, names)
            righe.append(f"{etichetta}: non disponibile" if c is None and o is None
                         else f"{etichetta}: {0 if c is None else c:.0f}% - {0 if o is None else o:.0f}%")
            continue
        valore = pick_stat(totali, names)
        if valore is None:
            righe.append(f"{etichetta}: non disponibile")
        elif float(valore).is_integer():
            righe.append(f"{etichetta}: {int(valore)}")
        else:
            righe.append(f"{etichetta}: {valore:.1f}")
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
