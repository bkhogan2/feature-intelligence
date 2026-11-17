"""Strict model output, independently validated after the SDK's JSON schema step."""

from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, TypeAdapter, model_validator, field_validator
from app_core.domain.models import StrictModel

Text = Annotated[str, Field(min_length=1, max_length=6000, pattern=r"^[^\x00]*$")]


class Evidence(StrictModel):
    feedback_id: UUID
    quote: Annotated[str, Field(min_length=1, max_length=500)]


class TriageBase(StrictModel):
    rationale_markdown: Text
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=6)]


class ExistingOpportunity(TriageBase):
    outcome: Literal["existing_opportunity"]
    opportunity_id: UUID


class NewOpportunity(TriageBase):
    outcome: Literal["new_opportunity"]
    proposed_name: Annotated[
        str, Field(min_length=1, max_length=160, pattern=r"^[^\x00]*$")
    ]
    proposed_problem: Annotated[
        str, Field(min_length=1, max_length=4000, pattern=r"^[^\x00]*$")
    ]


class InsufficientContext(TriageBase):
    outcome: Literal["insufficient_context"]
    ambiguity: Annotated[str, Field(min_length=1, max_length=2000)]
    questions: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=2),
    ]


TriageResult = Annotated[
    ExistingOpportunity | NewOpportunity | InsufficientContext,
    Field(discriminator="outcome"),
]
TRIAGE_RESULT = TypeAdapter(TriageResult)


class TriageOutput(StrictModel):
    decision: TriageResult


OpportunityStatus = Literal[
    "considering", "planned", "in_progress", "shipped", "not_pursuing"
]


class OpportunityDescription(StrictModel):
    markdown: Annotated[
        str, Field(min_length=1, max_length=20000, pattern=r"^[^\x00]*$")
    ]
    expected_revision: Annotated[int, Field(ge=0)]

    @field_validator("markdown")
    @classmethod
    def nonblank_markdown(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Description must not be blank")
        return value


class OpportunityDecision(StrictModel):
    status: OpportunityStatus
    expected_status: OpportunityStatus
    note: Annotated[str, Field(max_length=4000, pattern=r"^[^\x00]*$")] = ""


PROMPT_VERSION = "triage-v1"


def validate_result(payload, feedback, opportunities, request_id):
    result = TRIAGE_RESULT.validate_python(payload)
    if not any(str(item.feedback_id) == str(request_id) for item in result.evidence):
        raise ValueError("Result must cite the original request")
    for item in result.evidence:
        original = feedback.get(str(item.feedback_id))
        if not original or item.quote not in original["description"]:
            raise ValueError("Evidence must quote observed workspace feedback exactly")
    if (
        isinstance(result, ExistingOpportunity)
        and str(result.opportunity_id) not in opportunities
    ):
        raise ValueError("Opportunity was not observed in this workspace")
    return result.model_dump(mode="json")


def triage_json_schema():
    """JSON Schema for Claude's strict validator, without OpenAPI discriminator hints.

    The standard oneOf + outcome const branches preserve the union contract;
    Pydantic's discriminator is still used for server-side validation.
    """

    def standard(value):
        if isinstance(value, dict):
            return {
                key: standard(item)
                for key, item in value.items()
                if key != "discriminator"
            }
        if isinstance(value, list):
            return [standard(item) for item in value]
        return value

    return standard(TriageOutput.model_json_schema())


class TriageConfirmation(StrictModel):
    mode: Literal["accept", "existing", "edit_new"] = "accept"
    opportunity_id: UUID | None = None
    name: (
        Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[^\x00]*$")]
        | None
    ) = None
    problem: (
        Annotated[str, Field(min_length=1, max_length=4000, pattern=r"^[^\x00]*$")]
        | None
    ) = None
    reason: (
        Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^[^\x00]*$")]
        | None
    ) = None

    @field_validator("name", "problem", "reason", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_choice(self):
        if self.mode == "accept":
            if any(
                v is not None
                for v in (self.opportunity_id, self.name, self.problem, self.reason)
            ):
                raise ValueError("Accept cannot include correction fields")
        elif not self.reason:
            raise ValueError("Explain the human correction")
        elif self.mode == "existing":
            if (
                not self.opportunity_id
                or self.name is not None
                or self.problem is not None
            ):
                raise ValueError("Select an existing opportunity only")
        elif self.opportunity_id is not None or not self.name or not self.problem:
            raise ValueError("Provide the edited opportunity title and problem")
        return self


class TriageBatchItem(StrictModel):
    feedback_id: UUID
    run_id: UUID


class TriageBatchConfirmation(StrictModel):
    items: Annotated[list[TriageBatchItem], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def unique_feedback(self):
        if len({item.feedback_id for item in self.items}) != len(self.items):
            raise ValueError("Select each request only once")
        return self
