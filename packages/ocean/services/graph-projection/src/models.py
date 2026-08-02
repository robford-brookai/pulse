"""SQLAlchemy ORM models for the operational graph tables."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Patient(Base):
    __tablename__ = "patients"

    patient_id = Column(Text, primary_key=True)
    clinic_id = Column(Text, nullable=False)
    enrollment_status = Column(Text, nullable=False, default="pending")
    enrolled_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    last_event_id = Column(Text, nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    signal_id = Column(Text, primary_key=True)
    patient_id = Column(Text, ForeignKey("patients.patient_id", name="fk_signals_patient_id"), nullable=False)
    signal_type = Column(Text, nullable=False)
    value = Column(Float, nullable=True)
    unit = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False)
    anomalous = Column(Boolean, nullable=False, default=False)
    last_event_id = Column(Text, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(Text, primary_key=True)
    patient_id = Column(Text, ForeignKey("patients.patient_id", name="fk_alerts_patient_id"), nullable=False)
    alert_type = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="open")
    source_system = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    correlation_id = Column(Text, nullable=False)
    last_event_id = Column(Text, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    task_id = Column(Text, primary_key=True)
    alert_id = Column(Text, ForeignKey("alerts.alert_id", name="fk_tasks_alert_id"), nullable=True)
    patient_id = Column(Text, ForeignKey("patients.patient_id", name="fk_tasks_patient_id"), nullable=False)
    task_type = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="open")
    assigned_to = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    last_event_id = Column(Text, nullable=True)


class Interaction(Base):
    __tablename__ = "interactions"

    interaction_id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("tasks.task_id", name="fk_interactions_task_id"), nullable=False)
    patient_id = Column(Text, ForeignKey("patients.patient_id", name="fk_interactions_patient_id"), nullable=False)
    interaction_type = Column(Text, nullable=False)
    outcome = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_event_id = Column(Text, nullable=True)


class Outcome(Base):
    __tablename__ = "outcomes"

    outcome_id = Column(Text, primary_key=True)
    interaction_id = Column(
        Text, ForeignKey("interactions.interaction_id", name="fk_outcomes_interaction_id"), nullable=False
    )
    patient_id = Column(Text, ForeignKey("patients.patient_id", name="fk_outcomes_patient_id"), nullable=False)
    outcome_type = Column(Text, nullable=False)
    resolution_status = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    last_event_id = Column(Text, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id = Column(Text, primary_key=True)
    human_id = Column(Text, nullable=False, unique=True)
    category = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="open")
    patient_id = Column(
        Text,
        ForeignKey("patients.patient_id", name="fk_tickets_patient_id"),
        nullable=True,
    )
    description = Column(Text, nullable=False)
    waiting_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    correlation_id = Column(Text, nullable=False)
    last_event_id = Column(Text, nullable=True)


class TicketTask(Base):
    __tablename__ = "ticket_tasks"
    __table_args__ = (PrimaryKeyConstraint("ticket_id", "task_id"),)

    ticket_id = Column(
        Text,
        ForeignKey("tickets.ticket_id", name="fk_tt_ticket_id"),
        nullable=False,
    )
    task_id = Column(
        Text,
        ForeignKey("tasks.task_id", name="fk_tt_task_id"),
        nullable=False,
    )
    linked_at = Column(DateTime(timezone=True), nullable=False)


class AlertTask(Base):
    __tablename__ = "alert_tasks"
    __table_args__ = (PrimaryKeyConstraint("alert_id", "task_id"),)

    alert_id = Column(
        Text,
        ForeignKey("alerts.alert_id", name="fk_at_alert_id"),
        nullable=False,
    )
    task_id = Column(
        Text,
        ForeignKey("tasks.task_id", name="fk_at_task_id"),
        nullable=False,
    )
    linked_at = Column(DateTime(timezone=True), nullable=False)


class TicketAlert(Base):
    __tablename__ = "ticket_alerts"
    __table_args__ = (PrimaryKeyConstraint("ticket_id", "alert_id"),)

    ticket_id = Column(
        Text,
        ForeignKey("tickets.ticket_id", name="fk_ta_ticket_id"),
        nullable=False,
    )
    alert_id = Column(
        Text,
        ForeignKey("alerts.alert_id", name="fk_ta_alert_id"),
        nullable=False,
    )
    linked_at = Column(DateTime(timezone=True), nullable=False)
