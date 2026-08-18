from typing import Literal, TypedDict

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field


class PolicyFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str | None = None
    insurer: str | None = None
    product_name: str | None = None
    uin: str | None = None
    sha256: str | None = None
    document_type: str | None = None


class RouteDecision(BaseModel):
    route: Literal["kb", "direct"] = "kb"
    web_query: str = ""
    needs_details: bool = False


class EvidenceGrade(BaseModel):
    grade: Literal["good", "weak"] = "weak"
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    needs_details: bool = False


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class AgentState(TypedDict):
    question: str
    current_query: str
    web_query: str
    route: str
    filters: dict[str, str]
    kb_docs: list[Document]
    web_results: list[Document]
    kb_grade: str
    web_grade: str
    needs_details: bool
    retry_count: int
    allow_web: bool
    web_unavailable: bool
    answer: str
    status: Literal["answered", "clarification_required", "insufficient_evidence", "error"]
    source_used: str
    citations: list[dict]
    limitations: list[str]
    trace: list[str]
