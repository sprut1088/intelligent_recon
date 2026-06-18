from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel


class RegexSummary(BaseModel):
    """
    Structured summary of the regex + metadata and examples inferred by the LLM
    reverse-engineer pipeline.
    """

    regex_pattern: str
    delimiter_type: str
    amount_factor: float
    date_format: str
    samples: List[Dict[str, Any]]
    top_matches: List[Dict[str, Any]]


class ReconPatternRow(BaseModel):
    """
    Single reconciliation pattern bucket row aligned to the Master Level taxonomy.
    """

    pattern_level: str  # "MASTER_LEVEL_1" or "MASTER_LEVEL_2"
    pattern_subtype: str  # e.g. "EXACT_REFERENCE_1_TO_1", "COMPOSITE_KEY"
    description: str
    case_count: int
    bank_sum: float
    internal_sum: float
    example_psr_ids: List[str]
    example_camt_ids: List[str]


class ReconPatternsResponse(BaseModel):
    """
    Response shape for /api/reverse-engineer/recon-patterns.

    regex_summary: structured view of the underlying LLM reverse-engineer run.
    recon_patterns: aggregated pattern buckets on top of that run.
    """

    regex_summary: RegexSummary
    recon_patterns: List[ReconPatternRow]


class ReconPatternVersion(BaseModel):
    """
    Versioned snapshot of a reconciliation pattern configuration.

    Stored only in-memory for now. Represents a single version of a full
    recon pattern set (regex summary + all recon pattern rows).
    """

    id: str
    version: int
    name: str

    created_at: datetime
    updated_at: datetime

    regex_summary: RegexSummary
    recon_patterns: List[ReconPatternRow]


class ReconPatternVersionUpdate(BaseModel):
    """
    Payload for updating an existing recon pattern version in-place.
    All fields are optional and will be merged over the stored version.
    """

    name: Optional[str] = None
    regex_summary: Optional[RegexSummary] = None
    recon_patterns: Optional[List[ReconPatternRow]] = None


class ReconPatternVersionCloneRequest(BaseModel):
    """
    Payload for cloning an existing recon pattern version into a new version.
    """

    name: Optional[str] = None
    regex_summary: Optional[RegexSummary] = None
    recon_patterns: Optional[List[ReconPatternRow]] = None


class ReconPatternVersionListResponse(BaseModel):
    """
    Response wrapper for listing recon pattern versions.
    """

    items: List[ReconPatternVersion]
