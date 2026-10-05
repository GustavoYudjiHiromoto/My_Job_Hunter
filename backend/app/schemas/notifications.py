import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationSettingsUpdate(BaseModel):
    enabled: bool
    recipient_email: str = Field(default="", max_length=254)
    minimum_score: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_enabled_settings(self):
        if self.enabled:
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.recipient_email):
                raise ValueError("Informe um endereço de e-mail válido para ativar os alertas.")
            if self.minimum_score is None:
                raise ValueError("Defina a pontuação mínima para ativar os alertas.")
        return self


class NotificationSettingsRead(BaseModel):
    enabled: bool
    recipient_email: str
    minimum_score: int | None
    smtp_configured: bool


class NotifiedJobRead(BaseModel):
    job_id: int
    title: str
    company: str
    score: int
    source_url: str


class EmailNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    import_run_id: int
    recipient_email: str
    minimum_score: int
    status: Literal["pending", "sending", "sent", "failed"]
    jobs: list[NotifiedJobRead]
    error: str | None
    created_at: datetime
    sent_at: datetime | None
