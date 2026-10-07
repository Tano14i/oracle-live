import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(ENV_PATH)


def get_setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def resolve_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(BASE_DIR / path)


TOKEN_LIVE = get_setting("TOKEN_LIVE")
CHAT_ID = get_setting("CHAT_ID")
CHANNEL_ID = get_setting("CHANNEL_ID")
API_KEY = get_setting("API_KEY")
VIP_CHANNEL_ID = get_setting("VIP_CHANNEL_ID")
VIP_SUPPORT_CONTACT = get_setting("VIP_SUPPORT_CONTACT", "@your_support")

CSV_PATH = resolve_path(get_setting("CSV_PATH", "Matches.csv"))
MODEL_PATH = resolve_path(get_setting("MODEL_PATH", "oracle_brain.pkl"))
WEB_DATA_PATH = resolve_path(get_setting("WEB_DATA_PATH", "web_stats.json"))
MEMBERS_DB_PATH = resolve_path(get_setting("MEMBERS_DB_PATH", "vip_members.db"))
LOG_FILE_PATH = resolve_path(get_setting("LOG_FILE_PATH", "oracle_live.log"))

STAKE = float(get_setting("STAKE", "10.0") or "10.0")
QUOTA = float(get_setting("QUOTA", "1.75") or "1.75")

# Quote medie reali per market: usate per P/L, ROI e breakeven onesti.
# Solo fallback: quando il book espone la quota live si usa quella (OpenOdd).
# Valori rilevati dal vivo sul mercato "Over/Under (1st Half)" linea 0.5:
# 1.40-1.53 al minuto 1-5, 1.57-1.73 al 18-21, 2.10 al 28.
QUOTA_O05_HT = float(get_setting("QUOTA_O05_HT", "1.45") or "1.45")
QUOTA_O15_HT = float(get_setting("QUOTA_O15_HT", "1.50") or "1.50")
# Quote di fallback, usate per il P/L quando il book non espone la quota live.
#
# Regola: mai sopra la mediana misurata. Un fallback generoso non rende il bot
# piu' redditizio, rende il report una bugia. QUOTA_NEXT_GOAL valeva 1.75 (il
# QUOTA generico) contro una mediana reale di 1.04 su 39 segnali prezzati: il
# report per market mostrava +59.9% di ROI su un market che misura -3.9%.
#
# Mediane misurate il 01/10/2026: OVER 0.5 HT 1.50 (n=61), NEXT GOAL 1.04
# (n=39), OVER 1.5 HT 2.10 (n=6). I fallback di OVER 0.5 e OVER 1.5 restano
# sotto la mediana, quindi prudenti.
QUOTA_NEXT_GOAL = float(get_setting("QUOTA_NEXT_GOAL", "1.04") or "1.04")

# Filtro quote: quota live minima per pubblicare un segnale.
# Sotto questi valori il segnale non copre il proprio breakeven e viene scartato.
# NEXT GOAL sul mercato reale paga 1.02-1.13 contro un WR del 62.8%: con questa
# soglia si spegne da solo, che e' l'esito voluto finche' non ritrova valore.
MIN_ODD_O05_HT = float(get_setting("MIN_ODD_O05_HT", "1.40") or "1.40")
MIN_ODD_O15_HT = float(get_setting("MIN_ODD_O15_HT", "1.60") or "1.60")
MIN_ODD_NEXT_GOAL = float(get_setting("MIN_ODD_NEXT_GOAL", "1.60") or "1.60")
# Scarta anche i segnali per cui la quota non e' recuperabile.
# Default 1: con 0 il filtro era di fatto inerte, perche' la quota non e' quasi
# mai disponibile sui campionati che il filtro predilige - su 12 segnali
# pubblicati in una giornata, zero avevano un prezzo registrato, e nessun
# ODDS_GATE_SKIP e' mai scattato. Senza sapere a che quota si entra non si puo'
# valutare se la giocata abbia senso.
# Minuto prima del quale OVER 0.5 HT non apre nulla.
#
# Il book pubblica il mercato in-play intorno al minuto 3-10. Misurato sui
# segnali storici, la quota risulta nota nel 4.8% dei casi aprendo al minuto
# 1-2 e nel 48.5% aprendo al 9-12: dieci volte piu' spesso. Il valore atteso
# non cambia (quota mediana meno breakeven: -0.09 al minuto 1-2, -0.08 al 9-12),
# quindi non si perde niente e si guadagna un prezzo su cui decidere.
MIN_OPEN_MINUTE_O05_HT = int(get_setting("MIN_OPEN_MINUTE_O05_HT", "9") or "9")

# Osservatore del 47': manda il segnale con le statistiche al solo canale
# admin e registra snapshot ed esito in second_half_log.csv. Non pubblica su
# free/VIP: il tasso base misurato e' 74,2% (pareggio 1,348) contro quote
# offerte di 1,08-1,15, cioe' una perdita del 18% per scommessa.
SECOND_HALF_OBSERVER = get_setting("SECOND_HALF_OBSERVER", "1").lower() in {"1", "true", "yes"}
# Campionamento deliberato delle quote lunghe.
#
# Le regole di ritmo selezionano partite da gol, quindi il bot non vede mai la
# fascia di quota 1.60-2.50. E' l'unica cella del dataset con segno positivo
# (3 segnali, ROI +79%) e l'unica dove la teoria dice che il margine del book
# pesa meno: a n=3 non prova niente, e senza campionarla non lo prova mai.
#
# Apre solo shadow, mai pubblicato: compra informazione senza rischiare.
LONG_ODDS_SAMPLING = get_setting("LONG_ODDS_SAMPLING", "1").lower() in {"1", "true", "yes"}
LONG_ODDS_MIN = float(get_setting("LONG_ODDS_MIN", "1.60") or "1.60")
LONG_ODDS_MAX = float(get_setting("LONG_ODDS_MAX", "2.50") or "2.50")
LONG_ODDS_PER_SCAN = int(get_setting("LONG_ODDS_PER_SCAN", "2") or "2")


ODDS_GATE_STRICT = get_setting("ODDS_GATE_STRICT", "0").lower() in {"1", "true", "yes"}

# Finestra HT estesa oltre il minuto 20 sotto forte pressione live.
# Tenere spenta finche' l'analisi shadow (analyze_shadow_signals.py) non conferma WR >= 60%.
HT_PRESSURE_WINDOW_ENABLED = get_setting("HT_PRESSURE_WINDOW_ENABLED", "0").lower() in {"1", "true", "yes"}
HT_PRESSURE_WINDOW_MAX_MINUTE = int(get_setting("HT_PRESSURE_WINDOW_MAX_MINUTE", "28") or "28")
VIP_PRICE_XTR = int(get_setting("VIP_PRICE_XTR", "499") or "499")
VIP_DURATION_DAYS = int(get_setting("VIP_DURATION_DAYS", "30") or "30")
FREE_DELAY_SECONDS = int(get_setting("FREE_DELAY_SECONDS", "180") or "180")
FREE_EVERY_N_APPROVED = int(get_setting("FREE_EVERY_N_APPROVED", "3") or "3")
RECAP_HOUR_UTC = int(get_setting("RECAP_HOUR_UTC", "21") or "21")
RECAP_MINUTE_UTC = int(get_setting("RECAP_MINUTE_UTC", "0") or "0")
RENEWAL_REMINDER_DAYS = int(get_setting("RENEWAL_REMINDER_DAYS", "3") or "3")

REPORT_EVERY_N_SETTLED = int(get_setting("REPORT_EVERY_N_SETTLED", "10") or "10")
REPORT_MIN_SETTLED = int(get_setting("REPORT_MIN_SETTLED", "20") or "20")
PERFORMANCE_STAKE_EXAMPLE = float(get_setting("PERFORMANCE_STAKE_EXAMPLE", "100") or "100")
PERFORMANCE_STARTING_BANKROLL = float(get_setting("PERFORMANCE_STARTING_BANKROLL", "1000") or "1000")
AUTO_RETRAIN_EVERY_N_SETTLED = int(get_setting("AUTO_RETRAIN_EVERY_N_SETTLED", "50") or "50")
LIVE_TRAINING_DATA_PATH = resolve_path(get_setting("LIVE_TRAINING_DATA_PATH", "live_training_data.csv"))
MISSING_TEAMS_QUEUE_PATH = resolve_path(get_setting("MISSING_TEAMS_QUEUE_PATH", "missing_teams_queue.json"))

# Storico quote live: ogni lettura riuscita, anche quando il segnale non parte.
# Serve a misurare l'EV per minuto: il log registrava solo fallimenti e scarti
# del filtro, cioe' un campione sbilanciato verso le quote basse.
ODDS_HISTORY_PATH = resolve_path(get_setting("ODDS_HISTORY_PATH", "odds_history.csv"))
ODDS_HISTORY_ENABLED = (get_setting("ODDS_HISTORY_ENABLED", "1") or "1").strip() not in {"0", "false", "False", ""}






