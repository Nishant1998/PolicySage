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
    document_id: str | None = None
    document_type: str | None = None


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=2, max_length=3000)
    answer: str = Field(min_length=1, max_length=4000)


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    route: Literal["kb", "direct"] = Field(description="kb for public insurance questions; direct for conversation or missing private details")
    standalone_question: str = Field(min_length=2, max_length=3000, description="Current request with relevant conversational references resolved; preserve intent and never invent missing details")
    web_query: str = Field(description="Public insurance search query, or an empty string for direct responses")
    needs_details: bool = Field(description="True only when essential information must come from the user")
    needs_decomposition: bool = Field(description="True for distinct requested facts or policy sections needing separate searches")


class EvidenceGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: Literal["good", "weak"] = Field(description="good if the selected evidence answers the whole question, otherwise weak")
    supporting_evidence_ids: list[str] = Field(description="Relevant IDs exactly as supplied, such as K1 or W1; [] if none are relevant")
    missing_aspects: list[str] = Field(description="Up to three short requested aspects not supported by the evidence; [] if complete")
    needs_details: bool = Field(description="True only for missing user-specific information, not missing public evidence")


class QueryDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(min_length=1, max_length=3, description="One to three search queries")


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class AgentState(TypedDict):
    original_question: str
    history: list[dict[str, str]]
    question: str
    current_query: str
    decompose: bool
    subqueries: list[str]
    subquery_hits: list[dict]
    web_query: str
    route: str
    filters: dict[str, str]
    kb_docs: list[Document]
    kb_pool: list[Document]
    web_results: list[Document]
    kb_grade: str
    web_grade: str
    missing_aspects: list[str]
    needs_details: bool
    retry_count: int
    allow_web: bool
    web_disabled_reason: str
    next_evidence_step: str
    web_unavailable: bool
    answer: str
    status: Literal["answered", "clarification_required", "insufficient_evidence", "error"]
    source_used: str
    citations: list[dict]
    limitations: list[str]
    trace: list[str]
