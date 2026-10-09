"""Team/player analytics, comparison, extended form/H2H and entitlement shaping (Phase 6b)."""

from datetime import timedelta

import pytest

from app.models.billing import Entitlement
from app.models.enums import MatchStatus
from app.services.billing import entitlements as ent
from tests.football_data import NOW, add_player_stats, history, make_competition, make_match, make_player, make_team

API = "/api/v1"


async def grant(sf, user_id, *keys):
    async with sf() as s:
        for k in keys:
            s.add(Entitlement(user_id=user_id, key=k, source="test"))
        await s.commit()


@pytest.fixture
async def world(session_factory):
    """Reds (A) and Blues (B) with 6 finished meetings/results each, with statistics on some matches only."""
    comp = await make_competition(session_factory)
    a, b, c = await make_team(session_factory, "Reds"), await make_team(session_factory, "Blues"), await make_team(session_factory, "Greens")
    # Reds' results (oldest first): W 2-0 (h), D 1-1 (a), L 0-2 (h), W 3-1 (a), W 1-0 (h), D 0-0 (a)
    plan = [(a, c, 2, 0), (c, a, 1, 1), (a, c, 0, 2), (c, a, 1, 3), (a, c, 1, 0), (c, a, 0, 0)]
    ids = []
    for i, (h, aw, hs, as_) in enumerate(plan):
        stats = None
        if i >= 2:  # only the last four matches have team statistics
            stats = {
                a: dict(possession=60.0 + i, shots=10 + i, shots_on_target=4, fouls=9, yellow_cards=1, red_cards=0, pass_accuracy=80.0, expected_goals=1.5),
                c: dict(possession=40.0, shots=5, shots_on_target=2, fouls=11, yellow_cards=2, red_cards=0),
            }
        ids.append(await make_match(session_factory, comp, h, aw, 40 - i * 5, hs, as_, stats=stats))
    upcoming = await make_match(session_factory, comp, a, b, -2, status=MatchStatus.SCHEDULED)
    return dict(comp=comp, a=a, b=b, c=c, ids=ids, upcoming=upcoming)


async def test_basic_team_analytics_is_public_and_withholds_premium_sections(client, world):
    r = await client.get(f"{API}/teams/{world['a']}/analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "basic" and body["matches_considered"] == 6
    assert body["record"] == {"played": 6, "wins": 3, "draws": 2, "losses": 1, "points": 11, "points_per_match": 1.83}
    assert set(body["attack"]) == {"goals", "goals_per_match"} and body["attack"]["goals"]["value"] == 7.0
    assert body["defence"]["clean_sheets"]["value"] == 3.0  # 2-0, 1-0, 0-0
    assert body["possession"] == {} and body["discipline"] == {}
    assert set(body["locked"]) == {"attack", "possession", "defence", "discipline"}


async def test_premium_team_analytics_is_provider_aware_and_never_fabricates(client, world, session_factory, make_user):
    user, headers = await make_user("prem@example.com")
    await grant(session_factory, user.id, ent.ADVANCED_ANALYTICS)
    body = (await client.get(f"{API}/teams/{world['a']}/analytics", headers=headers)).json()
    assert body["tier"] == "full" and body["locked"] == []
    # statistics exist for 4 of 6 matches: the sample says so, and conversion only uses those matches
    shots = body["attack"]["shots"]
    assert shots["sample"] == 4 and shots["value"] == 12 + 13 + 14 + 15
    assert body["possession"]["possession_pct"]["sample"] == 4
    assert body["possession"]["possession_pct"]["value"] == pytest.approx((62 + 63 + 64 + 65) / 4, abs=0.01)  # 63.5
    assert body["attack"]["expected_goals"]["sample"] == 4
    # no player statistics were stored, so those are None -- not zero
    assert body["attack"]["assists"] == {"value": None, "sample": 0}
    assert body["defence"]["tackles"] == {"value": None, "sample": 0}
    assert "progressive_passes" in body["unavailable"]
    assert any("4 of 6" in x for x in body["limitations"])


async def test_longer_windows_need_extended_history(client, world, session_factory, make_user):
    user, headers = await make_user("prem@example.com")
    assert (await client.get(f"{API}/teams/{world['a']}/analytics?window=20")).status_code == 402
    r = await client.get(f"{API}/teams/{world['a']}/analytics?window=20", headers=headers)
    assert r.status_code == 402 and r.json()["detail"]["entitlement"] == ent.EXTENDED_HISTORY
    await grant(session_factory, user.id, ent.EXTENDED_HISTORY)
    ok = await client.get(f"{API}/teams/{world['a']}/analytics?window=20", headers=headers)
    assert ok.status_code == 200 and ok.json()["window"] == 20
    assert any("Only 6 of the last 20" in x for x in ok.json()["limitations"])


async def test_home_away_scopes_and_unknown_inputs(client, world):
    home = (await client.get(f"{API}/teams/{world['a']}/analytics?scope=home")).json()
    assert home["matches_considered"] == 3 and home["record"]["wins"] == 2
    assert (await client.get(f"{API}/teams/{world['a']}/analytics?scope=sideways")).status_code == 422
    assert (await client.get(f"{API}/teams/{world['a']}/analytics?window=7")).status_code == 422
    assert (await client.get(f"{API}/teams/999999/analytics")).status_code == 404


async def test_a_team_without_matches_gets_an_honest_empty_answer(client, world):
    body = (await client.get(f"{API}/teams/{world['b']}/analytics")).json()
    assert body["matches_considered"] == 0 and body["record"]["points_per_match"] is None
    assert body["attack"]["goals_per_match"]["value"] is None
    assert body["limitations"] and "No finished matches" in body["limitations"][0]


async def test_extended_form_has_streaks_and_requires_extended_history(client, world, session_factory, make_user):
    user, headers = await make_user("prem@example.com")
    assert (await client.get(f"{API}/teams/{world['a']}/form/extended?limit=10", headers=headers)).status_code == 402
    await grant(session_factory, user.id, ent.EXTENDED_HISTORY)
    body = (await client.get(f"{API}/teams/{world['a']}/form/extended?limit=10", headers=headers)).json()
    s = body["summary"]
    assert body["limit"] == 10 and s["played"] == 6 and s["requested"] == 10 and not s["complete"]
    assert "Only 6 of the last 10" in s["limitation"]
    assert s["unbeaten_streak"] == 3 and s["win_streak"] == 0 and s["clean_sheet_streak"] == 2 and s["scoring_streak"] == 0
    # the free last-5 form still works, anonymously, and carries the summary too
    free = (await client.get(f"{API}/teams/{world['a']}/form")).json()
    assert free["limit"] == 5 and free["summary"]["played"] == 5 and free["summary"]["complete"]
    assert free["sequence"] == "DLWWD"  # oldest -> newest, latest on the right


async def test_head_to_head_windows_and_totals(client, world, session_factory, make_user):
    a, b, comp = world["a"], world["b"], world["comp"]
    for i, (hosted, hs, as_) in enumerate([(True, 2, 1), (False, 1, 1), (True, 0, 3), (False, 0, 2), (True, 1, 0), (False, 2, 2), (True, 4, 0)]):
        h, aw = (a, b) if hosted else (b, a)
        await make_match(session_factory, comp, h, aw, 300 - i * 20, hs, as_)
    user, headers = await make_user("prem@example.com")
    default = (await client.get(f"{API}/matches/{world['upcoming']}/head-to-head")).json()
    assert default["window"] == "last5" and default["total_meetings"] == 5 and default["limit"] == 5
    assert (await client.get(f"{API}/matches/{world['upcoming']}/head-to-head/extended?window=all", headers=headers)).status_code == 402
    await grant(session_factory, user.id, ent.EXTENDED_HISTORY)
    everything = (await client.get(f"{API}/matches/{world['upcoming']}/head-to-head/extended?window=all", headers=headers)).json()
    assert everything["total_meetings"] == 7 and everything["limit"] is None and everything["complete"]
    # Reds' perspective, oldest first: W D L W W D W -> 4 wins, 2 draws, 1 loss; goals 12 for, 7 against
    assert (everything["home_team_wins"], everything["draws"], everything["away_team_wins"]) == (4, 2, 1)
    assert (everything["home_team_goals"], everything["away_team_goals"]) == (12, 7)
    assert everything["average_goals"] == pytest.approx(19 / 7, abs=0.01)
    assert everything["recent_form"] == "WDLWWDW"
    ten = (await client.get(f"{API}/matches/{world['upcoming']}/head-to-head/extended?window=last10", headers=headers)).json()
    assert ten["total_meetings"] == 7 and not ten["complete"] and "Only 7 of the last 10" in ten["limitation"]


async def test_comparison_free_vs_premium_is_enforced_server_side(client, world, session_factory, make_user):
    user, headers = await make_user("prem@example.com")
    free = (await client.get(f"{API}/matches/{world['upcoming']}/comparison")).json()
    keys = {r["key"] for r in free["rows"]}
    assert free["tier"] == "basic" and keys == {"points_per_match", "goals_for", "goals_against", "clean_sheets"}
    assert "possession" in free["locked"] and free["form_window"] == 5
    assert free["home_form"]["played"] == 5  # the free last-5 view
    await grant(session_factory, user.id, ent.ADVANCED_COMPARISON)
    full = (await client.get(f"{API}/matches/{world['upcoming']}/comparison", headers=headers)).json()
    assert full["tier"] == "full" and full["form_window"] == 10 and full["locked"] == []
    assert {"possession", "shots", "xg", "tackles", "fouls"} <= {r["key"] for r in full["rows"]}
    possession = next(r for r in full["rows"] if r["key"] == "possession")
    assert possession["higher_is_better"] is None and possession["premium"] is True
    # Blues have no matches: their side is empty, never zero
    assert possession["away"] is None and possession["away_sample"] == 0
    assert (await client.get(f"{API}/matches/999999/comparison")).status_code == 404


async def test_premium_state_is_not_cached_across_users(client, world, session_factory, make_user):
    """A cached full comparison must not be served to a free caller afterwards, or vice versa."""
    user, headers = await make_user("prem@example.com")
    await grant(session_factory, user.id, ent.ADVANCED_COMPARISON, ent.ADVANCED_ANALYTICS)
    assert (await client.get(f"{API}/matches/{world['upcoming']}/comparison", headers=headers)).json()["tier"] == "full"
    assert (await client.get(f"{API}/matches/{world['upcoming']}/comparison")).json()["tier"] == "basic"
    assert (await client.get(f"{API}/teams/{world['a']}/analytics", headers=headers)).json()["tier"] == "full"
    assert (await client.get(f"{API}/teams/{world['a']}/analytics")).json()["tier"] == "basic"


async def test_player_analytics_basic_history_and_premium_detail(client, world, session_factory, make_user):
    a, comp = world["a"], world["comp"]
    striker = await make_player(session_factory, "Sam Striker", a)
    for i, (mins, goals, assists, shots, kp) in enumerate([(90, 1, 0, 4, 2), (80, 0, 1, 2, 3), (90, 2, 0, 5, 1)]):
        mid = world["ids"][3 + i]
        await add_player_stats(session_factory, mid, striker, a, minutes_played=mins, goals=goals, assists=assists, shots=shots, key_passes=kp)
    free = (await client.get(f"{API}/players/{striker}/analytics")).json()
    assert free["tier"] == "basic" and free["recent"] == [] and free["totals"] == {}
    assert "recent_matches" in free["locked"]
    user, headers = await make_user("prem@example.com")
    await grant(session_factory, user.id, ent.PLAYER_ANALYTICS)
    full = (await client.get(f"{API}/players/{striker}/analytics", headers=headers)).json()
    assert full["tier"] == "full" and full["matches_with_statistics"] == 3 and len(full["recent"]) == 3
    assert full["totals"]["goals"] == {"value": 3.0, "sample": 3}
    assert full["per_90"]["goals"]["value"] == pytest.approx(3 / 260 * 90, abs=0.01)
    assert full["form_goal_involvements"] == [1, 1, 2]  # oldest -> newest: 1g, 1a, 2g
    assert "expected_goals" in full["unavailable"]  # xG is not stored, and is not invented
    assert (await client.get(f"{API}/players/999999/analytics")).status_code == 404


async def test_players_with_no_statistics_say_so(client, world, session_factory):
    p = await make_player(session_factory, "Nobody Stats", world["a"])
    body = (await client.get(f"{API}/players/{p}/analytics")).json()
    assert body["seasons"] == []
    anon = await client.get(f"{API}/players/{p}/analytics?window=10")
    assert anon.status_code == 200
