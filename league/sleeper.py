import requests
from scoring import DEFAULT_SCORING

_BASE = "https://api.sleeper.app/v1"

# Sleeper scoring key → (my key, conversion_fn)
# Sleeper stores pts-per-unit; I store units-per-point for yardage, direct for everything else
_SLEEPER_MAP = {
    "pass_yd":          ("pass_yds_per_pt",  lambda v: round(1 / v) if v else 25),
    "pass_td":          ("pass_td",           lambda v: v),
    "pass_int":         ("pass_int",          lambda v: v),
    "pass_2pt":         ("pass_2pt",          lambda v: v),
    "bonus_pass_yd_300":("pass_300_bonus",    lambda v: v),
    "rush_yd":          ("rush_yds_per_pt",   lambda v: round(1 / v) if v else 10),
    "rush_td":          ("rush_td",           lambda v: v),
    "rush_2pt":         ("rush_2pt",          lambda v: v),
    "bonus_rush_yd_100":("rush_100_bonus",    lambda v: v),
    "rec":              ("rec_ppr",           lambda v: v),
    "bonus_rec_te":     ("te_rec_bonus",      lambda v: v),
    "rec_yd":           ("rec_yds_per_pt",    lambda v: round(1 / v) if v else 10),
    "rec_td":           ("rec_td",            lambda v: v),
    "rec_2pt":          ("rec_2pt",           lambda v: v),
    "bonus_rec_yd_100": ("rec_100_bonus",     lambda v: v),
    "fum_lost":         ("fumble_lost",       lambda v: v),
}


def import_league(league_id: str) -> dict:
    """Fetch scoring settings from a Sleeper league. Returns scoring dict."""
    r = requests.get(f"{_BASE}/league/{league_id}", timeout=10)
    if r.status_code == 404:
        raise ValueError(f"League '{league_id}' not found on Sleeper.")
    r.raise_for_status()

    data = r.json()
    raw = data.get("scoring_settings", {})

    scoring = DEFAULT_SCORING.copy()
    for sleeper_key, (my_key, convert) in _SLEEPER_MAP.items():
        if sleeper_key in raw:
            try:
                scoring[my_key] = convert(raw[sleeper_key])
            except Exception:
                pass

    return scoring


def get_league_name(league_id: str) -> str:
    r = requests.get(f"{_BASE}/league/{league_id}", timeout=10)
    r.raise_for_status()
    return r.json().get("name", league_id)
