import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailNotification, ImportRun, NotificationPreference
from app.repositories.jobs import list_jobs
from app.repositories.profile import get_or_create_profile
from app.schemas.jobs import JobRecommendation
from app.services.matching import rank_jobs

logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    """Safe configuration error that can be shown in notification history."""


class EmailNotifier(Protocol):
    def send_email(self, recipient: str, subject: str, body: str) -> None: ...


@dataclass(frozen=True)
class SMTPConfiguration:
    host: str
    port: int
    sender: str
    security: str
    username: str | None
    password: str | None


class SMTPEmailNotifier:
    def __init__(self, configuration: SMTPConfiguration):
        self.configuration = configuration

    def send_email(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.configuration.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        if self.configuration.security == "ssl":
            server_context = smtplib.SMTP_SSL(
                self.configuration.host,
                self.configuration.port,
                timeout=20,
                context=context,
            )
        else:
            server_context = smtplib.SMTP(self.configuration.host, self.configuration.port, timeout=20)
        with server_context as server:
            if self.configuration.security == "starttls":
                server.starttls(context=context)
            if self.configuration.username:
                server.login(self.configuration.username, self.configuration.password or "")
            server.send_message(message)


def get_smtp_configuration() -> SMTPConfiguration:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    if not host or not sender:
        raise EmailConfigurationError("Configure SMTP_HOST e SMTP_FROM no ambiente do backend.")
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailConfigurationError("SMTP_PORT deve ser um número entre 1 e 65535.") from error
    if not 1 <= port <= 65535:
        raise EmailConfigurationError("SMTP_PORT deve ser um número entre 1 e 65535.")
    security = os.getenv("SMTP_SECURITY", "starttls").strip().casefold()
    if security not in {"starttls", "ssl"}:
        raise EmailConfigurationError("SMTP_SECURITY deve ser 'starttls' ou 'ssl'.")
    username = os.getenv("SMTP_USERNAME", "").strip() or None
    password = os.getenv("SMTP_PASSWORD", "") or None
    if bool(username) != bool(password):
        raise EmailConfigurationError(
            "Configure SMTP_USERNAME e SMTP_PASSWORD juntos, ou deixe ambos vazios."
        )
    return SMTPConfiguration(host, port, sender, security, username, password)


def smtp_is_configured() -> bool:
    try:
        get_smtp_configuration()
    except EmailConfigurationError:
        return False
    return True


def create_email_notifier() -> EmailNotifier:
    return SMTPEmailNotifier(get_smtp_configuration())


def notification_recommendations(
    db: Session, job_ids: set[int], minimum_score: int
) -> list[JobRecommendation]:
    if not job_ids:
        return []
    jobs = [job for job in list_jobs(db) if job.id in job_ids and job.status == "open"]
    if not jobs:
        return []
    profile = get_or_create_profile(db)
    return rank_jobs(jobs, profile, min_score=minimum_score, include_excluded=False)


def _email_content(recommendations: list[JobRecommendation]) -> str:
    lines = [
        f"Encontramos {len(recommendations)} nova(s) vaga(s) compatível(is) no Job Hunter:",
        "",
    ]
    for recommendation in recommendations:
        job = recommendation.job
        lines.extend(
            [
                f"{recommendation.score}% — {job.title} | {job.company}",
                f"Localização: {job.location or 'Não informada'}",
                f"Link: {job.sources[0].source_url if job.sources else ''}",
                "",
            ]
        )
    lines.append("Este resumo foi gerado pelo Job Hunter. Nenhuma candidatura foi enviada.")
    return "\n".join(lines)


def send_run_notifications(
    db: Session,
    run: ImportRun,
    new_job_ids: set[int],
    notifier: EmailNotifier | None = None,
) -> EmailNotification | None:
    if run.status not in {"succeeded", "partial"}:
        return None
    preference = db.get(NotificationPreference, 1)
    if preference is None or not preference.enabled or preference.minimum_score is None:
        return None
    if not new_job_ids:
        return None

    existing = db.scalar(select(EmailNotification).where(EmailNotification.import_run_id == run.id))
    if existing is not None:
        return existing

    recommendations = notification_recommendations(db, new_job_ids, preference.minimum_score)
    if not recommendations:
        return None

    jobs_snapshot = [
        {
            "job_id": item.job.id,
            "title": item.job.title,
            "company": item.job.company,
            "score": item.score,
            "source_url": item.job.sources[0].source_url if item.job.sources else "",
        }
        for item in recommendations
    ]
    delivery = EmailNotification(
        import_run_id=run.id,
        recipient_email=preference.recipient_email,
        minimum_score=preference.minimum_score,
        status="pending",
        jobs=jobs_snapshot,
    )
    db.add(delivery)
    db.commit()
    delivery_id = delivery.id

    try:
        sender = notifier or create_email_notifier()
        delivery.status = "sending"
        db.commit()
        sender.send_email(
            delivery.recipient_email,
            f"[Job Hunter] {len(recommendations)} nova(s) vaga(s) compatível(is)",
            _email_content(recommendations),
        )
        delivery.status = "sent"
        delivery.sent_at = datetime.now(UTC)
        delivery.error = None
        db.commit()
        return delivery
    except Exception as error:
        logger.exception("Falha ao enviar notificação do ImportRun %s", run.id)
        db.rollback()
        delivery = db.get(EmailNotification, delivery_id)
        if delivery is not None:
            delivery.status = "failed"
            delivery.error = (
                str(error)
                if isinstance(error, EmailConfigurationError)
                else "Não foi possível enviar o e-mail."
            )
            db.commit()
        return delivery
