import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evoweave.benchmarking.models import (
    AgentStrategy,
    BenchmarkRunStatus,
    EvidenceLevel,
    ModelStrategy,
)
from evoweave.benchmarking.runner import BenchmarkResultStore, BenchmarkRunner
from evoweave.benchmarking.suite_loader import load_benchmark_suite
from evoweave.domain.enums import InputModality, ModelAvailability, ModelTier
from evoweave.domain.model_routing import ModelProfile
from evoweave.domain.ports import ModelResponse
from evoweave.infrastructure.models.fake import ScriptedModelGateway

_PROJECT_ROOT = Path(__file__).parents[2]
_SUITE_PATH = _PROJECT_ROOT / "benchmarks/任务集/第一版任务集.json"


def test_runner_uses_hidden_acceptance_and_persists_unique_record(tmp_path: Path) -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)
    profile = _profile()
    gateway = ScriptedModelGateway(
        profiles=(profile,),
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
                            '    if customer_type.strip().upper() == "VIP":\n'
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
                    "summary": "已实现并保留证据",
                }
            ),
        ),
    )

    record = BenchmarkRunner(
        project_root=_PROJECT_ROOT,
        model_gateway=gateway,
        model_profiles=(profile,),
        suite_sha256=suite_digest,
        hidden_acceptance_source=suite.hidden_acceptance_source,
        hidden_acceptance_sha256=suite.hidden_acceptance_sha256,
        evidence_output_root=tmp_path / "evidence",
    ).run(
        task=suite.tasks[0],
        agent_strategy=AgentStrategy.ADAPTIVE,
        model_strategy=ModelStrategy.ADAPTIVE,
        evidence_level=EvidenceLevel.OFFLINE_REPLAY,
    )

    assert record.status is BenchmarkRunStatus.PASSED
    assert record.target_tests_passed is True
    assert record.full_regression_passed is True
    assert record.localization_candidates == ("calculator.py",)
    assert record.agent_count == 1
    assert record.input_tokens == 30
    assert record.selected_model_keys == ("fake:worker",)
    assert record.evidence_directory is not None
    assert (tmp_path / "evidence" / record.run_id / "最终补丁.diff").exists()

    store = BenchmarkResultStore(tmp_path / "results.json")
    store.append(record)
    assert store.load() == (record,)
    with pytest.raises(ValueError, match="已存在"):
        store.append(record)
    with pytest.raises(ValueError, match="其他系统 Git 提交"):
        store.append(
            record.model_copy(update={"run_id": "run-other-commit", "system_commit": "b" * 40})
        )


def test_failed_run_preserves_model_usage_and_structured_details(tmp_path: Path) -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)
    profile = _profile()
    gateway = ScriptedModelGateway(
        profiles=(profile,),
        responses=(
            ModelResponse(
                model_key=profile.key,
                text="not-json",
                input_tokens=13,
                output_tokens=7,
                reasoning_tokens=2,
            ),
        ),
    )

    record = BenchmarkRunner(
        project_root=_PROJECT_ROOT,
        model_gateway=gateway,
        model_profiles=(profile,),
        suite_sha256=suite_digest,
        hidden_acceptance_source=suite.hidden_acceptance_source,
        hidden_acceptance_sha256=suite.hidden_acceptance_sha256,
        evidence_output_root=tmp_path / "evidence",
        system_commit="a" * 40,
    ).run(
        task=suite.tasks[0],
        agent_strategy=AgentStrategy.ADAPTIVE,
        model_strategy=ModelStrategy.ADAPTIVE,
        evidence_level=EvidenceLevel.OFFLINE_REPLAY,
    )

    assert record.status is BenchmarkRunStatus.FAILED
    assert (record.input_tokens, record.output_tokens, record.reasoning_tokens) == (13, 7, 2)
    assert record.failure_reason is not None
    assert "invalid_model_output" in record.failure_reason
    failure_path = tmp_path / "evidence" / record.run_id / "失败信息.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["error_code"] == "invalid_model_output"
    assert failure["details"]["direct_errors"]


def _profile() -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id="worker",
        tier=ModelTier.HIGH,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT, InputModality.IMAGE),
        context_window_tokens=128_000,
        max_output_tokens=8_000,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_thinking=True,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _response(payload: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        model_key="fake:worker",
        text=json.dumps(payload, ensure_ascii=False),
        input_tokens=10,
        output_tokens=5,
    )
