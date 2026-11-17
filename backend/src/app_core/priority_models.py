"""Evidence-backed suggestions are distinct from explicit PM confirmation."""

from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field
from app_core.domain.models import StrictModel
from app_core.triage_models import Evidence

Priority = Literal["high", "medium", "low"]
Text = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^[^\x00]*$")]


class PrioritySuggestion(StrictModel):
    impact: Priority
    confidence: Priority
    priority: Priority
    goals_alignment: Text
    rationale: Text
    workflow_impact: Text
    evidence_strength: Text
    dependencies: Text
    missing_information: Annotated[list[Text], Field(max_length=6)]
    evidence: Annotated[list[Evidence], Field(max_length=6)]


class PriorityDecision(StrictModel):
    priority: Priority
    rationale: Text
    effort: Annotated[str, Field(max_length=1000, pattern=r"^[^\x00]*$")] = ""
    dependencies: Annotated[str, Field(max_length=1000, pattern=r"^[^\x00]*$")] = ""
    expected_revision: Annotated[int, Field(ge=0)]
    accepted_analysis_id: UUID | None = None


def validate_suggestion(payload, feedback):
    result = PrioritySuggestion.model_validate(payload)
    observed = {str(item["id"]): item for item in feedback}
    if observed and not result.evidence:
        raise ValueError("Linked evidence must be cited")
    for cite in result.evidence:
        if (
            str(cite.feedback_id) not in observed
            or cite.quote not in observed[str(cite.feedback_id)]["description"]
        ):
            raise ValueError("Citations must quote linked evidence exactly")
    return result.model_dump(mode="json")


class BatchPriorityRequest(StrictModel):
    opportunity_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]


class BatchPrioritySuggestion(StrictModel):
    opportunity_id: UUID
    suggestion: PrioritySuggestion


class BatchPriorityResult(StrictModel):
    items: Annotated[list[BatchPrioritySuggestion], Field(min_length=1, max_length=50)]


class BatchPriorityDecision(PriorityDecision):
    opportunity_id: UUID
    expected_evidence_revision: Annotated[int, Field(ge=0)]


class BatchPriorityDecisions(StrictModel):
    items: Annotated[list[BatchPriorityDecision], Field(min_length=1, max_length=50)]


def validate_batch_suggestions(payload, evidence):
    result = BatchPriorityResult.model_validate(payload)
    ids = [str(item.opportunity_id) for item in result.items]
    if len(set(ids)) != len(ids) or set(ids) != set(evidence):
        raise ValueError(
            "Assessment must cover every selected opportunity exactly once"
        )
    return {
        str(item.opportunity_id): validate_suggestion(
            item.suggestion.model_dump(mode="json"), evidence[str(item.opportunity_id)]
        )
        for item in result.items
    }
