import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evoweave.application.analysis_service import AnalysisService
from evoweave.application.configuration import EvoWeaveConfig
from evoweave.application.intake_service import IntakeService
from evoweave.application.run_state import JsonRunStateStore
from evoweave.application.runtime_layout import RuntimeLayout
from evoweave.application.update_workflow import SingleTaskUpdateWorkflow
from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    ResultStatus,
    RunStatus,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.model_routing import ModelProfile
from evoweave.domain.ports import CommandResult, ModelRequest, ModelResponse
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore
from evoweave.infrastructure.models.fake import ScriptedModelGateway
from evoweave.infrastructure.persistence.graph_repository import SQLiteOrchestrationStore
from evoweave.infrastructure.persistence.sqlite import SQLiteDatabase
from evoweave.orchestration.checkpointing import CheckpointManager


class FailPrimaryGateway:
    def __init__(
        self,
        profiles: tuple[ModelProfile, ...],
        fallback: ScriptedModelGateway,
    ) -> None:
        self._profiles = profiles
        self._fallback = fallback
        self.requests: list[ModelRequest] = []

    def list_profiles(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.model_key == "fake:primary":
            raise DomainError(ErrorCode.MODEL_UNAVAILABLE, "模拟首选模型不可用")
        return self._fallback.complete(request)


class AlwaysPassRunner:
    def run(self, argv: tuple[str, ...], *, timeout_seconds: int) -> CommandResult:
        assert timeout_seconds > 0
        return CommandResult(argv=argv, exit_code=0, stdout="passed", duration_ms=1)


class AlwaysFailGateway:
    def __init__(self, profiles: tuple[ModelProfile, ...]) -> None:
        self._profiles = profiles
        self.requests: list[ModelRequest] = []

    def list_profiles(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise DomainError(
            ErrorCode.MODEL_UNAVAILABLE,
            "模拟所有候选模型不可用",
            details={"model_key": request.model_key},
        )


def test_model_failure_creates_new_agent_and_versioned_fallback(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("single_module")
    config = EvoWeaveConfig(runtime_directory=".runtime-fallback")
    layout = RuntimeLayout.create(repository, config)
    artifact_store = LocalArtifactStore(layout.artifacts)
    run_store = JsonRunStateStore(layout.run_state)
    change = IntakeService().create(
        repository=repository,
        objective="修改 calculator.py，让客户类型匹配不区分大小写",
        acceptance_criteria=("VIP 折扣保持正确",),
        allowed_paths=("calculator.py",),
    )
    manifest, repository_profile = AnalysisService(
        run_store=run_store,
        artifact_store=artifact_store,
    ).analyze(change)
    primary = _profile("primary", priority=0)
    fallback = _profile("fallback", priority=1)
    scripted = ScriptedModelGateway(
        profiles=(fallback,),
        responses=(
            _response(
                "fallback",
                {
                    "action": "tool",
                    "tool_name": "file.read",
                    "arguments": {"path": "calculator.py"},
                },
            ),
            _response(
                "fallback",
                {
                    "action": "tool",
                    "tool_name": "file.write",
                    "arguments": {
                        "path": "calculator.py",
                        "content": (
                            "def calculate_discount(total: float, customer_type: str) -> float:\n"
                            '    if customer_type.upper() == "VIP":\n'
                            "        return total * 0.9\n"
                            "    return total\n"
                        ),
                    },
                },
            ),
            _response(
                "fallback",
                {
                    "action": "finish",
                    "status": "succeeded",
                    "summary": "回退模型完成修改",
                },
            ),
        ),
    )
    gateway = FailPrimaryGateway((primary, fallback), scripted)

    outcome = SingleTaskUpdateWorkflow(
        config=config,
        layout=layout,
        run_store=run_store,
        artifact_store=artifact_store,
        model_gateway=gateway,
        model_profiles=(primary, fallback),
        validation_runner_factory=lambda _lease: AlwaysPassRunner(),
    ).execute(manifest, repository_profile)

    assert outcome.manifest.status is RunStatus.COMPLETED
    assert outcome.agent_count == 2
    assert [item.status for item in outcome.task_results] == [
        ResultStatus.FAILED,
        ResultStatus.SUCCEEDED,
    ]
    assert outcome.task_results[0].failure is not None
    assert outcome.task_results[0].failure.code is ErrorCode.MODEL_UNAVAILABLE
    checkpoint = CheckpointManager(
        SQLiteOrchestrationStore(SQLiteDatabase(layout.orchestration_database))
    ).load(manifest.run_id)
    assert checkpoint is not None
    assert len(checkpoint.execution_specs) == 2
    by_version = sorted(checkpoint.execution_specs, key=lambda item: item.version)
    assert [item.model_routing.selected_model_key for item in by_version] == [
        "fake:primary",
        "fake:fallback",
    ]
    assert by_version[0].agent_id != by_version[1].agent_id
    assert by_version[1].model_routing.version == 2


def test_fallback_stops_at_graph_attempt_limit_without_masking_model_error(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("single_module")
    config = EvoWeaveConfig(runtime_directory=".runtime-fallback-limit")
    layout = RuntimeLayout.create(repository, config)
    artifact_store = LocalArtifactStore(layout.artifacts)
    run_store = JsonRunStateStore(layout.run_state)
    change = IntakeService().create(
        repository=repository,
        objective="修改 calculator.py，让客户类型匹配不区分大小写",
        acceptance_criteria=("VIP 折扣保持正确",),
        allowed_paths=("calculator.py",),
    )
    manifest, repository_profile = AnalysisService(
        run_store=run_store,
        artifact_store=artifact_store,
    ).analyze(change)
    profiles = tuple(_profile(f"candidate-{index}", priority=index) for index in range(4))
    gateway = AlwaysFailGateway(profiles)

    with pytest.raises(DomainError) as error:
        SingleTaskUpdateWorkflow(
            config=config,
            layout=layout,
            run_store=run_store,
            artifact_store=artifact_store,
            model_gateway=gateway,
            model_profiles=profiles,
            validation_runner_factory=lambda _lease: AlwaysPassRunner(),
        ).execute(manifest, repository_profile)

    assert error.value.code is ErrorCode.MODEL_UNAVAILABLE
    assert len(gateway.requests) == 3
    checkpoint = CheckpointManager(
        SQLiteOrchestrationStore(SQLiteDatabase(layout.orchestration_database))
    ).load(manifest.run_id)
    assert checkpoint is not None
    assert len(checkpoint.execution_specs) == 3
    assert checkpoint.graph.nodes[0].attempts == 3
    failed_manifest = run_store.get(manifest.run_id)
    assert failed_manifest.status is RunStatus.FAILED
    assert failed_manifest.error_code is ErrorCode.MODEL_UNAVAILABLE


def _profile(model_id: str, *, priority: int) -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id=model_id,
        tier=ModelTier.HIGH,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT,),
        context_window_tokens=128_000,
        max_output_tokens=8_000,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_thinking=True,
        stable_priority=priority,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _response(model_id: str, payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        model_key=f"fake:{model_id}",
        text=json.dumps(payload, ensure_ascii=False),
        input_tokens=10,
        output_tokens=5,
    )
