import pandas as pd
import os
import kagglehub
import glob
from datetime import datetime

def super_merge_esatto():
    print("🚀 Inizio processo di unificazione totale (Codice Originale del Record V2.1)...")
    
    # --- 1. DOWNLOAD DATASET INTERNAZIONALI (MARTJ42) ---
    print("🌍 Download match internazionali da Kaggle...")
    try:
        intl_path = kagglehub.dataset_download("martj42/international-football-results-from-1872-to-2017")
        results = pd.read_csv(os.path.join(intl_path, 'results.csv'))
        goals = pd.read_csv(os.path.join(intl_path, 'goalscorers.csv'))
        
        print("⚽ Calcolo punteggi primo tempo per Nazionali...")
        goals['is_home_goal'] = (goals['team'] == goals['home_team'])
        df_goals_ht = goals[goals['minute'] <= 45].copy()
        
        ht_scores = df_goals_ht.groupby(['date', 'home_team', 'away_team', 'is_home_goal']).size().unstack(fill_value=0).reset_index()
        
        if True not in ht_scores.columns: ht_scores[True] = 0
        if False not in ht_scores.columns: ht_scores[False] = 0
            
        ht_scores = ht_scores.rename(columns={True: 'HTHome', False: 'HTAway'})
        
        intl_df = pd.merge(results, ht_scores, on=['date', 'home_team', 'away_team'], how='left')
        intl_df = intl_df.rename(columns={
            'date': 'MatchDate', 'home_team': 'HomeTeam', 'away_team': 'AwayTeam', 
            'home_score': 'FTHome', 'away_score': 'FTAway'
        })
        intl_df = intl_df[['MatchDate', 'HomeTeam', 'AwayTeam', 'FTHome', 'FTAway', 'HTHome', 'HTAway']].fillna(0)
        print(f"✅ Nazionali completate: {len(intl_df)} match.")
    except Exception as e:
        print(f"⚠️ Errore Nazionali: {e}")
        intl_df = pd.DataFrame()

    # --- 2. DOWNLOAD DATASET CLUB (KAGGLE) ---
    kaggle_datasets = [
        "marcelbiezunski/laliga-matches-dataset-2019-2025-fbref",
        "estebanmarcelloni/liga-argentina-futbol",
        "adamgbor/club-football-match-data-2000-2025",
        "arsalanhashmi7/football-competitions-dataset", # Il nuovo dataset aggiunto in sicurezza
        "davidcariboo/player-scores" 
    ]
    
    kaggle_csv_files = []
    player_scores_path = None

    for dataset in kaggle_datasets:
        try:
            print(f"📥 Download in corso: {dataset}...")
            path = kagglehub.dataset_download(dataset)
            if "player-scores" in dataset:
                player_scores_path = path
            else:
                found_files = glob.glob(os.path.join(path, "**", "*.csv"), recursive=True)
                kaggle_csv_files.extend(found_files)
        except Exception as e:
            print(f"❌ Errore download {dataset}: {e}")

    # --- 3. LOGICA PLAYER-SCORES (TRANSFERMARKT) ---
    player_scores_df = pd.DataFrame()
    if player_scores_path:
        print("⚽ Elaborazione Player-Scores (Transfermarkt)...")
        try:
            games = pd.read_csv(os.path.join(player_scores_path, "games.csv"))
            clubs = pd.read_csv(os.path.join(player_scores_path, "clubs.csv"))
            club_mapping = dict(zip(clubs['club_id'], clubs['name']))
            
            games['HomeTeam'] = games['home_club_id'].map(club_mapping)
            games['AwayTeam'] = games['away_club_id'].map(club_mapping)
            games = games.rename(columns={'date': 'MatchDate', 'home_club_goals': 'FTHome', 'away_club_goals': 'FTAway'})
            games['HTHome'], games['HTAway'] = 0, 0
            
            player_scores_df = games[['MatchDate', 'HomeTeam', 'AwayTeam', 'FTHome', 'FTAway', 'HTHome', 'HTAway']].dropna()
            print(f"✅ Player-Scores completato.")
        except Exception as e:
            print(f"❌ Errore Player-Scores: {e}")

    # --- 4. ELABORAZIONE CLUB STANDARD ---
    # Usiamo SOLO i file locali dichiarati, ignorando eventuali file spazzatura nella cartella
    local_files = ['belgium.csv', 'england.csv', 'england5.csv', 'germany.csv', 'greece.csv', 'holland.csv', 'italy.csv', 'portugal.csv', 'scotland.csv', 'turkey.csv']
    all_club_files = [f for f in local_files if os.path.exists(f)] + kaggle_csv_files
    
    club_dfs = [player_scores_df]
    
    # Il Mapping V2.1 ESATTO (con le aggiunte di sicurezza per il nuovo file)
    mapping = {
        'Date': 'MatchDate', 'date': 'MatchDate', 'fecha': 'MatchDate', 'Date_New': 'MatchDate',
        'home': 'HomeTeam', 'HomeTeam': 'HomeTeam', 'local': 'HomeTeam', 'home_team': 'HomeTeam',
        'visitor': 'AwayTeam', 'AwayTeam': 'AwayTeam', 'visitante': 'AwayTeam', 'away_team': 'AwayTeam',
        'hgoal': 'FTHome', 'FTHG': 'FTHome', 'home_score': 'FTHome', 'Home_Goals': 'FTHome',
        'vgoal': 'FTAway', 'FTAG': 'FTAway', 'away_score': 'FTAway', 'Away_Goals': 'FTAway',
        'HTHG': 'HTHome', 'HTHome': 'HTHome', 'HTAG': 'HTAway', 'HTAway': 'HTAway',
        'hg': 'FTHome', 'ag': 'FTAway', 'gf': 'FTHome', 'ga': 'FTAway', 'score1': 'FTHome', 'score2': 'FTAway'
    }

    print(f"📊 Analisi di {len(all_club_files)} file CSV...")
    for f in all_club_files:
        try:
            df = pd.read_csv(f, low_memory=False)
            
            # Formato FBRef
            if 'venue' in df.columns and 'opponent' in df.columns:
                df = df[df['venue'].str.lower() == 'home'].copy()
                df = df.rename(columns={'team': 'HomeTeam', 'opponent': 'AwayTeam', 'gf': 'FTHome', 'ga': 'FTAway'})

            # Applichiamo il rinnovo nomi originale, senza abbassare maiuscole/minuscole
            df = df.rename(columns=mapping)
            
            cols_needed = ['MatchDate', 'HomeTeam', 'AwayTeam', 'FTHome', 'FTAway']
            if all(c in df.columns for c in cols_needed):
                if 'HTHome' not in df.columns: df['HTHome'] = 0
                if 'HTAway' not in df.columns: df['HTAway'] = 0
                club_dfs.append(df[cols_needed + ['HTHome', 'HTAway']])
        except:
            continue

    # --- 5. UNIONE, PULIZIA E DE-DUPLICAZIONE ---
    print("🔄 Unione finale e rimozione duplicati...")
    master_df = pd.concat([intl_df] + club_dfs, ignore_index=True)
    
    master_df['MatchDate'] = pd.to_datetime(master_df['MatchDate'], errors='coerce')
    master_df = master_df.dropna(subset=['MatchDate', 'HomeTeam', 'AwayTeam'])
    
    master_df['HomeTeam'] = master_df['HomeTeam'].astype(str).str.strip().str.upper()
    master_df['AwayTeam'] = master_df['AwayTeam'].astype(str).str.strip().str.upper()
    
    master_df = master_df.sort_values(by='MatchDate')
    
    initial_count = len(master_df)
    master_df = master_df.drop_duplicates(subset=['MatchDate', 'HomeTeam', 'AwayTeam'], keep='last')
    
    master_df.to_csv('Matches.csv', index=False)
    
    squadre = pd.concat([master_df['HomeTeam'], master_df['AwayTeam']]).nunique()
    
    print("\n" + "="*40)
    print(f"📊 RISULTATO FINALE (IL VERO RECORD)")
    print(f"📈 Record totali: {len(master_df)}")
    print(f"🏟️ SQUADRE PREPARATE: {squadre}")
    print(f"🧹 Duplicati rimossi: {initial_count - len(master_df)}")
    print(f"📂 File generato: Matches.csv")
    print("="*40)

if __name__ == "__main__":
    super_merge_esatto()