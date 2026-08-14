from evoweave.domain.artifacts import InputArtifactRef
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    ArtifactSource,
)
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore


def test_local_store_persists_content_and_enriched_input_metadata(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    reference = store.put_bytes(
        b"image",
        media_type="image/png",
        kind=ArtifactKind.INPUT_IMAGE,
    )
    enriched = InputArtifactRef(
        **reference.model_dump(),
        source=ArtifactSource.CONTROLLED_INGESTION,
        security_status=ArtifactSecurityStatus.ACCEPTED,
        original_name="input.png",
        width_px=10,
        height_px=20,
    )
    store.update_ref(enriched)
    restarted = LocalArtifactStore(tmp_path / "artifacts")

    assert restarted.get_bytes(reference.artifact_id) == b"image"
    assert restarted.get_ref(reference.artifact_id) == enriched


def test_local_store_deduplicates_equal_content(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes(b"same", media_type="text/plain", kind=ArtifactKind.GENERIC)
    second = store.put_bytes(b"same", media_type="text/plain", kind=ArtifactKind.GENERIC)

    assert first == second
