"""Explicit latest-patch rollback through the integration state manager."""

from evoweave.domain.identifiers import IntegrationId
from evoweave.domain.integration_models import IntegrationWorkspaceState
from evoweave.integration.integration_workspace import IntegrationWorkspaceManager
from evoweave.integration.patch_applier import PatchApplier


class IntegrationRollback:
    def __init__(
        self,
        manager: IntegrationWorkspaceManager,
        applier: PatchApplier,
    ) -> None:
        self._manager = manager
        self._applier = applier

    def latest(self, integration_id: IntegrationId) -> IntegrationWorkspaceState:
        state = self._manager.get(integration_id)
        revised = self._applier.rollback_latest(state)
        self._manager.save(revised)
        return revised
