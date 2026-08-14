"""Best-effort cleanup wrapper that preserves recoverable lease state."""

from evoweave.domain.identifiers import WorkspaceId
from evoweave.domain.workspace_models import WorkspaceLease
from evoweave.workspaces.manager import WorkspaceManager


class WorkspaceCleanup:
    def __init__(self, manager: WorkspaceManager) -> None:
        self._manager = manager

    def release(self, workspace_id: WorkspaceId) -> WorkspaceLease:
        return self._manager.release(workspace_id)
