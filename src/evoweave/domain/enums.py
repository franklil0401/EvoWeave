"""Closed vocabularies for EvoWeave domain contracts."""

from enum import StrEnum


class ArtifactKind(StrEnum):
    INPUT_IMAGE = "input_image"
    REPOSITORY_PROFILE = "repository_profile"
    CONTEXT_BUNDLE = "context_bundle"
    PATCH = "patch"
    TEST_REPORT = "test_report"
    COMMAND_LOG = "command_log"
    CONTROL_SUMMARY = "control_summary"
    GENERIC = "generic"


class ArtifactSecurityStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ArtifactSource(StrEnum):
    LOCAL_FILE = "local_file"
    CONTROLLED_INGESTION = "controlled_ingestion"
    GENERATED = "generated"


class EvidenceKind(StrEnum):
    FILE = "file"
    SYMBOL = "symbol"
    COMMAND = "command"
    ARTIFACT = "artifact"


class InputModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class ModelAvailability(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ModelTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskDifficulty(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskRelation(StrEnum):
    DEPENDS_ON = "depends_on"
    VALIDATES = "validates"
    SUPERSEDES = "supersedes"


class PolicyViolationCode(StrEnum):
    TOO_MANY_NODES = "too_many_nodes"
    TOO_MANY_RUNNING_TASKS = "too_many_running_tasks"
    GRAPH_INVALID = "graph_invalid"
    RETRY_LIMIT_EXCEEDED = "retry_limit_exceeded"


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    TASK_GRAPH_REPLACED = "task_graph_replaced"
    TASK_STATUS_CHANGED = "task_status_changed"
    MODEL_ROUTED = "model_routed"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    ARTIFACT_PERSISTED = "artifact_persisted"
    POLICY_REJECTED = "policy_rejected"
