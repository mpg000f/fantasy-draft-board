import requests
import pandas as pd
from io import StringIO
from bs4 import BeautifulSoup
import streamlit as st

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}

_STAT_COLS = [
    "passing_yds", "passing_tds", "passing_ints",
    "rushing_yds", "rushing_tds",
    "receiving_rec", "receiving_yds", "receiving_tds",
    "misc_fl", "fp_fpts",
]

_ADP_URLS = {
    "Standard": "https://www.fantasypros.com/nfl/adp/overall.php",
    "Half PPR": "https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php",
    "Full PPR": "https://www.fantasypros.com/nfl/adp/ppr-overall.php",
}


def _parse_name_team(raw: str):
    """Split 'Josh Allen BUF' → ('Josh Allen', 'BUF'). DST entries return (name, '')."""
    raw = str(raw).strip()
    parts = raw.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].upper() in _NFL_TEAMS:
        return parts[0], parts[1].upper()
    return raw, ""


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten multi-index columns, stripping 'Unnamed' prefixes."""
    if isinstance(df.columns, pd.MultiIndex):
        cols = []
        for col in df.columns:
            parts = [str(c).lower().replace(" ", "_") for c in col if not str(c).lower().startswith("unnamed")]
            cols.append("_".join(parts) if parts else str(col[-1]).lower().replace(" ", "_"))
        df.columns = cols
    else:
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    return df


def _standardize_columns(df: pd.DataFrame, pos: str) -> pd.DataFrame:
    """Rename position-specific FantasyPros column names to standard schema."""
    rename = {}
    for col in df.columns:
        if "passing_yd" in col:
            rename[col] = "passing_yds"
        elif "passing_td" in col:
            rename[col] = "passing_tds"
        elif "passing_int" in col:
            rename[col] = "passing_ints"
        elif "rushing_yd" in col:
            rename[col] = "rushing_yds"
        elif "rushing_td" in col:
            rename[col] = "rushing_tds"
        elif col in ("receiving_rec", "rec"):
            rename[col] = "receiving_rec"
        elif "receiving_yd" in col:
            rename[col] = "receiving_yds"
        elif "receiving_td" in col:
            rename[col] = "receiving_tds"
        elif col in ("misc_fl", "fl", "fum_lost"):
            rename[col] = "misc_fl"
        elif col in ("misc_fpts", "fpts"):
            rename[col] = "fp_fpts"

    df = df.rename(columns=rename)

    for col in _STAT_COLS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def _fetch_position(pos: str, week: str) -> pd.DataFrame | None:
    url = f"https://www.fantasypros.com/nfl/projections/{pos}.php?scoring=PPR&week={week}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find("table", id="data") or soup.find("table")
        if table is None:
            return None
        df = pd.read_html(StringIO(str(table)))[0]
        df = _flatten_columns(df)

        # Identify and rename player column
        player_col = df.columns[0]
        df = df.rename(columns={player_col: "player_raw"})
        df[["player", "team"]] = pd.DataFrame(
            df["player_raw"].map(_parse_name_team).tolist(), index=df.index
        )
        df["position"] = pos.upper()
        df = _standardize_columns(df, pos)

        keep = ["player", "team", "position"] + _STAT_COLS
        return df[[c for c in keep if c in df.columns]]
    except Exception as e:
        st.warning(f"Could not fetch {pos.upper()} projections: {e}")
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_projections(week: str = "draft") -> pd.DataFrame:
    """Fetch FantasyPros projections for all positions and return combined DataFrame."""
    frames = []
    for pos in ["qb", "rb", "wr", "te", "k", "dst"]:
        df = _fetch_position(pos, week)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["player"].str.strip() != ""]
    return combined


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_consensus_rankings() -> pd.DataFrame:
    """Fetch FantasyPros expert consensus rankings by position (preseason).

    Returns DataFrame with player, team, position, pos_rank columns.
    FantasyPros renders rankings via a JSON blob in the page script (ecrData).
    """
    import re, json

    frames = []
    for pos in ["qb", "rb", "wr", "te", "k", "dst"]:
        url = f"https://www.fantasypros.com/nfl/rankings/{pos}.php?week=draft"
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            ecr_match = None
            for script in soup.find_all("script"):
                txt = script.string or ""
                if "ecrData" in txt:
                    ecr_match = re.search(r"var ecrData\s*=\s*(\{.*?\});", txt, re.DOTALL)
                    break
            if not ecr_match:
                continue
            data = json.loads(ecr_match.group(1))
            players = data.get("players", [])
            rows = []
            for p in players:
                # pos_rank is like "RB3" — extract the number
                pr_raw = str(p.get("pos_rank", ""))
                pr_num = int(re.sub(r"[^0-9]", "", pr_raw)) if re.search(r"\d", pr_raw) else None
                if pr_num is None:
                    continue
                rows.append({
                    "player": p.get("player_name", ""),
                    "team": p.get("player_team_id", ""),
                    "position": p.get("player_position_id", pos.upper()),
                    "pos_rank": pr_num,
                })
            if rows:
                frames.append(pd.DataFrame(rows))
        except Exception as e:
            st.warning(f"Could not fetch {pos.upper()} consensus rankings: {e}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_adp(scoring_label: str = "Half PPR") -> pd.DataFrame:
    """Fetch FantasyPros consensus ADP matching the scoring format."""
    url = _ADP_URLS.get(scoring_label, _ADP_URLS["Half PPR"])
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        tables = pd.read_html(StringIO(r.text))
        if not tables:
            return pd.DataFrame()
        df = tables[0]
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
        # Player column is typically index 1; AVG column contains ADP
        player_col = df.columns[1]
        avg_col = next((c for c in df.columns if "avg" in c), None)
        if avg_col is None:
            return pd.DataFrame()
        df = df[[player_col, avg_col]].rename(columns={player_col: "player_raw", avg_col: "adp"})
        df["adp"] = pd.to_numeric(df["adp"], errors="coerce")
        df[["player", "team"]] = pd.DataFrame(
            df["player_raw"].map(_parse_name_team).tolist(), index=df.index
        )
        return df[["player", "adp"]].dropna()
    except Exception:
        return pd.DataFrame()
