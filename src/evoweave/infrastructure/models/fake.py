"""Deterministic, offline model gateway for tests and local development."""

from collections import deque
from collections.abc import Iterable

from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.model_routing import ModelProfile
from evoweave.domain.ports import ModelRequest, ModelResponse


class ScriptedModelGateway:
    """Return preloaded responses in order and never access the network."""

    def __init__(
        self,
        profiles: Iterable[ModelProfile] = (),
        responses: Iterable[ModelResponse] = (),
    ) -> None:
        self._profiles = tuple(profiles)
        self._responses = deque(responses)
        self.requests: list[ModelRequest] = []

    def list_profiles(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._responses:
            raise DomainError(
                ErrorCode.SCRIPT_EXHAUSTED,
                "脚本化假模型响应已经耗尽",
                details={"request_model": request.model_key},
            )
        response = self._responses.popleft()
        if response.model_key != request.model_key:
            raise DomainError(
                ErrorCode.MODEL_CAPABILITY_MISMATCH,
                "脚本响应模型与请求模型不一致",
                details={
                    "request_model": request.model_key,
                    "response_model": response.model_key,
                },
            )
        return response
