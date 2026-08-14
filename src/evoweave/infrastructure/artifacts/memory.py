"""In-memory content-addressed artifact store for deterministic tests."""

from hashlib import sha256

from evoweave.domain.artifacts import ArtifactRef
from evoweave.domain.enums import ArtifactKind
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import ArtifactId


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._content: dict[ArtifactId, bytes] = {}
        self._refs: dict[ArtifactId, ArtifactRef] = {}
        self._id_by_digest: dict[str, ArtifactId] = {}

    def put_bytes(
        self,
        data: bytes,
        *,
        media_type: str,
        kind: ArtifactKind,
    ) -> ArtifactRef:
        digest = sha256(data).hexdigest()
        existing_id = self._id_by_digest.get(digest)
        if existing_id is not None:
            existing = self._refs[existing_id]
            if existing.media_type != media_type or existing.kind is not kind:
                raise DomainError(
                    ErrorCode.ARTIFACT_INTEGRITY_ERROR,
                    "相同内容不能以冲突的媒体类型或产物类型重复登记",
                )
            return existing

        artifact_id = ArtifactId.new()
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            media_type=media_type,
            size_bytes=len(data),
            sha256=digest,
            storage_key=f"sha256/{digest}",
        )
        self._content[artifact_id] = bytes(data)
        self._refs[artifact_id] = ref
        self._id_by_digest[digest] = artifact_id
        return ref

    def get_bytes(self, artifact_id: ArtifactId) -> bytes:
        try:
            return self._content[artifact_id]
        except KeyError as exc:
            raise DomainError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                f"找不到产物：{artifact_id}",
            ) from exc

    def get_ref(self, artifact_id: ArtifactId) -> ArtifactRef:
        try:
            return self._refs[artifact_id]
        except KeyError as exc:
            raise DomainError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                f"找不到产物引用：{artifact_id}",
            ) from exc
