# Gates: chiusura del lavoro aperto in sessione (30/09 - 04/10)

OWNS: oracle_live.py, gates/**, GATES.md

Scope: chiudere i tre difetti di osservabilita' rimasti aperti (log illimitato,
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
  EVIDENCE: automatic-evidence=v1; definition-sha256=b182a2a4bb0f70038d566f7c6a9e5beb4c5822eb683508a5d6523834d65d3eb4; exit=0; EXPECT=matched; output-sha256=f78bde87a17a14051beb4c8fdc9b938fcf6c691c2f2322459d567d845538ee39; output-bytes=203; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G3: una dipendenza che fallisce in loop non riempie il disco di righe identiche
  CHECK: .venv\Scripts\python.exe gates\check_log_dedup.py
  EXPECT: log dedup verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=b838b3462fbc4d46cc443669eb100e735132408ab7f4263860bd0282e969c91e; exit=0; EXPECT=matched; output-sha256=f26f7e86884c646589732eefec0139ea5424f344c9d76ad4cf46bc1e7a557978; output-bytes=99; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G4: la raccolta quote a ogni scansione ha funzionato in produzione, misurata sul log reale
  CHECK: .venv\Scripts\python.exe gates\check_odds_tracking.py
  EXPECT: odds tracking verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=88faf9f5725553e3c85d9b803ab449d4587f464c56e5b35d2e1dde857b22be41; exit=0; EXPECT=matched; output-sha256=f903127a32ed9ef36685429efbd362711e16497fd8adeb4b7bde8a2ce7c8e5f2; output-bytes=114; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G5: la suite di test resta verde
  CHECK: .venv\Scripts\python.exe -m pytest -q tests
  EXPECT: /\b\d+ passed\b/
  EVIDENCE: automatic-evidence=v1; definition-sha256=db968df039adacda4a117159f4c91862a1c43a4dd3cc5944233e9398a43623b0; exit=0; EXPECT=matched; output-sha256=0dbcf5ee4160be77534e7fccfdf0cc3dbc995f3fcdb0358817cef3235323cdcc; output-bytes=101; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G6: nessun segreto e nessun dato personale risulta tracciato, e l'albero non ha derive impreviste
  CHECK: .venv\Scripts\python.exe gates\check_repo_hygiene.py
  EXPECT: repo hygiene verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=634ef5689ae18ae28b507b98a864dcecf357bd47a6ccb428efab496faa9e7c58; exit=0; EXPECT=matched; output-sha256=5d7266b27b43d25418af75676486f7c6a285a826332b4a58ceb6a2923001abd7; output-bytes=131; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

- [x] G11: il processo IN ESECUZIONE scrive l'ora vera, non solo il modulo
  CHECK: .venv\Scripts\python.exe gates\check_log_utc_live.py
  EXPECT: log utc live verification passed
  EVIDENCE: automatic-evidence=v1; definition-sha256=8ca32794763ed1d4929c30c1d6a2b45317cce1016b7a62802d76f1bd9a467fd9; exit=0; EXPECT=matched; output-sha256=8255b74bec803a2623766c41718b52e9a2605e98cf32a79c1859d1db57983499; output-bytes=210; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live; path=2073621dd5db/48 entries

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
