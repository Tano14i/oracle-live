import requests
from config import API_KEY

headers = {"x-apisports-key": API_KEY}

# Catalogo completo bet live — cerchiamo ID utili
r = requests.get("https://v3.football.api-sports.io/odds/live/bets", headers=headers, timeout=20)
bets_catalog = r.json().get("response", [])

# Parole chiave che ci interessano
keywords = ["next", "goal", "over", "under", "score", "corner", "shot", "first", "1st", "half"]

print("=== BET LIVE RILEVANTI ===")
for b in bets_catalog:
    name = b.get("name", "").lower()
    if any(k in name for k in keywords):
        print(f"  ID {b.get('id'):3d}: {b.get('name')}")

# Cerca una partita con statistiche disponibili
print("\n=== CERCA PARTITA CON DATI ===")
r2 = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"live": "all"}, timeout=20)
data = r2.json().get("response", [])
print(f"Partite live: {len(data)}")

found = None
for m in data:
    fixture_id = m["fixture"]["id"]
    country = m["league"].get("country", "")
    league = m["league"].get("name", "")
    home = m["teams"]["home"]["name"]
    away = m["teams"]["away"]["name"]
    minute = m["fixture"]["status"].get("elapsed", 0) or 0

    # Prova statistiche
    r3 = requests.get(
        "https://v3.football.api-sports.io/fixtures/statistics",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=10,
    )
    stats = r3.json().get("response", [])
    if not stats:
        continue

    # Prova odds live
    r4 = requests.get(
        "https://v3.football.api-sports.io/odds/live",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=10,
    )
    odds = r4.json().get("response", [])

    print(f"\n✅ TROVATA: {home} vs {away} ({country} — {league}) minuto {minute}'")
    print(f"   fixture_id: {fixture_id}")
    print(f"   Score: {m['goals']}")
    print(f"   Statistiche: {len(stats)} squadre")

    # Mostra tutte le stat disponibili
    for team_stats in stats:
        team_name = team_stats.get("team", {}).get("name", "?")
        print(f"   [{team_name}]")
        for stat in team_stats.get("statistics", []):
            print(f"     {stat['type']}: {stat['value']}")

    print(f"\n   Odds live: {len(odds)} risultati")
    if odds:
        for item in odds[:1]:
            for bm in item.get("bookmakers", [])[:2]:
                print(f"   Bookmaker: {bm.get('name')}")
                for bet in bm.get("bets", []):
                    print(f"     [ID {bet.get('id')}] {bet['name']}")
                    for v in bet.get("values", [])[:4]:
                        print(f"       {v.get('value')}: {v.get('odd')} (main={v.get('main')})")

    found = fixture_id
    break

if not found:
    print("\nNessuna partita con statistiche live trovata in questo momento.")
    print("Riprova durante una sessione con partite di campionati maggiori (sera europea).")