import requests
from urllib.parse import urlencode
from scoring import DEFAULT_SCORING

_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Yahoo stat ID → (my key, conversion)
# Yahoo stores pts-per-unit (e.g., "0.04" for pass yards)
_YAHOO_STAT_MAP = {
    "4":  ("pass_yds_per_pt",  lambda v: round(1 / float(v)) if float(v) else 25),
    "5":  ("pass_td",          lambda v: float(v)),
    "6":  ("pass_int",         lambda v: float(v)),
    "9":  ("pass_2pt",         lambda v: float(v)),
    "14": ("rush_yds_per_pt",  lambda v: round(1 / float(v)) if float(v) else 10),
    "15": ("rush_td",          lambda v: float(v)),
    "16": ("rush_2pt",         lambda v: float(v)),
    "17": ("rec_ppr",          lambda v: float(v)),
    "18": ("rec_yds_per_pt",   lambda v: round(1 / float(v)) if float(v) else 10),
    "19": ("rec_td",           lambda v: float(v)),
    "20": ("rec_2pt",          lambda v: float(v)),
    "23": ("fumble_lost",      lambda v: float(v)),
}


def get_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "language": "en-us",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    """Exchange OAuth authorization code for access token."""
    r = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def import_league(league_id: str, access_token: str) -> dict:
    """Fetch scoring settings from a Yahoo Fantasy Football league."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    url = f"{_API_BASE}/league/nfl.l.{league_id}/settings"
    r = requests.get(url, params={"format": "json"}, headers=headers, timeout=15)
    if r.status_code == 401:
        raise ValueError("Yahoo session expired — please reconnect.")
    if r.status_code == 404:
        raise ValueError(f"Yahoo league '{league_id}' not found.")
    r.raise_for_status()

    data = r.json()
    try:
        stat_mods = (
            data["fantasy_content"]["league"][1]["settings"]["stat_modifiers"]["stats"]["stat"]
        )
    except (KeyError, IndexError, TypeError):
        raise ValueError("Could not parse Yahoo scoring settings — unexpected response format.")

    scoring = DEFAULT_SCORING.copy()
    for item in stat_mods:
        stat_id = str(item.get("stat_id", ""))
        value = item.get("value", "0")
        if stat_id in _YAHOO_STAT_MAP:
            my_key, convert = _YAHOO_STAT_MAP[stat_id]
            try:
                scoring[my_key] = convert(value)
            except Exception:
                pass

    return scoring


def get_league_name(league_id: str, access_token: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"{_API_BASE}/league/nfl.l.{league_id}/metadata"
    r = requests.get(url, params={"format": "json"}, headers=headers, timeout=15)
    r.raise_for_status()
    try:
        return r.json()["fantasy_content"]["league"][0]["name"]
    except Exception:
        return league_id
