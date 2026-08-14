"""Build and persist a machine-readable validation report."""

from evoweave.domain.enums import ArtifactKind, FailureClassification
from evoweave.domain.identifiers import SpecId
from evoweave.domain.integration_models import (
    FailureDelta,
    IntegrationWorkspaceState,
    ValidationObservation,
    ValidationReport,
)
from evoweave.domain.ports import ArtifactStore


class ValidationReportBuilder:
    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._artifact_store = artifact_store

    def build(
        self,
        *,
        state: IntegrationWorkspaceState,
        observations: tuple[ValidationObservation, ...],
        failure_deltas: tuple[FailureDelta, ...],
    ) -> ValidationReport:
        blocking = {FailureClassification.NEW, FailureClassification.UNSTABLE}
        accepted = not any(item.classification in blocking for item in failure_deltas) and not any(
            item.timed_out or item.output_truncated for item in observations
        )
        report = ValidationReport(
            report_id=SpecId.new(),
            run_id=state.run_id,
            integration_id=state.integration_id,
            base_commit=state.base_commit,
            candidate_commit=state.head_commit,
            accepted=accepted,
            applied_patches=state.applied_patches,
            observations=observations,
            failure_deltas=failure_deltas,
        )
        reference = self._artifact_store.put_bytes(
            report.model_dump_json(indent=2).encode("utf-8"),
            media_type="application/json",
            kind=ArtifactKind.TEST_REPORT,
        )
        return report.model_copy(update={"report_ref": reference})
