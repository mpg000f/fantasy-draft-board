"""Sleeper per-player season projections — a reliable second raw-stat source.

Same output schema as espn_proj so the two can be averaged into a blend.
Sleeper returns full-season projections as JSON with player metadata and box-
score components embedded (pass_yd, rush_td, rec, fum_lost, ...).
"""
import requests
import pandas as pd
import streamlit as st

from espn_proj import _season_year

_URL = ("https://api.sleeper.com/projections/nfl/{year}?season_type=regular"
        "&position[]=QB&position[]=RB&position[]=WR&position[]=TE"
        "&order_by=pts_half_ppr")

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Sleeper stat key -> our stat column
_STAT_MAP = {
    "pass_yd": "passing_yds", "pass_td": "passing_tds", "pass_int": "passing_ints",
    "rush_yd": "rushing_yds", "rush_td": "rushing_tds",
    "rec": "receiving_rec", "rec_yd": "receiving_yds", "rec_td": "receiving_tds",
    "fum_lost": "misc_fl",
}

_STAT_COLS = list(dict.fromkeys(_STAT_MAP.values())) + ["fp_fpts"]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_projections_sleeper(year: int | None = None) -> pd.DataFrame:
    """Full-season QB/RB/WR/TE projections in the standard board schema."""
    year = year or _season_year()
    try:
        r = requests.get(_URL.format(year=year), headers=_HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.warning(f"Could not fetch Sleeper projections: {e}")
        return pd.DataFrame()

    rows = []
    for entry in data:
        pl = entry.get("player") or {}
        stats = entry.get("stats") or {}
        pos = pl.get("position")
        if pos not in ("QB", "RB", "WR", "TE"):
            continue
        name = f"{pl.get('first_name','')} {pl.get('last_name','')}".strip()
        if not name:
            continue
        row = {
            "player": name,
            "team": pl.get("team_abbr") or pl.get("team") or "",
            "position": pos,
            "fp_fpts": 0.0,  # recomputed from raw stats under league scoring
        }
        for skey, col in _STAT_MAP.items():
            row[col] = float(stats.get(skey) or 0.0)
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["player", "position"]).reset_index(drop=True)
