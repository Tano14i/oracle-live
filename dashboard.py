import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import PERFORMANCE_STARTING_BANKROLL, QUOTA, STAKE

# --- Bot control helpers (used by the Control Room tab) ---
DATA_DIR = os.environ.get("DATA_DIR", "/data")
_CONTROL_FILE = os.path.join(DATA_DIR, "control.json")
_LOG_FILE = os.path.join(DATA_DIR, "oracle_live.log")
_BOT_PID_FILE = os.path.join(DATA_DIR, "bot.pid")


def _read_control() -> dict:
    try:
        with open(_CONTROL_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"bot_enabled": False}


def _write_control(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_CONTROL_FILE, "w") as f:
        json.dump(data, f)


def _bot_is_running() -> bool:
    try:
        with open(_BOT_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _start_bot():
    _write_control({"bot_enabled": True})


def _stop_bot():
    _write_control({"bot_enabled": False})
    try:
        with open(_BOT_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)
    except Exception:
        pass


def _read_log_tail(n: int = 100) -> str:
    if not os.path.exists(_LOG_FILE):
        return "Log file not found."
    try:
        with open(_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:
        return f"Error reading log: {e}"

TIER_KEYS = [
    ("APPROVED", "APPROVED", "#59c36a"),
    ("CAUTION", "CAUTION", "#f4c95d"),
    ("GAMBLING", "GAMBLING", "#ff7a59"),
]

FILTER_LABELS = {
    "TOP10": "Top 10 Europe",
    "SERIE_AB": "Serie A/B Top 10",
    "GLOBAL_U23": "Global U23",
    "GLOBAL_ALLIN": "Global ALL-IN",
    "Top 10 Europe": "Top 10 Europe",
    "Serie A/B Top 10": "Serie A/B Top 10",
    "Global U23": "Global U23",
    "Global ALL-IN": "Global ALL-IN",
}

MARKET_LABELS = {
    "HT_05": "OVER 0.5 HT",
    "HT_15": "OVER 1.5 HT",
    "HT_BOTH": "OVER 0.5 HT + OVER 1.5 HT",
    "NEXT_GOAL": "NEXT GOAL LIVE",
    "HT_NEXT": "HT + NEXT GOAL",
    "OVER 0.5 HT": "OVER 0.5 HT",
    "OVER 1.5 HT": "OVER 1.5 HT",
    "OVER 0.5 HT + OVER 1.5 HT": "OVER 0.5 HT + OVER 1.5 HT",
    "NEXT GOAL LIVE": "NEXT GOAL LIVE",
    "HT + NEXT GOAL": "HT + NEXT GOAL",
}

SEPARATOR = "........................................"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(BASE_DIR, "live_training_data.csv")
WEB_STATS_PATH = os.path.join(BASE_DIR, "web_stats.json")


def load_dashboard_data():
    if not os.path.exists(WEB_STATS_PATH):
        return None
    try:
        with open(WEB_STATS_PATH, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
            if not content:
                return None
            return json.loads(content)
    except Exception:
        return None


def load_training_data() -> pd.DataFrame:
    if not os.path.exists(DATASET_PATH):
        return pd.DataFrame()
    df = pd.read_csv(DATASET_PATH)
    if df.empty:
        return df
    for column in ["OpenTimeUTC", "SettledTimeUTC"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)
    numeric_columns = [
        "Prob",
        "DNA",
        "Minute",
        "AvgTotalGoals",
        "AvgHTGoals",
        "HomeAvgTotalGoals",
        "AwayAvgTotalGoals",
        "HomeAvgHTGoals",
        "AwayAvgHTGoals",
        "ShotsOnGoalAtOpen",
        "TotalShotsAtOpen",
        "CornersAtOpen",
        "RedCardsAtOpen",
        "TitanPressureScore",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["Market", "Tier", "Outcome", "FilterMode", "LeagueName", "SignalKey", "Status"]:
        if column in df.columns:
            df[column] = df[column].fillna("").astype(str)
    return df


def build_dataset_view(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    defaults = {
        "LeagueName": "Unknown league",
        "FilterMode": "Unknown filter",
        "Market": "Unknown market",
        "Tier": "UNKNOWN",
        "SignalKey": "Unknown signal",
    }
    for column, default in defaults.items():
        if column not in view.columns:
            view[column] = default
        view[column] = view[column].replace({"": default}).fillna(default)
    if "Outcome" not in view.columns:
        view["Outcome"] = "PENDING"
    view["DisplayOutcome"] = view["Outcome"].replace({"": "PENDING"}).fillna("PENDING")
    if "OpenTimeUTC" in view.columns:
        view["DisplayTime"] = view["OpenTimeUTC"].dt.strftime("%d %b %H:%M").fillna("-")
    else:
        view["DisplayTime"] = "-"
    view["LeagueDisplay"] = view["LeagueName"]
    view["FilterDisplay"] = view["FilterMode"].map(lambda value: FILTER_LABELS.get(value, value))
    view["MarketDisplay"] = view["Market"].map(lambda value: MARKET_LABELS.get(value, value))
    view["ProbDisplay"] = view["Prob"].apply(lambda value: f"{value * 100:.1f}%" if pd.notna(value) else "-") if "Prob" in view.columns else "-"
    view["DNADisplay"] = view["DNA"].apply(lambda value: f"{value:.2f}" if pd.notna(value) else "-") if "DNA" in view.columns else "-"
    return view


def apply_period_filter(df: pd.DataFrame, period_label: str) -> pd.DataFrame:
    if df.empty or "OpenTimeUTC" not in df.columns or period_label == "All time":
        return df.copy()
    today = pd.Timestamp.now(tz="UTC").normalize()
    if period_label == "Today":
        cutoff = today
    elif period_label == "Last 7 days":
        cutoff = today - pd.Timedelta(days=7)
    elif period_label == "Last 30 days":
        cutoff = today - pd.Timedelta(days=30)
    else:
        return df.copy()
    return df[df["OpenTimeUTC"] >= cutoff].copy()


def build_filtered_dataset(df: pd.DataFrame):
    if df.empty:
        return df, {"period": "All time", "markets": [], "tiers": [], "outcomes": [], "filters": [], "league_search": ""}

    st.markdown("### Filters")
    st.caption("I filtri sono dentro la pagina così restano visibili anche da telefono.")

    with st.expander("Open dashboard filters", expanded=True):
        row1 = st.columns(2)
        row2 = st.columns(2)
        row3 = st.columns(2)

        period_label = row1[0].selectbox("Period", ["All time", "Today", "Last 7 days", "Last 30 days"], index=0)
        filtered = apply_period_filter(df, period_label)

        market_options = sorted(value for value in filtered["MarketDisplay"].dropna().unique().tolist() if str(value).strip())
        selected_markets = row1[1].multiselect("Market", market_options, default=market_options)
        if selected_markets:
            filtered = filtered[filtered["MarketDisplay"].isin(selected_markets)]

        tier_options = [value for value in ["APPROVED", "CAUTION", "GAMBLING"] if value in filtered["Tier"].unique().tolist()]
        selected_tiers = row2[0].multiselect("Tier", tier_options, default=tier_options)
        if selected_tiers:
            filtered = filtered[filtered["Tier"].isin(selected_tiers)]

        outcome_options = [value for value in ["WIN", "LOSS", "PENDING"] if value in filtered["DisplayOutcome"].unique().tolist()]
        selected_outcomes = row2[1].multiselect("Outcome", outcome_options, default=outcome_options)
        if selected_outcomes:
            filtered = filtered[filtered["DisplayOutcome"].isin(selected_outcomes)]

        filter_options = sorted(value for value in filtered["FilterDisplay"].dropna().unique().tolist() if str(value).strip())
        selected_filters = row3[0].multiselect("Bot Filter", filter_options, default=filter_options)
        if selected_filters:
            filtered = filtered[filtered["FilterDisplay"].isin(selected_filters)]

        league_search = row3[1].text_input("League contains", value="").strip().lower()
        if league_search:
            filtered = filtered[filtered["LeagueDisplay"].str.lower().str.contains(league_search, na=False)]

        st.caption(f"Rows visible: {len(filtered)} | Raw rows loaded: {len(df)}")

    active_filters = {
        "period": period_label,
        "markets": selected_markets,
        "tiers": selected_tiers,
        "outcomes": selected_outcomes,
        "filters": selected_filters,
        "league_search": league_search,
    }
    return filtered, active_filters


def build_kpi_card(label, value, sublabel="", tone="neutral"):
    tone_map = {
        "positive": ("#11281b", "#78e08f", "#c8ffd6"),
        "negative": ("#2c1212", "#ff6b6b", "#ffd0d0"),
        "neutral": ("#151a24", "#6ea8fe", "#edf4ff"),
        "gold": ("#2a2110", "#f4c95d", "#fff3d1"),
    }
    bg, border, text = tone_map.get(tone, tone_map["neutral"])
    return f"""
    <div style="background:{bg};border:1px solid {border};border-radius:18px;padding:18px 20px;min-height:118px;box-shadow:0 18px 40px rgba(0,0,0,0.18);">
        <div style="font-size:12px; letter-spacing:0.12em; text-transform:uppercase; color:{border};">{label}</div>
        <div style="font-size:34px; font-weight:800; color:{text}; margin-top:8px; line-height:1.05;">{value}</div>
        <div style="font-size:13px; color:#d9e2f2; margin-top:10px;">{sublabel}</div>
    </div>
    """


def build_signal_badge(text, background, foreground):
    return f"""
    <span style="display:inline-block;padding:4px 10px;border-radius:999px;background:{background};color:{foreground};font-size:12px;font-weight:700;letter-spacing:0.04em;">{text}</span>
    """


def render_signal_card(row):
    outcome = str(row.get("DisplayOutcome", "PENDING"))
    tier = str(row.get("Tier", "-"))
    market = str(row.get("MarketDisplay", "-"))
    if outcome == "WIN":
        outcome_badge = build_signal_badge("WIN", "#17351f", "#8ef0a7")
    elif outcome == "LOSS":
        outcome_badge = build_signal_badge("LOSS", "#371919", "#ff9f9f")
    else:
        outcome_badge = build_signal_badge("PENDING", "#3b3013", "#ffd978")
    tier_colors = {
        "APPROVED": ("#17351f", "#8ef0a7"),
        "CAUTION": ("#3a3118", "#ffd978"),
        "GAMBLING": ("#3a1d15", "#ffad8f"),
    }
    tier_bg, tier_fg = tier_colors.get(tier, ("#19202a", "#dfe8f8"))
    tier_badge = build_signal_badge(tier, tier_bg, tier_fg)
    return f"""
    <div style="background:linear-gradient(180deg, rgba(22,28,39,0.98), rgba(12,16,24,0.98));border:1px solid rgba(110,168,254,0.18);border-radius:18px;padding:16px 18px;margin-bottom:12px;box-shadow:0 14px 35px rgba(0,0,0,0.18);">
        <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">
            <div>
                <div style="font-size:12px; color:#8da2c0; text-transform:uppercase; letter-spacing:0.10em;">{row.get('DisplayTime', '-')} | {row.get('LeagueDisplay', '-')}</div>
                <div style="font-size:20px; color:#f4f7fb; font-weight:800; margin-top:6px; line-height:1.1;">{row.get('SignalKey', '-')}</div>
                <div style="font-size:13px; color:#9eb0c9; margin-top:8px;">Market: {market} | DNA: {row.get('DNADisplay', '-')} | Model: {row.get('ProbDisplay', '-')}</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end;">{tier_badge}{outcome_badge}</div>
        </div>
    </div>
    """


def compute_profit_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    working = df.copy()
    working["profit_eur"] = 0.0
    working.loc[working["DisplayOutcome"] == "WIN", "profit_eur"] = (QUOTA - 1) * STAKE
    working.loc[working["DisplayOutcome"] == "LOSS", "profit_eur"] = -STAKE
    return working


def market_results_frame(df: pd.DataFrame):
    if df.empty:
        return pd.DataFrame(columns=["Market", "WIN", "LOSS", "WR%", "P/L EUR", "Settled"])
    settled = df[df["DisplayOutcome"].isin(["WIN", "LOSS"])].copy()
    rows = []
    for market_name, part in settled.groupby("MarketDisplay"):
        wins = int((part["DisplayOutcome"] == "WIN").sum())
        losses = int((part["DisplayOutcome"] == "LOSS").sum())
        settled_count = wins + losses
        win_rate = (wins / settled_count * 100) if settled_count else 0.0
        rows.append({"Market": market_name, "WIN": wins, "LOSS": losses, "WR%": round(win_rate, 1), "P/L EUR": round(float(part["profit_eur"].sum()), 2), "Settled": settled_count})
    rows.sort(key=lambda item: (-item["Settled"], item["Market"]))
    return pd.DataFrame(rows)


def top_items_as_frame(df: pd.DataFrame, column: str, label: str, limit=6):
    if df.empty or column not in df.columns:
        return pd.DataFrame(columns=[label, "Count"])
    counts = df[df[column].astype(str).str.strip() != ""].groupby(column).size().sort_values(ascending=False).head(limit).reset_index(name="Count")
    return counts.rename(columns={column: label})


def render_screenshot_mode(filtered_df, settled_df, profit_value, profit_tone, win_count, loss_count, win_rate, signals_count, roi_value):
    st.markdown("## Screenshot Mode")
    st.caption("Compact layout for social posts, stories and Telegram promo screenshots.")
    a, b, c, d = st.columns(4)
    with a:
        st.markdown(build_kpi_card("P/L", f"{profit_value:+.2f} EUR", f"{win_count} WIN | {loss_count} LOSS", profit_tone), unsafe_allow_html=True)
    with b:
        st.markdown(build_kpi_card("Win Rate", f"{win_rate:.1f}%", f"{len(settled_df)} settled", "gold"), unsafe_allow_html=True)
    with c:
        st.markdown(build_kpi_card("ROI", f"{roi_value:+.1f}%", f"{len(settled_df)} settled", "gold"), unsafe_allow_html=True)
    with d:
        st.markdown(build_kpi_card("Visible Signals", f"{signals_count}", "Filtered rows", "neutral"), unsafe_allow_html=True)

    recent_col, proof_col = st.columns([1.35, 1.0], gap="large")
    with recent_col:
        st.subheader("Recent Proof")
        if not filtered_df.empty:
            recent_df = filtered_df.sort_values("OpenTimeUTC", ascending=False) if "OpenTimeUTC" in filtered_df.columns else filtered_df
            for _, row in recent_df.head(4).iterrows():
                st.markdown(render_signal_card(row), unsafe_allow_html=True)
        else:
            st.info("No visible signals with the current filters.")
    with proof_col:
        st.subheader("Market Snapshot")
        by_market = market_results_frame(filtered_df)
        st.dataframe(by_market.head(5), use_container_width=True, hide_index=True) if not by_market.empty else st.info("No market snapshot available.")
        st.subheader("League Snapshot")
        top_leagues = top_items_as_frame(filtered_df, "LeagueDisplay", "League", 5)
        st.dataframe(top_leagues, use_container_width=True, hide_index=True) if not top_leagues.empty else st.info("No league snapshot available.")


st.set_page_config(page_title="Oracle AI Control Room", layout="wide", page_icon="OR", initial_sidebar_state="collapsed")
st.markdown("""
<style>
.stApp {background:radial-gradient(circle at top left, rgba(34, 55, 94, 0.45), transparent 28%),radial-gradient(circle at top right, rgba(27, 83, 67, 0.26), transparent 24%),linear-gradient(180deg, #07111c 0%, #0d1725 45%, #0a1320 100%);} 
.main .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1320px;} 
h1, h2, h3 {letter-spacing: -0.02em;} 
div[data-testid="stDataFrame"], div[data-testid="stTable"] {border-radius: 18px; overflow: hidden;}
</style>
""", unsafe_allow_html=True)

# ── Control Room (always visible) ────────────────────────────────────────────
st.subheader("Bot Control Room")
_running = _bot_is_running()
_status_color = "#78e08f" if _running else "#ff6b6b"
_status_text = "RUNNING" if _running else "STOPPED"
st.markdown(
    f'<div style="display:inline-block;padding:6px 18px;border-radius:999px;'
    f'background:{"#11281b" if _running else "#2c1212"};'
    f'border:1px solid {_status_color};color:{_status_color};font-weight:700;'
    f'letter-spacing:0.08em;font-size:15px;">Bot: {_status_text}</div>',
    unsafe_allow_html=True,
)
st.write("")
_col1, _col2, _col3 = st.columns([1, 1, 2])
with _col1:
    if st.button("Start Bot", type="primary", disabled=_running):
        _start_bot()
        st.rerun()
with _col2:
    if st.button("Stop Bot", type="secondary", disabled=not _running):
        _stop_bot()
        st.rerun()
with _col3:
    if st.button("Refresh status"):
        st.rerun()

with st.expander("Live Log (last 150 lines)", expanded=False):
    st.code(_read_log_tail(150), language="text")

st.divider()

data = load_dashboard_data()
if not data:
    st.info("Bot non ancora avviato o nessun segnale ancora generato.")
    st.stop()

raw_df = load_training_data()
view_df = build_dataset_view(raw_df)
filtered_df, active_filters = build_filtered_dataset(view_df)
filtered_df = compute_profit_columns(filtered_df)
settled_df = filtered_df[filtered_df["DisplayOutcome"].isin(["WIN", "LOSS"])].copy() if not filtered_df.empty else filtered_df

filter_mode = data.get("filter_mode", "TOP10")
market_mode = data.get("market_mode", "HT_BOTH")
current_profit = float(data.get("total_profit", 0.0) or 0.0)
profit_value = float(settled_df["profit_eur"].sum()) if not settled_df.empty else 0.0
profit_tone = "positive" if profit_value >= 0 else "negative"
settled_count = len(settled_df)
win_count = int((settled_df["DisplayOutcome"] == "WIN").sum()) if not settled_df.empty else 0
loss_count = int((settled_df["DisplayOutcome"] == "LOSS").sum()) if not settled_df.empty else 0
win_rate = (win_count / settled_count * 100) if settled_count else 0.0
signals_count = len(filtered_df)
risked_amount = settled_count * STAKE
roi_value = (profit_value / risked_amount * 100) if risked_amount else 0.0
active_market_text = ", ".join(active_filters.get("markets", [])[:3]) if active_filters.get("markets") else "All"
if len(active_filters.get("markets", [])) > 3:
    active_market_text += f" +{len(active_filters.get('markets', [])) - 3}"
active_filter_text = ", ".join(active_filters.get("filters", [])[:3]) if active_filters.get("filters") else "All"
if len(active_filters.get("filters", [])) > 3:
    active_filter_text += f" +{len(active_filters.get('filters', [])) - 3}"
screenshot_mode = st.toggle("Screenshot mode", value=False, help="Compact social layout for mobile screenshots and promo posts.")

st.markdown(f"""
<div style="background:linear-gradient(135deg, rgba(19,30,49,0.96), rgba(10,17,28,0.96));border:1px solid rgba(126, 158, 204, 0.18);border-radius:24px;padding:24px 28px;margin-bottom:20px;box-shadow:0 24px 60px rgba(0,0,0,0.22);">
<div style="font-size:12px; letter-spacing:0.16em; text-transform:uppercase; color:#8ea8cf;">Oracle Live Showcase</div>
<div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-end; margin-top:10px; flex-wrap:wrap;">
<div>
<div style="font-size:44px; line-height:1.0; font-weight:900; color:#f5f7fb;">Performance Control Room</div>
<div style="font-size:15px; color:#9db0ca; margin-top:10px;">Current bot mode: <b>{FILTER_LABELS.get(filter_mode, filter_mode)}</b> | Current market: <b>{MARKET_LABELS.get(market_mode, market_mode)}</b> | Global tracker: <b>{current_profit:+.2f} EUR</b></div>
</div>
<div style="text-align:right;"><div style="font-size:12px; color:#8ea8cf; text-transform:uppercase; letter-spacing:0.14em;">Filtered social snapshot</div><div style="font-size:18px; font-weight:700; color:#e9eef8; margin-top:8px;">Market, period, tier and outcome driven showcase</div></div>
</div></div>
""", unsafe_allow_html=True)

st.caption(f"Active filters | Period: {active_filters.get('period', 'All time')} | Markets: {active_market_text} | Bot filters: {active_filter_text} | Visible rows: {signals_count}")
if filtered_df.empty and not view_df.empty:
    st.warning("I filtri attuali stanno nascondendo tutti i dati. Usa All time e lascia tutti i market selezionati per vedere lo storico completo.")

if screenshot_mode:
    render_screenshot_mode(filtered_df, settled_df, profit_value, profit_tone, win_count, loss_count, win_rate, signals_count, roi_value)
    st.caption(f"Screenshot mode | {SEPARATOR} | Current bot mode {FILTER_LABELS.get(filter_mode, filter_mode)} | Current market {MARKET_LABELS.get(market_mode, market_mode)}")
    st.stop()

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(build_kpi_card("Filtered P/L", f"{profit_value:+.2f} EUR", f"{win_count} WIN | {loss_count} LOSS", profit_tone), unsafe_allow_html=True)
with k2:
    st.markdown(build_kpi_card("Filtered Win Rate", f"{win_rate:.1f}%", f"{settled_count} settled signals", "gold"), unsafe_allow_html=True)
with k3:
    st.markdown(build_kpi_card("Filtered ROI", f"{roi_value:+.1f}%", f"{settled_count} settled signals", "gold"), unsafe_allow_html=True)
with k4:
    st.markdown(build_kpi_card("Visible Signals", f"{signals_count}", "Rows after filters", "neutral"), unsafe_allow_html=True)
with k5:
    st.markdown(build_kpi_card("Global Tracker", f"{current_profit:+.2f} EUR", f"Starting bankroll {PERFORMANCE_STARTING_BANKROLL:.0f} EUR", "neutral"), unsafe_allow_html=True)

left, right = st.columns([1.55, 1.0], gap="large")
with left:
    st.subheader("Equity Curve")
    if not settled_df.empty and "OpenTimeUTC" in settled_df.columns:
        curve_df = settled_df.sort_values("OpenTimeUTC").copy()
        curve_df["cum_profit"] = curve_df["profit_eur"].cumsum()
        curve_df["point_label"] = curve_df["OpenTimeUTC"].dt.strftime("%d %b %H:%M")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve_df["point_label"], y=curve_df["cum_profit"], mode="lines", line=dict(color="#74c0fc" if profit_value >= 0 else "#ff8787", width=4), fill="tozeroy", fillcolor="rgba(116, 192, 252, 0.16)" if profit_value >= 0 else "rgba(255, 135, 135, 0.14)", hovertemplate="%{x}<br>Cumulative %{y:.2f} EUR<extra></extra>"))
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(showgrid=False, color="#9fb0c9"), yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)", color="#9fb0c9"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun dato settled disponibile con i filtri scelti.")
    st.subheader("Recent Signals Feed")
    if not filtered_df.empty:
        recent_df = filtered_df.sort_values("OpenTimeUTC", ascending=False) if "OpenTimeUTC" in filtered_df.columns else filtered_df
        for _, row in recent_df.head(8).iterrows():
            st.markdown(render_signal_card(row), unsafe_allow_html=True)
    else:
        st.info("Nessun segnale visibile con i filtri scelti.")
with right:
    st.subheader("Tier Mix")
    if not filtered_df.empty:
        tier_rows = [{"Tier": label, "Count": int((filtered_df["Tier"] == key).sum()), "Color": color} for key, label, color in TIER_KEYS]
        df_tiers = pd.DataFrame(tier_rows)
        if df_tiers["Count"].sum() > 0:
            fig_tier = go.Figure(data=[go.Pie(labels=df_tiers["Tier"], values=df_tiers["Count"], hole=0.62, marker=dict(colors=df_tiers["Color"]), textinfo="label+percent", textfont=dict(color="#ecf2fb", size=12))])
            fig_tier.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", annotations=[dict(text=f"{signals_count}<br>signals", x=0.5, y=0.5, showarrow=False, font=dict(size=20, color="#f4f7fb"))])
            st.plotly_chart(fig_tier, use_container_width=True)
        else:
            st.info("Nessun segnale disponibile con i filtri scelti.")
    else:
        st.info("Nessun segnale disponibile con i filtri scelti.")
    st.subheader("By Market")
    df_market_results = market_results_frame(filtered_df)
    st.dataframe(df_market_results, use_container_width=True, hide_index=True) if not df_market_results.empty else st.info("Nessun market disponibile con i filtri scelti.")
    st.subheader("Top Leagues")
    df_leagues = top_items_as_frame(filtered_df, "LeagueDisplay", "League", 6)
    if not df_leagues.empty:
        fig_leagues = px.bar(df_leagues.sort_values("Count", ascending=True), x="Count", y="League", orientation="h", color_discrete_sequence=["#6ea8fe"])
        fig_leagues.update_layout(height=280, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)", color="#9fb0c9"), yaxis=dict(showgrid=False, color="#dce6f6"))
        st.plotly_chart(fig_leagues, use_container_width=True)
    else:
        st.info("Nessuna league disponibile con i filtri scelti.")

st.subheader("Social Proof Table")
if not filtered_df.empty:
    visible_columns = [column for column in ["DisplayTime", "LeagueDisplay", "FilterDisplay", "MarketDisplay", "DNADisplay", "Tier", "ProbDisplay", "DisplayOutcome"] if column in filtered_df.columns]
    export_df = filtered_df.sort_values("OpenTimeUTC", ascending=False) if "OpenTimeUTC" in filtered_df.columns else filtered_df
    st.dataframe(export_df[visible_columns], use_container_width=True, hide_index=True)
else:
    st.info("Nessun feed segnali disponibile con i filtri scelti.")

st.caption(f"Snapshot live | {SEPARATOR} | Current bot mode {FILTER_LABELS.get(filter_mode, filter_mode)} | Current market {MARKET_LABELS.get(market_mode, market_mode)}")
