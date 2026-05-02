import pandas as pd

DEFAULT_ROSTER = {
    "num_teams": 12,
    "budget": 200,
    "qb": 1,
    "rb": 2,
    "wr": 2,
    "te": 1,
    "flex": 1,   # RB/WR/TE eligible
    "k": 1,
    "dst": 1,
    "bench": 6,
}


def calculate_auction_values(df: pd.DataFrame, roster: dict) -> pd.DataFrame:
    """Add auction_value column using Value Above Replacement scaled to league budget."""
    df = df.copy()
    n = roster["num_teams"]
    budget = roster["budget"]

    qb_slots   = roster["qb"]   * n
    flex_slots  = (roster["rb"] + roster["wr"] + roster["te"] + roster["flex"]) * n
    k_slots    = roster["k"]    * n
    dst_slots  = roster["dst"]  * n
    total_per_team = sum(roster[k] for k in ["qb","rb","wr","te","flex","k","dst","bench"])

    # Spendable dollars after reserving $1 minimum per roster spot
    spendable = (budget - total_per_team) * n

    def replacement_fpts(subset: pd.DataFrame, slots: int) -> float:
        ranked = subset.sort_values("custom_fpts", ascending=False).reset_index(drop=True)
        return ranked.iloc[slots]["custom_fpts"] if slots < len(ranked) else 0.0

    repl_qb  = replacement_fpts(df[df["position"] == "QB"], qb_slots)
    repl_sk  = replacement_fpts(df[df["position"].isin(["RB","WR","TE"])], flex_slots)
    repl_k   = replacement_fpts(df[df["position"] == "K"], k_slots)
    repl_dst = replacement_fpts(df[df["position"] == "DST"], dst_slots)

    _repl = {"QB": repl_qb, "RB": repl_sk, "WR": repl_sk, "TE": repl_sk,
             "K": repl_k, "DST": repl_dst}

    df["par"] = df.apply(
        lambda r: max(0.0, r["custom_fpts"] - _repl.get(r["position"], 0.0)), axis=1
    )

    total_par = df["par"].sum()
    if total_par == 0:
        df["auction_value"] = 1
    else:
        df["auction_value"] = (df["par"] / total_par * spendable + 1).round().astype(int)
        df["auction_value"] = df["auction_value"].clip(lower=1)

    df = df.drop(columns=["par"])
    return df
