# Gates: chiusura del lavoro aperto in sessione (30/09 - 04/10)

OWNS: oracle_live.py, gates/**, GATES.md

Scope (ampliato il 07/10): chiudere i tre difetti di osservabilita' rimasti
aperti (log illimitato,
timestamp UTC falso, verifica della raccolta quote in produzione), tenere verde
la suite, e rendere visibili come handoff le quattro decisioni che spettano
all'owner invece di lasciarle implicite.

Prerequisito dichiarato: le verifiche girano con l'interprete del progetto
`.venv\Scripts\python.exe` su Windows. Una verifica lanciata con un altro
interprete non vale come evidenza.

- [x] G1: il log non puo' piu' crescere senza limite
  CHECK: .venv\Scripts\python.exe gates\check_log_rotation.py
  EXPECT: log rotation verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=f65e05130661d2af52e1ff4e107b703eedf7603d2143c51f2a32d0b4a0945198; exit=0; EXPECT=matched; output-sha256=ce696a8021b50b391f0bb5be1ab28f46138c7c4af66f659d907bf938ca09f7e8; output-bytes=69; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G2: un timestamp etichettato Z e' davvero UTC
  CHECK: .venv\Scripts\python.exe gates\check_log_utc.py
  EXPECT: log utc verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=b182a2a4bb0f70038d566f7c6a9e5beb4c5822eb683508a5d6523834d65d3eb4; exit=0; EXPECT=matched; output-sha256=4c4d09e2040db82dc5acd4ec5d8b14965b229d2b7132955b360752cc65e172ee; output-bytes=203; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G3: una dipendenza che fallisce in loop non riempie il disco di righe identiche
  CHECK: .venv\Scripts\python.exe gates\check_log_dedup.py
  EXPECT: log dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=b838b3462fbc4d46cc443669eb100e735132408ab7f4263860bd0282e969c91e; exit=0; EXPECT=matched; output-sha256=f26f7e86884c646589732eefec0139ea5424f344c9d76ad4cf46bc1e7a557978; output-bytes=99; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G4: la raccolta quote a ogni scansione ha funzionato in produzione, misurata sul log reale
  CHECK: .venv\Scripts\python.exe gates\check_odds_tracking.py
  EXPECT: odds tracking verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=88faf9f5725553e3c85d9b803ab449d4587f464c56e5b35d2e1dde857b22be41; exit=0; EXPECT=matched; output-sha256=909691747a80256bd04533f26a7b9ae0de1a6a74ba767d0aadad30e950cefebe; output-bytes=118; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G5: la suite di test resta verde
  CHECK: .venv\Scripts\python.exe -m pytest -q tests
  EXPECT: /\b\d+ passed\b/
  EVIDENCE: automatic-evidence=v1; definition-sha256=db968df039adacda4a117159f4c91862a1c43a4dd3cc5944233e9398a43623b0; exit=0; EXPECT=matched; output-sha256=67f3dedd22fa937696c791b78a2cbed6221bf7971199a31e3dfe4556e83884cd; output-bytes=101; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G6: nessun segreto e nessun dato personale risulta tracciato, e l'albero non ha derive impreviste
  CHECK: .venv\Scripts\python.exe gates\check_repo_hygiene.py
  EXPECT: repo hygiene verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=634ef5689ae18ae28b507b98a864dcecf357bd47a6ccb428efab496faa9e7c58; exit=0; EXPECT=matched; output-sha256=5d7266b27b43d25418af75676486f7c6a285a826332b4a58ceb6a2923001abd7; output-bytes=131; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G11: il processo IN ESECUZIONE scrive l'ora vera, non solo il modulo
  CHECK: .venv\Scripts\python.exe gates\check_log_utc_live.py
  EXPECT: log utc live verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=8ca32794763ed1d4929c30c1d6a2b45317cce1016b7a62802d76f1bd9a467fd9; exit=0; EXPECT=matched; output-sha256=ec9c4acdccb35930b4014a47269cee765ea63e4c0126384a786deaefe9bc40a6; output-bytes=210; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G12: ogni affermazione sul P/L passa da un solo strumento, che non produce mai un totale mescolato
  CHECK: .venv\Scripts\python.exe gates\check_pl_report.py
  EXPECT: pl report verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=5bf79e7525ce29b26fdd0c7433958546d85d39830a1d928f264402bc1d57e2ff; exit=0; EXPECT=matched; output-sha256=7695fb3c6e938f51755fa4a139793f4f73d008923509ff9bee1b362d26893044; output-bytes=154; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G13: la cifra misurata coincide con un calcolo indipendente, e il conteggio W-L col dataset
  CHECK: .venv\Scripts\python.exe gates\check_pl_independent.py
  EXPECT: pl independent verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=f02a00ab65ae2a0d369c5115fafdb3a24ab94037b5a18036924787e324ef64fe; exit=0; EXPECT=matched; output-sha256=4dde1622777b757471c4425f10f0c4c1d8061d3129af37e0a9638477eb45aaf6; output-bytes=123; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G14: il recap deduplica come tutto il resto (keep=first), non con l'ultima riga
  CHECK: .venv\Scripts\python.exe gates\check_recap_dedup.py
  EXPECT: recap dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=743fa8d55206d67071699c581c910bde4b114a6765d43a5d5fda5ded7d29c887; exit=0; EXPECT=matched; output-sha256=4b2c282c1d29f1e2f7ae533602cf4caa06705f81287f3c937e13c51cd80c9919; output-bytes=106; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G15: il log non tace a lungo mentre il processo lavora (battito a tempo)
  CHECK: .venv\Scripts\python.exe gates\check_log_heartbeat.py
  EXPECT: log heartbeat verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4c843e4f0e0bf90fe61b282a6e156af224d198ca91050b5138ffb1e029e3a959; exit=0; EXPECT=matched; output-sha256=29e6deac39f526927f6b7cef04199f58e6ee5aaaca065777358490dc668cdc1d; output-bytes=123; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G16: il segnale del 47 si apre solo nella finestra 46-48 e solo a 0-0
  CHECK: .venv\Scripts\python.exe gates\check_second_half_window.py
  EXPECT: second half window verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=29b8adac7160a5f74256d7bc18fcb4b3df651531ad614c487dad7ecb894dcf02; exit=0; EXPECT=matched; output-sha256=c56aebff3178b0c574cf17e7032b4533178d4ddfd485d53be68e70750f96fa6e; output-bytes=116; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G17: il blocco statistiche mostra i sette campi chiesti e dichiara quelli che l API non fornisce
  CHECK: .venv\Scripts\python.exe gates\check_stats_block.py
  EXPECT: stats block verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=3d79918582724ea4f92535fb84c7a7473c04a646e5459b378eff34e9aa726869; exit=0; EXPECT=matched; output-sha256=91ed68d498242dfae6134ddb5d3fc93b49f5ea15b3489ecea73efb128649188f; output-bytes=177; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G18: la cattura conserva ogni campo che l API manda, non solo quelli previsti
  CHECK: .venv\Scripts\python.exe gates\check_stats_capture.py
  EXPECT: stats capture verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=1223acfaec80dd5630e8e9cbafb58828f6a49349b7dcf2bb6ef3749ba10e1d79; exit=0; EXPECT=matched; output-sha256=ed6a97a1749b43d4dffd387941f78c693921c90332103c0ffe465de1625e8a78; output-bytes=117; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G19: il segnale del 47 non raggiunge free/VIP e dichiara la quota contro il pareggio misurato
  CHECK: .venv\Scripts\python.exe gates\check_second_half_channels.py
  EXPECT: second half channels verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=017a8a82ac76ecec7a56dff49d4f122bc5cfee75ed1741766a8e97d41123a79e; exit=0; EXPECT=matched; output-sha256=f3e2d0272fa0ce59526e66a1b8500330f4c06837c7cef5c7223102bd514a336d; output-bytes=185; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G20: un riavvio non lascia un segnale del 47 per sempre in corso: l attesa sopravvive, la chiusura modifica il messaggio
  CHECK: .venv\Scripts\python.exe gates\check_second_half_restart.py
  EXPECT: second half restart verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=ad283b22ce415875b51d3780bd34d6488b3f5991f1e55dd9033881b65f4c9a4f; exit=0; EXPECT=matched; output-sha256=c1aca1a0bd6a5f230979bdc345635cb04c50835781eb95ff296f12ca05ee97fa; output-bytes=273; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G21: chi spegne il bot legge che si ferma anche il supervisore e come riaccenderlo
  CHECK: .venv\Scripts\python.exe gates\check_shutdown_notice.py
  EXPECT: shutdown notice verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=675e61427a95b7a26ecb7536721558928f171413de38478d5eb6bcdc6c98a7dc; exit=0; EXPECT=matched; output-sha256=87bb5911e443cebf0f9e92b6bbd7ad6173e99aa29122b9376c11d1dc87dcf275; output-bytes=189; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G22: una risposta vuota dell API non viene scambiata per un nostro guasto: la copertura si legge, si tiene, e l ignoto non diventa un no
  CHECK: .venv\Scripts\python.exe gates\check_api_coverage.py
  EXPECT: api coverage verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b02170dd7f2958b24420f7fca902f7455a6fe6e376ad2e864e12022673b672e; exit=0; EXPECT=matched; output-sha256=e5413d7d8a9bbca1c552eb3a3a2ecb8bcae8a94901dc6ec82d768a14fb64e10f; output-bytes=411; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G23: dove le statistiche non sono raccolte gli eventi danno cartellini e minuto del gol, senza inventare zeri
  CHECK: .venv\Scripts\python.exe gates\check_events_fallback.py
  EXPECT: events fallback verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=8b5b9cc9248e8addc67c4db6a976f2534af1cb11af5c591d5bd8f054e339b018; exit=0; EXPECT=matched; output-sha256=b5e6cf6f04919a3db7ec50111039e123a6310ac6bcfc7180b0523997c0de0b9b; output-bytes=193; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G24: il registro dice se un buco e vuoto o errore, e non si disallinea quando le colonne cambiano
  CHECK: .venv\Scripts\python.exe gates\check_log_provenance.py
  EXPECT: log provenance verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=68a4b51a8dd2498fa04dcc7f53ebf660ece33e10ab87312ba952bc3dbd2e1061; exit=0; EXPECT=matched; output-sha256=da8a3f9b3787337be0645788339af3d8ea51850d093b5c6cccba9e347d1fea10; output-bytes=478; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G25: il minuto del gol non dipende da una gara con l API: limite superiore subito, minuto esatto inseguito, nessun doppio esito
  CHECK: .venv\Scripts\python.exe gates\check_goal_minute.py
  EXPECT: goal minute verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=178274cea54b84096ff21fd7d6f9d3d80ac7f2ffbbe15fa534b9f2e5c17ba48d; exit=0; EXPECT=matched; output-sha256=1e3a5f6d2d20480eb7f07dd3af92443ef5fcdea7ce0e89e4e87c6ffc22a69395; output-bytes=209; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G26: le partite non giocabili - giovanili e riserve - non si aprono, e le prime squadre con nomi simili non vengono toccate
  CHECK: .venv\Scripts\python.exe gates\check_playable.py
  EXPECT: playable verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=53e777670b48605810b91ba72dcb93ad50e4b236510a8579a0fc28ca43457fb6; exit=0; EXPECT=matched; output-sha256=dcb84b23a7061693078b4b8d190d6bdb897046e353c3909ba789197be64b9c3b; output-bytes=180; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G27: il bot non resta giu perche chi lo ha avviato e morto: si riconosce dal suo lock, si riavvia staccato, e non parte mai in due
  CHECK: .venv\Scripts\python.exe gates\check_watchdog.py
  EXPECT: watchdog verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=6bb7df023b76d622e2dbb54b5492546fa1a50e941edc0f4c74cb017eceb6fa9c; exit=0; EXPECT=matched; output-sha256=7a0ce698c733195cfbb64fcd3a0fc4bc8bc78c5e0dbad001a5e192f9c6622ef3; output-bytes=714; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G28: la regola dei corner non si puo ritoccare dopo aver visto i dati, e si giudica solo sui segnali che non l hanno suggerita
  CHECK: .venv\Scripts\python.exe gates\check_corner_preregistration.py
  EXPECT: corner preregistration verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=a88afbdb0ec03f21a5b1509457e5a5e161af7fee74d8e118c6100533fe12bd08; exit=0; EXPECT=matched; output-sha256=b1ffc9ac4cc6251f75c33e177e5319228809a9d9dfce5dc5ed1b2b63211808eb; output-bytes=231; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

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
