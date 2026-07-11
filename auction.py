import pandas as pd

# Defaults tuned to Mitchell's league: 16-team superflex, half PPR, 4pt pass TD.
DEFAULT_ROSTER = {
    "num_teams": 16,
    "budget": 200,
    "qb": 1,
    "rb": 2,
    "wr": 2,
    "te": 1,
    "flex": 1,       # RB/WR/TE eligible
    "superflex": 1,  # QB/RB/WR/TE eligible
    "k": 1,
    "dst": 1,
    "bench": 6,
}

_FLEX_POS = ["RB", "WR", "TE"]
_SUPERFLEX_POS = ["QB", "RB", "WR", "TE"]


def _replacement_levels(df: pd.DataFrame, roster: dict) -> dict:
    """Replacement points per position via greedy starter allocation.

    Dedicated slots fill first, then flex goes to the best remaining RB/WR/TE
    and superflex to the best remaining QB/RB/WR/TE. Each position's
    replacement level is the best player who never cracks a starting slot.
    """
    n = roster["num_teams"]

    # Points at each position, sorted best-first
    pts = {
        pos: df.loc[df["position"] == pos, "custom_fpts"]
               .sort_values(ascending=False).tolist()
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]
    }

    # Dedicated starters consumed off the top of each position
    used = {
        "QB": roster["qb"] * n,
        "RB": roster["rb"] * n,
        "WR": roster["wr"] * n,
        "TE": roster["te"] * n,
        "K": roster["k"] * n,
        "DST": roster["dst"] * n,
    }

    def _grab(eligible: list, count: int):
        """Assign `count` slots one at a time to the position whose next-best
        available player scores highest."""
        for _ in range(count):
            best_pos, best_val = None, float("-inf")
            for pos in eligible:
                idx = used[pos]
                if idx < len(pts[pos]) and pts[pos][idx] > best_val:
                    best_val, best_pos = pts[pos][idx], pos
            if best_pos is None:
                break
            used[best_pos] += 1

    _grab(_FLEX_POS, roster.get("flex", 0) * n)
    _grab(_SUPERFLEX_POS, roster.get("superflex", 0) * n)

    return {
        pos: (pts[pos][used[pos]] if used[pos] < len(pts[pos]) else 0.0)
        for pos in pts
    }


def calculate_auction_values(df: pd.DataFrame, roster: dict) -> pd.DataFrame:
    """Add auction_value column using Value Over Replacement scaled to budget."""
    df = df.copy()
    n = roster["num_teams"]
    budget = roster["budget"]

    repl = _replacement_levels(df, roster)

    df["vor"] = df.apply(
        lambda r: max(0.0, r["custom_fpts"] - repl.get(r["position"], 0.0)), axis=1
    )

    roster_size = sum(
        roster.get(k, 0)
        for k in ["qb", "rb", "wr", "te", "flex", "superflex", "k", "dst", "bench"]
    )
    # Dollars beyond the $1 minimum reserved for each of the n*roster_size
    # rostered spots. Above-replacement players split this by value; everyone
    # at or below replacement is a flat $1 min-bid (interchangeable, no cliff).
    # A full 256-man roster then sums to the league budget.
    spendable = (budget - roster_size) * n

    df["auction_value"] = 1
    total_vor = df["vor"].sum()
    if total_vor > 0 and spendable > 0:
        rate = spendable / total_vor
        above = df["vor"] > 0
        df.loc[above, "auction_value"] = (df.loc[above, "vor"] * rate).round().astype(int) + 1
    df["auction_value"] = df["auction_value"].clip(lower=1)

    df = df.drop(columns=["vor"])
    return df
