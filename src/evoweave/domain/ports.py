"""Framework-independent ports implemented by infrastructure adapters."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from evoweave.domain.agent_execution_spec import AgentExecutionSpec
from evoweave.domain.artifacts import ArtifactRef, ImageIngestionPolicy, InputArtifactRef
from evoweave.domain.enums import ArtifactKind
from evoweave.domain.identifiers import ArtifactId, TaskId, WorkspaceId
from evoweave.domain.model_routing import (
    ModelProfile,
    ModelRequirement,
    ModelRoutingDecision,
)
from evoweave.domain.task_result import TaskResult


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model_key: str
    messages: tuple[str, ...]
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class ModelResponse:
    model_key: str
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ImageInput:
    data: bytes
    declared_media_type: str
    original_name: str | None = None


@runtime_checkable
class ModelGateway(Protocol):
    def list_profiles(self) -> tuple[ModelProfile, ...]: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...


@runtime_checkable
class ModelRouter(Protocol):
    def route(
        self,
        requirement: ModelRequirement,
        profiles: tuple[ModelProfile, ...],
    ) -> ModelRoutingDecision: ...


@runtime_checkable
class WorkerAdapter(Protocol):
    def execute(self, execution_spec: AgentExecutionSpec) -> TaskResult: ...


@runtime_checkable
class ArtifactStore(Protocol):
    def put_bytes(
        self,
        data: bytes,
        *,
        media_type: str,
        kind: ArtifactKind,
    ) -> ArtifactRef: ...

    def get_bytes(self, artifact_id: ArtifactId) -> bytes: ...

    def get_ref(self, artifact_id: ArtifactId) -> ArtifactRef: ...


@runtime_checkable
class InputArtifactIngestor(Protocol):
    def ingest_image(
        self,
        image: ImageInput,
        *,
        policy: ImageIngestionPolicy,
    ) -> InputArtifactRef: ...


@runtime_checkable
class WorkspaceAdapter(Protocol):
    @property
    def workspace_id(self) -> WorkspaceId: ...

    @property
    def task_id(self) -> TaskId: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, content: str) -> None: ...
