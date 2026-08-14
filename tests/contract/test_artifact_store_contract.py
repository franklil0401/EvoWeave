"""Contract tests for content-addressed artifact persistence."""

import pytest

from evoweave.domain.artifacts import InputArtifactRef
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    ArtifactSource,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import ArtifactId
from evoweave.domain.ports import ArtifactStore
from evoweave.infrastructure.artifacts.memory import InMemoryArtifactStore


def test_artifact_store_put_get_and_deduplicate() -> None:
    store = InMemoryArtifactStore()
    assert isinstance(store, ArtifactStore)
    first = store.put_bytes(
        b"result",
        media_type="text/plain",
        kind=ArtifactKind.TEST_REPORT,
    )
    second = store.put_bytes(
        b"result",
        media_type="text/plain",
        kind=ArtifactKind.TEST_REPORT,
    )
    assert second == first
    assert store.get_bytes(first.artifact_id) == b"result"
    assert store.get_ref(first.artifact_id) == first


def test_same_content_cannot_have_conflicting_metadata() -> None:
    store = InMemoryArtifactStore()
    store.put_bytes(b"same", media_type="text/plain", kind=ArtifactKind.GENERIC)
    with pytest.raises(DomainError) as error:
        store.put_bytes(b"same", media_type="application/json", kind=ArtifactKind.GENERIC)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_ERROR


def test_unknown_artifact_has_stable_error_code() -> None:
    store = InMemoryArtifactStore()
    with pytest.raises(DomainError) as error:
        store.get_bytes(ArtifactId.new())
    assert error.value.code is ErrorCode.ARTIFACT_NOT_FOUND


def test_artifact_ref_can_be_enriched_without_changing_content_identity() -> None:
    store = InMemoryArtifactStore()
    base = store.put_bytes(b"png", media_type="image/png", kind=ArtifactKind.INPUT_IMAGE)
    enriched = InputArtifactRef(
        **base.model_dump(),
        source=ArtifactSource.CONTROLLED_INGESTION,
        security_status=ArtifactSecurityStatus.ACCEPTED,
        width_px=1,
        height_px=1,
    )
    store.update_ref(enriched)
    assert store.get_ref(base.artifact_id) == enriched


def test_artifact_ref_update_cannot_change_digest() -> None:
    store = InMemoryArtifactStore()
    base = store.put_bytes(b"data", media_type="text/plain", kind=ArtifactKind.GENERIC)
    tampered = base.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(DomainError) as error:
        store.update_ref(tampered)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_ERROR


def test_enriched_input_metadata_is_immutable() -> None:
    store = InMemoryArtifactStore()
    base = store.put_bytes(b"png", media_type="image/png", kind=ArtifactKind.INPUT_IMAGE)
    enriched = InputArtifactRef(
        **base.model_dump(),
        source=ArtifactSource.CONTROLLED_INGESTION,
        security_status=ArtifactSecurityStatus.ACCEPTED,
        original_name="first.png",
        width_px=1,
        height_px=1,
    )
    store.update_ref(enriched)
    changed = enriched.model_copy(update={"original_name": "second.png"})
    with pytest.raises(DomainError) as error:
        store.update_ref(changed)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_ERROR
