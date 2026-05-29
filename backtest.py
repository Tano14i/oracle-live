import pandas as pd
import numpy as np
import os

# ==========================================
# ⚙️ CONFIGURAZIONE BACKTEST
# ==========================================
CSV_PATH = 'Matches.csv'
STAKE = 10.0
QUOTA_MEDIA = 1.75  # Quota media leggermente più alta per entrate live 0-0
DNA_MINIMO = 2.8    # Soglia "Elite" per la Random Forest

def trova_colonna(df, nomi_possibili):
    for nome in nomi_possibili:
        for col in df.columns:
            if nome.lower() == col.lower().strip():
                return col
    return None

def run_backtest():
    print("🚀 Avvio Backtest Professionale Oracle v2.0...")
    if not os.path.exists(CSV_PATH):
        print(f"❌ Errore: File {CSV_PATH} non trovato.")
        return

    try:
        # Carichiamo solo le colonne necessarie per risparmiare RAM
        df = pd.read_csv(CSV_PATH, low_memory=False)
    except Exception as e:
        print(f"❌ Errore lettura CSV: {e}")
        return

    # Mappatura Colonne (Basata sui tuoi dati reali)
    c_date = trova_colonna(df, ['MatchDate', 'Date'])
    c_home = trova_colonna(df, ['HomeTeam', 'Home'])
    c_away = trova_colonna(df, ['AwayTeam', 'Away'])
    c_hthg = trova_colonna(df, ['HTHome', 'HTHG'])
    c_htag = trova_colonna(df, ['HTAway', 'HTAG'])
    c_fthg = trova_colonna(df, ['FTHome', 'FTHG'])
    c_ftag = trova_colonna(df, ['FTAway', 'FTAG'])

    print(f"📊 Database caricato: {len(df)} match.")
    
    # Pulizia e Ordinamento
    df[c_date] = pd.to_datetime(df[c_date], errors='coerce')
    df = df.dropna(subset=[c_home, c_away, c_fthg, c_ftag]).sort_values(c_date)
    
    results = []
    teams_history = {}

    print(f"🛰 Analisi in corso... (Filtro: 0-0 HT + DNA >= {DNA_MINIMO})")

    # Ottimizzazione: Usiamo liste per lo storico gol
    for _, row in df.iterrows():
        h, a = row[c_home], row[c_away]
        
        # Calcolo DNA (Media gol nelle ultime 15 partite)
        def get_dna(team):
            if team not in teams_history or len(teams_history[team]) < 5: return 0
            return np.mean(teams_history[team][-15:])

        dna_h, dna_a = get_dna(h), get_dna(a)
        dna_match = (dna_h + dna_a) / 2 if (dna_h > 0 and dna_a > 0) else 0

        # --- LOGICA PROFESSIONALE ---
        # 1. Simula il radar: Entra solo se il 1° Tempo è finito 0-0
        # Questo elimina tutti i "falsi persi" dove il gol è arrivato al 5° minuto.
        is_0_0_ht = (row[c_hthg] + row[c_htag]) == 0
        
        if is_0_0_ht and dna_match >= DNA_MINIMO:
            # 2. Esito: Vinciamo se viene segnato almeno 1 gol nel 2° Tempo (Over 0.5 FT)
            vinta = (row[c_fthg] + row[c_ftag]) > 0
            
            results.append({
                'Match': f"{h}-{a}",
                'DNA': round(dna_match, 2),
                'Esito': 'VINTO' if vinta else 'PERSO',
                'Profitto': (STAKE * QUOTA_MEDIA) - STAKE if vinta else -STAKE
            })

        # Aggiornamento storico gol totali (Fatto SEMPRE per nutrire il DNA)
        gol_totali = row[c_fthg] + row[c_ftag]
        if h not in teams_history: teams_history[h] = []
        if a not in teams_history: teams_history[a] = []
        teams_history[h].append(gol_totali)
        teams_history[a].append(gol_totali)

    if not results:
        print("⚠️ Nessun segnale trovato con DNA >= 2.8. Prova ad abbassare a 2.4.")
        return

    # Calcolo Statistiche
    res_df = pd.DataFrame(results)
    v, p = len(res_df[res_df['Esito'] == 'VINTO']), len(res_df[res_df['Esito'] == 'PERSO'])
    profitto = res_df['Profitto'].sum()
    wr = (v / (v + p)) * 100
    
    print("\n" + "═"*40)
    print(f"🏆 VERDETTO FINALE ORACLE v2.0")
    print("═"*40)
    print(f"📉 Match filtrati (0-0 HT): {len(res_df)}")
    print(f"✅ Vinte: {v} | ❌ Perse: {p}")
    print(f"🔥 WIN RATE: {wr:.2f}%")
    print(f"💰 PROFITTO NETTO: {profitto:.2f}€")
    print(f"📊 ROI: {(profitto/(len(res_df)*STAKE)*100):.2f}%")
    print("═"*40)
    
    # Salvataggio per Random Forest
    res_df.to_csv('cleaned_training_data.csv', index=False)
    print("💾 Dati puliti salvati in 'cleaned_training_data.csv' per l'IA.")

if __name__ == "__main__":
    run_backtest()