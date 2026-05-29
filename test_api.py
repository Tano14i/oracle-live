import requests
from config import API_KEY

headers = {"x-apisports-key": API_KEY}

# Vediamo cosa c'e live adesso
r = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"live": "all"}, timeout=20)
data = r.json().get("response", [])
print(f"Partite live ora: {len(data)}")

if not data:
    print("Nessuna partita live in questo momento. Riprova durante una sessione di partite.")
else:
    m = data[0]
    fixture_id = m["fixture"]["id"]
    home = m["teams"]["home"]["name"]
    away = m["teams"]["away"]["name"]
    print(f"Esempio fixture_id: {fixture_id}")
    print(f"Match: {home} vs {away}")
    print(f"Score: {m['goals']}")
    print(f"Status: {m['fixture']['status']}")

    # Statistiche live
    r2 = requests.get(
        "https://v3.football.api-sports.io/fixtures/statistics",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=20,
    )
    stats = r2.json().get("response", [])
    if stats:
        print(f"\nStatistiche disponibili:")
        for stat in stats[0].get("statistics", []):
            print(f"  {stat['type']}: {stat['value']}")
    else:
        print("\nNessuna statistica live disponibile per questo match.")

    # Events (gol, cartellini, sostituzioni)
    r4 = requests.get(
        "https://v3.football.api-sports.io/fixtures/events",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=20,
    )
    events = r4.json().get("response", [])
    print(f"\nEventi disponibili: {len(events)}")
    for ev in events[:8]:
        print(f"  {ev.get('time', {}).get('elapsed', '?')}' {ev.get('type', '?')} — {ev.get('detail', '?')} ({ev.get('team', {}).get('name', '?')})")

    # Odds live
    r3 = requests.get(
        "https://v3.football.api-sports.io/odds/live",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=20,
    )
    odds_data = r3.json().get("response", [])
    print(f"\nOdds live: {len(odds_data)} risultati")
    if odds_data:
        for item in odds_data[:1]:
            for bm in item.get("bookmakers", [])[:3]:
                print(f"  Bookmaker: {bm.get('name', '-')}")
                for bet in bm.get("bets", [])[:8]:
                    print(f"    [{bet.get('id')}] {bet['name']} -> {bet['values'][:3]}")
    else:
        print("Nessuna quota live disponibile per questo match.")

    # Odds live bets disponibili (catalogo)
    r5 = requests.get(
        "https://v3.football.api-sports.io/odds/live/bets",
        headers=headers,
        timeout=20,
    )
    bets_catalog = r5.json().get("response", [])
    print(f"\nCatalogo bet live disponibili ({len(bets_catalog)} tipi):")
    for b in bets_catalog[:20]:
        print(f"  ID {b.get('id')}: {b.get('name')}")