"""Engine transport boundary; no benchmark execution or calculation."""

from .errors import (
    EngineConnectionError,
    EngineError,
    EngineHTTPError,
    EngineRemoteError,
    EngineResponseError,
    EngineTimeoutError,
    ModelNotFoundError,
)
from .llama_cpp import LlamaCppEngine, LlamaServerConfig
from .ollama import OllamaEngine
from .protocol import (
    EngineHealth,
    EngineProtocol,
    GenerationMetadata,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)

__all__ = [
    "EngineConnectionError",
    "EngineError",
    "EngineHTTPError",
    "EngineHealth",
    "EngineProtocol",
    "EngineRemoteError",
    "EngineResponseError",
    "EngineTimeoutError",
    "GenerationMetadata",
    "GenerationRequest",
    "GenerationResult",
    "LlamaCppEngine",
    "LlamaServerConfig",
    "ModelInfo",
    "ModelNotFoundError",
    "OllamaEngine",
]
