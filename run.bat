@echo off
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
.venv\Scripts\python.exe oracle_live.py %*
pause
