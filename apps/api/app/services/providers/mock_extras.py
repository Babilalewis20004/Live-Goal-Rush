"""Phase 4 additions to the mock provider's dataset: squads, lineups, match
and player statistics, historical results, top scorers, standings zones.

Everything here is *generated deterministically* from the static pool in
`mock_data.py` so the development stack has something to show for every
Phase 4 screen. It is fixture data for the mock provider only -- a real
provider returns what it actually has (see `real_provider.py`), and the
app never computes any of this itself. Squads are padded with clearly
labelled generic players ("ARS Player 12") rather than invented names.
"""

from __future__ import annotations

import hashlib
from app.services.providers.mock_data import COMPETITIONS, FIXTURES, PLAYERS, STANDINGS, TEAMS


def h(*args: object) -> int:
    """Stable small hash (md5, so it is identical across processes -- unlike
    Python's salted `hash()`). The LAST argument is the modulus; the rest
    are hashed: `h("match-1", "shots", 10)` -> 0..9."""
    *parts, mod = args
    digest = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16) % int(mod)


# -- venues ---------------------------------------------------------------------

TEAM_VENUES: dict[str, str] = {}
for _fixture in FIXTURES:
    if _fixture.get("venue"):
        TEAM_VENUES.setdefault(_fixture["home"], _fixture["venue"])

# -- squads -----------------------------------------------------------------------

PLAYER_TEAM: dict[str, str] = {}
for _fixture in FIXTURES:
    for _event in _fixture.get("events", []):
        _team = _fixture["home"] if _event["side"] == "home" else _fixture["away"]
        for _key in ("player", "assist"):
            if _event.get(_key):
                PLAYER_TEAM.setdefault(_event[_key], _team)

# (position, shirt number) slots of an 18-man squad.
_SLOTS: list[tuple[str, int]] = [
    ("Goalkeeper", 1), ("Goalkeeper", 13),
    ("Defender", 2), ("Defender", 3), ("Defender", 4), ("Defender", 5), ("Defender", 12), ("Defender", 15),
    ("Midfielder", 6), ("Midfielder", 8), ("Midfielder", 10), ("Midfielder", 14), ("Midfielder", 16),
    ("Midfielder", 18),
    ("Forward", 7), ("Forward", 9), ("Forward", 11), ("Forward", 17),
]  # fmt: skip

_squad_cache: dict[str, list[dict]] = {}


def build_squad(team_id: str) -> list[dict]:
    if team_id in _squad_cache:
        return _squad_cache[team_id]
    team = TEAMS[team_id]
    slots: list[dict | None] = [None] * len(_SLOTS)
    for pid, owner in PLAYER_TEAM.items():
        if owner != team_id:
            continue
        position = PLAYERS[pid]["position"]
        for index, (slot_position, number) in enumerate(_SLOTS):
            if slots[index] is None and slot_position == position:
                slots[index] = {
                    "provider_id": pid,
                    "name": PLAYERS[pid]["name"],
                    "position": position,
                    "shirt_number": number,
                    "nationality": None,
                }
                break
    squad: list[dict] = []
    for index, (position, number) in enumerate(_SLOTS):
        squad.append(
            slots[index]
            or {
                "provider_id": f"p-{team_id[2:]}-{number}",
                "name": f"{team['short_name']} Player {number}",
                "position": position,
                "shirt_number": number,
                "nationality": team["country"],
            }
        )
    _squad_cache[team_id] = squad
    return squad


def player_index() -> dict[str, tuple[dict, str]]:
    """provider_id -> (player dict, team id) across every squad."""
    index: dict[str, tuple[dict, str]] = {}
    for team_id in TEAMS:
        for player in build_squad(team_id):
            index[player["provider_id"]] = (player, team_id)
    return index


# -- lineups -----------------------------------------------------------------------

_FORMATION_QUOTAS = {"Goalkeeper": 1, "Defender": 4, "Midfielder": 3, "Forward": 3}
_POSITION_ORDER = ["Goalkeeper", "Defender", "Midfielder", "Forward"]


def build_lineup(fixture: dict, side: str) -> dict:
    """Starting XI + bench for one side. Decided from *all* authored events
    (not just the revealed ones) so a live match's lineup is stable as the
    clock advances: anyone who is substituted on starts on the bench,
    anyone who scores / is carded / is substituted off starts."""
    team_id = fixture["home"] if side == "home" else fixture["away"]
    squad = build_squad(team_id)
    events = [e for e in fixture.get("events", []) if e["side"] == side]
    on_ids = {e["player"] for e in events if e["type"] == "substitution" and e.get("player")}
    participants: list[str] = []
    for e in events:
        for key in ("player", "assist"):
            pid = e.get(key)
            if pid and pid not in on_ids and pid not in participants:
                participants.append(pid)

    by_position = {p: [pl for pl in squad if pl["position"] == p] for p in _POSITION_ORDER}
    starters: list[dict] = []
    for position in _POSITION_ORDER:
        quota = _FORMATION_QUOTAS[position]
        candidates = by_position[position]
        preferred = [pl for pl in candidates if pl["provider_id"] in participants]
        rest = [pl for pl in candidates if pl["provider_id"] not in participants and pl["provider_id"] not in on_ids]
        starters.extend((preferred + rest)[:quota])
    starter_ids = {pl["provider_id"] for pl in starters}
    bench = [pl for pl in squad if pl["provider_id"] not in starter_ids]
    bench.sort(key=lambda pl: (pl["provider_id"] not in on_ids, pl["shirt_number"]))
    formation = "-".join(str(_FORMATION_QUOTAS[p]) for p in _POSITION_ORDER[1:])
    return {"team_id": team_id, "formation": formation, "starters": starters, "bench": bench}


# -- match statistics -------------------------------------------------------------------


def team_statistics(fixture: dict, side: str, fraction: float, revealed: list[dict]) -> dict:
    key = fixture["provider_id"]
    goals = sum(1 for e in revealed if e["side"] == side and e["type"] in ("goal", "penalty"))
    goals += sum(1 for e in revealed if e["side"] != side and e["type"] == "own_goal")
    home_possession = 42 + h(key, "possession", 17)
    shots = max(round((7 + h(key, side, "shots", 10)) * fraction), goals)
    on_target = min(shots, max(goals, round((2 + h(key, side, "sot", 5)) * fraction)))
    cards = [e for e in revealed if e["side"] == side]
    return {
        "possession": float(home_possession if side == "home" else 100 - home_possession),
        "shots": shots,
        "shots_on_target": on_target,
        "corners": round((3 + h(key, side, "corners", 6)) * fraction),
        "fouls": round((8 + h(key, side, "fouls", 7)) * fraction),
        "offsides": round((1 + h(key, side, "offsides", 4)) * fraction),
        "yellow_cards": sum(1 for e in cards if e["type"] in ("yellow_card", "second_yellow")),
        "red_cards": sum(1 for e in cards if e["type"] == "red_card"),
        "pass_accuracy": float(76 + h(key, side, "passacc", 15)),
        # expected_goals intentionally omitted: demonstrates that an
        # unsupplied statistic stays "not available" end to end.
    }


def player_statistics(fixture: dict, side: str, fraction: float, revealed: list[dict]) -> list[dict]:
    """Per-player stats for everyone who has played: starters, plus
    substitutes who have come on."""
    lineup = build_lineup(fixture, side)
    key = fixture["provider_id"]
    subs_on = {e["player"]: e["minute"] for e in revealed if e["side"] == side and e["type"] == "substitution"}
    subs_off = {e["assist"]: e["minute"] for e in revealed if e["side"] == side and e["type"] == "substitution"}
    elapsed = round(90 * fraction)
    rows: list[dict] = []
    for player in lineup["starters"] + lineup["bench"]:
        pid = player["provider_id"]
        started = player in lineup["starters"]
        if not started and pid not in subs_on:
            continue
        start = 0 if started else subs_on[pid]
        end = subs_off.get(pid, elapsed)
        minutes = max(0, end - start)
        share = minutes / 90
        position = player["position"]
        attacking = position in ("Forward", "Midfielder")
        rows.append(
            {
                "player": player,
                "minutes_played": minutes,
                "goals": sum(1 for e in revealed if e["side"] == side and e.get("player") == pid and e["type"] in ("goal", "penalty")),
                "assists": sum(1 for e in revealed if e["side"] == side and e.get("assist") == pid and e["type"] in ("goal", "penalty")),
                "shots": round((h(key, pid, "shots", 4) + (1 if attacking else 0)) * share),
                "shots_on_target": round(h(key, pid, "sot", 3) * share * (1 if attacking else 0.3)),
                "passes": round((25 + h(key, pid, "passes", 45)) * share),
                "pass_accuracy": float(68 + h(key, pid, "pacc", 27)),
                "key_passes": round(h(key, pid, "kp", 3) * share),
                "tackles": round(h(key, pid, "tk", 5) * share),
                "interceptions": round(h(key, pid, "int", 4) * share),
                "clearances": round(h(key, pid, "clr", 6) * share * (2 if position == "Defender" else 0.5)),
                "blocks": round(h(key, pid, "blk", 3) * share),
                "yellow_cards": sum(1 for e in revealed if e["side"] == side and e.get("player") == pid and e["type"] in ("yellow_card", "second_yellow")),
                "red_cards": sum(1 for e in revealed if e["side"] == side and e.get("player") == pid and e["type"] == "red_card"),
                "fouls_committed": round(h(key, pid, "fouls", 3) * share),
            }
        )
    return rows


# -- history (finished past meetings, for form + head-to-head) ------------------------


def history_fixtures() -> list[dict]:
    """Two past meetings between every pair of the first six teams of each
    competition's table, at fixed days-ago offsets (so the dataset is the
    same every day). Gives form (>=5 results for those teams) and
    head-to-head history. Teams outside the top six have no history --
    deliberately, so the empty states stay exercised."""
    fixtures: list[dict] = []
    for competition, rows in STANDINGS.items():
        teams = [row["team"] for row in rows][:6]
        for i, a in enumerate(teams):
            for b in teams[i + 1 :]:
                for n, (home, away, base, spread) in enumerate(((a, b, 12, 90), (b, a, 120, 200))):
                    key = f"{competition}-{a}-{b}-{n}"
                    fixtures.append(
                        dict(
                            provider_id=f"hist-{key}",
                            competition=competition,
                            home=home,
                            away=away,
                            kind="history",
                            days_ago=base + h(key, "days", spread),
                            hour=15 + h(key, "hour", 6),
                            home_score=h(key, "hs", 4),
                            away_score=h(key, "as", 3),
                            venue=TEAM_VENUES.get(home),
                            events=[],
                        )
                    )
    return fixtures


# -- top scorers / standings -----------------------------------------------------------


def top_scorers(competition_id: str) -> list[dict]:
    teams = {row["team"]: row for row in STANDINGS.get(competition_id, [])}
    rows: list[dict] = []
    for pid, team_id in PLAYER_TEAM.items():
        if team_id not in teams:
            continue
        position = PLAYERS[pid]["position"]
        base = {"Forward": 3 + h(pid, competition_id, "g", 7), "Midfielder": 1 + h(pid, competition_id, "g", 4)}.get(
            position, h(pid, competition_id, "g", 3)
        )
        if base <= 0:
            continue
        rows.append(
            {
                "player_id": pid,
                "team_id": team_id,
                "goals": base,
                "assists": h(pid, competition_id, "a", 6),
                "appearances": max(base, teams[team_id]["played"] - h(pid, competition_id, "app", 2)),
                "penalties": h(pid, competition_id, "pen", base + 1) // 2 if position == "Forward" else 0,
            }
        )
    rows.sort(key=lambda r: (-r["goals"], -r["assists"], PLAYERS[r["player_id"]]["name"]))
    return rows[:10]


def standing_description(competition_id: str, position: int, size: int) -> str | None:
    """Mock-only zone labels. A real provider supplies its own
    classifications -- the app never hard-codes competition rules."""
    if competition_id in ("comp-epl", "comp-laliga"):
        if position <= 4:
            return "Champions League"
        if position >= size:
            return "Relegation"
    elif competition_id in ("comp-seriea", "comp-ligue1"):
        if position <= 2:
            return "Champions League"
        if position >= size:
            return "Relegation"
    elif competition_id == "comp-bundesliga":
        if position <= 2:
            return "Champions League"
        if position >= size:
            return "Relegation play-off"
    elif competition_id == "comp-ucl" and position <= 4:
        return "Knockout stage"
    return None


def standing_form(competition_id: str, team_id: str, won: int, drawn: int, played: int) -> str:
    chars = []
    for n in range(5):
        r = h(competition_id, team_id, "form", n, played * 2) if played else 0
        chars.append("W" if r < won * 2 else "D" if r < (won + drawn) * 2 else "L")
    return "".join(chars)


__all__ = [
    "COMPETITIONS",
    "TEAM_VENUES",
    "PLAYER_TEAM",
    "build_squad",
    "player_index",
    "build_lineup",
    "team_statistics",
    "player_statistics",
    "history_fixtures",
    "top_scorers",
    "standing_description",
    "standing_form",
]
