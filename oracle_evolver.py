import json
import pandas as pd
import os

WEB_DATA_PATH = 'web_stats.json'
CSV_PATH = 'Matches.csv'

def evolvi_database():
    if not os.path.exists(WEB_DATA_PATH):
        print("❌ Nessun dato live trovato.")
        return

    with open(WEB_DATA_PATH, 'r') as f:
        data = json.load(f)

    segnali = data.get("recent_signals", [])
    nuove_righe = []

    for s in segnali:
        # Procediamo solo se il match è concluso (WIN o LOSS)
        if "WIN" in s.get("Esito", "") or "LOSS" in s.get("Esito", ""):
            # Estraiamo i nomi delle squadre
            teams = s["Match"].split(" vs ")
            if len(teams) == 2:
                # Nota: Qui simuliamo il risultato finale per l'addestramento DNA
                # Se WIN = almeno 1 gol segnato dopo il segnale
                # Se LOSS = 0 gol segnati
                valore_finto_gol = 1 if "WIN" in s["Esito"] else 0
                
                nuove_righe.append({
                    'HomeTeam': teams[0].strip(),
                    'AwayTeam': teams[1].strip(),
                    'FTHome': valore_finto_gol, # Diamo all'IA l'informazione del gol
                    'FTAway': 0,
                    'Date': pd.Timestamp.now().strftime('%d/%m/%Y')
                })

    if nuove_righe:
        df_nuovi = pd.DataFrame(nuove_righe)
        df_nuovi.to_csv(CSV_PATH, mode='a', header=False, index=False)
        print(f"✅ Aggiunti {len(nuove_righe)} nuovi match al database storico.")
        
        # PULIZIA: resettiamo i segnali inviati per non intasare la memoria
        data["recent_signals"] = []
        data["segnali_inviati"] = []
        with open(WEB_DATA_PATH, 'w') as f:
            json.dump(data, f, indent=4)
        print("🧹 Memoria live pulita per la nuova sessione.")
    else:
        print("pocchissimi dati nuovi o match ancora in corso.")

if __name__ == "__main__":
    evolvi_database()