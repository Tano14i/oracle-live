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
  EVIDENCE: automatic-evidence=v1; definition-sha256=b182a2a4bb0f70038d566f7c6a9e5beb4c5822eb683508a5d6523834d65d3eb4; exit=0; EXPECT=matched; output-sha256=b94381bc9b21aa8ac7c878bc303292ded360ceeb32cb13fc66acf0a518e3deb6; output-bytes=203; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G3: una dipendenza che fallisce in loop non riempie il disco di righe identiche
  CHECK: .venv\Scripts\python.exe gates\check_log_dedup.py
  EXPECT: log dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=b838b3462fbc4d46cc443669eb100e735132408ab7f4263860bd0282e969c91e; exit=0; EXPECT=matched; output-sha256=f26f7e86884c646589732eefec0139ea5424f344c9d76ad4cf46bc1e7a557978; output-bytes=99; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G4: la raccolta quote a ogni scansione ha funzionato in produzione, misurata sul log reale
  CHECK: .venv\Scripts\python.exe gates\check_odds_tracking.py
  EXPECT: odds tracking verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=88faf9f5725553e3c85d9b803ab449d4587f464c56e5b35d2e1dde857b22be41; exit=0; EXPECT=matched; output-sha256=ea14593b061e349811cf9e0b3bc4641267a4232bfde2ff9a629a0c390ff3f043; output-bytes=118; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G5: la suite di test resta verde
  CHECK: .venv\Scripts\python.exe -m pytest -q tests
  EXPECT: /\b\d+ passed\b/
  EVIDENCE: automatic-evidence=v1; definition-sha256=db968df039adacda4a117159f4c91862a1c43a4dd3cc5944233e9398a43623b0; exit=0; EXPECT=matched; output-sha256=38260456e1d1e4e1cb63d2645fc7c9e4abb64c0f758843ba215d80b372ae112e; output-bytes=101; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G6: nessun segreto e nessun dato personale risulta tracciato, e l'albero non ha derive impreviste
  CHECK: .venv\Scripts\python.exe gates\check_repo_hygiene.py
  EXPECT: repo hygiene verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=634ef5689ae18ae28b507b98a864dcecf357bd47a6ccb428efab496faa9e7c58; exit=0; EXPECT=matched; output-sha256=5d7266b27b43d25418af75676486f7c6a285a826332b4a58ceb6a2923001abd7; output-bytes=131; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G11: il processo IN ESECUZIONE scrive l'ora vera, non solo il modulo
  CHECK: .venv\Scripts\python.exe gates\check_log_utc_live.py
  EXPECT: log utc live verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=8ca32794763ed1d4929c30c1d6a2b45317cce1016b7a62802d76f1bd9a467fd9; exit=0; EXPECT=matched; output-sha256=dc478428a7f43896be466164b56a88cdce6bf3d6e0f41e7ddfa2440c8532c39a; output-bytes=210; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

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
  EVIDENCE: automatic-evidence=v1; definition-sha256=743fa8d55206d67071699c581c910bde4b114a6765d43a5d5fda5ded7d29c887; exit=0; EXPECT=matched; output-sha256=dffe1749ead7910d0a855dd885c589a2cadac3c543bf000440439da7bcaedd09; output-bytes=106; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G15: il log non tace a lungo mentre il processo lavora (battito a tempo)
  CHECK: .venv\Scripts\python.exe gates\check_log_heartbeat.py
  EXPECT: log heartbeat verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=4c843e4f0e0bf90fe61b282a6e156af224d198ca91050b5138ffb1e029e3a959; exit=0; EXPECT=matched; output-sha256=29e6deac39f526927f6b7cef04199f58e6ee5aaaca065777358490dc668cdc1d; output-bytes=123; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

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
