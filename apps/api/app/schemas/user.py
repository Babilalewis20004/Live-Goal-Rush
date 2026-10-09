from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    role: UserRole
    created_at: datetime


def _normalise_email(value: str) -> str:
    """Addresses are matched case-insensitively (the CLI already lowercases): `Bob@x.com` and `bob@x.com` are
    one account, one rate-limit bucket, one reset target."""
    return value.strip().lower()


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str
    display_name: str | None = Field(default=None, max_length=100)

    _lower_email = field_validator("email", mode="after")(_normalise_email)

    @model_validator(mode="after")
    def passwords_match(self) -> "UserRegister":
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)

    _lower_email = field_validator("email", mode="after")(_normalise_email)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class AccountDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """Only ever included in a response body when the request identified
    itself as `X-Client: mobile` -- a browser page's JS never sees these
    (Phase 3 §5/§22); web auth relies on the httpOnly cookies set alongside
    this same response instead."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    user: UserOut
    tokens: TokenResponse | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class PasswordResetRequest(BaseModel):
    email: EmailStr

    _lower_email = field_validator("email", mode="after")(_normalise_email)


class PasswordResetRequestOut(BaseModel):
    detail: str
    dev_reset_url: str | None = None


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
