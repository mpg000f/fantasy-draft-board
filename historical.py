import pandas as pd
import streamlit as st

YEARS = [2020, 2021, 2022, 2023, 2024]
WEIGHTS = {2020: 0.10, 2021: 0.15, 2022: 0.20, 2023: 0.25, 2024: 0.30}

_STAT_COLS = [
    "passing_yds", "passing_tds", "passing_ints",
    "rushing_yds", "rushing_tds",
    "receiving_rec", "receiving_yds", "receiving_tds",
    "misc_fl",
]

_POSITIONS = ["QB", "RB", "WR", "TE"]

# Half PPR used as the neutral baseline for ranking players within each historical season.
# This determines which player "was the RB8" in a given year — not the user's scoring.
def _rank_pts(row) -> float:
    return (
        row["passing_yds"] / 25 + row["passing_tds"] * 4 + row["passing_ints"] * -2 +
        row["rushing_yds"] / 10 + row["rushing_tds"] * 6 +
        row["receiving_rec"] * 0.5 + row["receiving_yds"] / 10 + row["receiving_tds"] * 6 +
        row["misc_fl"] * -2
    )


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_rank_curves() -> dict:
    """5-year recency-weighted average raw stats at each positional rank.

    Returns dict of position -> DataFrame(pos_rank, stat_cols...).
    Stats are normalized to a 17-game season before averaging so
    injury-shortened years don't drag down a rank's historical average.
    """
    try:
        import nfl_data_py as nfl
    except ImportError:
        return {}

    stats = nfl.import_seasonal_data(YEARS, s_type="REG")

    # nfl_data_py seasonal data has no position/name — join from rosters
    rosters = nfl.import_seasonal_rosters(YEARS)[["player_id", "player_name", "position", "season"]].drop_duplicates()
    raw = stats.merge(rosters, on=["player_id", "season"], how="left")

    col_map = {
        "passing_yards": "passing_yds",
        "passing_tds": "passing_tds",
        "interceptions": "passing_ints",
        "rushing_yards": "rushing_yds",
        "rushing_tds": "rushing_tds",
        "receptions": "receiving_rec",
        "receiving_yards": "receiving_yds",
        "receiving_tds": "receiving_tds",
    }
    raw = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

    raw["misc_fl"] = (
        raw.get("sack_fumbles_lost", pd.Series(0, index=raw.index)).fillna(0) +
        raw.get("rushing_fumbles_lost", pd.Series(0, index=raw.index)).fillna(0)
    )

    for col in _STAT_COLS:
        if col not in raw.columns:
            raw[col] = 0.0
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)

    raw = raw[raw["position"].isin(_POSITIONS)]
    raw = raw[raw["games"] >= 4]  # drop players who barely suited up

    # Normalize all stats to a full 17-game season
    games = raw["games"].clip(lower=1)
    for col in _STAT_COLS:
        raw[col] = raw[col] / games * 17

    raw["rank_pts"] = raw.apply(_rank_pts, axis=1)
    raw["weight"] = raw["season"].map(WEIGHTS)
    raw["pos_rank"] = (
        raw.groupby(["season", "position"])["rank_pts"]
        .rank(ascending=False, method="first")
        .astype(int)
    )

    curves = {}
    for pos in _POSITIONS:
        pos_df = raw[raw["position"] == pos].copy()

        def wavg(group):
            w = group["weight"]
            return pd.Series({col: (group[col] * w).sum() / w.sum() for col in _STAT_COLS})

        curve = pos_df.groupby("pos_rank").apply(wavg, include_groups=False).reset_index()
        curves[pos] = curve

    return curves


def build_historical_projections(consensus_df: pd.DataFrame, curves: dict,
                                  fp_fallback: pd.DataFrame) -> pd.DataFrame:
    """Map consensus-ranked players onto historical rank curves.

    K and DST fall back to FantasyPros projections since their scoring is
    too dependent on team context to model from raw historical stats.
    """
    skill = consensus_df[consensus_df["position"].isin(_POSITIONS)].copy()
    rows = []

    for _, player in skill.iterrows():
        pos = player["position"]
        rank = int(player["pos_rank"])
        curve = curves.get(pos, pd.DataFrame())

        if curve.empty or rank > curve["pos_rank"].max():
            # Beyond historical depth — use the last available rank's stats
            if curve.empty:
                stat_row = {col: 0.0 for col in _STAT_COLS}
            else:
                stat_row = curve.iloc[-1][_STAT_COLS].to_dict()
        else:
            stat_row = curve[curve["pos_rank"] == rank].iloc[0][_STAT_COLS].to_dict()

        rows.append({
            "player": player["player"],
            "team": player.get("team", ""),
            "position": pos,
            "pos_rank": rank,
            **stat_row,
            "fp_fpts": 0.0,
        })

    skill_out = pd.DataFrame(rows)

    # K and DST: pull from FantasyPros projections
    kd_fallback = fp_fallback[fp_fallback["position"].isin(["K", "DST"])].copy()

    return pd.concat([skill_out, kd_fallback], ignore_index=True)
