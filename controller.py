import pandas as pd

df = pd.read_csv('Matches.csv')
print(f"🏟️ Partite totali nel database: {len(df)}")
print(f"📅 Prima partita: {df['MatchDate'].min()}")
print(f"📅 Ultima partita: {df['MatchDate'].max()}")

# Vediamo quali sono i campionati più presenti (top 10 squadre per match)
print("\n🔥 Top 10 Squadre per numero di dati:")
print(df['HomeTeam'].value_counts().head(10))