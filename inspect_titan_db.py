import sqlite3
from pathlib import Path

DB_PATH = Path(r"C:\Users\Gebruiker\Desktop\Oracle Titan v5.0 - Full API Script\oracle_titan_v24_simple.db")


def fetch_one(cursor, query):
    cursor.execute(query)
    row = cursor.fetchone()
    return row[0] if row else None


def describe_table(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return cursor.fetchall()


def print_header(title):
    print("\n" + "=" * 50)
    print(title)
    print("=" * 50)


def main():
    print_header("Titan DB Inspection")
    print(f"DB path: {DB_PATH}")
    print(f"Exists: {DB_PATH.exists()}")
    if not DB_PATH.exists():
        return
    print(f"Size bytes: {DB_PATH.stat().st_size}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cur.fetchall()]
    print_header("Tables")
    for table in tables:
        print(f"- {table}")

    target_tables = [table for table in ["raw_snapshots", "signals_log", "sent_signals"] if table in tables]
    for table in target_tables:
        print_header(f"Schema: {table}")
        for cid, name, col_type, notnull, default_value, pk in describe_table(cur, table):
            print(f"{cid:02d} | {name} | {col_type} | notnull={notnull} | default={default_value} | pk={pk}")
        total_rows = fetch_one(cur, f"SELECT COUNT(*) FROM {table}")
        print(f"Rows: {total_rows}")

    if "raw_snapshots" in tables:
        print_header("raw_snapshots summary")
        queries = {
            "Total snapshots": "SELECT COUNT(*) FROM raw_snapshots",
            "Settled target_outcome 0/1": "SELECT COUNT(*) FROM raw_snapshots WHERE target_outcome IN (0,1)",
            "Pending target_outcome -1": "SELECT COUNT(*) FROM raw_snapshots WHERE target_outcome = -1",
            "Rows with odds": "SELECT COUNT(*) FROM raw_snapshots WHERE odds_live IS NOT NULL AND odds_live > 1.0",
            "Rows with shots": "SELECT COUNT(*) FROM raw_snapshots WHERE shots IS NOT NULL",
            "Rows with sot": "SELECT COUNT(*) FROM raw_snapshots WHERE sot IS NOT NULL",
            "Rows with corners": "SELECT COUNT(*) FROM raw_snapshots WHERE corners IS NOT NULL",
            "Rows with possession_diff": "SELECT COUNT(*) FROM raw_snapshots WHERE possession_diff IS NOT NULL",
            "Rows with red cards": "SELECT COUNT(*) FROM raw_snapshots WHERE rc_home IS NOT NULL AND rc_away IS NOT NULL",
            "Distinct fixtures": "SELECT COUNT(DISTINCT fixture_id) FROM raw_snapshots",
            "Distinct leagues": "SELECT COUNT(DISTINCT league) FROM raw_snapshots WHERE league IS NOT NULL AND league != ''",
            "Distinct markets": "SELECT COUNT(DISTINCT market_type) FROM raw_snapshots WHERE market_type IS NOT NULL AND market_type != ''",
        }
        for label, query in queries.items():
            print(f"{label}: {fetch_one(cur, query)}")

        print_header("raw_snapshots market breakdown")
        cur.execute("""
            SELECT market_type, COUNT(*) as n
            FROM raw_snapshots
            GROUP BY market_type
            ORDER BY n DESC
            LIMIT 10
        """)
        for market_type, n in cur.fetchall():
            print(f"{market_type}: {n}")

        print_header("raw_snapshots sample rows")
        cur.execute("""
            SELECT fixture_id, timestamp, league, dna_xg, shots, sot, da, corners,
                   possession_diff, rc_home, rc_away, minute, score_diff,
                   total_goals_at_signal, market_type, odds_live, target_outcome
            FROM raw_snapshots
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        for row in cur.fetchall():
            print(row)

    if "signals_log" in tables:
        print_header("signals_log summary")
        queries = {
            "Total signals": "SELECT COUNT(*) FROM signals_log",
            "Settled signals": "SELECT COUNT(*) FROM signals_log WHERE settled = 1",
            "Winning signals": "SELECT COUNT(*) FROM signals_log WHERE outcome = 1",
            "Losing signals": "SELECT COUNT(*) FROM signals_log WHERE outcome = 0",
            "Signals with odds": "SELECT COUNT(*) FROM signals_log WHERE odds_live IS NOT NULL AND odds_live > 1.0",
        }
        for label, query in queries.items():
            print(f"{label}: {fetch_one(cur, query)}")

    conn.close()


if __name__ == "__main__":
    main()
