"""Provider lifecycle state diagnostics utility.

Defines locally determinable states for external integration providers:
- disabled: provider intentionally turned off.
- missing_credentials: no usable credential is configured.
- configured: a non-empty credential is available, but its validity has not been confirmed.
- unavailable: the provider cannot currently be used because of a runtime failure.
"""

from typing import Dict, Literal, Optional
from app.config import settings

ProviderLifecycleState = Literal["disabled", "missing_credentials", "configured", "unavailable"]


def get_tinyfish_lifecycle_state(
    runtime_failure: bool = False,
    circuit_open: Optional[bool] = None,
) -> ProviderLifecycleState:
    """Determine the lifecycle state of the TinyFish documentation provider.
    
    Guarantees:
    - Never evaluates key validity without an upstream provider response.
    - Never returns or inspects secret key contents beyond emptiness.
    - Dynamically reports 'unavailable' if the runtime circuit breaker is actively OPEN.
    """
    if runtime_failure or circuit_open is True:
        return "unavailable"

    if settings.MOCK_MODE:
        return "disabled"

    raw_key = settings.TINYFISH_API_KEY
    if not raw_key or not raw_key.strip():
        return "missing_credentials"

    if circuit_open is False:
        return "configured"

    try:
        from app.services.documentation.retrieval_service import retrieval_service
        from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
        if isinstance(retrieval_service.live_retriever, TinyFishLiveRetriever):
            if retrieval_service.live_retriever.circuit_breaker.state == "open":
                return "unavailable"
    except Exception:
        pass

    return "configured"


def get_llm_lifecycle_state(runtime_failure: bool = False) -> ProviderLifecycleState:
    """Determine the lifecycle state of the LLM reasoning provider.
    
    Guarantees:
    - Never evaluates key validity without an upstream provider response.
    - Never returns or inspects secret key contents beyond emptiness.
    """
    if runtime_failure:
        return "unavailable"

    provider_name = (settings.LLM_PROVIDER or "disabled").strip().lower()

    if provider_name == "disabled":
        return "disabled"

    if provider_name == "mock":
        return "configured"

    if provider_name == "openai":
        raw_key = settings.LLM_API_KEY
        if not raw_key or not raw_key.strip():
            return "missing_credentials"
        return "configured"

    return "disabled"


def get_all_provider_lifecycle_states() -> Dict[str, ProviderLifecycleState]:
    """Return dictionary of all provider lifecycle states."""
    return {
        "tinyfish": get_tinyfish_lifecycle_state(),
        "llm": get_llm_lifecycle_state(),
    }
