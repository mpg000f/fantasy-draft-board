"""Blend multiple projection sources by averaging raw stats per player.

Averaging box-score components (not final points) means the league's custom
scoring still applies cleanly on top. Skill positions (QB/RB/WR/TE) are blended
where both sources cover a player; K/DST come from ESPN alone since Sleeper's
skill endpoint doesn't carry them.
"""
import re

import pandas as pd

from espn_proj import fetch_projections_espn
from sleeper_proj import fetch_projections_sleeper

_RAW = ["passing_yds", "passing_tds", "passing_ints", "rushing_yds", "rushing_tds",
        "receiving_rec", "receiving_yds", "receiving_tds", "misc_fl"]
_SKILL = {"QB", "RB", "WR", "TE"}


def _norm(name: str) -> str:
    n = re.sub(r"[.'’]", "", str(name).lower())
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def fetch_projections_blended(year: int | None = None) -> pd.DataFrame:
    """ESPN + Sleeper, averaged per player on the skill positions."""
    espn = fetch_projections_espn(year)
    sleeper = fetch_projections_sleeper(year)
    if espn.empty:
        return sleeper
    if sleeper.empty:
        return espn

    espn = espn.copy()
    espn["_k"] = espn["player"].map(_norm) + "|" + espn["position"]
    sleeper = sleeper.copy()
    sleeper["_k"] = sleeper["player"].map(_norm) + "|" + sleeper["position"]
    s_by_key = sleeper.set_index("_k")

    # Universe is ESPN's (it covers every draft-relevant player); average in
    # Sleeper's raw stats wherever the player matches. Sleeper's long tail of
    # near-zero deep players is intentionally left out.
    out = espn.copy()
    matched = 0
    for i, row in out.iterrows():
        if row["position"] not in _SKILL or row["_k"] not in s_by_key.index:
            continue
        sr = s_by_key.loc[row["_k"]]
        if isinstance(sr, pd.DataFrame):
            sr = sr.iloc[0]
        for c in _RAW:
            out.at[i, c] = (float(row[c]) + float(sr[c])) / 2.0
        matched += 1

    return out.drop(columns=["_k"])
