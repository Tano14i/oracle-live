import sqlite3
import pandas as pd
import os

# 1. Definiamo i percorsi esatti basandoci sul tuo screenshot
cartella = r"C:\Users\Gebruiker\Desktop\Oracle Live"
csv_path = os.path.join(cartella, "Matches.csv")
db_path = os.path.join(cartella, "oracle_data.db")

print(f"🔍 Controllo cartella: {cartella}")

# 2. Verifica presenza file CSV
if not os.path.exists(csv_path):
    print(f"❌ ERRORE: Il file {csv_path} non esiste!")
    print(f"Contenuto cartella: {os.listdir(cartella)}")
else:
    print(f"✅ File CSV trovato ({os.path.getsize(csv_path)} bytes)")
    
    try:
        # 3. Caricamento dati
        print("📖 Caricamento CSV in corso (un attimo di pazienza)...")
        df = pd.read_csv(csv_path, low_memory=False)
        print(f"📊 Dati caricati in memoria: {len(df)} righe.")
        
        # 4. Scrittura su Database
        print("📦 Scrittura nel database in corso...")
        conn = sqlite3.connect(db_path)
        df.to_sql('matches', conn, if_exists='replace', index=False)
        conn.commit()
        conn.close()
        
        # 5. Verifica finale
        nuova_dimensione = os.path.getsize(db_path)
        print(f"✅ OPERAZIONE COMPLETATA!")
        print(f"💾 Dimensione finale del database: {nuova_dimensione / 1024:.2f} KB")
        
        if nuova_dimensione > 0:
            print("🚀 ORA IL DATABASE È PRONTO! Puoi avviare oracle_live.py")
        else:
            print("❗ Attenzione: Il file è ancora 0 KB. C'è un problema di permessi di scrittura.")
            
    except Exception as e:
        print(f"❌ ERRORE DURANTE L'IMPORTAZIONE: {e}")