import csv, collections, math, sys
from datetime import datetime

PATH = r"C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live\second_half_log.csv"

with open(PATH, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"Righe totali: {len(rows)}")
print(f"RowType presente: {'RowType' in rows[0]}")

def row_priority(r):
    rt = r.get("RowType", "")
    if rt == "backfill": return 3
    if rt == "settle":   return 2
    if rt == "open":     return 1
    if r.get("Outcome") and r.get("GoalMinute"): return 3
    if r.get("Outcome"): return 2
    return 1

by_fid = collections.defaultdict(list)
for r in rows:
    by_fid[r["FixtureId"]].append(r)

deduped = [max(g, key=row_priority) for g in by_fid.values()]
print(f"Fixture unici: {len(deduped)}")

con_esito = [r for r in deduped if r.get("Outcome") in ("WIN", "LOSS")]
print(f"Con esito: {len(con_esito)}")

def wilson(w, n):
    if n == 0: return 0.0, 0.0
    z = 1.96
    p = w / n
    centre = (p + z*z/(2*n)) / (1 + z*z/n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return centre - margin, centre + margin

wins = sum(1 for r in con_esito if r["Outcome"] == "WIN")
n_tot = len(con_esito)
wr = wins / n_tot
lo, hi = wilson(wins, n_tot)
print(f"\n=== TOTALE ===")
print(f"WIN {wins}  LOSS {n_tot - wins}  WR {wr:.1%}  CI95[{lo:.1%},{hi:.1%}]")
print(f"Breakeven quota: {1/wr:.3f}")

# Per settimana
by_week = collections.defaultdict(lambda: [0, 0])
for r in con_esito:
    try:
        dt = datetime.fromisoformat(r["ObservedAtUTC"])
        week = dt.strftime("%Y-W%V")
    except Exception:
        week = "?"
    by_week[week][0 if r["Outcome"] == "WIN" else 1] += 1

print(f"\n=== PER SETTIMANA ===")
for w in sorted(by_week):
    ww, ll = by_week[w]
    nn = ww + ll
    lo_w, hi_w = wilson(ww, nn)
    print(f"  {w}:  {ww:3d}W {ll:3d}L  WR {ww/nn:.0%}  CI[{lo_w:.0%},{hi_w:.0%}]  n={nn}")

# Per fascia LiveOdd
print(f"\n=== PER FASCIA LiveOdd ===")
con_odd = [r for r in con_esito if r.get("LiveOdd")]
try:
    for r in con_odd:
        r["_odd"] = float(r["LiveOdd"])
except Exception:
    pass

fasce = [(1.0, 1.2, "1.10-1.20"),
         (1.2, 1.3, "1.20-1.30"),
         (1.3, 1.5, "1.30-1.50"),
         (1.5, 2.0, "1.50-2.00"),
         (2.0, 99,  "2.00+    ")]
for lo_q, hi_q, label in fasce:
    sub = [r for r in con_odd if lo_q <= r["_odd"] < hi_q]
    if not sub:
        continue
    w = sum(1 for r in sub if r["Outcome"] == "WIN")
    n = len(sub)
    wr_f = w / n
    avg_odd = sum(r["_odd"] for r in sub) / n
    ev = wr_f * avg_odd - 1
    be = 1 / wr_f if wr_f > 0 else 999
    lo_c, hi_c = wilson(w, n)
    print(f"  {label}: {w:3d}W/{n-w:3d}L  WR {wr_f:.1%}  CI[{lo_c:.1%},{hi_c:.1%}]  "
          f"avgQ {avg_odd:.3f}  EV {ev:+.2%}  BE {be:.3f}  n={n}")

# Per ModelP
con_p = [r for r in con_esito if r.get("ModelP") not in (None, "")]
if con_p:
    print(f"\n=== PER ModelP (n={len(con_p)}) ===")
    sys.path.insert(0, r"C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live")
    try:
        import modello_2t
        modello_2t.carica()
        soglia = modello_2t.soglia_decile_alto()
        print(f"Soglia decile alto: {soglia:.4f}")
        sopra = [r for r in con_p if float(r["ModelP"]) >= soglia]
        sotto = [r for r in con_p if float(r["ModelP"]) < soglia]
        for label, grp in [("sopra soglia (decile 10)", sopra),
                            ("sotto soglia             ", sotto)]:
            if not grp:
                continue
            w = sum(1 for r in grp if r["Outcome"] == "WIN")
            n = len(grp)
            lo_c, hi_c = wilson(w, n)
            print(f"  {label}: {w:3d}W/{n-w:3d}L  WR {w/n:.1%}  CI[{lo_c:.1%},{hi_c:.1%}]  n={n}")
    except Exception as e:
        print(f"  (errore modello: {e})")

# Per giorno della settimana
print(f"\n=== PER GIORNO DELLA SETTIMANA ===")
by_dow = collections.defaultdict(lambda: [0, 0])
dow_names = ["Lun","Mar","Mer","Gio","Ven","Sab","Dom"]
for r in con_esito:
    try:
        dt = datetime.fromisoformat(r["ObservedAtUTC"])
        dow = dt.weekday()
    except Exception:
        continue
    by_dow[dow][0 if r["Outcome"] == "WIN" else 1] += 1
for d in range(7):
    if d not in by_dow:
        continue
    ww, ll = by_dow[d]
    nn = ww + ll
    print(f"  {dow_names[d]}: {ww:3d}W {ll:3d}L  WR {ww/nn:.0%}  n={nn}")

# Ultimo: quante partite hanno ModelP vs non
n_con_p = len(con_p)
n_senza_p = len(con_esito) - n_con_p
print(f"\n=== COPERTURA ModelP ===")
print(f"  Con ModelP:  {n_con_p}  ({n_con_p/len(con_esito):.0%})")
print(f"  Senza ModelP: {n_senza_p}  ({n_senza_p/len(con_esito):.0%})")
