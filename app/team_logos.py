"""Team name to ESPN logo URL mapping for NBA, NHL, and NFL teams."""

# ESPN CDN base URL for team logos
_ESPN_LOGO_BASE = "https://a.espncdn.com/i/teamlogos"

# Mapping: ESPN displayName -> (league_path, abbreviation)
_TEAM_MAP: dict[str, tuple[str, str]] = {
    # ── NBA ──────────────────────────────────────────────────
    "Atlanta Hawks": ("nba", "atl"),
    "Boston Celtics": ("nba", "bos"),
    "Brooklyn Nets": ("nba", "bkn"),
    "Charlotte Hornets": ("nba", "cha"),
    "Chicago Bulls": ("nba", "chi"),
    "Cleveland Cavaliers": ("nba", "cle"),
    "Dallas Mavericks": ("nba", "dal"),
    "Denver Nuggets": ("nba", "den"),
    "Detroit Pistons": ("nba", "det"),
    "Golden State Warriors": ("nba", "gs"),
    "Houston Rockets": ("nba", "hou"),
    "Indiana Pacers": ("nba", "ind"),
    "LA Clippers": ("nba", "lac"),
    "Los Angeles Clippers": ("nba", "lac"),
    "Los Angeles Lakers": ("nba", "lal"),
    "Memphis Grizzlies": ("nba", "mem"),
    "Miami Heat": ("nba", "mia"),
    "Milwaukee Bucks": ("nba", "mil"),
    "Minnesota Timberwolves": ("nba", "min"),
    "New Orleans Pelicans": ("nba", "no"),
    "New York Knicks": ("nba", "ny"),
    "Oklahoma City Thunder": ("nba", "okc"),
    "Orlando Magic": ("nba", "orl"),
    "Philadelphia 76ers": ("nba", "phi"),
    "Phoenix Suns": ("nba", "phx"),
    "Portland Trail Blazers": ("nba", "por"),
    "Sacramento Kings": ("nba", "sac"),
    "San Antonio Spurs": ("nba", "sa"),
    "Toronto Raptors": ("nba", "tor"),
    "Utah Jazz": ("nba", "utah"),
    "Washington Wizards": ("nba", "wsh"),
    # ── NHL ──────────────────────────────────────────────────
    "Anaheim Ducks": ("nhl", "ana"),
    "Arizona Coyotes": ("nhl", "ari"),
    "Boston Bruins": ("nhl", "bos"),
    "Buffalo Sabres": ("nhl", "buf"),
    "Calgary Flames": ("nhl", "cgy"),
    "Carolina Hurricanes": ("nhl", "car"),
    "Chicago Blackhawks": ("nhl", "chi"),
    "Colorado Avalanche": ("nhl", "col"),
    "Columbus Blue Jackets": ("nhl", "cbj"),
    "Dallas Stars": ("nhl", "dal"),
    "Detroit Red Wings": ("nhl", "det"),
    "Edmonton Oilers": ("nhl", "edm"),
    "Florida Panthers": ("nhl", "fla"),
    "Los Angeles Kings": ("nhl", "la"),
    "Minnesota Wild": ("nhl", "min"),
    "Montreal Canadiens": ("nhl", "mtl"),
    "Montréal Canadiens": ("nhl", "mtl"),
    "Nashville Predators": ("nhl", "nsh"),
    "New Jersey Devils": ("nhl", "nj"),
    "New York Islanders": ("nhl", "nyi"),
    "New York Rangers": ("nhl", "nyr"),
    "Ottawa Senators": ("nhl", "ott"),
    "Philadelphia Flyers": ("nhl", "phi"),
    "Pittsburgh Penguins": ("nhl", "pit"),
    "San Jose Sharks": ("nhl", "sj"),
    "Seattle Kraken": ("nhl", "sea"),
    "St. Louis Blues": ("nhl", "stl"),
    "St Louis Blues": ("nhl", "stl"),
    "Tampa Bay Lightning": ("nhl", "tb"),
    "Toronto Maple Leafs": ("nhl", "tor"),
    "Utah Hockey Club": ("nhl", "utah"),
    "Vancouver Canucks": ("nhl", "van"),
    "Vegas Golden Knights": ("nhl", "vgs"),
    "Washington Capitals": ("nhl", "wsh"),
    "Winnipeg Jets": ("nhl", "wpg"),
    # ── NFL ──────────────────────────────────────────────────
    "Arizona Cardinals": ("nfl", "ari"),
    "Atlanta Falcons": ("nfl", "atl"),
    "Baltimore Ravens": ("nfl", "bal"),
    "Buffalo Bills": ("nfl", "buf"),
    "Carolina Panthers": ("nfl", "car"),
    "Chicago Bears": ("nfl", "chi"),
    "Cincinnati Bengals": ("nfl", "cin"),
    "Cleveland Browns": ("nfl", "cle"),
    "Dallas Cowboys": ("nfl", "dal"),
    "Denver Broncos": ("nfl", "den"),
    "Detroit Lions": ("nfl", "det"),
    "Green Bay Packers": ("nfl", "gb"),
    "Houston Texans": ("nfl", "hou"),
    "Indianapolis Colts": ("nfl", "ind"),
    "Jacksonville Jaguars": ("nfl", "jax"),
    "Kansas City Chiefs": ("nfl", "kc"),
    "Las Vegas Raiders": ("nfl", "lv"),
    "Los Angeles Chargers": ("nfl", "lac"),
    "Los Angeles Rams": ("nfl", "lar"),
    "Miami Dolphins": ("nfl", "mia"),
    "Minnesota Vikings": ("nfl", "min"),
    "New England Patriots": ("nfl", "ne"),
    "New Orleans Saints": ("nfl", "no"),
    "New York Giants": ("nfl", "nyg"),
    "New York Jets": ("nfl", "nyj"),
    "Philadelphia Eagles": ("nfl", "phi"),
    "Pittsburgh Steelers": ("nfl", "pit"),
    "San Francisco 49ers": ("nfl", "sf"),
    "Seattle Seahawks": ("nfl", "sea"),
    "Tampa Bay Buccaneers": ("nfl", "tb"),
    "Tennessee Titans": ("nfl", "ten"),
    "Washington Commanders": ("nfl", "wsh"),
}

# League-level logos
_LEAGUE_LOGOS: dict[str, str] = {
    "NBA": "https://a.espncdn.com/i/teamlogos/leagues/500/nba.png",
    "NHL": "https://a.espncdn.com/i/teamlogos/leagues/500/nhl.png",
    "NFL": "https://a.espncdn.com/i/teamlogos/leagues/500/nfl.png",
}


def team_logo_url(team_name: str, size: int = 500) -> str:
    """Return ESPN CDN logo URL for a team display name.

    Falls back to a generic placeholder when the team isn't recognized.
    """
    entry = _TEAM_MAP.get(team_name)
    if entry:
        league_path, abbrev = entry
        return f"{_ESPN_LOGO_BASE}/{league_path}/{size}/{abbrev}.png"
    return ""


def league_logo_url(league: str) -> str:
    """Return ESPN CDN logo URL for a league (NBA, NHL, NFL)."""
    return _LEAGUE_LOGOS.get(league.upper(), "")
