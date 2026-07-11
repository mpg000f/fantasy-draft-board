import io
import sys
import os
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from scraper import fetch_projections, fetch_adp, fetch_consensus_rankings
from scoring import DEFAULT_SCORING, PRESETS, calculate_fpts
from auction import DEFAULT_ROSTER, calculate_auction_values
from historical import fetch_rank_curves, build_historical_projections
from espn_proj import fetch_projections_espn
from sleeper_proj import fetch_projections_sleeper
from blend import fetch_projections_blended
from league import sleeper, espn, yahoo

st.set_page_config(page_title="Fantasy Draft Board", layout="wide")

# ── Session state defaults ─────────────────────────────────────────────────────

if "scoring" not in st.session_state:
    st.session_state.scoring = PRESETS["Half PPR"].copy()
if "preset" not in st.session_state:
    st.session_state.preset = "Half PPR"
if "roster" not in st.session_state:
    st.session_state.roster = DEFAULT_ROSTER.copy()
if "import_status" not in st.session_state:
    st.session_state.import_status = None
if "yahoo_token" not in st.session_state:
    st.session_state.yahoo_token = None
if "week" not in st.session_state:
    st.session_state.week = "draft"


# ── Yahoo OAuth callback (runs before any rendering) ──────────────────────────

def _handle_yahoo_callback():
    params = st.query_params
    if "code" not in params:
        return
    code = params["code"]
    try:
        cfg = st.secrets.get("yahoo", {})
        token_data = yahoo.exchange_code(
            code=code,
            client_id=cfg.get("client_id", ""),
            client_secret=cfg.get("client_secret", ""),
            redirect_uri=cfg.get("redirect_uri", ""),
        )
        st.session_state.yahoo_token = token_data.get("access_token")
        st.session_state.import_status = ("success", "Yahoo connected. Enter your league ID to import settings.")
    except Exception as e:
        st.session_state.import_status = ("error", f"Yahoo auth failed: {e}")
    st.query_params.clear()

_handle_yahoo_callback()


def _apply_import(scoring: dict, roster: dict, name: str):
    """Update session state AND widget keys so the sidebar reflects imported values."""
    st.session_state.scoring = scoring
    st.session_state.roster = {**roster, "budget": st.session_state.roster["budget"]}
    st.session_state.preset = "Custom"
    st.session_state.import_status = ("success", f"Loaded: **{name}**")

    # Sync scoring widget keys
    st.session_state["pass_yds"]  = float(scoring["pass_yds_per_pt"])
    st.session_state["pass_td"]   = float(scoring["pass_td"])
    st.session_state["pass_int"]  = float(scoring["pass_int"])
    st.session_state["pass_300"]  = float(scoring["pass_300_bonus"])
    st.session_state["rush_yds"]  = float(scoring["rush_yds_per_pt"])
    st.session_state["rush_td"]   = float(scoring["rush_td"])
    st.session_state["rush_100"]  = float(scoring["rush_100_bonus"])
    st.session_state["rec_ppr"]   = float(scoring["rec_ppr"])
    st.session_state["te_toggle"] = scoring["te_rec_bonus"] > 0
    st.session_state["te_bonus"]  = float(scoring["te_rec_bonus"]) if scoring["te_rec_bonus"] > 0 else 0.25
    st.session_state["rec_yds"]   = float(scoring["rec_yds_per_pt"])
    st.session_state["rec_td"]    = float(scoring["rec_td"])
    st.session_state["rec_100"]   = float(scoring["rec_100_bonus"])
    st.session_state["fum"]       = float(scoring["fumble_lost"])
    st.session_state["pass_2pt"]  = float(scoring["pass_2pt"])
    st.session_state["rush_2pt"]  = float(scoring["rush_2pt"])
    st.session_state["rec_2pt"]   = float(scoring["rec_2pt"])

    # Sync roster widget keys
    st.session_state["num_teams"] = int(roster["num_teams"])
    st.session_state["r_qb"]      = int(roster["qb"])
    st.session_state["r_rb"]      = int(roster["rb"])
    st.session_state["r_wr"]      = int(roster["wr"])
    st.session_state["r_te"]      = int(roster["te"])
    st.session_state["r_flex"]      = int(roster["flex"])
    st.session_state["r_superflex"] = int(roster.get("superflex", 0))
    st.session_state["r_k"]         = int(roster["k"])
    st.session_state["r_dst"]     = int(roster["dst"])
    st.session_state["r_bench"]   = int(roster["bench"])

    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Fantasy Draft Board")
    st.caption("Customize rankings for your league's exact scoring.")

    # Week selector
    st.subheader("Projections")
    week_options = ["draft"] + [str(w) for w in range(1, 18)]
    week_labels = ["Full Season (Draft)"] + [f"Week {w}" for w in range(1, 18)]
    week_idx = week_options.index(st.session_state.week)
    selected_week_label = st.selectbox("Week", week_labels, index=week_idx)
    st.session_state.week = week_options[week_labels.index(selected_week_label)]

    st.divider()

    # League import
    st.subheader("Import League Settings")
    platform = st.selectbox("Platform", ["Sleeper", "ESPN", "Yahoo", "Manual"])

    if platform == "Sleeper":
        league_id = st.text_input("Sleeper League ID", placeholder="e.g. 1048952639781294080")
        if st.button("Import from Sleeper", use_container_width=True):
            with st.spinner("Fetching league settings..."):
                try:
                    lid = league_id.strip()
                    _apply_import(sleeper.import_league(lid), sleeper.import_roster(lid), sleeper.get_league_name(lid))
                except Exception as e:
                    st.session_state.import_status = ("error", str(e))

    elif platform == "ESPN":
        league_id = st.text_input("ESPN League ID", placeholder="e.g. 1234567")
        year = st.number_input("Season Year", min_value=2020, max_value=2030, value=2025)
        with st.expander("Private league? (optional)"):
            espn_s2 = st.text_input("espn_s2 cookie", type="password",
                help="Open ESPN in browser → F12 → Application → Cookies → espn_s2")
            swid = st.text_input("SWID cookie",
                help="Same location as espn_s2, looks like {XXXXXXXX-XXXX-...}")
        if st.button("Import from ESPN", use_container_width=True):
            with st.spinner("Fetching league settings..."):
                try:
                    lid, yr = league_id.strip(), int(year)
                    kw = dict(espn_s2=espn_s2.strip(), swid=swid.strip())
                    _apply_import(espn.import_league(lid, yr, **kw), espn.import_roster(lid, yr, **kw), espn.get_league_name(lid, yr, **kw))
                except Exception as e:
                    st.session_state.import_status = ("error", str(e))

    elif platform == "Yahoo":
        cfg = st.secrets.get("yahoo", {}) if hasattr(st, "secrets") else {}
        has_yahoo_config = bool(cfg.get("client_id"))

        if not has_yahoo_config:
            st.info("Yahoo import requires OAuth setup. See the README for instructions.")
        elif st.session_state.yahoo_token is None:
            auth_url = yahoo.get_auth_url(cfg["client_id"], cfg["redirect_uri"])
            st.markdown(f"[Connect Yahoo Account]({auth_url})", unsafe_allow_html=False)
            st.caption("You'll be redirected back here after authorizing.")
        else:
            st.success("Yahoo connected")
            league_id = st.text_input("Yahoo League ID", placeholder="e.g. 1234567")
            if st.button("Import from Yahoo", use_container_width=True):
                with st.spinner("Fetching league settings..."):
                    try:
                        lid, tok = league_id.strip(), st.session_state.yahoo_token
                        _apply_import(yahoo.import_league(lid, tok), yahoo.import_roster(lid, tok), yahoo.get_league_name(lid, tok))
                    except Exception as e:
                        st.session_state.import_status = ("error", str(e))
            if st.button("Disconnect Yahoo"):
                st.session_state.yahoo_token = None
                st.rerun()

    if st.session_state.import_status:
        status, msg = st.session_state.import_status
        if status == "success":
            st.success(msg)
        else:
            st.error(msg)

    st.divider()

    # Scoring settings
    st.subheader("Scoring Settings")

    preset_keys = list(PRESETS.keys())
    preset_idx = preset_keys.index(st.session_state.preset) if st.session_state.preset in preset_keys else 0
    chosen_preset = st.selectbox("Preset", preset_keys, index=preset_idx)

    if chosen_preset != "Custom" and chosen_preset != st.session_state.preset:
        st.session_state.scoring = PRESETS[chosen_preset].copy()
        st.session_state.preset = chosen_preset
        st.rerun()

    s = st.session_state.scoring

    with st.expander("Passing", expanded=False):
        s["pass_yds_per_pt"] = st.number_input("Yards per point", value=float(s["pass_yds_per_pt"]),
            min_value=1.0, step=1.0, key="pass_yds", help="e.g. 25 = 1 pt per 25 pass yards")
        s["pass_td"] = st.number_input("TD points", value=float(s["pass_td"]),
            step=0.5, key="pass_td")
        s["pass_int"] = st.number_input("INT points", value=float(s["pass_int"]),
            step=0.5, key="pass_int")
        s["pass_300_bonus"] = st.number_input("300+ yd game bonus", value=float(s["pass_300_bonus"]),
            step=0.5, key="pass_300")

    with st.expander("Rushing", expanded=False):
        s["rush_yds_per_pt"] = st.number_input("Yards per point", value=float(s["rush_yds_per_pt"]),
            min_value=1.0, step=1.0, key="rush_yds", help="e.g. 10 = 1 pt per 10 rush yards")
        s["rush_td"] = st.number_input("TD points", value=float(s["rush_td"]),
            step=0.5, key="rush_td")
        s["rush_100_bonus"] = st.number_input("100+ yd game bonus", value=float(s["rush_100_bonus"]),
            step=0.5, key="rush_100")

    with st.expander("Receiving", expanded=True):
        s["rec_ppr"] = st.number_input("PPR (pts per reception)", value=float(s["rec_ppr"]),
            min_value=0.0, max_value=2.0, step=0.25, key="rec_ppr",
            help="0 = standard, 0.5 = half PPR, 1.0 = full PPR")
        te_premium = st.toggle("TE Premium", value=s["te_rec_bonus"] > 0, key="te_toggle")
        if te_premium:
            s["te_rec_bonus"] = st.number_input("Extra PPR for TEs", value=max(float(s["te_rec_bonus"]), 0.25),
                min_value=0.0, max_value=1.5, step=0.25, key="te_bonus",
                help="Added on top of base PPR. E.g. 0.5 makes TEs 1.0 PPR in a 0.5 PPR league.")
        else:
            s["te_rec_bonus"] = 0.0
        s["rec_yds_per_pt"] = st.number_input("Yards per point", value=float(s["rec_yds_per_pt"]),
            min_value=1.0, step=1.0, key="rec_yds")
        s["rec_td"] = st.number_input("TD points", value=float(s["rec_td"]),
            step=0.5, key="rec_td")
        s["rec_100_bonus"] = st.number_input("100+ yd game bonus", value=float(s["rec_100_bonus"]),
            step=0.5, key="rec_100")

    with st.expander("Other", expanded=False):
        s["fumble_lost"] = st.number_input("Fumble lost", value=float(s["fumble_lost"]),
            step=0.5, key="fum")
        s["pass_2pt"] = st.number_input("2PT conversion (pass)", value=float(s["pass_2pt"]),
            step=0.5, key="pass_2pt")
        s["rush_2pt"] = st.number_input("2PT conversion (rush)", value=float(s["rush_2pt"]),
            step=0.5, key="rush_2pt")
        s["rec_2pt"] = st.number_input("2PT conversion (rec)", value=float(s["rec_2pt"]),
            step=0.5, key="rec_2pt")

    st.divider()

    # Auction settings
    st.subheader("Auction Settings")
    r = st.session_state.roster
    r["budget"] = st.number_input("Budget per team ($)", value=int(r["budget"]),
        min_value=50, step=10, key="budget")

    with st.expander("Roster slots", expanded=False):
        st.caption("Auto-filled from league import. Adjust if needed.")
        r["num_teams"] = st.number_input("Teams", value=int(r["num_teams"]), min_value=2, step=1, key="num_teams")
        r["qb"]    = st.number_input("QB",    value=int(r["qb"]),    min_value=0, step=1, key="r_qb")
        r["rb"]    = st.number_input("RB",    value=int(r["rb"]),    min_value=0, step=1, key="r_rb")
        r["wr"]    = st.number_input("WR",    value=int(r["wr"]),    min_value=0, step=1, key="r_wr")
        r["te"]    = st.number_input("TE",    value=int(r["te"]),    min_value=0, step=1, key="r_te")
        r["flex"]      = st.number_input("FLEX",      value=int(r.get("flex", 1)),      min_value=0, step=1, key="r_flex",      help="RB/WR/TE eligible")
        r["superflex"] = st.number_input("Superflex", value=int(r.get("superflex", 0)), min_value=0, step=1, key="r_superflex", help="QB/RB/WR/TE eligible")
        r["k"]     = st.number_input("K",     value=int(r["k"]),     min_value=0, step=1, key="r_k")
        r["dst"]   = st.number_input("DST",   value=int(r["dst"]),   min_value=0, step=1, key="r_dst")
        r["bench"] = st.number_input("Bench", value=int(r["bench"]), min_value=0, step=1, key="r_bench")

    st.divider()

    st.subheader("Projection Source")
    proj_source = st.radio(
        "Source",
        ["Blend (ESPN + Sleeper)", "ESPN Projections", "Sleeper Projections",
         "FantasyPros Projections", "Historical (5yr weighted)"],
        help="Blend: averages ESPN + Sleeper raw stats per player (recommended — "
             "cancels single-source bias like ESPN's high RB/WR numbers). "
             "ESPN / Sleeper: either alone. "
             "FantasyPros: expert stats (loads can be truncated/flaky). "
             "Historical: 5-year positional-rank averages onto consensus ranks.",
    )

    if st.button("Refresh Projection Data", use_container_width=True):
        fetch_projections_blended.clear()
        fetch_projections_espn.clear()
        fetch_projections_sleeper.clear()
        fetch_projections.clear()
        fetch_adp.clear()
        fetch_consensus_rankings.clear()
        fetch_rank_curves.clear()
        st.rerun()


# ── Main content ───────────────────────────────────────────────────────────────

st.header("Fantasy Draft Board")

scoring_label = (
    "Full PPR" if s["rec_ppr"] >= 1.0
    else "Standard" if s["rec_ppr"] == 0.0
    else "Half PPR"
)

with st.spinner("Loading projections..."):
    is_draft = st.session_state.week == "draft"
    adp_df = fetch_adp(scoring_label) if is_draft else pd.DataFrame()

    if proj_source == "Blend (ESPN + Sleeper)" and is_draft:
        raw_df = fetch_projections_blended()
        if raw_df.empty:
            st.warning("Blend unavailable — falling back to FantasyPros.")
            raw_df = fetch_projections(st.session_state.week)
    elif proj_source == "ESPN Projections" and is_draft:
        raw_df = fetch_projections_espn()
        if raw_df.empty:
            st.warning("ESPN projections unavailable — falling back to FantasyPros.")
            raw_df = fetch_projections(st.session_state.week)
    elif proj_source == "Sleeper Projections" and is_draft:
        raw_df = fetch_projections_sleeper()
        if raw_df.empty:
            st.warning("Sleeper projections unavailable — falling back to FantasyPros.")
            raw_df = fetch_projections(st.session_state.week)
    elif proj_source == "Historical (5yr weighted)" and is_draft:
        fp_df = fetch_projections(st.session_state.week)
        consensus_df = fetch_consensus_rankings()
        curves = fetch_rank_curves()
        if consensus_df.empty or not curves:
            st.warning("Could not load historical data — falling back to FantasyPros projections.")
            raw_df = fp_df
        else:
            raw_df = build_historical_projections(consensus_df, curves, fp_df)
    else:
        if not is_draft and proj_source != "FantasyPros Projections":
            st.info("Only FantasyPros has weekly projections. Showing FantasyPros week projections.")
        raw_df = fetch_projections(st.session_state.week)

if raw_df.empty:
    st.error("Could not load projections. Try refreshing.")
    st.stop()

# Apply scoring, auction values, merge ADP
df = calculate_fpts(raw_df, st.session_state.scoring)
df = calculate_auction_values(df, st.session_state.roster)

if not adp_df.empty:
    df = df.merge(adp_df, on="player", how="left")
else:
    df["adp"] = float("nan")

# Overall rank by custom FPTS
df = df.sort_values("custom_fpts", ascending=False).reset_index(drop=True)
df.insert(0, "rank", df.index + 1)

# Position rank
df["pos_rank"] = df.groupby("position").cumcount() + 1
df["pos_rank_label"] = df["position"] + df["pos_rank"].astype(str)

# Value vs ADP
df["value"] = (df["adp"] - df["rank"]).round(1)


def _fmt_df(subset: pd.DataFrame, show_stats: bool = False) -> pd.DataFrame:
    cols = ["rank", "player", "team", "position", "pos_rank_label", "custom_fpts", "auction_value"]
    rename = {
        "rank": "Rank", "player": "Player", "team": "Team",
        "position": "Pos", "pos_rank_label": "Pos Rank",
        "custom_fpts": "Proj FPTS", "auction_value": "$Value",
    }
    if "adp" in subset.columns and subset["adp"].notna().any():
        cols += ["adp", "value"]
        rename.update({"adp": "ADP", "value": "Value vs ADP"})
    if show_stats:
        stat_cols = [c for c in [
            "passing_yds", "passing_tds", "rushing_yds", "rushing_tds",
            "receiving_rec", "receiving_yds", "receiving_tds",
        ] if c in subset.columns and subset[c].sum() > 0]
        cols = cols[:6] + stat_cols + cols[6:]
        rename.update({
            "passing_yds": "Pass Yds", "passing_tds": "Pass TDs",
            "rushing_yds": "Rush Yds", "rushing_tds": "Rush TDs",
            "receiving_rec": "Rec", "receiving_yds": "Rec Yds", "receiving_tds": "Rec TDs",
        })
    out = subset[[c for c in cols if c in subset.columns]].rename(columns=rename)
    return out


def _export_buttons(display_df: pd.DataFrame, key_prefix: str):
    col1, col2 = st.columns([1, 1])
    with col1:
        csv = display_df.to_csv(index=False).encode()
        st.download_button("⬇ Export CSV", csv, f"{key_prefix}_rankings.csv",
                           "text/csv", key=f"csv_{key_prefix}")
    with col2:
        buf = io.BytesIO()
        display_df.to_excel(buf, index=False, engine="openpyxl")
        st.download_button("⬇ Export Excel", buf.getvalue(), f"{key_prefix}_rankings.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"xlsx_{key_prefix}")


# Tabs
tab_all, tab_qb, tab_rb, tab_wr, tab_te, tab_k, tab_dst = st.tabs(
    ["All", "QB", "RB", "WR", "TE", "K", "DST"]
)

with tab_all:
    display = _fmt_df(df)
    _export_buttons(display, "all")
    st.dataframe(display, use_container_width=True, hide_index=True,
                 column_config={
                     "$Value": st.column_config.NumberColumn(
                         help=f"Auction value based on ${r['budget']} budget, {r['num_teams']} teams"
                     ),
                     "Value vs ADP": st.column_config.NumberColumn(
                         help="Positive = ranked higher by FPTS than ADP suggests (value pick)"
                     ),
                 })

for tab, pos in [
    (tab_qb, "QB"), (tab_rb, "RB"), (tab_wr, "WR"),
    (tab_te, "TE"), (tab_k, "K"), (tab_dst, "DST"),
]:
    with tab:
        subset = df[df["position"] == pos].copy()
        subset["rank"] = range(1, len(subset) + 1)
        display = _fmt_df(subset, show_stats=True)
        _export_buttons(display, pos.lower())
        st.dataframe(display, use_container_width=True, hide_index=True)

# Footer
te_total = round(s["rec_ppr"] + s["te_rec_bonus"], 2)
st.caption(
    f"Scoring: {s['rec_ppr']} PPR · "
    + (f"TE: {te_total} PPR · " if s['te_rec_bonus'] else "")
    + f"{s['pass_td']}pt pass TD · {s['rush_td']}pt rush/rec TD · "
    + f"1 pt per {int(s['pass_yds_per_pt'])} pass yds / {int(s['rush_yds_per_pt'])} rush yds / {int(s['rec_yds_per_pt'])} rec yds · "
    + f"{s['pass_int']} INT · {s['fumble_lost']} fumble · "
    + f"Auction: ${r['budget']}/team · {r['num_teams']} teams · "
    + f"{r['qb']}QB {r['rb']}RB {r['wr']}WR {r['te']}TE {r['flex']}FLEX {r['k']}K {r['dst']}DST {r['bench']}BN"
)
