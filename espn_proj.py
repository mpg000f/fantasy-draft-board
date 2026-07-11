"""ESPN per-player season projections.

FantasyPros' projection pages are scraped from HTML whose CDN intermittently
serves truncated 10-row stubs, so they can't be fetched reliably. ESPN exposes
full season projections as clean JSON — same schema out, far more dependable.
"""
import json
from datetime import datetime

import requests
import pandas as pd
import streamlit as st

_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
        "{year}/segments/0/leaguedefaults/3?view=kona_player_info")

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# defaultPositionId -> our position label
_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

# proTeamId -> abbreviation
_TEAM = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# ESPN stat id -> our stat column
_STAT_MAP = {
    "3": "passing_yds", "4": "passing_tds", "20": "passing_ints",
    "24": "rushing_yds", "25": "rushing_tds",
    "53": "receiving_rec", "42": "receiving_yds", "43": "receiving_tds",
    "72": "misc_fl",
}

_STAT_COLS = list(dict.fromkeys(_STAT_MAP.values())) + ["fp_fpts"]


def _season_year() -> int:
    """Upcoming NFL season. Before March, the season in play is last year's."""
    now = datetime.now()
    return now.year if now.month >= 3 else now.year - 1


def _season_projection(player: dict, year: int):
    """Return (stats_dict, applied_total) for the player's full-season projection."""
    for s in player.get("stats", []):
        if (s.get("statSourceId") == 1 and s.get("seasonId") == year
                and s.get("statSplitTypeId") == 0):
            return s.get("stats", {}), s.get("appliedTotal", 0.0)
    return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_projections_espn(year: int | None = None) -> pd.DataFrame:
    """Full-season per-player projections in the standard board schema."""
    year = year or _season_year()
    flt = {"players": {"limit": 1500,
                       "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
    headers = {**_HEADERS, "x-fantasy-filter": json.dumps(flt)}

    try:
        r = requests.get(_URL.format(year=year), headers=headers, timeout=25)
        r.raise_for_status()
        players = r.json().get("players", [])
    except Exception as e:
        st.warning(f"Could not fetch ESPN projections: {e}")
        return pd.DataFrame()

    rows = []
    for entry in players:
        p = entry.get("player", {})
        pos = _POS.get(p.get("defaultPositionId"))
        if pos is None:
            continue
        stats, total = _season_projection(p, year)
        if stats is None:
            continue

        row = {
            "player": p.get("fullName", ""),
            "team": _TEAM.get(p.get("proTeamId"), ""),
            "position": pos,
            "fp_fpts": round(float(total or 0.0), 1),
        }
        for espn_id, col in _STAT_MAP.items():
            row[col] = float(stats.get(espn_id, 0.0) or 0.0)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in _STAT_COLS:
        if col not in df.columns:
            df[col] = 0.0
    df = df[df["player"].str.strip() != ""]
    return df.reset_index(drop=True)
