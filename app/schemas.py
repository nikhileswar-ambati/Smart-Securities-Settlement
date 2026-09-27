from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Category(StrEnum):
    BUSINESS = "Business"
    STAKEHOLDER = "Stakeholder"
    FUNCTIONAL = "Functional"
    SECURITY = "Security"
    PRIVACY = "Privacy"
    REGULATORY = "Regulatory"
    PERFORMANCE = "Performance"
    AVAILABILITY = "Availability / reliability"
    USABILITY = "Usability"
    DATA = "Data management"
    INTEGRATION = "Integration"
    AUDIT = "Audit / reporting"
    OPERATIONAL = "Operational / maintenance"


class Evidence(BaseModel):
    document_id: str
    document_name: str
    chunk_id: str
    excerpt: str
    relevance: float = Field(ge=0, le=1)


class Requirement(BaseModel):
    id: str
    statement: str
    categories: list[Category]
    source_stakeholder: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    business_justification: str
    priority: Literal["Must", "Should", "Could"] = "Should"
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    applicable_policy: str | None = None
    risk_level: Literal["Low", "Medium", "High"] = "Medium"
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    approval_status: Literal["Draft", "Approved", "Rejected", "Needs review"] = "Draft"


class RequirementUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=10, max_length=2000)
    business_justification: str | None = Field(default=None, max_length=2000)
    priority: Literal["Must", "Should", "Could"] | None = None
    acceptance_criteria: list[str] | None = None
    assumptions: list[str] | None = None
    dependencies: list[str] | None = None
    source_stakeholder: str | None = Field(default=None, max_length=200)


class QualityIssue(BaseModel):
    id: str
    requirement_id: str | None = None
    check: str
    severity: Literal["Low", "Medium", "High"]
    message: str
    recommendation: str


class SdlcFactor(BaseModel):
    name: str
    value: str
    score: int = Field(ge=1, le=5)
    rationale: str
    requirement_ids: list[str] = Field(default_factory=list)


class SdlcOption(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)
    suitability: str


class WorkflowPhase(BaseModel):
    phase: str
    activities: list[str]
    roles: list[str]
    deliverables: list[str]
    gate: str


class SdlcRecommendation(BaseModel):
    recommended_sdlc: str
    factors: list[SdlcFactor]
    options: list[SdlcOption]
    justification: str
    workflow: list[WorkflowPhase]
    human_approval_required: bool = True
    approval_status: Literal["Needs review", "Approved", "Rejected"] = "Needs review"


class Project(BaseModel):
    id: str
    functionality: str
    business_objective: str = ""
    users_and_roles: str = ""
    created_at: datetime
    documents: list[dict] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    sdlc: SdlcRecommendation | None = None
