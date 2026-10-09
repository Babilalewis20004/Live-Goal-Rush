"""Responses of the administrator API (Phase 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AdminUserOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: str
    is_active: bool
    suspended_at: datetime | None
    suspended_reason: str | None
    deleted_at: datetime | None
    created_at: datetime
    subscription_status: str | None = None
    subscription_plan: str | None = None


class AdminSubscriptionOut(BaseModel):
    plan: str
    status: str
    provider: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    created_at: datetime


class AdminUserDetail(AdminUserOut):
    subscriptions: list[AdminSubscriptionOut]
    entitlements: list[str]
    open_reports_against: int


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: int | None
    actor_label: str
    action: str
    target_type: str
    target_id: str
    reason: str | None
    details: dict[str, Any] | None


class FailedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_name: str
    task_id: str | None
    error_type: str
    error_message: str
    classification: str
    retries: int
    occurrences: int
    entity: str | None
    args_summary: str | None
    request_id: str | None
    failed_at: datetime
    resolved_at: datetime | None


class ResolveRequest(BaseModel):
    note: str | None = None


class SystemStatusOut(BaseModel):
    version: str
    environment: str
    database: str
    redis: str
    provider: dict[str, Any]
    queue_length: int | None
    unresolved_failed_jobs: int
    websocket_connections: int
    db_pool: dict[str, int]
    data_freshness: dict[str, Any]
    unresolved_reports: dict[str, int]
    recent_payment_event_failures: int
