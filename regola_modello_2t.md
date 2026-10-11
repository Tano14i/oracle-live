# Selezione col modello del secondo tempo — registrata prima di misurarla

Fabio: "come facciamo selezione delle partite che hanno la probabilità più alta
del gol al secondo tempo?" Questa è la risposta, scritta prima di giudicarla.

## Il modello

Addestrato su 67.953 partite 0-0 all'intervallo, ricavate da 2.031.156 partite
dal 1995. Sei feature, tutte calcolate solo sul passato di ogni squadra: tasso
storico di gol-nel-2T di casa e trasferta, gol medi totali di ciascuna, forma
nelle ultime dieci partite 0-0 all'intervallo di ciascuna.

Addestrato fino al 2022, provato su 35.623 partite del 2023-2026 mai viste:

    decile  1:  prevista 63,8%  ->  reale 63,5%
    decile  5:  prevista 73,4%  ->  reale 72,6%
    decile 10:  prevista 81,3%  ->  reale 80,8%   +/- 1,3%

    differenza fra decile alto e basso: +17,3 punti

Previsto e reale coincidono entro un punto in tutti e dieci i decili. Questa
calibrazione è la cosa che conta: permette di confrontare la probabilità col
prezzo invece di confrontare due opinioni.

## La regola, fissata adesso e non più modificabile

    Il segnale del 47' SUONA se e solo se:
      - il modello sa calcolare p  (entrambe le squadre hanno 30+ precedenti)
      - p >= 0.7915793918550821    (decile alto, soglia letta da modello_2t.pkl)
    Tutti gli altri si registrano e restano muti.

La soglia non è scritta a mano nel codice: viene da `soglie["d9"]` dentro il
modello, così se il modello cambia la soglia lo segue. Qui è trascritta perché
il cancello possa verificare che siano lo stesso numero.

## Da quando si misura

    congelato a: 2026-10-11T15:19:43.695524+00:00

Contano solo i segnali con ObservedAtUTC successivo. I 572 che hanno costruito
tutto quello che sappiamo finora non entrano nel conto che giudica la regola.

## Cosa mi aspetto, e cosa NON mi aspetto

Sui 572 segnali già raccolti il modello seleziona 38 segnali (6,6%), e quei 38
hanno fatto **33W-3L = 91,7%** su 36 chiusi. È fuori campione per il modello,
che non ha mai visto un segnale live — ma sono 36 partite, e il modello
prevedeva l'80,8%, non il 91,7%. Quindi l'attesa onesta è **80,8%**, non quello
che è successo.

Dove sta il problema, e va detto adesso: sui 23 selezionati con una quota, il
book ha offerto in media **1,178**. All'80,8% il pareggio richiede **1,238**.
A quel prezzo la regola perde il 4,8% per scommessa, per quanto buono sia il
modello. Il P/L positivo osservato (+0,54 unità, ROI +2,3%) viene dal 91,7%
realizzato, non da quello previsto — e su 23 scommesse è rumore.

**Quindi questa regola, oggi, è un riduttore di rumore con un tasso di
successo alto, non un margine dimostrato.** Da 150-300 messaggi al giorno a
10-18, e niente di più finché i due criteri qui sotto non hanno una risposta.

## I due criteri, decisi adesso

**1. Il modello regge in diretta?** Su almeno **60 segnali selezionati e
chiusi** dopo il congelamento, l'intervallo di confidenza al 95% del tasso di
successo deve contenere o superare l'80,8%. Se finisce tutto sotto, il modello
non si trasferisce dal mio storico alle partite che il bot incontra, e la
selezione va rifatta.

**2. C'è un margine?** Su almeno **130 segnali selezionati con una quota**,
l'IC95 bootstrap del ROI deve stare tutto sopra lo zero. Il numero viene dalla
potenza: con l'effetto del campione attuale (91,7% a quota 1,178) servono circa
129 scommesse; con l'80,8% previsto non basterebbe nessun campione raggiungibile,
perché a 1,178 il valore atteso è negativo.

Criterio 1 senza criterio 2 significa: il modello seleziona bene e il prezzo si
mangia il vantaggio. È l'esito più probabile, ed è comunque un risultato utile —
dice di non giocare, e lo dice con un numero.

Al ritmo attuale (10-18 selezionati al giorno, 60% con quota) il criterio 1
arriva in quattro o cinque giorni, il criterio 2 in due o tre settimane.

## Cosa non si tocca

Né la soglia, né le feature, né il modello, né l'istante di congelamento. Se
volessi provare una variante — un'altra soglia, il decile alto unito alla
regola dei corner — è una registrazione nuova con il suo campione nuovo.

Fino al verdetto questa selezione **non si gioca**: serve a far tacere il bot,
non a dirti su cosa puntare.
