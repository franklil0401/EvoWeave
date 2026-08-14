import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from evoweave.application.analysis_service import AnalysisService
from evoweave.application.configuration import EvoWeaveConfig
from evoweave.application.intake_service import IntakeService
from evoweave.application.reporting_service import ReportingService
from evoweave.application.run_state import JsonRunStateStore
from evoweave.application.runtime_layout import RuntimeLayout
from evoweave.application.update_workflow import SingleTaskUpdateWorkflow
from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    RunStatus,
)
from evoweave.domain.model_routing import ModelProfile
from evoweave.domain.ports import ModelResponse
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore
from evoweave.infrastructure.models.fake import ScriptedModelGateway
from evoweave.infrastructure.persistence.graph_repository import SQLiteOrchestrationStore
from evoweave.infrastructure.persistence.sqlite import SQLiteDatabase
from evoweave.orchestration.checkpointing import CheckpointManager
from evoweave.workspaces.command_policy import LocalWorkspaceCommandRunner


def test_offline_single_task_flow_reads_modifies_integrates_validates_and_exports(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("single_module")
    config = EvoWeaveConfig(runtime_directory=".runtime-test")
    layout = RuntimeLayout.create(repository, config)
    artifact_store = LocalArtifactStore(layout.artifacts)
    run_store = JsonRunStateStore(layout.run_state)
    change = IntakeService().create(
        repository=repository,
        objective="修改 calculator.py，让客户类型匹配不区分大小写",
        acceptance_criteria=("VIP 折扣保持正确",),
        allowed_paths=("calculator.py",),
    )
    manifest, profile = AnalysisService(
        run_store=run_store,
        artifact_store=artifact_store,
    ).analyze(change)
    model = _profile()
    gateway = ScriptedModelGateway(
        profiles=(model,),
        responses=(
            _response(
                {
                    "action": "tool",
                    "tool_name": "file.read",
                    "arguments": {"path": "calculator.py"},
                }
            ),
            _response(
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
                }
            ),
            _response(
                {
                    "action": "finish",
                    "status": "succeeded",
                    "summary": "已完成大小写兼容修改",
                }
            ),
        ),
    )

    outcome = SingleTaskUpdateWorkflow(
        config=config,
        layout=layout,
        run_store=run_store,
        artifact_store=artifact_store,
        model_gateway=gateway,
        model_profiles=(model,),
        validation_runner_factory=lambda lease: LocalWorkspaceCommandRunner(
            lease=lease,
            allowed_commands=("python",),
            allow_host_execution=True,
        ),
    ).execute(manifest, profile)

    assert outcome.manifest.status is RunStatus.COMPLETED
    assert outcome.validation_report.accepted is True
    assert outcome.final_patch.changed_paths == ("calculator.py",)
    assert "upper()" in artifact_store.get_bytes(outcome.final_patch.ref.artifact_id).decode()
    assert "upper()" not in (repository / "calculator.py").read_text(encoding="utf-8")
    assert not tuple(layout.worker_worktrees.iterdir())
    assert not tuple(layout.integration_worktrees.iterdir())
    checkpoint = CheckpointManager(
        SQLiteOrchestrationStore(SQLiteDatabase(layout.orchestration_database))
    ).load(manifest.run_id)
    assert checkpoint is not None
    assert checkpoint.finished is True
    assert checkpoint.acceptance_satisfied is True
    assert len(checkpoint.execution_specs) == 1
    markdown, machine_json = ReportingService().export(
        outcome.manifest,
        layout.reports,
        checkpoint=checkpoint,
    )
    assert "EvoWeave 运行报告" in markdown.read_text(encoding="utf-8")
    machine_report = json.loads(machine_json.read_text(encoding="utf-8"))
    assert machine_report["status"] == "completed"
    assert len(machine_report["orchestration"]["execution_specs"]) == 1


def _profile() -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id="worker",
        tier=ModelTier.HIGH,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT,),
        context_window_tokens=128_000,
        max_output_tokens=8_000,
        supports_tool_calling=True,
        supports_structured_output=True,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _response(payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        model_key="fake:worker",
        text=json.dumps(payload, ensure_ascii=False),
        input_tokens=10,
        output_tokens=5,
    )
