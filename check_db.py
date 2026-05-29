import pandas as pd

df = pd.read_csv('Matches.csv')
print(f"📊 Totale match nel DB: {len(df)}")
print("\n🔍 Ultime 5 squadre aggiunte (Internazionali):")
print(df['HomeTeam'].tail(5).unique())

# Vediamo se trova una squadra famosa
test_team = "Italy"
count = len(df[(df['HomeTeam'] == test_team) | (df['AwayTeam'] == test_team)])
print(f"\n🇮🇹 Match trovati per '{test_team}': {count}")