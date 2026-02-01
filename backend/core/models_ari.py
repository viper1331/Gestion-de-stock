"""Modèles Pydantic pour le module ARI."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AriSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collaborator_id: int
    performed_at: datetime
    course_name: Optional[str] = None
    duration_seconds: int = Field(ge=1)
    start_pressure_bar: int
    end_pressure_bar: int
    air_consumed_bar: Optional[int] = None
    stress_level: int = Field(ge=1, le=10)
    rpe: Optional[int] = Field(default=None, ge=1, le=10)
    physio_notes: Optional[str] = None
    observations: Optional[str] = None
    bp_sys_pre: Optional[int] = None
    bp_dia_pre: Optional[int] = None
    hr_pre: Optional[int] = None
    spo2_pre: Optional[int] = None
    bp_sys_post: Optional[int] = None
    bp_dia_post: Optional[int] = None
    hr_post: Optional[int] = None
    spo2_post: Optional[int] = None


class AriCertificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collaborator_id: int
    status: Literal["APPROVED", "REJECTED", "CONDITIONAL"]
    comment: Optional[str] = None

    @model_validator(mode="after")
    def _require_comment_when_needed(self) -> "AriCertificationDecision":
        if self.status in {"REJECTED", "CONDITIONAL"}:
            if not self.comment or not self.comment.strip():
                raise ValueError("Commentaire requis pour ce statut")
        return self


class AriSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_enabled: bool
    stress_required: bool
    rpe_enabled: bool
    min_sessions_for_certification: int = Field(ge=1)


class AriSettings(BaseModel):
    feature_enabled: bool
    stress_required: bool
    rpe_enabled: bool
    min_sessions_for_certification: int


class AriSession(BaseModel):
    id: int
    collaborator_id: int
    performed_at: str
    course_name: str
    duration_seconds: int
    start_pressure_bar: int
    end_pressure_bar: int
    air_consumed_bar: int
    stress_level: int
    rpe: Optional[int] = None
    physio_notes: Optional[str] = None
    observations: Optional[str] = None
    bp_sys_pre: Optional[int] = None
    bp_dia_pre: Optional[int] = None
    hr_pre: Optional[int] = None
    spo2_pre: Optional[int] = None
    bp_sys_post: Optional[int] = None
    bp_dia_post: Optional[int] = None
    hr_post: Optional[int] = None
    spo2_post: Optional[int] = None
    created_at: str
    created_by: str


class AriCertification(BaseModel):
    collaborator_id: int
    status: Literal["PENDING", "APPROVED", "REJECTED", "CONDITIONAL"]
    comment: Optional[str] = None
    decision_at: Optional[str] = None
    decided_by: Optional[str] = None


class AriCollaboratorStats(BaseModel):
    sessions_count: int
    avg_duration_seconds: Optional[float] = None
    avg_air_consumed_bar: Optional[float] = None
    avg_air_per_min: Optional[float] = None
    avg_stress_level: Optional[float] = None
    last_session_at: Optional[str] = None
    certification_status: Literal["PENDING", "APPROVED", "REJECTED", "CONDITIONAL"]
    certification_decision_at: Optional[str] = None
