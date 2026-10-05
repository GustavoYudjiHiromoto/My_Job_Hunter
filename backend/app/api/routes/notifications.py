from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import EmailNotification, NotificationPreference
from app.schemas.notifications import (
    EmailNotificationRead,
    NotificationSettingsRead,
    NotificationSettingsUpdate,
)
from app.services.notifications import smtp_is_configured

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _settings_read(preference: NotificationPreference | None) -> NotificationSettingsRead:
    return NotificationSettingsRead(
        enabled=preference.enabled if preference else False,
        recipient_email=preference.recipient_email if preference else "",
        minimum_score=preference.minimum_score if preference else None,
        smtp_configured=smtp_is_configured(),
    )


@router.get("/settings", response_model=NotificationSettingsRead)
def read_settings(db: Session = Depends(get_db)):
    return _settings_read(db.get(NotificationPreference, 1))


@router.put("/settings", response_model=NotificationSettingsRead)
def save_settings(payload: NotificationSettingsUpdate, db: Session = Depends(get_db)):
    preference = db.get(NotificationPreference, 1)
    if preference is None:
        preference = NotificationPreference(id=1)
        db.add(preference)
    preference.enabled = payload.enabled
    preference.recipient_email = payload.recipient_email.strip()
    preference.minimum_score = payload.minimum_score
    db.commit()
    db.refresh(preference)
    return _settings_read(preference)


@router.get("", response_model=list[EmailNotificationRead])
def read_history(limit: int = 20, db: Session = Depends(get_db)):
    bounded_limit = max(1, min(limit, 100))
    return list(
        db.scalars(
            select(EmailNotification)
            .order_by(EmailNotification.created_at.desc(), EmailNotification.id.desc())
            .limit(bounded_limit)
        ).all()
    )
