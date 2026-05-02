import requests
from scoring import DEFAULT_SCORING
from auction import DEFAULT_ROSTER

# ESPN lineup slot ID → roster key
_ESPN_SLOT_MAP = {
    0: "qb", 2: "rb", 4: "wr", 6: "te",
    23: "flex", 7: "superflex",
    16: "k", 24: "dst", 20: "bench",
}

_BASE = "https://fantasy.espn.com/apis/v3/games/ffl"

# ESPN stat ID → (my key, conversion)
# ESPN stores pts-per-unit (like 0.04 for pass yards = 1 pt/25 yds)
_ESPN_STAT_MAP = {
    3:   ("pass_yds_per_pt",  lambda v: round(1 / v) if v else 25),
    4:   ("pass_td",          lambda v: v),
    20:  ("pass_int",         lambda v: v),
    24:  ("rush_yds_per_pt",  lambda v: round(1 / v) if v else 10),
    25:  ("rush_td",          lambda v: v),
    41:  ("rec_yds_per_pt",   lambda v: round(1 / v) if v else 10),
    42:  ("rec_td",           lambda v: v),
    53:  ("rec_ppr",          lambda v: v),
    72:  ("fumble_lost",      lambda v: v),
    74:  ("pass_2pt",         lambda v: v),
    83:  ("pass_300_bonus",   lambda v: v),
    86:  ("rush_100_bonus",   lambda v: v),
    155: ("rec_100_bonus",    lambda v: v),
}


def import_league(league_id: str, year: int = 2025,
                  espn_s2: str = "", swid: str = "") -> dict:
    """Fetch scoring settings from an ESPN league.

    For private leagues, provide espn_s2 and swid cookies from your browser session
    (ESPN > Developer Tools > Application > Cookies).
    """
    url = f"{_BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    params = {"view": "mSettings"}
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid

    r = requests.get(url, params=params, cookies=cookies, timeout=10)
    if r.status_code == 401:
        raise ValueError("Private league — provide your espn_s2 and SWID cookies.")
    if r.status_code == 404:
        raise ValueError(f"ESPN league '{league_id}' not found for {year} season.")
    r.raise_for_status()

    data = r.json()
    items = (
        data.get("settings", {})
            .get("scoringSettings", {})
            .get("scoringItems", [])
    )

    scoring = DEFAULT_SCORING.copy()
    for item in items:
        stat_id = item.get("statId")
        mult = item.get("pointsMultiplier", 0)
        if stat_id in _ESPN_STAT_MAP and mult != 0:
            my_key, convert = _ESPN_STAT_MAP[stat_id]
            try:
                scoring[my_key] = convert(mult)
            except Exception:
                pass

    return scoring


def import_roster(league_id: str, year: int = 2025,
                  espn_s2: str = "", swid: str = "") -> dict:
    """Fetch roster slot counts and team count from an ESPN league."""
    url = f"{_BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid

    r = requests.get(url, params={"view": "mSettings"}, cookies=cookies, timeout=10)
    if r.status_code == 401:
        raise ValueError("Private league — provide your espn_s2 and SWID cookies.")
    r.raise_for_status()

    data = r.json()
    settings = data.get("settings", {})

    roster = DEFAULT_ROSTER.copy()
    roster["num_teams"] = settings.get("size", 12)

    for slot in settings.get("rosterSettings", {}).get("lineupSlotCounts", {}):
        key = _ESPN_SLOT_MAP.get(int(slot))
        count = settings["rosterSettings"]["lineupSlotCounts"][slot]
        if key and count:
            roster[key] = count

    return roster


def get_league_name(league_id: str, year: int = 2025,
                    espn_s2: str = "", swid: str = "") -> str:
    url = f"{_BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid
    r = requests.get(url, params={"view": "mSettings"}, cookies=cookies, timeout=10)
    r.raise_for_status()
    return r.json().get("settings", {}).get("name", league_id)
