# Regola dei corner al 47' — registrata prima di misurarla

Questo file esiste per impedirmi di ingannarti, e di ingannarmi.

L'11 ottobre 2026, sui 103 segnali del 47' che avevano le statistiche, ho
provato quattro campi per vedere se spostavano l'esito. Tre non dicono niente.
Il quarto sì:

    corner > 4 al 47'   ->  89,4% di gol nel secondo tempo  (n=47)
    corner <= 4         ->  72,2%                           (n=54)
    differenza: +17,1 punti,  z = +2,26,  p = 0,024

E sui soli segnali che avevano anche una quota:

    corner > 4    43 segnali   40W-3L = 93,0%   quota media 1,232 (pareggio 81,2%)
                  ROI +14,5%   IC95 bootstrap +3,5% / +22,8%
    corner <= 4   47 segnali   33W-14L = 70,2%  quota media 1,256
                  ROI -12,3%

Il book quasi non distingue: correlazione corner/quota -0,16, quota media
1,232 contro 1,256. Due centesimi e mezzo di quota per ventitré punti di
differenza negli esiti.

## Perché NON è ancora una scoperta

Tre ragioni, e la terza è la più importante.

1. **Ho provato quattro campi.** Correggendo per i quattro tentativi
   (Bonferroni) p passa da 0,024 a **0,095**: sopra la soglia. Trovare un
   campo su quattro a z>1,96 accade per caso circa una volta su cinque.

2. **Tre perdite su 43.** Il bootstrap con tre sconfitte pesca spesso campioni
   che non ne contengono nessuna, quindi stringe l'intervallo più di quanto
   dovrebbe. È lo stesso difetto che l'8 ottobre mi ha fatto vedere un
   intervallo sopra lo zero su 13W-1L — e due giorni dopo quel margine era
   sparito.

3. **La soglia e il campo li ho scelti dopo aver visto i dati.** Qualunque
   numero misurato sugli stessi dati che lo hanno suggerito è gonfiato.

Un controllo di coerenza va nella direzione sbagliata: sui pochi segnali con
statistiche e senza quota (n=11) il verso si inverte. Troppo pochi per contare,
ma non è una conferma.

Quello che il dato ha di buono: i 43 segnali vengono da **31 campionati
distinti**, nessuno oltre il 7% del campione, quindi non è l'artefatto di una
lega sola. E togliendo l'ultimo giorno (12W-0L, il più fortunato) restano 31
segnali a +11,3%: non dipende da una sola serata.

## La regola, fissata adesso e non più modificabile

    Si considera un segnale del 47' se e solo se:
      - StatsSource == "dati"      (le statistiche sono arrivate davvero)
      - Corners > 4                (totale delle due squadre al 47')
      - LiveOdd presente           (una scommessa esisteva)
    Puntata: 1 unità. Nessun altro filtro.

Niente di questo si tocca: non la soglia 4, non il campo "corner", non la
quota minima, non le leghe. Se mi venisse voglia di provare una variante, è una
registrazione nuova con il suo campione nuovo.

## Da quando si misura

    congelato a: 2026-10-11T14:14:45.689079+00:00
    (ultima osservazione presente nel registro al momento della registrazione)

Contano **solo** i segnali con ObservedAtUTC successivo a questo istante. I 43
che hanno suggerito la regola non entrano nel conto: hanno già fatto il loro
lavoro, cioè suggerirla.

## Quanti servono e cosa decide

Con l'effetto osservato (93% a quota media 1,232, ROI +14,5%) la potenza
richiede circa **40 segnali nuovi**:

    n ≈ (1,96 + 0,84)² × σ² / μ²    con σ = 1,232 × √(0,93 × 0,07) = 0,314
                                    e μ = 0,145   ->   n ≈ 37

Criterio deciso adesso, prima di vedere i dati:

- **Confermata** se, su almeno 40 segnali nuovi, l'IC95 bootstrap del ROI sta
  **tutto sopra lo zero**.
- **Respinta** altrimenti. Un ROI positivo con l'intervallo che tocca lo zero
  non è una conferma: è dove siamo adesso, e dove eravamo l'8 ottobre.

Al ritmo di questi giorni (27 e 12 segnali idonei il 10 e l'11 ottobre) servono
due o tre giorni.

Fino a quel momento questa regola **non si gioca**. Non perché sia prudente
dirlo, ma perché il numero che la fa sembrare buona è lo stesso numero che l'ha
scelta fra quattro.
