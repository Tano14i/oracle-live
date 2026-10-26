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

# Parole che non distinguono una squadra da un'altra. La lista e' quella di
# simplify_team_tokens in oracle_live: il bot abbina i nomi dell'API a quelli
# del suo database da mesi, e la sua tecnica funziona meglio della mia prima
# versione - teneva gli spazi e confrontava insiemi di token, mentre io
# schiacciavo tutto in una stringa unica e perdevo "Real Madrid" vs "Madrid
# Real". Con la mia la probabilita' si calcolava sul 37% dei segnali.
RUMORE_TOKEN = (" fc ", " cf ", " sc ", " ac ", " afc ", " cd ", " ca ", " club ",
                " calcio ", " futbol ", " football ", " sporting ", " sport ",
                " association ", " team ", " the ", " if ", " bk ", " sk ", " fk ",
                " ks ", " as ", " us ", " ii ", " b ", " de ", " do ", " da ")
# Le tre soglie sono quelle di trova_squadra in oracle_live, scelte su 18.948
# squadre: oltre 0,94 sul nome intero si accetta subito, altrimenti si prende
# il migliore se arriva a 0,88 sul nome semplificato o a 0,86 su quello intero.
# Sotto, si preferisce non sapere: una squadra sbagliata produce una
# probabilita' sbagliata, che e' peggio di nessuna probabilita'.
ACCETTA_SUBITO = 0.94
SOGLIA_SEMPLIFICATO = 0.88
SOGLIA_INTERO = 0.86

_lock = threading.Lock()
_stato = {"caricato": False, "modello": None, "feat": None, "soglie": None,
          "squadre": {}, "indice": {}, "semplici": {}, "token": {}, "cache": {}}


def chiave(nome) -> str:
    """Nome confrontabile: minuscolo, senza accenti, SPAZI CONSERVATI."""
    testo = unicodedata.normalize("NFD", str(nome or "").lower())
    testo = "".join(c for c in testo if unicodedata.category(c) != "Mn")
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def semplifica(nome) -> str:
    """Il nome senza le parole che non distinguono e senza i numeri d'anno."""
    testo = f" {chiave(nome)} "
    for token in RUMORE_TOKEN:
        testo = testo.replace(token, " ")
    testo = re.sub(r"\b\d{2,4}\b", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def normalizza(nome) -> str:
    """Compatibilita': la vecchia forma schiacciata, usata solo come indice."""
    return chiave(nome).replace(" ", "")


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
        _stato["indice"] = {chiave(k): k for k in squadre}
        _stato["semplici"] = {}
        _stato["token"] = {}
        for nome in squadre:
            sem = semplifica(nome)
            if sem:
                _stato["semplici"].setdefault(sem, nome)
                _stato["token"].setdefault(frozenset(sem.split()), nome)
        _stato["cache"] = {}
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
    k = chiave(nome)
    if not k:
        return None
    if k in _stato["cache"]:
        trovato = _stato["cache"][k]
        return _stato["squadre"][trovato] if trovato else None

    def esito(nome_db):
        _stato["cache"][k] = nome_db
        return _stato["squadre"][nome_db] if nome_db else None

    # 1. nome identico
    if k in _stato["indice"]:
        return esito(_stato["indice"][k])
    sem = semplifica(nome)
    # 2. nome semplificato identico
    if sem and sem in _stato["semplici"]:
        return esito(_stato["semplici"][sem])
    # 3. stesse parole in ordine diverso
    if sem:
        insieme = frozenset(sem.split())
        if insieme in _stato["token"]:
            return esito(_stato["token"][insieme])
    # 4. somiglianza, con le tre soglie del bot
    migliore_intero, r_intero = None, 0.0
    migliore_sem, r_sem = None, 0.0
    for k_db, nome_db in _stato["indice"].items():
        r = difflib.SequenceMatcher(None, k, k_db).ratio()
        if r > ACCETTA_SUBITO:
            return esito(nome_db)
        if r > r_intero:
            migliore_intero, r_intero = nome_db, r
    if sem:
        for sem_db, nome_db in _stato["semplici"].items():
            r = difflib.SequenceMatcher(None, sem, sem_db).ratio()
            if r > r_sem:
                migliore_sem, r_sem = nome_db, r
    if migliore_sem and r_sem >= SOGLIA_SEMPLIFICATO:
        return esito(migliore_sem)
    if migliore_intero and r_intero >= SOGLIA_INTERO:
        return esito(migliore_intero)
    return esito(None)


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
