from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

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

class UserEventRequest(BaseModel):
    event_type: str
    case_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    user_id: str = "prototype_user"

class ReconcileRunRequest(BaseModel):
    reset: bool = True
    amount_divisor: Optional[float] = None

class CandidateApprovalRequest(BaseModel):
    approved_by: str = "recon_lead"
    execution_mode: str = "SUGGESTION"
    confidence_threshold: float = 0.90
