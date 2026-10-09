"""Public profiles, badges and football insights (Phase 6)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.models.competition import Competition
from app.models.enums import UserRole
from app.models.team import Team
from app.models.user import User
from app.schemas.competition import CompetitionOut
from app.schemas.form import FormResultOut, HeadToHeadMeetingOut, HeadToHeadOut
from app.schemas.team import TeamOut
from app.services.insights_service import head_to_head_insights, team_insights
from app.services.profile_service import compute_badges

API = "/api/v1"


# -- profiles --------------------------------------------------------------------------------------


async def test_profiles_are_private_by_default_and_indistinguishable_from_missing(client, make_user):
    user, headers = await make_user("fan@example.com")
    assert (await client.get(f"{API}/profiles/{user.id}")).status_code == 404
    assert (await client.get(f"{API}/profiles/999999")).status_code == 404  # same answer: no probing
    mine = (await client.get(f"{API}/users/me/profile", headers=headers)).json()
    assert mine["profile_public"] is False and mine["id"] == user.id  # the owner always sees their own
    assert (await client.get(f"{API}/users/me/profile")).status_code == 401


async def test_making_a_profile_public_exposes_only_the_safe_fields(seeded_client, make_user, lookup, publish_article):
    user, headers = await make_user("fan.private@example.com")
    arsenal, pl = await lookup(Team, "Arsenal"), await lookup(Competition, "Premier League")
    await seeded_client.post(f"{API}/favourites/teams/{arsenal}", headers=headers)
    await seeded_client.post(f"{API}/favourites/competitions/{pl}", headers=headers)
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    story = await publish_article(editor, "A story to talk about")
    await seeded_client.post(f"{API}/comments", json={"target_type": "article", "target_id": story["id"], "body": "Great story"}, headers=headers)

    updated = await seeded_client.patch(f"{API}/users/me/profile", json={"profile_public": True, "bio": "  Gooner   since  '98 "}, headers=headers)
    assert updated.status_code == 200 and updated.json()["bio"] == "Gooner since '98"

    profile = await seeded_client.get(f"{API}/profiles/{user.id}")  # anonymous
    assert profile.status_code == 200
    body = profile.json()
    assert body["display_name"] == "Fan.Private" and body["bio"] == "Gooner since '98"
    assert [t["name"] for t in body["favourite_teams"]] == ["Arsenal"]
    assert [c["name"] for c in body["favourite_competitions"]] == ["Premier League"]
    assert body["stats"] == {"comments": 1, "poll_votes": 0, "followed_teams": 1, "followed_competitions": 1}
    assert [a["text"] for a in body["activity"]] == ["Great story"] and body["activity"][0]["target_label"] == "A story to talk about"
    assert {b["key"] for b in body["badges"]} == {"first_word"}
    # nothing private leaks
    text = profile.text
    for secret in ("fan.private@example.com", "email", "role", "hashed", "profile_public", "password"):
        assert secret not in text.lower().replace("display_name", "")


async def test_going_private_again_hides_it_and_hidden_things_stay_hidden(client, make_user, publish_article):
    user, headers = await make_user("fan@example.com")
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    story = await publish_article(editor, "Soon to be unpublished")
    await client.patch(f"{API}/users/me/profile", json={"profile_public": True}, headers=headers)
    comment = (await client.post(f"{API}/comments", json={"target_type": "article", "target_id": story["id"], "body": "Visible for now"}, headers=headers)).json()
    assert len((await client.get(f"{API}/profiles/{user.id}")).json()["activity"]) == 1
    await client.post(f"{API}/editor/articles/{story['id']}/unpublish", headers=editor)
    assert (await client.get(f"{API}/profiles/{user.id}")).json()["activity"] == []  # the article is gone, so is its trace
    await client.patch(f"{API}/users/me/profile", json={"profile_public": False}, headers=headers)
    assert (await client.get(f"{API}/profiles/{user.id}")).status_code == 404
    assert comment["id"]


async def test_deactivated_users_have_no_public_profile(client, make_user, session_factory):
    user, headers = await make_user("fan@example.com")
    await client.patch(f"{API}/users/me/profile", json={"profile_public": True}, headers=headers)
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await session.commit()
    assert (await client.get(f"{API}/profiles/{user.id}")).status_code == 404


async def test_profile_updates_are_validated_and_partial(client, make_user):
    _, headers = await make_user("fan@example.com")
    assert (await client.patch(f"{API}/users/me/profile", json={"bio": "x" * 281}, headers=headers)).status_code == 422
    await client.patch(f"{API}/users/me/profile", json={"bio": "Hello"}, headers=headers)
    kept = (await client.patch(f"{API}/users/me/profile", json={"profile_public": True}, headers=headers)).json()
    assert kept["bio"] == "Hello" and kept["profile_public"] is True  # unspecified fields untouched
    assert (await client.patch(f"{API}/users/me/profile", json={"bio": "   "}, headers=headers)).json()["bio"] is None


def test_badge_rules():
    def keys(**kw):
        base = dict(comments=0, poll_votes=0, followed_teams=0, role=UserRole.USER, published_articles=0)
        return {b.key for b in compute_badges(**{**base, **kw})}

    assert keys() == set()
    assert keys(comments=1) == {"first_word"}
    assert keys(comments=10) == {"commentator"} and keys(comments=50) == {"regular"}
    assert keys(poll_votes=5) == {"pollster"} and keys(poll_votes=4) == set()
    assert keys(followed_teams=3) == {"supporter"}
    assert keys(role=UserRole.EDITOR, published_articles=2) == {"editor", "writer"}
    assert keys(role=UserRole.AUTHOR, published_articles=0) == set()
    assert "admin" in keys(role=UserRole.ADMIN)


# -- insights (pure) -------------------------------------------------------------------------------------


def _team(i=1, name="Reds"):
    return TeamOut(id=i, name=name, short_name=None, country=None, logo_url=None)


def _results(spec: str):
    """spec like "W2-0 W1-0 D1-1 L0-3": most recent first."""
    comp = CompetitionOut(id=1, name="League", country=None, logo_url=None, type="league")
    out = []
    for n, token in enumerate(spec.split()):
        gf, ga = (int(x) for x in token[1:].split("-"))
        out.append(
            FormResultOut(
                match_id=n, result=token[0], venue="home", opponent=_team(9, "Opp"), goals_for=gf, goals_against=ga,
                kickoff_time=datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(days=n), competition=comp,
            )
        )
    return out


def test_no_insights_without_enough_history():
    assert team_insights("Reds", []) == []
    assert team_insights("Reds", _results("W1-0 W2-0")) == []  # two results is anecdote, not insight


def test_form_summary_and_win_streak():
    insights = {i.key: i for i in team_insights("Reds", _results("W2-0 W1-0 W3-1 D1-1 L0-2 L0-1"))}
    assert insights["form_summary"].text == "Reds: won 3, drew 1, lost 1 of the last 5."
    assert insights["win_streak"].value == 3 and "won their last 3" in insights["win_streak"].text
    assert insights["unbeaten_run"].value == 4  # longer than the win streak, so worth saying too
    assert insights["goal_average"].text == "Reds averaged 1.4 goals scored and 0.8 conceded over the last 5."


def test_an_unbeaten_run_equal_to_the_win_streak_is_not_said_twice():
    keys = {i.key for i in team_insights("Reds", _results("W2-0 W1-0 W3-1 L1-2 D0-0"))}
    assert "win_streak" in keys and "unbeaten_run" not in keys


def test_unbeaten_losing_and_winless_runs():
    unbeaten = {i.key for i in team_insights("Reds", _results("D1-1 W1-0 D0-0 W2-1 L0-1"))}
    assert "unbeaten_run" in unbeaten and "win_streak" not in unbeaten
    losing = {i.key: i for i in team_insights("Reds", _results("L0-1 L1-3 L0-2 W1-0"))}
    assert losing["losing_streak"].value == 3
    assert "winless_run" not in losing  # the losing streak already says it
    winless = {i.key: i for i in team_insights("Reds", _results("D0-0 D1-1 D2-2 W1-0"))}
    assert winless["winless_run"].value == 3 and "unbeaten_run" in winless


def test_clean_sheets_blanks_and_scoring_runs():
    clean = {i.key: i for i in team_insights("Reds", _results("W1-0 W2-0 D0-0 L1-2 W3-1"))}
    assert clean["clean_sheets"].value == 3 and "3 clean sheets" in clean["clean_sheets"].text
    blanks = {i.key: i for i in team_insights("Reds", _results("L0-1 D0-0 W1-0 W2-0 W1-0"))}
    assert blanks["blanks"].value == 2
    scoring = {i.key: i for i in team_insights("Reds", _results("W1-0 D1-1 W2-1 L1-2 D0-0"))}
    assert "scoring_run" in scoring and scoring["scoring_run"].value == 4
    assert "scoring_run" not in {i.key for i in team_insights("Reds", _results("W1-0 D1-1 W2-1"))}  # needs 4+


def _h2h(*scores):
    comp = CompetitionOut(id=1, name="League", country=None, logo_url=None, type="league")
    meetings = [
        HeadToHeadMeetingOut(
            match_id=i, kickoff_time=datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(days=30 * i), competition=comp,
            home_team=_team(1, "Reds"), away_team=_team(2, "Blues"), home_score=h, away_score=a,
        )
        for i, (h, a) in enumerate(scores)
    ]
    wins = sum(h > a for h, a in scores)
    losses = sum(a > h for h, a in scores)
    return HeadToHeadOut(
        home_team_id=1, away_team_id=2, limit=5, period_start=datetime(2016, 1, 1, tzinfo=timezone.utc),
        before=datetime(2026, 6, 1, tzinfo=timezone.utc), meetings=meetings,
        home_team_wins=wins, draws=len(scores) - wins - losses, away_team_wins=losses,
    )


def test_head_to_head_summary():
    assert head_to_head_insights("Reds", "Blues", _h2h((1, 0), (2, 2))) == []
    insights = {i.key: i for i in head_to_head_insights("Reds", "Blues", _h2h((2, 1), (0, 0), (1, 3), (2, 2)))}
    assert insights["h2h_record"].text == "Last 4 meetings: Reds 1 win, Blues 1 win, 2 draws."
    assert insights["h2h_last"].text.startswith("Most recent meeting: Reds 2-1 Blues")
    assert insights["h2h_goals"].text == "These meetings averaged 2.8 goals; both teams scored in 3 of 4."


# -- insights (API) ----------------------------------------------------------------------------------------


async def test_team_insights_endpoint(seeded_client, lookup):
    arsenal = await lookup(Team, "Arsenal")
    body = (await seeded_client.get(f"{API}/teams/{arsenal}/insights")).json()
    assert body["team_name"] == "Arsenal" and body["sample_size"] >= 3
    keys = {i["key"] for i in body["insights"]}
    assert "form_summary" in keys and "goal_average" in keys
    assert all(i["text"] for i in body["insights"])
    assert (await seeded_client.get(f"{API}/teams/999999/insights")).status_code == 404


async def test_a_team_with_no_history_gets_no_insights_not_invented_ones(client, session_factory):
    async with session_factory() as session:
        team = Team(provider_id="new-team", name="Brand New FC")
        session.add(team)
        await session.commit()
        team_id = team.id
    body = (await client.get(f"{API}/teams/{team_id}/insights")).json()
    assert body == {"team_id": team_id, "team_name": "Brand New FC", "sample_size": 0, "insights": []}


async def test_match_insights_endpoint(seeded_client, session_factory):
    from app.models.match import Match

    async with session_factory() as session:
        match_id = (await session.execute(select(Match.id).where(Match.provider_id == "epl-1"))).scalar_one()
    body = (await seeded_client.get(f"{API}/matches/{match_id}/insights")).json()
    assert body["match_id"] == match_id and body["note"] == "Historical results only. Not a prediction."
    assert body["home"]["team_name"] and body["away"]["team_name"]
    assert body["home"]["sample_size"] >= 3
    text = str(body).lower()
    for forbidden in ("will win", "predict", "likely to", "odds", "chance of"):
        assert forbidden not in text.replace("not a prediction", "")
    assert (await seeded_client.get(f"{API}/matches/999999/insights")).status_code == 404
