"""Database schema shared by SQLite (local) and PostgreSQL (cloud)."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    # Keep naive UTC in DB, emit explicit Z to clients.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SystemState(Base):
    __tablename__ = 'system_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default='SIM')
    gate: Mapped[str] = mapped_column(String(16), default='CLOSED')
    sensors: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[str] = mapped_column(String(24), default='IDLE')
    first_sensor: Mapped[str | None] = mapped_column(String(1), nullable=True)
    passage_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    permit_plate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    permit_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_seq: Mapped[int] = mapped_column(Integer, default=-1)
    device_boot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_plate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alert: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Plate(Base):
    __tablename__ = 'plates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    note: Mapped[str] = mapped_column(String(120), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Visit(Base):
    __tablename__ = 'visits'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


Index('idx_visits_plate_left', Visit.plate, Visit.left_at)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(35), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DeviceCommand(Base):
    __tablename__ = 'device_commands'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default='PENDING')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str | None] = mapped_column(String(160), nullable=True)
