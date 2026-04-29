import pandas as pd

DEFAULT_SCORING = {
    "pass_yds_per_pt": 25.0,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "pass_2pt": 2.0,
    "pass_300_bonus": 0.0,
    "rush_yds_per_pt": 10.0,
    "rush_td": 6.0,
    "rush_2pt": 2.0,
    "rush_100_bonus": 0.0,
    "rec_ppr": 0.5,
    "te_rec_bonus": 0.0,
    "rec_yds_per_pt": 10.0,
    "rec_td": 6.0,
    "rec_2pt": 2.0,
    "rec_100_bonus": 0.0,
    "fumble_lost": -2.0,
}

PRESETS = {
    "Standard": {**DEFAULT_SCORING, "rec_ppr": 0.0},
    "Half PPR": {**DEFAULT_SCORING, "rec_ppr": 0.5},
    "Full PPR": {**DEFAULT_SCORING, "rec_ppr": 1.0},
    "Half PPR + TE Premium (0.75)": {**DEFAULT_SCORING, "rec_ppr": 0.5, "te_rec_bonus": 0.25},
    "Half PPR + TE Premium (1.0)": {**DEFAULT_SCORING, "rec_ppr": 0.5, "te_rec_bonus": 0.5},
    "Full PPR + 6pt Pass TDs": {**DEFAULT_SCORING, "rec_ppr": 1.0, "pass_td": 6.0},
    "Custom": None,
}


def calculate_fpts(df: pd.DataFrame, scoring: dict) -> pd.DataFrame:
    """Add custom_fpts column based on scoring settings. K/DST use FantasyPros fpts."""
    df = df.copy()
    df["custom_fpts"] = 0.0

    skill = df["position"].isin(["QB", "RB", "WR", "TE"])

    # Passing
    df.loc[skill, "custom_fpts"] += df["passing_yds"] / scoring["pass_yds_per_pt"]
    df.loc[skill, "custom_fpts"] += df["passing_tds"] * scoring["pass_td"]
    df.loc[skill, "custom_fpts"] += df["passing_ints"] * scoring["pass_int"]
    if scoring["pass_300_bonus"]:
        df.loc[skill & (df["passing_yds"] >= 300), "custom_fpts"] += scoring["pass_300_bonus"]

    # Rushing
    df.loc[skill, "custom_fpts"] += df["rushing_yds"] / scoring["rush_yds_per_pt"]
    df.loc[skill, "custom_fpts"] += df["rushing_tds"] * scoring["rush_td"]
    if scoring["rush_100_bonus"]:
        df.loc[skill & (df["rushing_yds"] >= 100), "custom_fpts"] += scoring["rush_100_bonus"]

    # Receiving — base PPR for all, extra bonus for TEs
    df.loc[skill, "custom_fpts"] += df["receiving_rec"] * scoring["rec_ppr"]
    if scoring["te_rec_bonus"]:
        te = df["position"] == "TE"
        df.loc[te, "custom_fpts"] += df["receiving_rec"] * scoring["te_rec_bonus"]
    df.loc[skill, "custom_fpts"] += df["receiving_yds"] / scoring["rec_yds_per_pt"]
    df.loc[skill, "custom_fpts"] += df["receiving_tds"] * scoring["rec_td"]
    if scoring["rec_100_bonus"]:
        df.loc[skill & (df["receiving_yds"] >= 100), "custom_fpts"] += scoring["rec_100_bonus"]

    # Fumbles
    df.loc[skill, "custom_fpts"] += df["misc_fl"] * scoring["fumble_lost"]

    # K and DST use FantasyPros pre-calculated fpts
    df.loc[~skill, "custom_fpts"] = df["fp_fpts"]

    df["custom_fpts"] = df["custom_fpts"].round(1)
    return df
