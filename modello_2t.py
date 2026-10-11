"""Quanto e' probabile un gol nel secondo tempo, data una partita 0-0 all'intervallo.

Nasce da una domanda di Fabio: come si selezionano le partite col gol piu'
probabile? Finora l'osservatore del 47' non selezionava niente - apriva su
ogni 0-0, perche' era uno strumento di misura - e il risultato erano
cinquantotto messaggi in un'ora.

Il modello e' costruito come quello dei market principali: addestrato sullo
storico, validato fuori campione. 67.953 partite 0-0 all'intervallo, ricavate
da due milioni di partite dal 1995. Sei feature, tutte calcolate solo sul
passato di ogni squadra, mai sulla partita in corso:

    tasso storico di gol-nel-2T della squadra di casa e di quella in trasferta
    gol medi totali di ciascuna
    forma recente: le ultime dieci partite 0-0 all'intervallo di ciascuna

Addestrato fino al 2022, provato su 35.623 partite del 2023-2026 mai viste:

    decile  1:  prevista 63,8%  ->  reale 63,5%   serve quota 1,576
    decile  5:  prevista 73,4%  ->  reale 72,6%   serve quota 1,378
    decile 10:  prevista 81,3%  ->  reale 80,8%   serve quota 1,238  (+/-1,3%)

    differenza fra decile alto e basso: +17,3 punti

Previsto e reale coincidono entro un punto in tutti e dieci i decili: quando
dice 80% e' 80%. E' questa calibrazione che permette di confrontare la
probabilita' con il prezzo, invece di confrontare due opinioni.

Cosa NON fa: non dice se conviene scommettere. All'80,8% il pareggio richiede
1,238, e il book sconta la probabilita' alta - sui dati veri il quinto piu'
alto riceveva in media 1,194, che richiederebbe l'83,8%. Se su quelle partite
il prezzo resta sotto 1,238 il margine non c'e', per bravo che sia il modello.
E' la domanda aperta, e si risponde raccogliendo p e quota su ogni segnale.
"""
import difflib
import json
import os
import re
import threading
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELLO_PATH = os.path.join(BASE_DIR, "modello_2t.pkl")
SQUADRE_PATH = os.path.join(BASE_DIR, "squadre_2t.json")

# Parole che non distinguono una squadra da un'altra: vanno togliete prima di
# confrontare i nomi, altrimenti "FC Porto" e "Porto" sembrano due squadre.
RUMORE = re.compile(r"\b(fc|cf|sc|ac|afc|cd|ca|club|de|the|if|bk|sk|fk|ks|as|us)\b")
# Somiglianza minima per accettare un abbinamento incerto. Sotto questa soglia
# si preferisce non sapere: una squadra sbagliata produce una probabilita'
# sbagliata, che e' peggio di nessuna probabilita'.
SOMIGLIANZA_MINIMA = 0.92

_lock = threading.Lock()
_stato = {"caricato": False, "modello": None, "feat": None, "soglie": None,
          "squadre": {}, "indice": {}, "nomi": []}


def normalizza(nome) -> str:
    testo = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    testo = RUMORE.sub(" ", testo.lower())
    return re.sub(r"[^a-z0-9]+", "", testo)


def carica() -> bool:
    """Carica modello e tabella squadre. Torna False se non ci sono."""
    with _lock:
        if _stato["caricato"]:
            return _stato["modello"] is not None
        _stato["caricato"] = True
        try:
            import joblib
            pacco = joblib.load(MODELLO_PATH)
            with open(SQUADRE_PATH, encoding="utf-8") as handle:
                squadre = json.load(handle)
        except Exception as exc:
            print(f"modello_2t: non caricato ({exc})")
            return False
        _stato["modello"] = pacco.get("modello")
        _stato["feat"] = pacco.get("feat")
        _stato["soglie"] = pacco.get("soglie") or {}
        _stato["squadre"] = squadre
        _stato["indice"] = {normalizza(k): k for k in squadre}
        _stato["nomi"] = list(_stato["indice"])
        return _stato["modello"] is not None


def soglia_decile_alto() -> float:
    """La soglia del decile alto, letta dal modello stesso.

    Non e' scritta a mano qui: se il modello viene riaddestrato, la soglia lo
    segue. Un numero copiato a mano si scollerebbe dal modello senza che
    nessuno lo noti.
    """
    if not carica():
        return 1.0
    return float((_stato["soglie"] or {}).get("d9", 1.0))


def trova_squadra(nome):
    """La riga storica di una squadra, o None se non si riesce a identificarla.

    Prima il confronto esatto sul nome normalizzato, poi uno sfumato con una
    soglia alta. Non si tira a indovinare: senza squadra non c'e' probabilita',
    e il segnale resta registrato ma muto.
    """
    if not carica():
        return None
    chiave = normalizza(nome)
    if not chiave:
        return None
    esatta = _stato["indice"].get(chiave)
    if esatta:
        return _stato["squadre"][esatta]
    vicine = difflib.get_close_matches(chiave, _stato["nomi"], n=1,
                                       cutoff=SOMIGLIANZA_MINIMA)
    if not vicine:
        return None
    return _stato["squadre"][_stato["indice"][vicine[0]]]


def probabilita(casa, fuori):
    """(p, motivo). p e' None quando una delle due squadre non si identifica."""
    if not carica():
        return None, "modello non caricato"
    a, b = trova_squadra(casa), trova_squadra(fuori)
    if a is None or b is None:
        mancante = casa if a is None else fuori
        return None, f"squadra senza storia: {mancante}"
    valori = {"c2": a["r2"], "f2": b["r2"], "cg": a["gol"], "fg": b["gol"],
              "cr": a["rec"], "fr": b["rec"]}
    try:
        # Con i nomi delle colonne, non con una lista: il modello e' stato
        # addestrato su un DataFrame e senza i nomi stampa un avviso a ogni
        # chiamata - che nel log del bot diventerebbe una riga ogni segnale.
        import pandas as pd
        riga = pd.DataFrame([[valori[k] for k in _stato["feat"]]],
                            columns=list(_stato["feat"]))
        p = float(_stato["modello"].predict_proba(riga)[0][1])
    except Exception as exc:
        return None, f"previsione fallita: {exc}"
    return p, f"{a['n2']}+{b['n2']} precedenti"


def selezionato(p) -> bool:
    """True solo per il decile alto. Il resto si registra e tace."""
    if p is None:
        return False
    return float(p) >= soglia_decile_alto()
