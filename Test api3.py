"""
test_api3.py - Verifica disponibilita odds per fascia temporale
Esegui nella cartella del progetto:
    python test_api3.py
"""
import requests
from config import API_KEY

headers = {"x-apisports-key": API_KEY}

# Trova partita con statistiche disponibili
r = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"live": "all"}, timeout=20)
data = r.json().get("response", [])
print(f"Partite live: {len(data)}")

found_fixture = None
for m in data:
    fixture_id = m["fixture"]["id"]
    country = m["league"].get("country", "")
    league = m["league"].get("name", "")
    minute = m["fixture"]["status"].get("elapsed", 0) or 0

    r2 = requests.get(
        "https://v3.football.api-sports.io/fixtures/statistics",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=10,
    )
    stats = r2.json().get("response", [])
    if not stats:
        continue

    home = m["teams"]["home"]["name"]
    away = m["teams"]["away"]["name"]
    print(f"\nPartita trovata: {home} vs {away} ({country}) min {minute}'")
    print(f"fixture_id: {fixture_id}")

    # Mostra goalkeeper saves e shots insidebox
    for team_stats in stats:
        team_name = team_stats.get("team", {}).get("name", "?")
        for stat in team_stats.get("statistics", []):
            if stat["type"] in ["Goalkeeper Saves", "Shots insidebox", "expected_goals", "Shots on Goal"]:
                print(f"  [{team_name}] {stat['type']}: {stat['value']}")

    found_fixture = fixture_id

    # Test bet ID per fascia temporale
    print("\n--- TEST ODDS FASCIA TEMPORALE ---")
    bet_ids_to_test = [
        (261, "Over/Under 00-10 min"),
        (263, "Over/Under 10-20 min"),
        (262, "Over/Under 20-30 min"),
        (258, "Over/Under 30-40 min"),
        (257, "Over/Under 40-50 min"),
        (65,  "Next 10 Minutes Total"),
        (116, "Action In Next 1 Minute"),
        (117, "First Action In Next 5 Minutes"),
        (73,  "Which team scores 1st goal"),
        (149, "Total Shots"),
        (150, "Total Shots on Goal"),
    ]

    for bet_id, bet_name in bet_ids_to_test:
        r3 = requests.get(
            "https://v3.football.api-sports.io/odds/live",
            headers=headers,
            params={"fixture": fixture_id, "bet": bet_id},
            timeout=10,
        )
        odds_data = r3.json().get("response", [])
        if odds_data:
            print(f"\n  BET ID {bet_id} ({bet_name}): DISPONIBILE")
            for item in odds_data[:1]:
                for bm in item.get("bookmakers", [])[:2]:
                    print(f"    Bookmaker: {bm.get('name')}")
                    for bet in bm.get("bets", [])[:1]:
                        for v in bet.get("values", [])[:4]:
                            print(f"      {v.get('value')}: {v.get('odd')}")
        else:
            print(f"  BET ID {bet_id} ({bet_name}): non disponibile")

    break

if not found_fixture:
    print("\nNessuna partita con statistiche trovata.")
    print("Riprova durante una sessione con partite di campionati maggiori.")