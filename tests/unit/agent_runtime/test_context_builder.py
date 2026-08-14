"""Tests for minimal context construction and image isolation."""

from io import BytesIO

import pytest
from PIL import Image

from evoweave.agent_runtime.context_builder import ContextBuilder, ContextPolicy
from evoweave.domain.agent_execution_spec import AgentExecutionSpec
from evoweave.domain.artifacts import ImageIngestionPolicy
from evoweave.domain.enums import ArtifactKind, InputModality
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import AgentId, ArtifactId, RunId, SpecId, TaskId
from evoweave.domain.model_routing import ModelRoutingDecision
from evoweave.domain.ports import ImageInput
from evoweave.infrastructure.artifacts.image_ingestor import PillowImageIngestor
from evoweave.infrastructure.artifacts.memory import InMemoryArtifactStore


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), color="blue").save(buffer, format="PNG")
    return buffer.getvalue()


def _spec(
    *,
    task_id: TaskId,
    input_ids: tuple[ArtifactId, ...],
    context_ids: tuple[ArtifactId, ...] = (),
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
) -> AgentExecutionSpec:
    return AgentExecutionSpec(
        spec_id=SpecId.new(),
        run_id=RunId.new(),
        agent_id=AgentId.new(),
        task_id=task_id,
        task_spec_id=SpecId.new(),
        task_spec_version=1,
        base_commit="a" * 40,
        goal="理解界面并更新代码",
        acceptance_criteria=("界面符合需求",),
        required_modalities=modalities,
        model_routing=ModelRoutingDecision(
            decision_id=SpecId.new(),
            requirement_id=SpecId.new(),
            requirement_version=1,
            selected_model_key="fake:vision",
            reason="测试",
        ),
        read_scope=("src",),
        input_artifact_ids=input_ids,
        context_artifact_ids=context_ids,
    )


def test_only_visual_spec_receives_raw_image_attachment() -> None:
    store = InMemoryArtifactStore()
    image = PillowImageIngestor(store).ingest_image(
        ImageInput(data=_png(), declared_media_type="image/png", original_name="ui.png"),
        policy=ImageIngestionPolicy(),
    )
    visual = ContextBuilder(store).build(
        _spec(
            task_id=TaskId.new(),
            input_ids=(image.artifact_id,),
            modalities=(InputModality.TEXT, InputModality.IMAGE),
        )
    )
    text_only = ContextBuilder(store).build(
        _spec(task_id=TaskId.new(), input_ids=(image.artifact_id,))
    )
    assert visual.attachments[0].data == _png()
    assert not text_only.attachments
    assert text_only.excluded_image_artifact_ids == (image.artifact_id,)


def test_text_worker_receives_structured_visual_conclusion_not_raw_image() -> None:
    store = InMemoryArtifactStore()
    image = PillowImageIngestor(store).ingest_image(
        ImageInput(data=_png(), declared_media_type="image/png"),
        policy=ImageIngestionPolicy(),
    )
    conclusion = store.put_bytes(
        b'{"source_image_sha256":"abc","finding":"button is blue"}',
        media_type="application/json",
        kind=ArtifactKind.CONTEXT_BUNDLE,
    )
    bundle = ContextBuilder(store).build(
        _spec(
            task_id=TaskId.new(),
            input_ids=(image.artifact_id,),
            context_ids=(conclusion.artifact_id,),
        )
    )
    assert "button is blue" in bundle.text
    assert not bundle.attachments


def test_uncontrolled_image_reference_is_rejected() -> None:
    store = InMemoryArtifactStore()
    image = store.put_bytes(
        _png(),
        media_type="image/png",
        kind=ArtifactKind.INPUT_IMAGE,
    )
    with pytest.raises(DomainError) as error:
        ContextBuilder(store).build(_spec(task_id=TaskId.new(), input_ids=(image.artifact_id,)))
    assert error.value.code is ErrorCode.IMAGE_REJECTED


def test_context_byte_limit_rejects_large_artifact() -> None:
    store = InMemoryArtifactStore()
    context = store.put_bytes(
        b"large context",
        media_type="text/plain",
        kind=ArtifactKind.CONTEXT_BUNDLE,
    )
    with pytest.raises(DomainError) as error:
        ContextBuilder(store, ContextPolicy(max_artifact_bytes=2)).build(
            _spec(
                task_id=TaskId.new(),
                input_ids=(),
                context_ids=(context.artifact_id,),
            )
        )
    assert error.value.code is ErrorCode.CONTEXT_LIMIT_EXCEEDED
