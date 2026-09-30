from pydantic import BaseModel


class CapabilitiesOut(BaseModel):
    match_events: bool
    lineups: bool
    match_statistics: bool
    player_statistics: bool
    team_squads: bool
    player_profiles: bool
    standings: bool
    top_scorers: bool
    venues: bool
    head_to_head: bool = True
    """Derived from stored results, so always available (may be empty)."""
    form: bool = True
