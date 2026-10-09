@echo off
rem Avvia il bot se non sta girando. Lanciato dalla cartella Esecuzione
rem automatica di Windows a ogni accesso, e dall'operazione pianificata ogni
rem dieci minuti. Chiama il watchdog, non il supervisore: cosi' se il bot c'e'
rem gia' non ne parte un secondo.
rem
rem "start" serve a staccare: questo .cmd esce subito e pythonw resta in piedi
rem senza console. Il 9 ottobre 2026 il bot e' morto perche' era attaccato
rem all'albero di processi di chi lo aveva avviato.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "watchdog.py"
