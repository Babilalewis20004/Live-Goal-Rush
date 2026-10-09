"""Shared search ranking helpers (discovery §21/§22).

PostgreSQL stays the search engine: `pg_trgm` GIN indexes (created in the
Phase 4 migration, extended to articles in the discovery migration) make
`ILIKE '%q%'` and the trigram `%` operator index-assisted. Results are ordered
by *match quality tier* first -- exact, prefix, substring, fuzzy -- then by
trigram similarity, so "Arsenal" beats "Arsenal Women" beats "North Arsenal FC".
"""

from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.sql.elements import ColumnElement

MAX_QUERY_LENGTH = 100
# Below this, a trigram comparison is meaningless (a trigram needs 3 chars) and
# `ILIKE '%a%'` would match most of the table, so short queries are prefix-only.
FUZZY_MIN_LENGTH = 3

EXACT, PREFIX, CONTAINS, FUZZY = 0, 1, 2, 3


def normalize_query(raw: str) -> str:
    """Collapse whitespace and cap the length. Case is left alone (matching
    is case-insensitive in SQL); `lower()` is only for cache/dedup keys."""
    return " ".join(raw.split())[:MAX_QUERY_LENGTH]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def tier(column: ColumnElement, query: str) -> ColumnElement:
    """0 exact / 1 prefix / 2 contains / 3 fuzzy, for a text column."""
    escaped = escape_like(query.lower())
    lowered = func.lower(column)
    return case(
        (lowered == query.lower(), EXACT),
        (lowered.like(f"{escaped}%", escape="\\"), PREFIX),
        (lowered.like(f"%{escaped}%", escape="\\"), CONTAINS),
        else_=FUZZY,
    )


def matches(column: ColumnElement, query: str) -> ColumnElement:
    """The WHERE clause: substring match (prefix-only for 1-2 characters),
    plus trigram-fuzzy for longer queries so typos still find things."""
    escaped = escape_like(query)
    if len(query) < FUZZY_MIN_LENGTH:
        return column.ilike(f"{escaped}%", escape="\\")
    return column.ilike(f"%{escaped}%", escape="\\") | column.op("%")(query)


def similarity(column: ColumnElement, query: str) -> ColumnElement:
    return func.similarity(column, query)
