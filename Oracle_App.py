import json
import os

import pandas as pd
import streamlit as st

from config import CHAT_ID, MODEL_PATH


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_STATS_PATH = os.path.join(BASE_DIR, "web_stats.json")
TRAINING_DATA_PATH = os.path.join(BASE_DIR, "live_training_data.csv")
SNIPER_STATE_PATH = os.path.join(BASE_DIR, "oracle_sniper_state.json")
SNIPER_JOURNAL_PATH = os.path.join(BASE_DIR, "oracle_sniper_journal.csv")
SNIPER_LOG_PATH = os.path.join(BASE_DIR, "oracle_sniper.log")

APP_TITLE = "Oracle One"
APP_SUBTITLE = "Private live trading cockpit for Oracle Live, Premium flow and Oracle Sniper"
NAV_ITEMS = ["Overview", "Signals", "Sniper", "ML", "Runtime"]


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_training_data() -> pd.DataFrame:
    df = load_csv(TRAINING_DATA_PATH)
    if df.empty:
        return df
    for column in ["OpenTimeUTC", "SettledTimeUTC"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)
    numeric_columns = [
        "Prob",
        "DNA",
        "Minute",
        "TotalGoalsAtOpen",
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
    for column in ["Tier", "Market", "LeagueName", "Country", "Reason", "Outcome", "SignalKey", "Status"]:
        if column in df.columns:
            df[column] = df[column].fillna("").astype(str)
    return df


def load_sniper_journal() -> pd.DataFrame:
    df = load_csv(SNIPER_JOURNAL_PATH)
    if df.empty:
        return df
    if "TimestampUTC" in df.columns:
        df["TimestampUTC"] = pd.to_datetime(df["TimestampUTC"], errors="coerce", utc=True)
    return df


def format_timestamp(value) -> str:
    if pd.isna(value):
        return "-"
    try:
        return value.tz_convert("Europe/Rome").strftime("%d %b %H:%M")
    except Exception:
        return str(value)


def build_metric_card(label: str, value: str, hint: str = "") -> str:
    return f"""
    <div style="padding:20px 22px;border-radius:22px;background:
        radial-gradient(circle at top right, rgba(231,184,92,0.08), transparent 24%),
        linear-gradient(180deg,#131b29,#0d141d);border:1px solid rgba(255,255,255,0.08);
        box-shadow:0 20px 45px rgba(0,0,0,0.22);min-height:126px;">
        <div style="font-size:11px;color:#9cb2cf;text-transform:uppercase;letter-spacing:0.16em;font-weight:700;">{label}</div>
        <div style="font-size:40px;font-weight:900;color:#f7f4ee;margin-top:12px;line-height:0.98;">{value}</div>
        <div style="font-size:13px;color:#b7c7dd;margin-top:12px;line-height:1.45;">{hint}</div>
    </div>
    """


def build_section_card(title: str, body: str) -> str:
    return f"""
    <div style="padding:20px 22px;border-radius:22px;background:
        linear-gradient(180deg,#121927,#0c121a);border:1px solid rgba(255,255,255,0.07);
        box-shadow:0 16px 36px rgba(0,0,0,0.18);margin-bottom:14px;">
        <div style="font-size:12px;color:#f1c768;text-transform:uppercase;letter-spacing:0.16em;font-weight:800;">{title}</div>
        <div style="font-size:14px;color:#dde7f4;margin-top:12px;line-height:1.65;">{body}</div>
    </div>
    """


def build_filter_hint(text: str) -> str:
    return f"""
    <div style="padding:12px 14px;border-radius:16px;background:
        linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.025));
        border:1px solid rgba(255,255,255,0.06);font-size:12px;color:#c7d4e7;line-height:1.55;margin-bottom:12px;">
        {text}
    </div>
    """


def build_badge(text: str, kind: str = "neutral") -> str:
    palette = {
        "approved": ("rgba(32,92,57,0.95)", "#8ff0af"),
        "caution": ("rgba(120,92,28,0.95)", "#ffd978"),
        "learning": ("rgba(39,70,110,0.95)", "#9fccff"),
        "gambling": ("rgba(120,48,35,0.95)", "#ffb199"),
        "win": ("rgba(32,92,57,0.95)", "#8ff0af"),
        "loss": ("rgba(124,41,41,0.95)", "#ffb3b3"),
        "pending": ("rgba(61,67,78,0.95)", "#d8e3f2"),
        "premium": ("rgba(129,100,24,0.95)", "#ffe39a"),
        "sniper": ("rgba(91,42,108,0.95)", "#f0b7ff"),
        "neutral": ("rgba(44,52,66,0.95)", "#d8e3f2"),
    }
    bg, fg = palette.get(kind, palette["neutral"])
    return f"<span style='display:inline-block;padding:5px 11px;border-radius:999px;background:{bg};color:{fg};font-size:10px;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;'>{text}</span>"


def get_tier_badge(tier: str) -> str:
    mapping = {
        "APPROVED": "approved",
        "CAUTION": "caution",
        "LEARNING": "learning",
        "GAMBLING": "gambling",
    }
    return build_badge(tier or "-", mapping.get(tier or "", "neutral"))


def get_outcome_badge(outcome: str) -> str:
    mapping = {
        "WIN": "win",
        "LOSS": "loss",
        "PENDING": "pending",
    }
    return build_badge(outcome or "-", mapping.get(outcome or "", "neutral"))


def get_feed_title(view_name: str) -> str:
    titles = {
        "Overview": "Command Center",
        "Signals": "Signal Feed",
        "Sniper": "Sniper Feed",
        "ML": "Model Lab",
        "Runtime": "Runtime Console",
    }
    return titles.get(view_name, view_name)


def build_signal_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    if "OpenTimeUTC" in view.columns:
        view["Time"] = view["OpenTimeUTC"].apply(format_timestamp)
    else:
        view["Time"] = "-"
    if "Prob" in view.columns:
        view["Model"] = view["Prob"].apply(lambda value: f"{value:.2f}" if pd.notna(value) else "-")
    else:
        view["Model"] = "-"
    if "DNA" in view.columns:
        view["DNAx"] = view["DNA"].apply(lambda value: f"{value:.2f}" if pd.notna(value) else "-")
    else:
        view["DNAx"] = "-"
    if "Minute" in view.columns:
        view["MinuteLive"] = view["Minute"].apply(lambda value: int(value) if pd.notna(value) else "-")
    else:
        view["MinuteLive"] = "-"
    columns = [
        "Time",
        "Country",
        "LeagueName",
        "Market",
        "Tier",
        "MinuteLive",
        "DNAx",
        "Model",
        "Outcome",
        "Reason",
    ]
    available = [column for column in columns if column in view.columns]
    return view[available].sort_index(ascending=False)


def normalize_outcome(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "PENDING"}:
        return "PENDING"
    if text in {"WIN", "LOSS"}:
        return text
    return text


def compute_signal_priority(row: pd.Series) -> float:
    score = 0.0
    tier = str(row.get("Tier", "") or "")
    market = str(row.get("Market", "") or "")
    outcome = normalize_outcome(row.get("Outcome", ""))
    prob = float(row.get("Prob")) if pd.notna(row.get("Prob")) else 0.0
    dna = float(row.get("DNA")) if pd.notna(row.get("DNA")) else 0.0
    minute = float(row.get("Minute")) if pd.notna(row.get("Minute")) else 0.0
    reason = str(row.get("Reason", "") or "").lower()

    score += {"APPROVED": 28, "CAUTION": 18, "LEARNING": 8, "GAMBLING": -8}.get(tier, 0)
    score += {"NEXT GOAL LIVE": 8, "OVER 0.5 HT": 6, "OVER 1.5 HT": 4}.get(market, 0)
    score += prob * 55
    score += min(10, max(0, (dna - 1.4) * 4))
    if 15 <= minute <= 35:
        score += 9
    elif minute <= 5:
        score -= 6
    if "premium" in reason:
        score += 12
    if "sniper" in reason:
        score += 10
    if "titan pressure alert" in reason:
        score -= 10
    if outcome == "PENDING":
        score += 6
    return round(score, 2)


def classify_signal_score(score: float) -> tuple[str, str]:
    if score >= 78:
        return "Elite", "premium"
    if score >= 62:
        return "Strong", "approved"
    if score >= 48:
        return "Watch", "caution"
    return "Low", "neutral"


def time_group_label(value) -> str:
    if pd.isna(value):
        return "Unknown"
    try:
        now = pd.Timestamp.now(tz="UTC")
        diff_minutes = int((now - value).total_seconds() // 60)
    except Exception:
        return "Unknown"
    if diff_minutes <= 5:
        return "Now"
    if diff_minutes <= 30:
        return "Last 30 min"
    if diff_minutes <= 180:
        return "Last 3h"
    return "Earlier"


def prepare_signal_feed(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    view = df.copy()
    if "OpenTimeUTC" in view.columns:
        view = view.sort_values("OpenTimeUTC", ascending=False)
        view["TimeGroup"] = view["OpenTimeUTC"].apply(time_group_label)
    else:
        view["TimeGroup"] = "Unknown"
    view["NormalizedOutcome"] = view["Outcome"].apply(normalize_outcome) if "Outcome" in view.columns else "PENDING"
    view["PriorityScore"] = view.apply(compute_signal_priority, axis=1)
    view["IsPremiumLike"] = view["Reason"].str.contains("premium", case=False, na=False) | view["Tier"].eq("APPROVED")
    view["IsSniperLike"] = view["Reason"].str.contains("sniper", case=False, na=False)
    return view


def render_signal_cards(df: pd.DataFrame, limit: int, show_time_groups: bool = False) -> None:
    if df.empty:
        st.info("No signals match these filters.")
        return
    view = df.copy().head(limit)
    last_group = None
    for _, row in view.iterrows():
        current_group = row.get("TimeGroup", "Unknown")
        if show_time_groups and current_group != last_group:
            st.markdown(f"#### {current_group}")
            last_group = current_group
        time_label = format_timestamp(row.get("OpenTimeUTC")) if "OpenTimeUTC" in view.columns else "-"
        model = f"{row.get('Prob', 0):.2f}" if pd.notna(row.get("Prob")) else "-"
        dna = f"{row.get('DNA', 0):.2f}" if pd.notna(row.get("DNA")) else "-"
        minute = int(row.get("Minute")) if pd.notna(row.get("Minute")) else "-"
        tier = row.get("Tier", "-") or "-"
        outcome = normalize_outcome(row.get("Outcome", "-"))
        market = row.get("Market", "-") or "-"
        reason = row.get("Reason", "-") or "-"
        score_value = float(row.get("PriorityScore", 0.0) or 0.0)
        score_label, score_kind = classify_signal_score(score_value)
        badges = f"{get_tier_badge(tier)} {get_outcome_badge(outcome)}"
        if "premium" in reason.lower():
            badges += f" {build_badge('Premium', 'premium')}"
        if "sniper" in reason.lower():
            badges += f" {build_badge('Sniper', 'sniper')}"
        badges += f" {build_badge(score_label, score_kind)}"
        body = (
            f"<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:10px;'>"
            f"<div>"
            f"<div style='font-size:18px;font-weight:800;color:#f5f7fb;'>{row.get('LeagueName', '-')}</div>"
            f"<div style='font-size:13px;color:#8ea5c5;margin-top:4px;'>{row.get('Country', '-')} | {time_label}</div>"
            f"</div>"
            f"<div style='text-align:right;'>{badges}</div>"
            f"</div>"
            f"<div style='margin-top:14px;font-size:15px;color:#ffffff;font-weight:700;'>{market}</div>"
            f"<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px;'>"
            f"<div><div style='font-size:11px;color:#8aa1c1;text-transform:uppercase;'>Minute</div><div style='font-size:19px;color:#f5f7fb;font-weight:800;'>{minute}</div></div>"
            f"<div><div style='font-size:11px;color:#8aa1c1;text-transform:uppercase;'>DNA</div><div style='font-size:19px;color:#f5f7fb;font-weight:800;'>{dna}</div></div>"
            f"<div><div style='font-size:11px;color:#8aa1c1;text-transform:uppercase;'>Model</div><div style='font-size:19px;color:#f5f7fb;font-weight:800;'>{model}</div></div>"
            f"</div>"
            f"<div style='margin-top:10px;font-size:12px;color:#8aa1c1;text-transform:uppercase;'>Signal Score</div>"
            f"<div style='font-size:24px;color:#f5f7fb;font-weight:900;'>{score_value:.0f}/100</div>"
            f"<div style='margin-top:14px;padding:12px 14px;border-radius:14px;background:rgba(255,255,255,0.04);font-size:13px;color:#d8e3f2;'>{reason}</div>"
        )
        st.markdown(build_section_card("Signal", body), unsafe_allow_html=True)


def render_feed_block(title: str, df: pd.DataFrame, limit: int, empty_text: str) -> None:
    st.markdown(f"### {title}")
    if df.empty:
        st.info(empty_text)
        return
    render_signal_cards(df, limit, show_time_groups=True)


def render_top_pick(df: pd.DataFrame) -> None:
    st.markdown("### Top Pick Now")
    if df.empty:
        st.info("No live top pick available right now.")
        return
    top = df.sort_values("PriorityScore", ascending=False).head(1)
    render_signal_cards(top, 1, show_time_groups=False)


def render_header() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(
        """
        <style>
        :root {
            --bg-1: #07121b;
            --bg-2: #0c1622;
            --panel: #111a27;
            --panel-soft: #0e1722;
            --text: #f7f4ee;
            --muted: #afbdd0;
            --accent: #e7b85c;
            --accent-soft: #86b9ff;
            --success: #8ff0af;
            --danger: #ffb0a8;
        }
        .stApp { background:
            radial-gradient(circle at top left, rgba(43,92,138,0.32), transparent 28%),
            radial-gradient(circle at top right, rgba(231,184,92,0.16), transparent 22%),
            linear-gradient(180deg, var(--bg-1) 0%, #08131f 100%);
        }
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1450px; }
        h1, h2, h3 { color: var(--text) !important; letter-spacing: -0.02em; }
        .stMarkdown, p, label, div { color: var(--text); }
        [data-testid="stMetricValue"] { color: var(--text); font-weight: 800; }
        [data-testid="stMetricLabel"] { color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
        [data-testid="stSidebar"] {
            background:
                radial-gradient(circle at top, rgba(231,184,92,0.10), transparent 18%),
                linear-gradient(180deg, #0b1018 0%, #0f1724 100%);
            border-right: 1px solid rgba(255,255,255,0.05);
        }
        [data-testid="stSidebar"] * { color: var(--text) !important; }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {
            color: var(--muted) !important;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 14px;
            padding: 10px 12px;
            margin-bottom: 8px;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] {
            background: rgba(231,184,92,0.10);
            border-color: rgba(231,184,92,0.35);
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] div:first-child {
            transform: scale(0.9);
        }
        .stToggle label, .stSelectbox label, .stSlider label {
            font-size: 0.92rem !important;
            font-weight: 600 !important;
            color: var(--muted) !important;
        }
        .stSelectbox > div > div, .stSlider > div, .stTextInput > div > div {
            background: rgba(255,255,255,0.03);
            border-radius: 14px;
        }
        .stDataFrame, [data-testid="stTable"] {
            border-radius: 18px;
            overflow: hidden;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 0.25rem; overflow-x: auto; }
        .stTabs [data-baseweb="tab"] { white-space: nowrap; }
        .oracle-topbar {
            padding: 24px 26px;
            border-radius: 28px;
            background:
                radial-gradient(circle at top right, rgba(231,184,92,0.22), transparent 24%),
                radial-gradient(circle at bottom left, rgba(65,114,168,0.16), transparent 28%),
                linear-gradient(135deg, rgba(15,23,36,0.98), rgba(11,17,25,0.98));
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 26px 60px rgba(0,0,0,0.28);
            margin-bottom: 18px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="oracle-topbar">
            <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
                <div>
                    <div style="font-size:12px;color:#8fb0d8;letter-spacing:0.18em;text-transform:uppercase;font-weight:800;">Oracle Mobile</div>
                    <div style="font-size:46px;font-weight:900;color:#f7f4ee;line-height:1.00;margin-top:8px;">{APP_TITLE}</div>
                    <div style="font-size:15px;color:#d8e2ef;margin-top:10px;max-width:760px;line-height:1.5;">{APP_SUBTITLE}</div>
                </div>
                <div style="text-align:right;">
                    {build_badge("Private", "premium")}
                    <div style="font-size:12px;color:#8aa1c1;margin-top:12px;">Owner {CHAT_ID}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(f"## {APP_TITLE}")
    st.sidebar.caption("Private mobile command app")
    selected_view = st.sidebar.radio("Navigate", NAV_ITEMS, index=0)
    compact_mode = st.sidebar.toggle("Compact layout", value=True)
    signal_card_mode = st.sidebar.toggle("Card feed", value=True)
    st.sidebar.markdown(
        build_section_card(
            "Status",
            f"<b>Owner:</b> {CHAT_ID}<br><b>Production model:</b> {'Online' if os.path.exists(MODEL_PATH) else 'Missing'}<br><b>Access:</b> Private only"
        ),
        unsafe_allow_html=True,
    )
    return selected_view, compact_mode, signal_card_mode


def render_view_header(selected_view: str, compact_mode: bool) -> None:
    subtitle_map = {
        "Overview": "High-level view of bankroll, signal quality and overall engine health.",
        "Signals": "Priority feed with segmented views for live, premium and settled signals.",
        "Sniper": "Separate speculative stream with dedicated limits, stops and journal.",
        "ML": "Dataset maturity, feature coverage and production model readiness.",
        "Runtime": "Internal runtime snapshot for modes, routing and latest raw payloads.",
    }
    compact_text = "Compact layout" if compact_mode else "Expanded layout"
    st.markdown(
        build_section_card(
            get_feed_title(selected_view),
            f"{subtitle_map.get(selected_view, '-')}"
            f"<br><br>{build_badge(compact_text, 'neutral')}"
        ),
        unsafe_allow_html=True,
    )


def render_overview(web_stats: dict, training_df: pd.DataFrame, sniper_state: dict, sniper_journal: pd.DataFrame) -> None:
    total_profit = float(web_stats.get("total_profit", 0.0) or 0.0)
    matches_analyzed = int(web_stats.get("matches_analyzed", 0) or 0)
    settled_df = training_df[training_df.get("Outcome", "").isin(["WIN", "LOSS"])] if not training_df.empty and "Outcome" in training_df.columns else pd.DataFrame()
    settled_total = len(settled_df)
    wins = int((settled_df["Outcome"] == "WIN").sum()) if not settled_df.empty else 0
    win_rate = (wins / settled_total * 100.0) if settled_total else 0.0
    sniper_daily = int(sniper_state.get("daily_signals", 0) or 0)

    top_row = st.columns(2)
    top_row[0].markdown(build_metric_card("Total Profit", f"{total_profit:.2f} EUR", "Net performance of the main Oracle engine"), unsafe_allow_html=True)
    top_row[1].markdown(build_metric_card("Settled Signals", str(settled_total), f"Confirmed win rate {win_rate:.1f}%"), unsafe_allow_html=True)

    second_row = st.columns(2)
    second_row[0].markdown(build_metric_card("Matches Analyzed", str(matches_analyzed), "Live fixture scans processed by the engine"), unsafe_allow_html=True)
    second_row[1].markdown(build_metric_card("Sniper Today", str(sniper_daily), "Speculative sniper entries opened today"), unsafe_allow_html=True)

    st.markdown("### Performance Curve")
    history = web_stats.get("profit_history", [])
    history_df = pd.DataFrame(history)
    if not history_df.empty and {"time", "profit"}.issubset(history_df.columns):
        history_df["profit"] = pd.to_numeric(history_df["profit"], errors="coerce")
        history_df["step"] = range(1, len(history_df) + 1)
        st.line_chart(history_df.set_index("step")["profit"], height=260)
    else:
        st.info("Performance history is not available yet.")

    daily_units = float(sniper_state.get("daily_units", 0.0) or 0.0)
    streak = int(sniper_state.get("consecutive_losses", 0) or 0)
    open_positions = sniper_state.get("open_positions", {}) or {}
    status_cols = st.columns(3)
    status_cols[0].metric("Daily Units", f"{daily_units:.1f}u")
    status_cols[1].metric("Loss Streak", str(streak))
    status_cols[2].metric("Open Sniper Positions", str(len(open_positions)))
    if not sniper_journal.empty and "Event" in sniper_journal.columns:
        last_event = sniper_journal.iloc[-1]
        st.caption(f"Latest sniper event: {last_event.get('Event', '-')} | {last_event.get('Market', '-')}")


def render_live_signals(training_df: pd.DataFrame, signal_card_mode: bool) -> None:
    st.markdown("### Signal Feed")
    if training_df.empty:
        st.info("No live training rows found.")
        return

    st.markdown(build_filter_hint("Clean the feed with a few quick switches. On mobile, start with Pending + Last 3 Hours + Approved for the clearest operational view."), unsafe_allow_html=True)

    st.markdown("#### Feed Filters")
    filters_top = st.columns(2)
    market_options = sorted([item for item in training_df["Market"].dropna().unique().tolist() if item])
    selected_market = filters_top[0].selectbox("Market Type", ["All markets"] + market_options, index=0)
    tier_options = sorted([item for item in training_df["Tier"].dropna().unique().tolist() if item])
    selected_tier = filters_top[1].selectbox("Signal Tier", ["All tiers"] + tier_options, index=0)

    filters_bottom = st.columns(2)
    outcome_options = sorted([item for item in training_df["Outcome"].dropna().unique().tolist() if item])
    selected_outcome = filters_bottom[0].selectbox("Signal Status", ["All statuses"] + outcome_options, index=0)
    limit = filters_bottom[1].slider("Cards to show", min_value=10, max_value=150, value=30, step=10)

    st.markdown("#### Quick Shortcuts")
    quick_filters = st.columns(2)
    live_only = quick_filters[0].toggle("Only Pending Live Signals", value=False)
    recent_only = quick_filters[1].toggle("Only Last 3 Hours", value=True)

    quick_filters = st.columns(2)
    approved_only = quick_filters[0].toggle("Only Approved", value=False)
    premium_only = quick_filters[1].toggle("Only Premium Style", value=False)

    quick_filters = st.columns(2)
    sniper_only = quick_filters[0].toggle("Only Sniper Style", value=False)
    signal_card_mode = quick_filters[1].toggle("Use Signal Cards", value=signal_card_mode)

    filtered = training_df.copy()
    if selected_market != "All markets":
        filtered = filtered[filtered["Market"] == selected_market]
    if selected_tier != "All tiers":
        filtered = filtered[filtered["Tier"] == selected_tier]
    if selected_outcome != "All statuses":
        filtered = filtered[filtered["Outcome"] == selected_outcome]
    if live_only:
        filtered = filtered[filtered["Outcome"].fillna("").isin(["", "PENDING"])]
    if "OpenTimeUTC" in filtered.columns:
        filtered = filtered.sort_values("OpenTimeUTC", ascending=False)
        if recent_only:
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3)
            filtered = filtered[filtered["OpenTimeUTC"] >= cutoff]

    feed = prepare_signal_feed(filtered)
    if approved_only:
        feed = feed[feed["Tier"] == "APPROVED"]
    if premium_only:
        feed = feed[feed["IsPremiumLike"]]
    if sniper_only:
        feed = feed[feed["IsSniperLike"]]

    signal_counts = st.columns(3)
    signal_counts[0].metric("Visible", str(len(feed.head(limit))))
    signal_counts[1].metric("Pending", str(int(feed["NormalizedOutcome"].eq("PENDING").sum())) if not feed.empty else "0")
    signal_counts[2].metric("Approved", str(int(feed["Tier"].eq("APPROVED").sum())) if not feed.empty else "0")

    secondary_counts = st.columns(3)
    secondary_counts[0].metric("Premium", str(int(feed["IsPremiumLike"].sum())) if not feed.empty else "0")
    secondary_counts[1].metric("Sniper", str(int(feed["IsSniperLike"].sum())) if not feed.empty else "0")
    secondary_counts[2].metric("Avg Score", f"{feed['PriorityScore'].mean():.0f}" if not feed.empty else "0")

    active_filters = []
    if selected_market != "All markets":
        active_filters.append(build_badge(selected_market, "neutral"))
    if selected_tier != "All tiers":
        active_filters.append(build_badge(selected_tier, "neutral"))
    if selected_outcome != "All statuses":
        active_filters.append(build_badge(selected_outcome, "neutral"))
    if live_only:
        active_filters.append(build_badge("Pending", "pending"))
    if recent_only:
        active_filters.append(build_badge("Last 3h", "neutral"))
    if approved_only:
        active_filters.append(build_badge("Approved", "approved"))
    if premium_only:
        active_filters.append(build_badge("Premium", "premium"))
    if sniper_only:
        active_filters.append(build_badge("Sniper", "sniper"))
    if active_filters:
        st.markdown("#### Active Filters")
        st.markdown(" ".join(active_filters), unsafe_allow_html=True)

    pending_feed = feed[feed["NormalizedOutcome"] == "PENDING"].sort_values("PriorityScore", ascending=False)
    premium_feed = feed[feed["IsPremiumLike"]].sort_values("PriorityScore", ascending=False)
    settled_feed = feed[feed["NormalizedOutcome"].isin(["WIN", "LOSS"])].sort_values("OpenTimeUTC", ascending=False)

    if signal_card_mode:
        render_top_pick(pending_feed)
        render_feed_block("Pending Live", pending_feed, min(limit, 12), "No pending live signals in this view.")
        render_feed_block("Premium Focus", premium_feed, min(limit, 8), "No premium-grade signals in this view.")
        render_feed_block("Recently Settled", settled_feed, min(limit, 8), "No recently settled signals in this view.")
    else:
        st.dataframe(build_signal_table(feed.head(limit)), use_container_width=True, hide_index=True)


def render_sniper(sniper_state: dict, sniper_journal: pd.DataFrame) -> None:
    st.markdown("### Oracle Sniper")
    state_cols = st.columns(2)
    state_cols[0].metric("Date", sniper_state.get("date_utc", "-"))
    state_cols[1].metric("Daily Signals", int(sniper_state.get("daily_signals", 0) or 0))
    state_cols = st.columns(2)
    state_cols[0].metric("Daily Units", f"{float(sniper_state.get('daily_units', 0.0) or 0.0):.1f}u")
    state_cols[1].metric("Consecutive Losses", int(sniper_state.get("consecutive_losses", 0) or 0))

    open_positions = sniper_state.get("open_positions", {}) or {}
    if open_positions:
        st.markdown("#### Open Positions")
        open_df = pd.DataFrame(list(open_positions.values()))
        if "sniper_score" in open_df.columns:
            open_df["sniper_score"] = open_df["sniper_score"].map(lambda value: f"{value:.2f}")
        st.dataframe(open_df, use_container_width=True, hide_index=True)
    else:
        st.info("No open sniper positions right now.")

    st.markdown("#### Journal")
    if sniper_journal.empty:
        st.info("Sniper journal not created yet.")
    else:
        journal_view = sniper_journal.copy()
        if "TimestampUTC" in journal_view.columns:
            journal_view["TimestampUTC"] = journal_view["TimestampUTC"].apply(format_timestamp)
        st.dataframe(journal_view.sort_index(ascending=False), use_container_width=True, hide_index=True)

    st.markdown("#### Local Files")
    st.code(
        "\n".join(
            [
                SNIPER_STATE_PATH,
                SNIPER_JOURNAL_PATH,
                SNIPER_LOG_PATH,
            ]
        )
    )


def render_ml_status(training_df: pd.DataFrame) -> None:
    st.markdown("### Model Status")
    total_rows = len(training_df)
    settled_df = training_df[training_df.get("Outcome", "").isin(["WIN", "LOSS"])] if not training_df.empty and "Outcome" in training_df.columns else pd.DataFrame()
    full_feature_df = training_df.dropna(
        subset=[
            column
            for column in [
                "DNA",
                "Minute",
                "TotalGoalsAtOpen",
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
            if column in training_df.columns
        ]
    ) if not training_df.empty else pd.DataFrame()
    full_feature_settled = full_feature_df[full_feature_df.get("Outcome", "").isin(["WIN", "LOSS"])] if not full_feature_df.empty and "Outcome" in full_feature_df.columns else pd.DataFrame()

    row = st.columns(2)
    row[0].metric("Total Rows", str(total_rows))
    row[1].metric("Settled Rows", str(len(settled_df)))
    row = st.columns(2)
    row[0].metric("Full-Feature Rows", str(len(full_feature_df)))
    row[1].metric("Full-Feature Settled", str(len(full_feature_settled)))

    coverage_rows = []
    for column in [
        "DNA",
        "Minute",
        "TotalGoalsAtOpen",
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
    ]:
        if column in training_df.columns and total_rows:
            pct = training_df[column].notna().mean() * 100.0
            coverage_rows.append({"Feature": column, "Coverage %": round(pct, 1)})
    if coverage_rows:
        st.dataframe(pd.DataFrame(coverage_rows), use_container_width=True, hide_index=True)

    model_exists = os.path.exists(MODEL_PATH)
    st.caption(f"Production model path: {MODEL_PATH} | Present: {'YES' if model_exists else 'NO'}")


def render_runtime_panel(web_stats: dict) -> None:
    st.markdown("### Runtime Snapshot")
    filter_mode = web_stats.get("filter_mode", "-")
    market_mode = web_stats.get("market_mode", "-")
    recent = web_stats.get("recent_signals", []) or []
    stats_cols = st.columns(2)
    stats_cols[0].metric("Owner Chat ID", str(CHAT_ID))
    stats_cols[1].metric("Filter Mode", str(filter_mode))
    st.metric("Market Mode", str(market_mode))
    if recent:
        st.json(recent[:5], expanded=False)
    else:
        st.info("No recent signals stored in runtime state.")


def main() -> None:
    selected_view, compact_mode, signal_card_mode = render_header()
    web_stats = load_json(WEB_STATS_PATH)
    training_df = load_training_data()
    sniper_state = load_json(SNIPER_STATE_PATH)
    sniper_journal = load_sniper_journal()

    if compact_mode:
        st.caption("Compact mobile mode active")

    render_view_header(selected_view, compact_mode)

    if selected_view == "Overview":
        render_overview(web_stats, training_df, sniper_state, sniper_journal)
    elif selected_view == "Signals":
        render_live_signals(training_df, signal_card_mode)
    elif selected_view == "Sniper":
        render_sniper(sniper_state, sniper_journal)
    elif selected_view == "ML":
        render_ml_status(training_df)
    else:
        render_runtime_panel(web_stats)


if __name__ == "__main__":
    main()
