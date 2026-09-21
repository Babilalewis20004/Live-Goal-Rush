"""Static reference data for the mock football provider.

Team names, competitions, and players below are used purely to make the
Phase 1 mock feel realistic; kickoff times and match state are computed
dynamically (relative to "now") by `mock_provider.py` so that /live,
/today and /upcoming always return sensible data no matter when the app
is queried.
"""

from __future__ import annotations

COMPETITIONS: dict[str, dict[str, str]] = {
    "comp-ucl": {"name": "Champions League", "country": "Europe", "type": "international"},
    "comp-epl": {"name": "Premier League", "country": "England", "type": "league"},
    "comp-laliga": {"name": "LaLiga", "country": "Spain", "type": "league"},
    "comp-seriea": {"name": "Serie A", "country": "Italy", "type": "league"},
    "comp-bundesliga": {"name": "Bundesliga", "country": "Germany", "type": "league"},
    "comp-ligue1": {"name": "Ligue 1", "country": "France", "type": "league"},
}

TEAMS: dict[str, dict[str, str]] = {
    "t-rma": {"name": "Real Madrid", "short_name": "RMA", "country": "Spain"},
    "t-mci": {"name": "Manchester City", "short_name": "MCI", "country": "England"},
    "t-bay": {"name": "Bayern München", "short_name": "BAY", "country": "Germany"},
    "t-int": {"name": "Inter", "short_name": "INT", "country": "Italy"},
    "t-ars": {"name": "Arsenal", "short_name": "ARS", "country": "England"},
    "t-psg": {"name": "Paris Saint-Germain", "short_name": "PSG", "country": "France"},
    "t-liv": {"name": "Liverpool", "short_name": "LIV", "country": "England"},
    "t-che": {"name": "Chelsea", "short_name": "CHE", "country": "England"},
    "t-tot": {"name": "Tottenham Hotspur", "short_name": "TOT", "country": "England"},
    "t-new": {"name": "Newcastle United", "short_name": "NEW", "country": "England"},
    "t-mun": {"name": "Manchester United", "short_name": "MUN", "country": "England"},
    "t-avl": {"name": "Aston Villa", "short_name": "AVL", "country": "England"},
    "t-bha": {"name": "Brighton & Hove Albion", "short_name": "BHA", "country": "England"},
    "t-whu": {"name": "West Ham United", "short_name": "WHU", "country": "England"},
    "t-bar": {"name": "Barcelona", "short_name": "BAR", "country": "Spain"},
    "t-atm": {"name": "Atlético Madrid", "short_name": "ATM", "country": "Spain"},
    "t-sev": {"name": "Sevilla", "short_name": "SEV", "country": "Spain"},
    "t-bet": {"name": "Real Betis", "short_name": "BET", "country": "Spain"},
    "t-rso": {"name": "Real Sociedad", "short_name": "RSO", "country": "Spain"},
    "t-vil": {"name": "Villarreal", "short_name": "VIL", "country": "Spain"},
    "t-juv": {"name": "Juventus", "short_name": "JUV", "country": "Italy"},
    "t-nap": {"name": "Napoli", "short_name": "NAP", "country": "Italy"},
    "t-mil": {"name": "AC Milan", "short_name": "MIL", "country": "Italy"},
    "t-rom": {"name": "Roma", "short_name": "ROM", "country": "Italy"},
    "t-bvb": {"name": "Borussia Dortmund", "short_name": "BVB", "country": "Germany"},
    "t-b04": {"name": "Bayer Leverkusen", "short_name": "B04", "country": "Germany"},
    "t-rbl": {"name": "RB Leipzig", "short_name": "RBL", "country": "Germany"},
    "t-vfb": {"name": "VfB Stuttgart", "short_name": "VfB", "country": "Germany"},
    "t-om": {"name": "Marseille", "short_name": "OM", "country": "France"},
    "t-asm": {"name": "Monaco", "short_name": "ASM", "country": "France"},
    "t-ol": {"name": "Lyon", "short_name": "OL", "country": "France"},
    "t-lil": {"name": "Lille", "short_name": "LIL", "country": "France"},
}

PLAYERS: dict[str, dict[str, str]] = {
    "p-vinicius": {"name": "Vinícius Jr.", "position": "Forward"},
    "p-bellingham": {"name": "Bellingham", "position": "Midfielder"},
    "p-mbappe": {"name": "Mbappé", "position": "Forward"},
    "p-rodrygo": {"name": "Rodrygo", "position": "Forward"},
    "p-haaland": {"name": "Haaland", "position": "Forward"},
    "p-debruyne": {"name": "De Bruyne", "position": "Midfielder"},
    "p-rodri": {"name": "Rodri", "position": "Midfielder"},
    "p-foden": {"name": "Foden", "position": "Midfielder"},
    "p-grealish": {"name": "Grealish", "position": "Forward"},
    "p-kane": {"name": "Kane", "position": "Forward"},
    "p-musiala": {"name": "Musiala", "position": "Midfielder"},
    "p-barella": {"name": "Barella", "position": "Midfielder"},
    "p-salah": {"name": "Salah", "position": "Forward"},
    "p-szoboszlai": {"name": "Szoboszlai", "position": "Midfielder"},
    "p-nunez": {"name": "Núñez", "position": "Forward"},
    "p-gakpo": {"name": "Gakpo", "position": "Forward"},
    "p-robertson": {"name": "Robertson", "position": "Defender"},
    "p-palmer": {"name": "Palmer", "position": "Forward"},
    "p-caicedo": {"name": "Caicedo", "position": "Midfielder"},
    "p-bentancur": {"name": "Bentancur", "position": "Midfielder"},
    "p-fernandes": {"name": "Fernandes", "position": "Midfielder"},
    "p-hojlund": {"name": "Højlund", "position": "Forward"},
    "p-garnacho": {"name": "Garnacho", "position": "Forward"},
    "p-casemiro": {"name": "Casemiro", "position": "Midfielder"},
    "p-watkins": {"name": "Watkins", "position": "Forward"},
    "p-bailey": {"name": "Bailey", "position": "Forward"},
    "p-rogers": {"name": "Rogers", "position": "Midfielder"},
    "p-tielemans": {"name": "Tielemans", "position": "Midfielder"},
    "p-lewandowski": {"name": "Lewandowski", "position": "Forward"},
    "p-yamal": {"name": "Yamal", "position": "Forward"},
    "p-gundogan": {"name": "Gündoğan", "position": "Midfielder"},
    "p-griezmann": {"name": "Griezmann", "position": "Forward"},
    "p-isco": {"name": "Isco", "position": "Midfielder"},
    "p-fornals": {"name": "Fornals", "position": "Midfielder"},
    "p-navas": {"name": "Navas", "position": "Defender"},
    "p-kvaratskhelia": {"name": "Kvaratskhelia", "position": "Forward"},
    "p-politano": {"name": "Politano", "position": "Forward"},
    "p-locatelli": {"name": "Locatelli", "position": "Midfielder"},
    "p-leao": {"name": "Leão", "position": "Forward"},
    "p-pulisic": {"name": "Pulisic", "position": "Forward"},
    "p-giroud": {"name": "Giroud", "position": "Forward"},
    "p-reijnders": {"name": "Reijnders", "position": "Midfielder"},
    "p-cristante": {"name": "Cristante", "position": "Midfielder"},
    "p-wirtz": {"name": "Wirtz", "position": "Midfielder"},
    "p-grimaldo": {"name": "Grimaldo", "position": "Defender"},
    "p-adeyemi": {"name": "Adeyemi", "position": "Forward"},
    "p-brandt": {"name": "Brandt", "position": "Midfielder"},
    "p-boniface": {"name": "Boniface", "position": "Forward"},
    "p-fullkrug": {"name": "Füllkrug", "position": "Forward"},
    "p-schick": {"name": "Schick", "position": "Forward"},
    "p-frimpong": {"name": "Frimpong", "position": "Defender"},
    "p-can": {"name": "Can", "position": "Midfielder"},
    "p-benyedder": {"name": "Ben Yedder", "position": "Forward"},
    "p-golovin": {"name": "Golovin", "position": "Midfielder"},
    "p-aubameyang": {"name": "Aubameyang", "position": "Forward"},
    "p-harit": {"name": "Harit", "position": "Midfielder"},
    "p-balogun": {"name": "Balogun", "position": "Forward"},
    "p-fofana": {"name": "Fofana", "position": "Midfielder"},
    "p-veretout": {"name": "Veretout", "position": "Midfielder"},
}

# Each fixture's "kind" drives how mock_provider.py computes kickoff_time and
# status relative to "now" -- see `_STATUS_BUILDERS` there.
#   live       -> in progress right now, kickoff = now - minute
#   halftime   -> in progress, at the break
#   finished_today / finished_yesterday -> already completed
#   upcoming_today / upcoming_future    -> not started yet
FIXTURES: list[dict] = [
    dict(
        provider_id="ucl-1", competition="comp-ucl", home="t-rma", away="t-mci",
        kind="live", minute=74, home_score=2, away_score=2,
        venue="Santiago Bernabéu",
        events=[
            dict(minute=12, type="goal", side="home", player="p-vinicius", assist="p-bellingham"),
            dict(minute=23, type="goal", side="away", player="p-haaland", assist="p-debruyne"),
            dict(minute=34, type="yellow_card", side="away", player="p-rodri"),
            dict(minute=51, type="penalty", side="home", player="p-mbappe", description="Penalty"),
            dict(minute=66, type="goal", side="away", player="p-foden", assist="p-grealish"),
            dict(minute=70, type="substitution", side="home", player="p-rodrygo", assist="p-vinicius"),
        ],
    ),
    dict(
        provider_id="ucl-2", competition="comp-ucl", home="t-bay", away="t-int",
        kind="live", minute=58, home_score=1, away_score=0,
        venue="Allianz Arena",
        events=[
            dict(minute=28, type="goal", side="home", player="p-kane", assist="p-musiala"),
            dict(minute=41, type="yellow_card", side="away", player="p-barella"),
        ],
    ),
    dict(
        provider_id="ucl-3", competition="comp-ucl", home="t-ars", away="t-psg",
        kind="upcoming_today", hour=21, home_score=0, away_score=0,
        venue="Emirates Stadium", events=[],
    ),
    dict(
        provider_id="epl-1", competition="comp-epl", home="t-liv", away="t-che",
        kind="live", minute=63, home_score=3, away_score=1,
        venue="Anfield",
        events=[
            dict(minute=8, type="goal", side="home", player="p-salah", assist="p-szoboszlai"),
            dict(minute=19, type="penalty", side="away", player="p-palmer", description="Penalty"),
            dict(minute=37, type="goal", side="home", player="p-nunez", assist="p-salah"),
            dict(minute=45, type="yellow_card", side="away", player="p-caicedo"),
            dict(minute=58, type="goal", side="home", player="p-gakpo", assist="p-robertson"),
        ],
    ),
    dict(
        provider_id="epl-2", competition="comp-epl", home="t-tot", away="t-new",
        kind="halftime", minute=45, home_score=0, away_score=0,
        venue="Tottenham Hotspur Stadium",
        events=[dict(minute=31, type="yellow_card", side="home", player="p-bentancur")],
    ),
    dict(
        provider_id="epl-3", competition="comp-epl", home="t-mun", away="t-avl",
        kind="finished_today", hour=9, home_score=2, away_score=2,
        venue="Old Trafford",
        events=[
            dict(minute=14, type="goal", side="away", player="p-watkins", assist="p-bailey"),
            dict(minute=30, type="penalty", side="home", player="p-fernandes", description="Penalty"),
            dict(minute=62, type="goal", side="home", player="p-hojlund", assist="p-garnacho"),
            dict(minute=78, type="red_card", side="home", player="p-casemiro"),
            dict(minute=88, type="goal", side="away", player="p-rogers", assist="p-tielemans"),
        ],
    ),
    dict(
        provider_id="epl-4", competition="comp-epl", home="t-bha", away="t-whu",
        kind="upcoming_future", day_offset=1, hour=18, home_score=0, away_score=0,
        venue="Amex Stadium", events=[],
    ),
    dict(
        provider_id="ll-1", competition="comp-laliga", home="t-bar", away="t-atm",
        kind="live", minute=81, home_score=1, away_score=1,
        venue="Spotify Camp Nou",
        events=[
            dict(minute=44, type="goal", side="home", player="p-lewandowski", assist="p-yamal"),
            dict(minute=55, type="yellow_card", side="home", player="p-gundogan"),
            dict(minute=73, type="penalty", side="away", player="p-griezmann", description="Penalty"),
        ],
    ),
    dict(
        provider_id="ll-2", competition="comp-laliga", home="t-sev", away="t-bet",
        kind="finished_today", hour=11, home_score=0, away_score=1,
        venue="Ramón Sánchez-Pizjuán",
        events=[
            dict(minute=67, type="goal", side="away", player="p-isco", assist="p-fornals"),
            dict(minute=84, type="yellow_card", side="home", player="p-navas"),
        ],
    ),
    dict(
        provider_id="ll-3", competition="comp-laliga", home="t-rso", away="t-vil",
        kind="upcoming_today", hour=22, home_score=0, away_score=0,
        venue="Reale Arena", events=[],
    ),
    dict(
        provider_id="sa-1", competition="comp-seriea", home="t-juv", away="t-nap",
        kind="live", minute=39, home_score=0, away_score=1,
        venue="Allianz Stadium",
        events=[
            dict(minute=21, type="goal", side="away", player="p-kvaratskhelia", assist="p-politano"),
            dict(minute=35, type="yellow_card", side="home", player="p-locatelli"),
        ],
    ),
    dict(
        provider_id="sa-2", competition="comp-seriea", home="t-mil", away="t-rom",
        kind="finished_yesterday", hour=19, home_score=3, away_score=0,
        venue="San Siro",
        events=[
            dict(minute=18, type="goal", side="home", player="p-leao", assist="p-pulisic"),
            dict(minute=49, type="goal", side="home", player="p-giroud", assist="p-reijnders"),
            dict(minute=71, type="red_card", side="away", player="p-cristante"),
            dict(minute=83, type="goal", side="home", player="p-pulisic", assist="p-leao"),
        ],
    ),
    dict(
        provider_id="bl-1", competition="comp-bundesliga", home="t-bvb", away="t-b04",
        kind="live", minute=67, home_score=2, away_score=3,
        venue="Signal Iduna Park",
        events=[
            dict(minute=6, type="goal", side="away", player="p-wirtz", assist="p-grimaldo"),
            dict(minute=22, type="goal", side="home", player="p-adeyemi", assist="p-brandt"),
            dict(minute=38, type="goal", side="away", player="p-boniface", assist="p-wirtz"),
            dict(minute=44, type="penalty", side="home", player="p-fullkrug", description="Penalty"),
            dict(minute=59, type="goal", side="away", player="p-schick", assist="p-frimpong"),
            dict(minute=63, type="yellow_card", side="home", player="p-can"),
        ],
    ),
    dict(
        provider_id="bl-2", competition="comp-bundesliga", home="t-rbl", away="t-vfb",
        kind="upcoming_future", day_offset=1, hour=19, home_score=0, away_score=0,
        venue="Red Bull Arena", events=[],
    ),
    dict(
        provider_id="l1-1", competition="comp-ligue1", home="t-om", away="t-asm",
        kind="finished_yesterday", hour=21, home_score=1, away_score=2,
        venue="Stade Vélodrome",
        events=[
            dict(minute=25, type="goal", side="away", player="p-benyedder", assist="p-golovin"),
            dict(minute=52, type="goal", side="home", player="p-aubameyang", assist="p-harit"),
            dict(minute=79, type="goal", side="away", player="p-balogun", assist="p-fofana"),
            dict(minute=90, type="yellow_card", side="home", player="p-veretout"),
        ],
    ),
    dict(
        provider_id="l1-2", competition="comp-ligue1", home="t-ol", away="t-lil",
        kind="upcoming_future", day_offset=1, hour=20, home_score=0, away_score=0,
        venue="Groupama Stadium", events=[],
    ),
]

# Hand-authored standings per competition -- illustrative, not derived from
# the fixtures above (Phase 1 has no season-long results history yet).
STANDINGS: dict[str, list[dict]] = {
    "comp-epl": [
        {"team": "t-liv", "played": 8, "won": 6, "drawn": 1, "lost": 1, "gf": 19, "ga": 8},
        {"team": "t-mci", "played": 8, "won": 5, "drawn": 2, "lost": 1, "gf": 17, "ga": 9},
        {"team": "t-ars", "played": 8, "won": 5, "drawn": 1, "lost": 2, "gf": 15, "ga": 10},
        {"team": "t-che", "played": 8, "won": 4, "drawn": 2, "lost": 2, "gf": 14, "ga": 11},
        {"team": "t-tot", "played": 8, "won": 3, "drawn": 3, "lost": 2, "gf": 13, "ga": 12},
        {"team": "t-new", "played": 8, "won": 3, "drawn": 2, "lost": 3, "gf": 12, "ga": 12},
        {"team": "t-mun", "played": 8, "won": 3, "drawn": 1, "lost": 4, "gf": 11, "ga": 13},
        {"team": "t-avl", "played": 8, "won": 2, "drawn": 3, "lost": 3, "gf": 10, "ga": 13},
        {"team": "t-bha", "played": 8, "won": 2, "drawn": 2, "lost": 4, "gf": 9, "ga": 14},
        {"team": "t-whu", "played": 8, "won": 1, "drawn": 2, "lost": 5, "gf": 7, "ga": 15},
    ],
    "comp-laliga": [
        {"team": "t-bar", "played": 8, "won": 6, "drawn": 2, "lost": 0, "gf": 21, "ga": 7},
        {"team": "t-rma", "played": 8, "won": 6, "drawn": 1, "lost": 1, "gf": 18, "ga": 8},
        {"team": "t-atm", "played": 8, "won": 5, "drawn": 1, "lost": 2, "gf": 16, "ga": 10},
        {"team": "t-rso", "played": 8, "won": 4, "drawn": 2, "lost": 2, "gf": 13, "ga": 11},
        {"team": "t-vil", "played": 8, "won": 3, "drawn": 2, "lost": 3, "gf": 12, "ga": 12},
        {"team": "t-bet", "played": 8, "won": 3, "drawn": 1, "lost": 4, "gf": 10, "ga": 13},
        {"team": "t-sev", "played": 8, "won": 1, "drawn": 3, "lost": 4, "gf": 8, "ga": 14},
    ],
    "comp-seriea": [
        {"team": "t-nap", "played": 8, "won": 6, "drawn": 1, "lost": 1, "gf": 17, "ga": 7},
        {"team": "t-mil", "played": 8, "won": 5, "drawn": 2, "lost": 1, "gf": 16, "ga": 9},
        {"team": "t-juv", "played": 8, "won": 4, "drawn": 3, "lost": 1, "gf": 14, "ga": 8},
        {"team": "t-rom", "played": 8, "won": 3, "drawn": 2, "lost": 3, "gf": 11, "ga": 12},
    ],
    "comp-bundesliga": [
        {"team": "t-b04", "played": 8, "won": 6, "drawn": 1, "lost": 1, "gf": 22, "ga": 10},
        {"team": "t-bay", "played": 8, "won": 6, "drawn": 0, "lost": 2, "gf": 20, "ga": 9},
        {"team": "t-bvb", "played": 8, "won": 4, "drawn": 2, "lost": 2, "gf": 16, "ga": 13},
        {"team": "t-rbl", "played": 8, "won": 4, "drawn": 1, "lost": 3, "gf": 14, "ga": 12},
        {"team": "t-vfb", "played": 8, "won": 2, "drawn": 2, "lost": 4, "gf": 11, "ga": 15},
    ],
    "comp-ligue1": [
        {"team": "t-psg", "played": 8, "won": 7, "drawn": 1, "lost": 0, "gf": 23, "ga": 6},
        {"team": "t-asm", "played": 8, "won": 5, "drawn": 1, "lost": 2, "gf": 16, "ga": 10},
        {"team": "t-om", "played": 8, "won": 4, "drawn": 1, "lost": 3, "gf": 13, "ga": 11},
        {"team": "t-lil", "played": 8, "won": 3, "drawn": 2, "lost": 3, "gf": 10, "ga": 11},
        {"team": "t-ol", "played": 8, "won": 2, "drawn": 2, "lost": 4, "gf": 9, "ga": 14},
    ],
    "comp-ucl": [
        {"team": "t-rma", "played": 6, "won": 5, "drawn": 1, "lost": 0, "gf": 16, "ga": 6},
        {"team": "t-bay", "played": 6, "won": 4, "drawn": 1, "lost": 1, "gf": 14, "ga": 7},
        {"team": "t-mci", "played": 6, "won": 4, "drawn": 0, "lost": 2, "gf": 13, "ga": 8},
        {"team": "t-int", "played": 6, "won": 3, "drawn": 1, "lost": 2, "gf": 10, "ga": 8},
        {"team": "t-ars", "played": 6, "won": 2, "drawn": 2, "lost": 2, "gf": 9, "ga": 9},
        {"team": "t-psg", "played": 6, "won": 2, "drawn": 1, "lost": 3, "gf": 8, "ga": 10},
    ],
}
