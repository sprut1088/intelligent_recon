from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class AiVerifyRequest(BaseModel):
    case_ids: Optional[List[str]] = None

class CaseResolveRequest(BaseModel):
    resolution_type: str = Field(..., examples=["MATCHED_MANUAL"])
    reason_code: str = Field(..., examples=["REMITTANCE_FORMAT_MISMATCH"])
    selected_bank_ids: List[str] = Field(default_factory=list)
    selected_psr_ids: List[str] = Field(default_factory=list)
    fields_used: List[str] = Field(default_factory=list)
    fields_ignored: List[str] = Field(default_factory=list)
    accepted_variance: Optional[float] = None
    comment: Optional[str] = None
    final_user_confidence: str = "confirmed"
    learning_eligible: bool = True
    override_reason: Optional[str] = None
    override_note: Optional[str] = None

class UserEventRequest(BaseModel):
    event_type: str
    case_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    user_id: str = "prototype_user"

class ReconcileRunRequest(BaseModel):
    reset: bool = True
    amount_divisor: Optional[float] = None
    pattern_group: Optional[str] = None

class CandidateApprovalRequest(BaseModel):
    approved_by: str = "recon_lead"
    execution_mode: str = "SUGGESTION"
    confidence_threshold: float = 0.90


class PatternCreateRequest(BaseModel):
    pattern_id: Optional[str] = None
    pattern_name: str
    pattern_type: str = "CUSTOM"
    pattern_group: str = "default"
    pattern_version: str = "1.0"
    pattern_rule: Dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"
    execution_mode: str = "SUGGESTION"
    confidence_threshold: float = 0.80
    approved_by: str = "prototype_user"

class BulkPatternSaveRequest(BaseModel):
    group_name: str
    patterns: List["PatternCreateRequest"]


class IdentifiedPatternItem(BaseModel):
    pattern_name: str
    pattern_type: str = "FILE_DETECTED"
    pattern_rule: Dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = "SUGGESTION"
    confidence_threshold: float = 0.80


class PatternCompareRequest(BaseModel):
    identified_patterns: List[IdentifiedPatternItem]
    compare_group: str


class PatternUpdateRequest(BaseModel):
    pattern_name: Optional[str] = None
    pattern_type: Optional[str] = None
    pattern_group: Optional[str] = None
    pattern_version: Optional[str] = None
    pattern_rule: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    execution_mode: Optional[str] = None
    confidence_threshold: Optional[float] = None
    approved_by: Optional[str] = None


class WorkflowUpdateRequest(BaseModel):
    workflow_status: Optional[str] = None
    owner: Optional[str] = None
    priority: Optional[str] = None
    comment: Optional[str] = None
    updated_by: str = "prototype_user"
