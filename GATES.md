# Gates: chiusura del lavoro aperto in sessione (30/09 - 29/10)

OWNS: oracle_live.py, second_half_observer.py, modello_2t.py, gates/**, GATES.md

Scope (ampliato il 07/10, aggiornato il 24/10): chiudere i tre difetti di osservabilita' rimasti
aperti (log illimitato, timestamp UTC falso, verifica della raccolta quote in produzione), tenere verde
la suite, e rendere visibili come handoff le quattro decisioni che spettano
all'owner invece di lasciarle implicite.

Aggiornamento 24/10: aggiunto RowType al registro dell'osservatore 47' (open/settle/backfill),
eliminando i 112 duplicati che sporcavano l'analisi; allineato trova_squadra di modello_2t alla
logica di oracle_live (copertura sale dal 37% al livello del bot).

Aggiornamento 29/10: sistema di coda segnali (un attivo alla volta, rilascio al minuto 75 o a
chiusura, re-fetch dati live al momento del rilascio); second_half_queue.json aggiunto al .gitignore.

Prerequisito dichiarato: le verifiche girano con Python 3.12
`C:\Users\Gebruiker\AppData\Local\Programs\Python\Python312\python.exe`.
Il Python 3.14 di sistema non ha sklearn/joblib e non vale come evidenza per G31.

- [x] G1: il log non puo' piu' crescere senza limite
  CHECK: python3.12 gates\check_log_rotation.py
  EXPECT: log rotation verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=2b65fd03fc4d9667ae952e5fb21eba1adc4579b097f848b1cb44e0ce7186d963; exit=0; EXPECT=matched; output-sha256=d40e799756b8871cab880a65d87b61b49905ae62d12acde224a59921388797e5; output-bytes=66; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G2: un timestamp etichettato Z e' davvero UTC
  CHECK: python3.12 gates\check_log_utc.py
  EXPECT: log utc verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=e822a023d17b3d40f3a6227dd89cb0da6624dc14fbfe1cdee4de9193b62672bc; exit=0; EXPECT=matched; output-sha256=6345af3e5f5393936ec7e5d7c67356d17a3044755f0dfafdd551d4028f486618; output-bytes=199; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G3: una dipendenza che fallisce in loop non riempie il disco di righe identiche
  CHECK: python3.12 gates\check_log_dedup.py
  EXPECT: log dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4835550020cd1476da982a2b5aa2e6e32bda3e821dd996bb1da1e6a26c8b68fb; exit=0; EXPECT=matched; output-sha256=8671c7a8d047c2c2e9669da642fa1297e68df8c865bd75faec0cee6cfd7bff58; output-bytes=96; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G4: la raccolta quote a ogni scansione ha funzionato in produzione, misurata sul log reale
  CHECK: python3.12 gates\check_odds_tracking.py
  EXPECT: odds tracking verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4862ca6155efea7397f4f109facd6b76f4c4392221e3ae0525102e662a2358df; exit=0; EXPECT=matched; output-sha256=ebcdc0455a6778d3de61ecb565bb94aa877c391d1a5f4d420b152141ff35551f; output-bytes=116; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G6: nessun segreto e nessun dato personale risulta tracciato, e l'albero non ha derive impreviste
  CHECK: python3.12 gates\check_repo_hygiene.py
  EXPECT: repo hygiene verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=993abdde78c346a936a4b002a5adb24c7ce515b194ecde7c18a5ca0fdd8fb330; exit=0; EXPECT=matched; output-sha256=fdd1c861ac656fd782a3f74552aa35192db7fe6ba0996cebe6fb6691c6e46b7e; output-bytes=128; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G11: il processo IN ESECUZIONE scrive l'ora vera, non solo il modulo
  CHECK: python3.12 gates\check_log_utc_live.py
  EXPECT: log utc live verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=8db56882fd8b72ee51a4343638af1be356a1e3d241620925235634aa9b877496; exit=0; EXPECT=matched; output-sha256=8d0fc2dcc4539d9cfb6218cc5079fd86af9a10f5f3366ac68f1aeb10e4806f6e; output-bytes=206; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G12: ogni affermazione sul P/L passa da un solo strumento, che non produce mai un totale mescolato
  CHECK: python3.12 gates\check_pl_report.py
  EXPECT: pl report verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=e1a87b408a8decf0a6c9d4be2e7c0368880e7038bc02ed050fe824c7bd23f236; exit=0; EXPECT=matched; output-sha256=08a3e97a4124bbfe36d0f4acc7e3b680397f0c23ce9cfd3875437155ef29fb06; output-bytes=149; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G13: la cifra misurata coincide con un calcolo indipendente, e il conteggio W-L col dataset
  CHECK: python3.12 gates\check_pl_independent.py
  EXPECT: pl independent verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=2923f7e5150b6a87a467dd75b3644fd69adcc8130702d7cffe5d0041dc219898; exit=0; EXPECT=matched; output-sha256=1788e5b1bd6f3866e2b6d9561df02f0116374721bfadca7bf8d1572b0977f587; output-bytes=118; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G14: il recap deduplica come tutto il resto (keep=first), non con l'ultima riga
  CHECK: python3.12 gates\check_recap_dedup.py
  EXPECT: recap dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=12fd23894a4bd68fd2d04336ef4560f3c580f78243c4e4d4f40ab7db2514b88c; exit=0; EXPECT=matched; output-sha256=754562e60d0ca7fe93834f732ddfbca7c1b0bbe84f46cc7ef00c25df18041041; output-bytes=103; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G15: il log non tace a lungo mentre il processo lavora (battito a tempo)
  CHECK: python3.12 gates\check_log_heartbeat.py
  EXPECT: log heartbeat verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=9d1bc67f42c3bfe09168f12dd6cb8c22652ec3f254060f56f0de134e3c52473f; exit=0; EXPECT=matched; output-sha256=f0b8d1fbcb20bbd0ff9c5751be7f3988f571a9589dd5e8b7168a69850d9327d3; output-bytes=120; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G16: il segnale del 47 si apre solo nella finestra 46-48 e solo a 0-0
  CHECK: python3.12 gates\check_second_half_window.py
  EXPECT: second half window verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=897f473ee2c7347cb23e1b36ad68c3d1377c4128440a9ff65253b91c080f63b6; exit=0; EXPECT=matched; output-sha256=7677bc05167f3eb7d8a09eb184bfe75266ef9fa10c481fbbcbb222f3e60bcd95; output-bytes=113; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G17: il blocco statistiche mostra i sette campi chiesti e dichiara quelli che l API non fornisce
  CHECK: python3.12 gates\check_stats_block.py
  EXPECT: stats block verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=9e43f383588d078cb2d99db7a564127fab141b19c2c64f2857b21f52400f8485; exit=0; EXPECT=matched; output-sha256=430a6e966d7f72a42c4670ff622148cf4ec64e32fb91ca79a25c2c80d568be8d; output-bytes=237; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G18: la cattura conserva ogni campo che l API manda, non solo quelli previsti
  CHECK: python3.12 gates\check_stats_capture.py
  EXPECT: stats capture verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4e0a9138243e3c14a1e6a29fda9a5d6ab43b4b5aeb5adc127881ff1d30e1d74a; exit=0; EXPECT=matched; output-sha256=6b6b50f5162eaf5b65f56585ef41ecb525f596888015a14fb682a4c52e286c3d; output-bytes=114; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G19: il segnale del 47 non raggiunge free/VIP e dichiara la quota contro il pareggio misurato
  CHECK: python3.12 gates\check_second_half_channels.py
  EXPECT: second half channels verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=5e9f0678ced47ad81ba5941016f7851b769f093a40a1aa7e5544214c64b4bb5a; exit=0; EXPECT=matched; output-sha256=4d1a1e05682e7c99010ae1629d1fe96624f5989c2a9baacff6c68d073f527ca8; output-bytes=241; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G20: un riavvio non lascia un segnale del 47 per sempre in corso: l attesa sopravvive, la chiusura modifica il messaggio
  CHECK: python3.12 gates\check_second_half_restart.py
  EXPECT: second half restart verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=a9c0269690350a2ddb7a404bbc26938b7132b2081f1feb361292c44f383b2463; exit=0; EXPECT=matched; output-sha256=99c137ad6ec952c88525b2a42cc453ac7bfb0a438e3655a35b513e0dd5c56f79; output-bytes=167; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G21: chi spegne il bot legge che si ferma anche il supervisore e come riaccenderlo
  CHECK: python3.12 gates\check_shutdown_notice.py
  EXPECT: shutdown notice verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=258e2f9c3d37c08aafaa26dd67c445dbe027677a6c417dc020aa521a471fccfe; exit=0; EXPECT=matched; output-sha256=d043028e4f0d2aef2e0ef6d3a3f8e481204293f33dd9866503d61c4cbc9434c6; output-bytes=186; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G22: una risposta vuota dell API non viene scambiata per un nostro guasto: la copertura si legge, si tiene, e l ignoto non diventa un no
  CHECK: python3.12 gates\check_api_coverage.py
  EXPECT: api coverage verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=32a642bba26ac0b43a5340857a4f3d88eeb1748b6950aeeb97349938b5502c9e; exit=0; EXPECT=matched; output-sha256=c326a16d30d4ff89f1f78362ae3fc5aa63edef29ac6185383543f55e8e45a234; output-bytes=230; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G23: dove le statistiche non sono raccolte gli eventi danno cartellini e minuto del gol, senza inventare zeri
  CHECK: python3.12 gates\check_events_fallback.py
  EXPECT: events fallback verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4a8b62b7182af508c9e3a3f39e8f7c8dde2d5438ef1a772cfb922a84a193a894; exit=0; EXPECT=matched; output-sha256=13137d57a5647e4a21c3726207357758ca96910e3efd138cadc6fdf778b89bc4; output-bytes=190; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G24: il registro dice se un buco e vuoto o errore, e non si disallinea quando le colonne cambiano
  CHECK: python3.12 gates\check_log_provenance.py
  EXPECT: log provenance verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=059ff32f2e015e3097b7c0d510107e31b2041a904596745a563927583636f167; exit=0; EXPECT=matched; output-sha256=bea53ce1cf38e0af3e5c21233f98d30d03bc51631c3359f16b5a85af6b44394a; output-bytes=236; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G25: il minuto del gol non dipende da una gara con l API: limite superiore subito, minuto esatto inseguito, nessun doppio esito
  CHECK: python3.12 gates\check_goal_minute.py
  EXPECT: goal minute verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=7452479a6f44d387dbf7e044c15e9f7abf7ebc0e2f77d363f01e87aaa28cdb37; exit=0; EXPECT=matched; output-sha256=e589248526701ecaa9ddaa218c366c882b2489d00c6b515a97de899477117694; output-bytes=206; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G26: le partite non giocabili - giovanili e riserve - non si aprono, e le prime squadre con nomi simili non vengono toccate
  CHECK: python3.12 gates\check_playable.py
  EXPECT: playable verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=1467415ec23f6e99fb9733ac50948ab5422345cf1a364d68439360aa1f158c4c; exit=0; EXPECT=matched; output-sha256=dfc3685e34cd9bc9b358fedb1025730342d39285e0e4715dbb450ba7987f7513; output-bytes=177; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G27: il bot non resta giu perche chi lo ha avviato e morto: si riconosce dal suo lock, si riavvia staccato, e non parte mai in due
  CHECK: python3.12 gates\check_watchdog.py
  EXPECT: watchdog verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=88a7328ff544aa58f7a3fe4cfe9c4a168beb50a66eb5df84667dbea8ec57907c; exit=0; EXPECT=matched; output-sha256=1a1bbb9318600ea75288cd9f08859d390106a6ab115fd60185df643fb5912544; output-bytes=706; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G28: la regola dei corner non si puo ritoccare dopo aver visto i dati, e si giudica solo sui segnali che non l hanno suggerita
  CHECK: python3.12 gates\check_corner_preregistration.py
  EXPECT: corner preregistration verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=ac33854ec53abb4091a4cddbd5ef6b2019a5a81756db038f25883578dfd81064; exit=0; EXPECT=matched; output-sha256=d379307629d42992f55f611def9aa30fdf829833cc9967820982905e196c3fc9; output-bytes=289; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G29: il minuto vero arriva alla riga registrata, cosi la curva del book esiste e si puo confrontare con quella equa
  CHECK: python3.12 gates\check_odds_curve.py
  EXPECT: odds curve verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=863dccde2765f6aa01579b6cda56a67e966fc735dc5a0235dd2f4bcba54f371c; exit=0; EXPECT=matched; output-sha256=20e38539a8180505e5d853d1df86c83b0d2221ceab14b3e1029b4a40cc5c43aa; output-bytes=198; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G30: il report di performance non si pubblica da solo e il suo titolo e la somma delle sue righe, non un contatore che le contraddice
  CHECK: python3.12 gates\check_performance_report.py
  EXPECT: performance report verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=5977b848c77743e334534e793bec36c51cef95efce8f230a368c924f95d50416; exit=0; EXPECT=matched; output-sha256=fc577a562c7f579ef1bdc1cdc80c01a6362b4ee87eab02db1936d78b557821b1; output-bytes=323; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [x] G31: il modello seleziona il decile alto, una squadra ignota non produce una probabilita inventata, e si registra tutto ma suona solo il selezionato
  CHECK: python3.12 gates\check_modello_2t.py
  EXPECT: modello 2t verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=0a5cae945620d9dcee835c825abce09d867e14d39e84699840ddd4ed8b4b6a5a; exit=0; EXPECT=matched; output-sha256=7368601f12f2722de4c5660d157998211f17fdb643d440ad640ccfe580d4d9be; output-bytes=227; shell=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=d0bad89/46 entries

- [ ] G7: destino di oracle_brain.pkl deciso (56 MB su LFS, modello v1 di solo fallback)
  EVIDENCE: pending

- [ ] G8: destino dei 4,5 GB di Matches_*.csv deciso (cancellazione irreversibile)
  EVIDENCE: pending

- [ ] G9: il recap mostra, oltre al P/L sulle sole prezzate, una stima su tutti i segnali chiusi
  EVIDENCE: pending

- [ ] G10: destino della PR #2 deciso (chiudere e riportare momentum.py, oppure altro)
  EVIDENCE: pending

ABANDON: G7 decisione dell'owner: committare 56 MB di binario LFS per un modello di solo fallback, o smettere di tracciarlo. Non e' una scelta tecnica neutra (quota LFS) e non la prendo io.
ABANDON: G8 decisione dell'owner: cancellare 4,5 GB di backup e' irreversibile. Elenco dei file e spazio recuperato riportati nel messaggio finale, esecuzione in attesa di consenso esplicito.
ABANDON: G9 decisione dell'owner: cambia quello che vedono i canali free e VIP. Proposta e numeri riportati nel messaggio finale, mai approvata.
ABANDON: G10 decisione dell'owner: un merge diretto rimetterebbe .env.prematch nel repo pubblico, riporterebbe indietro Matches.csv e resusciterebbe 15 file cancellati da ec4409a. Il port del solo momentum.py abiliterebbe un market che pubblica su canali reali con soglie derivate da dati corrotti.
