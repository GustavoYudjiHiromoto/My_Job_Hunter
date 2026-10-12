from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProfessionalProfile(Base):
    __tablename__ = "professional_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    professional_summary: Mapped[str] = mapped_column(Text, default="")
    resume_text: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    languages: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    experiences: Mapped[list["Experience"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Experience.id"
    )
    education: Mapped[list["Education"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Education.id"
    )
    preference: Mapped["Preference | None"] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )


class Experience(Base):
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="CASCADE"), index=True
    )
    company: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(default=False)
    profile: Mapped[ProfessionalProfile] = relationship(back_populates="experiences")


class Education(Base):
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="CASCADE"), index=True
    )
    institution: Mapped[str] = mapped_column(String(160))
    degree: Mapped[str] = mapped_column(String(160))
    field_of_study: Mapped[str] = mapped_column(String(160), default="")
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    profile: Mapped[ProfessionalProfile] = relationship(back_populates="education")


class Preference(Base):
    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="CASCADE"), unique=True
    )
    desired_titles: Mapped[str] = mapped_column(Text, default="")
    search_keywords: Mapped[str] = mapped_column(Text, default="")
    search_areas: Mapped[str] = mapped_column(Text, default="")
    desired_locations: Mapped[str] = mapped_column(Text, default="")
    work_modes: Mapped[str] = mapped_column(Text, default="")
    seniority: Mapped[str] = mapped_column(String(80), default="")
    employment_types: Mapped[str] = mapped_column(Text, default="")
    minimum_salary: Mapped[int | None] = mapped_column(Integer)
    maximum_salary: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str] = mapped_column(String(3), default="BRL")
    must_have: Mapped[str] = mapped_column(Text, default="")
    excluded_criteria: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[ProfessionalProfile] = relationship(back_populates="preference")
