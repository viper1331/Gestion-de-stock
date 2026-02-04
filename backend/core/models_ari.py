"""Modèles Pydantic pour le module ARI."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AriSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collaborator_id: int
    performed_at: datetime
    course_name: Optional[str] = None
    duration_seconds: int
    start_pressure_bar: int
    end_pressure_bar: int
    air_consumed_bar: Optional[int] = None
    cylinder_capacity_l: float
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


class AriSessionCreate(AriSessionInput):
    model_config = ConfigDict(extra="forbid")


class AriSessionUpdate(AriSessionInput):
    model_config = ConfigDict(extra="forbid")


AriSessionStatus = Literal["DRAFT", "COMPLETED", "CERTIFIED", "REJECTED"]


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


class AriCertificationResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class AriSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_enabled: bool
    stress_required: bool
    rpe_enabled: bool
    min_sessions_for_certification: int = Field(ge=1)
    cert_validity_days: int = Field(ge=1)
    cert_expiry_warning_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_cert_alerts(self) -> "AriSettingsUpdate":
        if self.cert_expiry_warning_days >= self.cert_validity_days:
            raise ValueError("Le seuil d'alerte doit être inférieur à la durée de validité")
        return self


class AriSettings(BaseModel):
    feature_enabled: bool
    stress_required: bool
    rpe_enabled: bool
    min_sessions_for_certification: int
    cert_validity_days: int
    cert_expiry_warning_days: int


class AriSession(BaseModel):
    id: int
    collaborator_id: int
    performed_at: str
    course_name: str
    duration_seconds: int
    start_pressure_bar: int
    end_pressure_bar: int
    air_consumed_bar: int
    cylinder_capacity_l: float
    air_consumed_l: float
    air_consumption_lpm: float
    autonomy_start_min: float
    autonomy_end_min: float
    stress_level: int
    status: AriSessionStatus
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
    status: Literal["PENDING", "APPROVED", "REJECTED", "CONDITIONAL", "NONE"]
    comment: Optional[str] = None
    decision_at: Optional[str] = None
    decided_by: Optional[str] = None
    certified_at: Optional[str] = None
    expires_at: Optional[str] = None
    certified_by_user_id: Optional[int] = None
    notes: Optional[str] = None
    reset_at: Optional[str] = None
    reset_by_user_id: Optional[int] = None
    reset_reason: Optional[str] = None
    alert_state: Optional[Literal["valid", "expiring_soon", "expired", "none"]] = None
    days_until_expiry: Optional[int] = None


class AriCollaboratorStats(BaseModel):
    sessions_count: int
    avg_duration_seconds: Optional[float] = None
    avg_air_consumed_bar: Optional[float] = None
    avg_air_per_min: Optional[float] = None
    avg_stress_level: Optional[float] = None
    last_session_at: Optional[str] = None
    certification_status: Literal["PENDING", "APPROVED", "REJECTED", "CONDITIONAL", "NONE"]
    certification_decision_at: Optional[str] = None


class AriPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Literal["CURRENT", "ALL"] = "CURRENT"
    older_than_days: Optional[int] = Field(default=None, ge=1)
    before_date: Optional[date] = None
    include_certified: bool = False
    dry_run: bool = True


class AriPurgeResponse(BaseModel):
    ok: bool
    dry_run: bool
    total: int
    by_site: dict[str, int]


class AriStatsTopSession(BaseModel):
    session_id: int
    performed_at: str
    collaborator_id: int
    collaborator_name: str
    air_lpm: Optional[float] = None
    duration_min: Optional[float] = None


class AriStatsOverview(BaseModel):
    total_sessions: int
    distinct_collaborators: int
    avg_duration_min: Optional[float] = None
    avg_air_lpm: Optional[float] = None
    validated_count: int
    rejected_count: int
    pending_count: int
    top_sessions_by_air: list[AriStatsTopSession]


class AriStatsByCollaboratorRow(BaseModel):
    collaborator_id: int
    collaborator_name: str
    sessions_count: int
    avg_duration_min: Optional[float] = None
    avg_air_lpm: Optional[float] = None
    max_air_lpm: Optional[float] = None
    last_session_at: Optional[str] = None
    status: Literal["pending", "certified", "mixed"]


class AriStatsByCollaboratorResponse(BaseModel):
    rows: list[AriStatsByCollaboratorRow]
