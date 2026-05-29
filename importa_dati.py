import sqlite3
import pandas as pd
import os

# Forza il programma a lavorare nella cartella dove si trova questo script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

CSV_NAME = 'Matches.csv'
DB_NAME = 'oracle_data.db'

print(f"📂 Percorso attuale: {os.getcwd()}")

if not os.path.exists(CSV_NAME):
    print(f"❌ Errore: Non trovo {CSV_NAME} qui! Controlla che il nome sia esatto (maiuscole incluse).")
else:
    try:
        print("📖 Lettura del file CSV in corso... (attendi circa 30 secondi)")
        # Leggiamo il CSV
        df = pd.read_csv(CSV_NAME, low_memory=False)
        
        # Connessione al database
        conn = sqlite3.connect(DB_NAME)
        
        print("📦 Trasferimento dati nel database professionale...")
        # Creiamo la tabella 'matches'
        df.to_sql('matches', conn, if_exists='replace', index=False)
        
        conn.close()
        print(f"✅ OPERAZIONE COMPLETATA! Database popolato con {len(df)} righe.")
        print("Ora puoi chiudere questo script e far ripartire oracle_live.py")
    except Exception as e:
        print(f"❌ Errore imprevisto: {e}")