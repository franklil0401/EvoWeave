"""Stable domain error codes and exceptions."""

from collections.abc import Mapping
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_SPEC = "invalid_spec"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    INVALID_GRAPH = "invalid_graph"
    POLICY_REJECTED = "policy_rejected"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_CAPABILITY_MISMATCH = "model_capability_mismatch"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    CAPABILITY_NOT_FOUND = "capability_not_found"
    CAPABILITY_DENIED = "capability_denied"
    COMMAND_DENIED = "command_denied"
    CONTEXT_LIMIT_EXCEEDED = "context_limit_exceeded"
    RUNTIME_LIMIT_EXCEEDED = "runtime_limit_exceeded"
    IMAGE_REJECTED = "image_rejected"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    ARTIFACT_INTEGRITY_ERROR = "artifact_integrity_error"
    WORKSPACE_ACCESS_DENIED = "workspace_access_denied"
    SCRIPT_EXHAUSTED = "script_exhausted"


class DomainError(Exception):
    """Base exception with a stable machine-readable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
