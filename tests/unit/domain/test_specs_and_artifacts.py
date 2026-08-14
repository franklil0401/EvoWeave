"""Tests for input security, task specs, and worker execution specs."""

from hashlib import sha256

import pytest
from pydantic import ValidationError

from evoweave.domain.agent_execution_spec import AgentExecutionSpec
from evoweave.domain.artifacts import InputArtifactRef
from evoweave.domain.change_spec import ChangeSpec
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    ArtifactSource,
    InputModality,
    TaskDifficulty,
)
from evoweave.domain.identifiers import AgentId, ArtifactId, RunId, SpecId, TaskId
from evoweave.domain.model_routing import (
    DifficultyAssessment,
    ModelRequirement,
    ModelRoutingDecision,
)
from evoweave.domain.task_spec import TaskSpec

BASE_COMMIT = "a" * 40


def _image_ref(
    status: ArtifactSecurityStatus = ArtifactSecurityStatus.ACCEPTED,
) -> InputArtifactRef:
    data = b"safe-test-image"
    return InputArtifactRef(
        artifact_id=ArtifactId.new(),
        kind=ArtifactKind.INPUT_IMAGE,
        media_type="image/png",
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        storage_key="sha256/test-image",
        source=ArtifactSource.CONTROLLED_INGESTION,
        security_status=status,
        original_name="ui.png",
        width_px=800,
        height_px=600,
    )


def _requirement(
    task_id: TaskId,
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
) -> ModelRequirement:
    return ModelRequirement(
        requirement_id=SpecId.new(),
        task_id=task_id,
        difficulty=TaskDifficulty.LOW,
        required_modalities=modalities,
    )


def _task_spec(
    *,
    task_id: TaskId,
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
    input_artifact_ids: tuple[ArtifactId, ...] = (),
    read_scope: tuple[str, ...] = ("src",),
    write_scope: tuple[str, ...] = ("src/evoweave",),
) -> TaskSpec:
    return TaskSpec(
        spec_id=SpecId.new(),
        task_id=task_id,
        change_spec_id=SpecId.new(),
        goal="修改并验证领域协议",
        base_commit=BASE_COMMIT,
        acceptance_criteria=("测试通过",),
        input_artifact_ids=input_artifact_ids,
        read_scope=read_scope,
        write_scope=write_scope,
        required_modalities=modalities,
        difficulty=DifficultyAssessment(
            difficulty=TaskDifficulty.LOW,
            rationale="局部、低风险修改",
        ),
        model_requirement=_requirement(task_id, modalities),
    )


def test_image_artifact_requires_dimensions() -> None:
    with pytest.raises(ValidationError, match="宽度和高度"):
        InputArtifactRef(
            artifact_id=ArtifactId.new(),
            kind=ArtifactKind.INPUT_IMAGE,
            media_type="image/png",
            size_bytes=1,
            sha256="0" * 64,
            storage_key="sha256/example",
            source=ArtifactSource.CONTROLLED_INGESTION,
            security_status=ArtifactSecurityStatus.ACCEPTED,
        )


@pytest.mark.parametrize(
    "missing_field",
    ["media_type", "size_bytes", "sha256", "security_status"],
)
def test_input_artifact_rejects_missing_required_metadata(missing_field: str) -> None:
    data: dict[str, object] = {
        "artifact_id": ArtifactId.new(),
        "kind": ArtifactKind.INPUT_IMAGE,
        "media_type": "image/png",
        "size_bytes": 1,
        "sha256": "0" * 64,
        "storage_key": "sha256/example",
        "source": ArtifactSource.CONTROLLED_INGESTION,
        "security_status": ArtifactSecurityStatus.ACCEPTED,
        "width_px": 1,
        "height_px": 1,
    }
    del data[missing_field]
    with pytest.raises(ValidationError):
        InputArtifactRef.model_validate(data)


@pytest.mark.parametrize("missing_field", ["objective", "acceptance_criteria", "base_commit"])
def test_change_spec_rejects_missing_core_contract_field(missing_field: str) -> None:
    data: dict[str, object] = {
        "spec_id": SpecId.new(),
        "run_id": RunId.new(),
        "objective": "更新软件",
        "repository": "local/repository",
        "base_commit": BASE_COMMIT,
        "acceptance_criteria": ("测试通过",),
    }
    del data[missing_field]
    with pytest.raises(ValidationError):
        ChangeSpec.model_validate(data)


def test_change_spec_accepts_only_security_approved_inputs() -> None:
    with pytest.raises(ValidationError, match="安全摄取"):
        ChangeSpec(
            spec_id=SpecId.new(),
            run_id=RunId.new(),
            objective="按截图更新界面",
            repository="local/repository",
            base_commit=BASE_COMMIT,
            acceptance_criteria=("界面与截图一致",),
            input_artifacts=(_image_ref(ArtifactSecurityStatus.PENDING),),
        )


def test_accepted_input_must_come_from_controlled_ingestion() -> None:
    image = _image_ref().model_copy(update={"source": ArtifactSource.LOCAL_FILE})
    with pytest.raises(ValidationError, match="受控摄取"):
        InputArtifactRef.model_validate(image.model_dump())


def test_change_spec_rejects_duplicate_input_artifacts() -> None:
    image = _image_ref()
    with pytest.raises(ValidationError, match="不能重复"):
        ChangeSpec(
            spec_id=SpecId.new(),
            run_id=RunId.new(),
            objective="按截图更新界面",
            repository="local/repository",
            base_commit=BASE_COMMIT,
            acceptance_criteria=("界面与截图一致",),
            input_artifacts=(image, image),
        )


def test_write_scope_may_be_nested_below_read_scope() -> None:
    spec = _task_spec(task_id=TaskId.new())
    assert spec.write_scope == ("src/evoweave",)


def test_write_scope_cannot_escape_read_scope() -> None:
    with pytest.raises(ValidationError, match="write_scope"):
        _task_spec(
            task_id=TaskId.new(),
            read_scope=("src",),
            write_scope=("tests",),
        )


def test_image_task_requires_ingested_artifact_reference() -> None:
    modalities = (InputModality.TEXT, InputModality.IMAGE)
    with pytest.raises(ValidationError, match="图片任务"):
        _task_spec(task_id=TaskId.new(), modalities=modalities)


def test_task_and_model_modalities_must_match() -> None:
    task_id = TaskId.new()
    with pytest.raises(ValidationError, match="输入模态"):
        TaskSpec(
            spec_id=SpecId.new(),
            task_id=task_id,
            change_spec_id=SpecId.new(),
            goal="分析截图",
            base_commit=BASE_COMMIT,
            acceptance_criteria=("输出结论",),
            read_scope=("src",),
            required_modalities=(InputModality.TEXT, InputModality.IMAGE),
            difficulty=DifficultyAssessment(
                difficulty=TaskDifficulty.LOW,
                rationale="只读分析",
            ),
            model_requirement=_requirement(task_id),
        )


@pytest.mark.parametrize("missing_field", ["goal", "acceptance_criteria", "base_commit"])
def test_task_spec_rejects_missing_core_contract_field(missing_field: str) -> None:
    task_id = TaskId.new()
    data: dict[str, object] = {
        "spec_id": SpecId.new(),
        "task_id": task_id,
        "change_spec_id": SpecId.new(),
        "goal": "更新领域模型",
        "base_commit": BASE_COMMIT,
        "acceptance_criteria": ("测试通过",),
        "read_scope": ("src",),
        "difficulty": DifficultyAssessment(
            difficulty=TaskDifficulty.LOW,
            rationale="局部修改",
        ),
        "model_requirement": _requirement(task_id),
    }
    del data[missing_field]
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(data)


def test_agent_execution_spec_is_version_pinned() -> None:
    task_id = TaskId.new()
    decision = ModelRoutingDecision(
        decision_id=SpecId.new(),
        requirement_id=SpecId.new(),
        requirement_version=2,
        selected_model_key="fake:text-small",
        reason="满足硬能力约束",
    )
    spec = AgentExecutionSpec(
        spec_id=SpecId.new(),
        run_id=RunId.new(),
        agent_id=AgentId.new(),
        task_id=task_id,
        task_spec_id=SpecId.new(),
        task_spec_version=3,
        base_commit="a" * 40,
        goal="更新领域协议",
        acceptance_criteria=("测试通过",),
        model_routing=decision,
        read_scope=("src",),
        write_scope=("src/evoweave",),
    )
    assert spec.task_spec_version == 3
    assert spec.model_routing.requirement_version == 2
