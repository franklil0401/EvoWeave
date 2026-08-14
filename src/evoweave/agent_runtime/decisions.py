"""Finite structured decisions accepted from the model loop."""

import json
from typing import Annotated, Literal, cast

from pydantic import Field, JsonValue, TypeAdapter, ValidationError, model_validator

from evoweave.domain.base import DomainModel
from evoweave.domain.enums import ResultStatus, RiskLevel
from evoweave.domain.errors import DomainError, ErrorCode


class ToolCallDecision(DomainModel):
    action: Literal["tool"]
    tool_name: str = Field(min_length=3, max_length=128)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class FinishDecision(DomainModel):
    action: Literal["finish"]
    status: ResultStatus
    summary: str = Field(min_length=1, max_length=10_000)
    risk_level: RiskLevel = RiskLevel.LOW
    risk_notes: tuple[str, ...] = ()
    failure_code: ErrorCode | None = None
    failure_message: str | None = Field(default=None, min_length=1, max_length=2_000)
    retryable: bool = False

    @model_validator(mode="after")
    def validate_finish_state(self) -> "FinishDecision":
        if self.status is ResultStatus.SUCCEEDED:
            if self.failure_code is not None or self.failure_message is not None:
                raise ValueError("成功决定不能包含失败信息")
        elif self.failure_code is None or self.failure_message is None:
            raise ValueError("非成功决定必须包含失败代码和消息")
        return self


WorkerDecision = Annotated[ToolCallDecision | FinishDecision, Field(discriminator="action")]
_DECISION_ADAPTER: TypeAdapter[WorkerDecision] = TypeAdapter(WorkerDecision)


def parse_worker_decision(text: str) -> WorkerDecision:
    try:
        return _DECISION_ADAPTER.validate_json(text)
    except ValidationError as direct_error:
        try:
            payload = _extract_single_json_object(text)
            return _DECISION_ADAPTER.validate_python(payload)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            errors = (
                exc.errors(include_url=False)
                if isinstance(exc, ValidationError)
                else [{"type": type(exc).__name__, "msg": str(exc)}]
            )
            raise DomainError(
                ErrorCode.INVALID_MODEL_OUTPUT,
                "模型输出不符合 Worker 决策协议",
                details={
                    "direct_errors": direct_error.errors(include_url=False),
                    "extraction_errors": errors,
                },
            ) from exc


def _extract_single_json_object(text: str) -> dict[str, object]:
    """Accept one object wrapped by prose or one Markdown fence, never trailing data."""

    start = text.find("{")
    if start < 0:
        raise ValueError("模型输出不包含 JSON 对象")
    payload, consumed = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise TypeError("Worker 决策必须是 JSON 对象")
    suffix = text[start + consumed :].strip()
    if suffix == "```":
        suffix = ""
    if suffix:
        raise DomainError(
            ErrorCode.INVALID_MODEL_OUTPUT,
            "模型输出在决策 JSON 后包含额外内容",
        )
    return payload


def worker_decision_json_schema() -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], _DECISION_ADAPTER.json_schema())
