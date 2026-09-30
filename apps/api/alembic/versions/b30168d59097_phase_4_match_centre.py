"""phase 4: match centre (lineups, statistics, seasons, search indexes)

Non-destructive for an existing Phase 3 database:
  * every new column on an existing table is nullable or defaulted;
  * `standings.season` is added with a temporary default, backfilled with the
    current season label for rows synced before seasons existed, then the
    default is dropped so new writes must state their season;
  * `pg_trgm` is required for the trigram search indexes (a trusted
    extension on PostgreSQL 13+, so the database owner can create it).

Revision ID: b30168d59097
Revises: 490ba085e61c
Create Date: 2026-09-30 22:05:04.154682

"""
from typing import Sequence, Union

from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b30168d59097'
down_revision: Union[str, None] = '490ba085e61c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _current_season_label(today: date) -> str:
    # Mirrors app/services/season.py (duplicated on purpose: migrations must
    # not import application code that may change after they were written).
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('match_lineups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('formation', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'team_id', name='uq_match_lineups_match_team')
    )
    op.create_index(op.f('ix_match_lineups_match_id'), 'match_lineups', ['match_id'], unique=False)
    op.create_table('match_statistics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('possession', sa.Float(), nullable=True),
    sa.Column('shots', sa.Integer(), nullable=True),
    sa.Column('shots_on_target', sa.Integer(), nullable=True),
    sa.Column('corners', sa.Integer(), nullable=True),
    sa.Column('fouls', sa.Integer(), nullable=True),
    sa.Column('offsides', sa.Integer(), nullable=True),
    sa.Column('yellow_cards', sa.Integer(), nullable=True),
    sa.Column('red_cards', sa.Integer(), nullable=True),
    sa.Column('pass_accuracy', sa.Float(), nullable=True),
    sa.Column('expected_goals', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'team_id', name='uq_match_statistics_match_team')
    )
    op.create_index(op.f('ix_match_statistics_match_id'), 'match_statistics', ['match_id'], unique=False)
    op.create_table('player_match_statistics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('minutes_played', sa.Integer(), nullable=True),
    sa.Column('goals', sa.Integer(), nullable=True),
    sa.Column('assists', sa.Integer(), nullable=True),
    sa.Column('shots', sa.Integer(), nullable=True),
    sa.Column('shots_on_target', sa.Integer(), nullable=True),
    sa.Column('passes', sa.Integer(), nullable=True),
    sa.Column('pass_accuracy', sa.Float(), nullable=True),
    sa.Column('key_passes', sa.Integer(), nullable=True),
    sa.Column('tackles', sa.Integer(), nullable=True),
    sa.Column('interceptions', sa.Integer(), nullable=True),
    sa.Column('clearances', sa.Integer(), nullable=True),
    sa.Column('blocks', sa.Integer(), nullable=True),
    sa.Column('yellow_cards', sa.Integer(), nullable=True),
    sa.Column('red_cards', sa.Integer(), nullable=True),
    sa.Column('fouls_committed', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'player_id', name='uq_player_match_statistics_match_player')
    )
    op.create_index(op.f('ix_player_match_statistics_match_id'), 'player_match_statistics', ['match_id'], unique=False)
    op.create_index(op.f('ix_player_match_statistics_player_id'), 'player_match_statistics', ['player_id'], unique=False)
    op.create_table('player_season_statistics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=True),
    sa.Column('competition_id', sa.Integer(), nullable=False),
    sa.Column('season', sa.String(length=16), nullable=False),
    sa.Column('appearances', sa.Integer(), nullable=True),
    sa.Column('goals', sa.Integer(), nullable=False),
    sa.Column('assists', sa.Integer(), nullable=True),
    sa.Column('penalties', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'competition_id', 'season', name='uq_player_season_statistics_player_comp_season')
    )
    op.create_index('ix_player_season_statistics_comp_season_goals', 'player_season_statistics', ['competition_id', 'season', 'goals'], unique=False)
    op.create_index(op.f('ix_player_season_statistics_player_id'), 'player_season_statistics', ['player_id'], unique=False)
    op.create_table('lineup_players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lineup_id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('is_starter', sa.Boolean(), nullable=False),
    sa.Column('position', sa.String(length=50), nullable=True),
    sa.Column('shirt_number', sa.Integer(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['lineup_id'], ['match_lineups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lineup_id', 'player_id', name='uq_lineup_players_lineup_player')
    )
    op.create_index(op.f('ix_lineup_players_lineup_id'), 'lineup_players', ['lineup_id'], unique=False)
    op.create_index(op.f('ix_lineup_players_player_id'), 'lineup_players', ['player_id'], unique=False)
    op.create_index('ix_competitions_name_trgm', 'competitions', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.add_column('match_events', sa.Column('event_detail', sa.String(length=128), nullable=True))
    op.create_index('ix_matches_away_team_kickoff', 'matches', ['away_team_id', 'kickoff_time'], unique=False)
    op.create_index('ix_matches_home_team_kickoff', 'matches', ['home_team_id', 'kickoff_time'], unique=False)
    op.add_column('players', sa.Column('nationality', sa.String(length=100), nullable=True))
    op.add_column('players', sa.Column('shirt_number', sa.Integer(), nullable=True))
    op.add_column('players', sa.Column('profile_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_players_name_trgm', 'players', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.add_column('standings', sa.Column('season', sa.String(length=16), nullable=False, server_default='pending'))
    op.execute(
        sa.text("UPDATE standings SET season = :season").bindparams(season=_current_season_label(date.today()))
    )
    op.alter_column('standings', 'season', server_default=None)
    op.add_column('standings', sa.Column('group_name', sa.String(length=64), server_default='', nullable=False))
    op.add_column('standings', sa.Column('description', sa.String(length=128), nullable=True))
    op.add_column('standings', sa.Column('form', sa.String(length=16), nullable=True))
    op.drop_constraint(op.f('uq_standings_competition_team'), 'standings', type_='unique')
    op.create_index('ix_standings_competition_season', 'standings', ['competition_id', 'season'], unique=False)
    op.create_unique_constraint('uq_standings_competition_season_group_team', 'standings', ['competition_id', 'season', 'group_name', 'team_id'])
    op.add_column('teams', sa.Column('venue', sa.String(length=255), nullable=True))
    op.create_index('ix_teams_name_trgm', 'teams', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})


def downgrade() -> None:
    # NOTE: restoring the Phase 3 (competition_id, team_id) unique constraint
    # fails if more than one season of standings has been stored since.
    op.drop_index('ix_teams_name_trgm', table_name='teams', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_column('teams', 'venue')
    op.drop_constraint('uq_standings_competition_season_group_team', 'standings', type_='unique')
    op.drop_index('ix_standings_competition_season', table_name='standings')
    op.create_unique_constraint(op.f('uq_standings_competition_team'), 'standings', ['competition_id', 'team_id'], postgresql_nulls_not_distinct=False)
    op.drop_column('standings', 'form')
    op.drop_column('standings', 'description')
    op.drop_column('standings', 'group_name')
    op.drop_column('standings', 'season')
    op.drop_index('ix_players_name_trgm', table_name='players', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_column('players', 'profile_synced_at')
    op.drop_column('players', 'shirt_number')
    op.drop_column('players', 'nationality')
    op.drop_index('ix_matches_home_team_kickoff', table_name='matches')
    op.drop_index('ix_matches_away_team_kickoff', table_name='matches')
    op.drop_column('match_events', 'event_detail')
    op.drop_index('ix_competitions_name_trgm', table_name='competitions', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_lineup_players_player_id'), table_name='lineup_players')
    op.drop_index(op.f('ix_lineup_players_lineup_id'), table_name='lineup_players')
    op.drop_table('lineup_players')
    op.drop_index(op.f('ix_player_season_statistics_player_id'), table_name='player_season_statistics')
    op.drop_index('ix_player_season_statistics_comp_season_goals', table_name='player_season_statistics')
    op.drop_table('player_season_statistics')
    op.drop_index(op.f('ix_player_match_statistics_player_id'), table_name='player_match_statistics')
    op.drop_index(op.f('ix_player_match_statistics_match_id'), table_name='player_match_statistics')
    op.drop_table('player_match_statistics')
    op.drop_index(op.f('ix_match_statistics_match_id'), table_name='match_statistics')
    op.drop_table('match_statistics')
    op.drop_index(op.f('ix_match_lineups_match_id'), table_name='match_lineups')
    op.drop_table('match_lineups')
