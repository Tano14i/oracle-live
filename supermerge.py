import pandas as pd
import os
import kagglehub
import glob

def super_merge_v5():
    print("🔥 AVVIO RECOVERY v5.0: RIPRISTINO DATABASE ORIGINALE + ESPANSIONE...")
    
    datasets = [
        "arsalanhashmi7/football-competitions-dataset",
        "adamgbor/club-football-match-data-2000-2025",
        "martj42/international-football-results-from-1872-to-2017",
        "marcelbiezunski/laliga-matches-dataset-2019-2025-fbref",
        "estebanmarcelloni/liga-argentina-futbol",
        "davidcariboo/player-scores"
    ]
    
    all_chunks = []

    for ds in datasets:
        print(f"📂 Analisi dataset: {ds}")
        try:
            path = kagglehub.dataset_download(ds)
            # Scansione profonda di OGNI file CSV
            files = glob.glob(os.path.join(path, "**", "*.csv"), recursive=True)
            
            for f in files:
                try:
                    # Carichiamo il file con una logica più permissiva
                    df = pd.read_csv(f, low_memory=False)
                    
                    # Rinominiamo solo quello che troviamo con certezza
                    df.columns = [c.strip().lower() for c in df.columns]
                    
                    # Mapping ultra-semplice
                    m = {
                        'home_team': 'HomeTeam', 'hometeam': 'HomeTeam', 'home': 'HomeTeam', 'local': 'HomeTeam',
                        'away_team': 'AwayTeam', 'awayteam': 'AwayTeam', 'away': 'AwayTeam', 'visitor': 'AwayTeam',
                        'fthg': 'FTHome', 'hg': 'FTHome', 'home_score': 'FTHome', 'gf': 'FTHome',
                        'ftag': 'FTAway', 'ag': 'FTAway', 'away_score': 'FTAway', 'ga': 'FTAway',
                        'date': 'MatchDate', 'matchdate': 'MatchDate', 'fecha': 'MatchDate'
                    }
                    
                    # Applichiamo il mapping alle colonne che esistono nel file
                    cols_to_rename = {k: v for k, v in m.items() if k in df.columns}
                    df = df.rename(columns=cols_to_rename)
                    
                    # Verifichiamo se abbiamo almeno HomeTeam, AwayTeam e i Gol
                    if 'HomeTeam' in df.columns and 'AwayTeam' in df.columns:
                        needed = ['HomeTeam', 'AwayTeam', 'FTHome', 'FTAway']
                        # Se mancano i gol, proviamo a cercarli in altre colonne comuni
                        if 'FTHome' not in df.columns: continue 
                        
                        # Creiamo il subset
                        temp = df[df.columns.intersection(needed + ['MatchDate', 'HTHome', 'HTAway'])].copy()
                        
                        # Assicuriamoci che tutte le colonne esistano
                        for col in ['FTHome', 'FTAway', 'HTHome', 'HTAway']:
                            if col not in temp.columns: temp[col] = 0
                        if 'MatchDate' not in temp.columns: temp['MatchDate'] = '2020-01-01'
                        
                        all_chunks.append(temp)
                        print(f"   ✅ Caricati {len(temp)} record da: {os.path.basename(f)}")
                except: continue
        except: continue

    if not all_chunks:
        print("❌ Nessun dato recuperato. Controlla i download di Kaggle.")
        return

    # Unione massiva
    print("🔄 Unificazione dei chunk...")
    master_df = pd.concat(all_chunks, ignore_index=True)
    
    # Pulizia nomi (per il bot)
    master_df['HomeTeam'] = master_df['HomeTeam'].astype(str).str.upper().str.strip()
    master_df['AwayTeam'] = master_df['AwayTeam'].astype(str).str.upper().str.strip()
    
    # Rimozione duplicati ma solo se identici (MatchDate + Squadre)
    # Riduciamo il drop_duplicates per non perdere squadre
    initial_len = len(master_df)
    master_df = master_df.drop_duplicates(subset=['MatchDate', 'HomeTeam', 'AwayTeam'])
    
    master_df.to_csv('Matches.csv', index=False)
    
    # Conteggio finale squadre
    squadre_preparate = pd.concat([master_df['HomeTeam'], master_df['AwayTeam']]).nunique()

    print("\n" + "="*40)
    print(f"✨ OPERAZIONE PHOENIX COMPLETATA")
    print(f"📊 Match totali salvati: {len(master_df)}")
    print(f"🏟️ SQUADRE PREPARATE (NEL BOT): {squadre_preparate}")
    print(f"="*40)

if __name__ == "__main__":
    super_merge_v5()