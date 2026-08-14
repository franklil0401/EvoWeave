"""Immutable references to persisted inputs, evidence, and task artifacts."""

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from evoweave.domain.base import DomainModel, utc_now
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    ArtifactSource,
    EvidenceKind,
)
from evoweave.domain.identifiers import (
    AgentId,
    ArtifactId,
    EvidenceId,
    SpecId,
    TaskId,
    WorkspaceId,
)
from evoweave.domain.validation import validate_repository_path, validate_unique_strings


class ImageIngestionPolicy(DomainModel):
    allowed_media_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")
    max_size_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_pixels: int = Field(default=40_000_000, ge=1)

    @field_validator("allowed_media_types")
    @classmethod
    def validate_media_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("allowed_media_types 不能为空")
        if len(set(values)) != len(values):
            raise ValueError("allowed_media_types 不能重复")
        if any(not value.startswith("image/") for value in values):
            raise ValueError("图片摄取策略只能允许 image/* MIME")
        return values


class ArtifactRef(DomainModel):
    artifact_id: ArtifactId
    kind: ArtifactKind
    media_type: str = Field(min_length=3, max_length=255, pattern=r"^[^/\s]+/[^/\s]+$")
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_key: str = Field(min_length=1, max_length=512)
    created_at: datetime = Field(default_factory=utc_now)


class InputArtifactRef(ArtifactRef):
    """A user-supplied artifact after controlled ingestion."""

    source: ArtifactSource
    security_status: ArtifactSecurityStatus
    original_name: str | None = Field(default=None, max_length=255)
    width_px: int | None = Field(default=None, ge=1, le=100_000)
    height_px: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_image_metadata(self) -> "InputArtifactRef":
        if (
            self.security_status is ArtifactSecurityStatus.ACCEPTED
            and self.source is not ArtifactSource.CONTROLLED_INGESTION
        ):
            raise ValueError("已通过安全检查的输入必须来自受控摄取")
        if self.kind is ArtifactKind.INPUT_IMAGE:
            if not self.media_type.startswith("image/"):
                raise ValueError("图片输入产物必须使用 image/* MIME")
            if self.width_px is None or self.height_px is None:
                raise ValueError("图片输入产物必须记录宽度和高度")
        return self


class EvidenceRef(DomainModel):
    evidence_id: EvidenceId
    kind: EvidenceKind
    summary: str = Field(min_length=1, max_length=2_000)
    artifact_id: ArtifactId | None = None
    repository_path: str | None = Field(default=None, min_length=1, max_length=1_024)
    symbol: str | None = Field(default=None, min_length=1, max_length=512)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    command: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_locator(self) -> "EvidenceRef":
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_end 存在时必须提供 line_start")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end 不能小于 line_start")
        if self.kind is EvidenceKind.ARTIFACT and self.artifact_id is None:
            raise ValueError("产物证据必须引用 artifact_id")
        if self.kind in {EvidenceKind.FILE, EvidenceKind.SYMBOL} and self.repository_path is None:
            raise ValueError("文件或符号证据必须包含仓库路径")
        if self.kind is EvidenceKind.SYMBOL and self.symbol is None:
            raise ValueError("符号证据必须包含 symbol")
        if self.kind is EvidenceKind.COMMAND and self.command is None:
            raise ValueError("命令证据必须包含 command")
        return self


class PatchArtifact(DomainModel):
    ref: ArtifactRef
    task_id: TaskId
    agent_id: AgentId
    execution_spec_id: SpecId
    execution_spec_version: int = Field(ge=1)
    workspace_id: WorkspaceId
    base_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    changed_paths: tuple[str, ...] = Field(min_length=1)
    supporting_artifact_ids: tuple[ArtifactId, ...] = ()

    @field_validator("changed_paths")
    @classmethod
    def validate_changed_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(validate_repository_path(value) for value in values)
        return validate_unique_strings(validated, "changed_paths")

    @model_validator(mode="after")
    def validate_patch(self) -> "PatchArtifact":
        if self.ref.kind is not ArtifactKind.PATCH:
            raise ValueError("PatchArtifact.ref.kind 必须为 patch")
        if len(set(self.supporting_artifact_ids)) != len(self.supporting_artifact_ids):
            raise ValueError("supporting_artifact_ids 不能重复")
        if self.ref.artifact_id in self.supporting_artifact_ids:
            raise ValueError("补丁自身不能作为 supporting artifact")
        return self
