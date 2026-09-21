"""phase 2: realtime infrastructure

Adds what Phase 2's background sync/cache/change-detection pipeline needs
on top of Phase 1's schema:

- `matches.last_synced_at` -- when a match row was last written by a
  provider sync, used to compute stale-data status (spec §21).
- `standings` table -- competition tables are now persisted (synced by the
  worker) instead of only ever being fetched live from the provider, so
  `GET /competitions/{id}/standings` can be served cache-aside from the
  database on a cache miss (spec §5/§23).
- a unique `(match_id, provider_id)` constraint on `match_events` -- match
  events now have a stable identity so re-syncing upserts in place instead
  of delete-and-reinsert, which is what makes event ids stable across polls
  for change detection and real deduplication (spec §24/§25).

Revision ID: ad4916a7b31a
Revises: f95a7852dc3f
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad4916a7b31a'
down_revision: Union[str, None] = 'f95a7852dc3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('matches', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))

    op.create_unique_constraint(
        'uq_match_events_match_provider', 'match_events', ['match_id', 'provider_id']
    )

    op.create_table(
        'standings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('competition_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('played', sa.Integer(), nullable=False),
        sa.Column('won', sa.Integer(), nullable=False),
        sa.Column('drawn', sa.Integer(), nullable=False),
        sa.Column('lost', sa.Integer(), nullable=False),
        sa.Column('goals_for', sa.Integer(), nullable=False),
        sa.Column('goals_against', sa.Integer(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('competition_id', 'team_id', name='uq_standings_competition_team'),
    )
    op.create_index(op.f('ix_standings_competition_id'), 'standings', ['competition_id'], unique=False)
    op.create_index(op.f('ix_standings_team_id'), 'standings', ['team_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_standings_team_id'), table_name='standings')
    op.drop_index(op.f('ix_standings_competition_id'), table_name='standings')
    op.drop_table('standings')

    op.drop_constraint('uq_match_events_match_provider', 'match_events', type_='unique')

    op.drop_column('matches', 'last_synced_at')
