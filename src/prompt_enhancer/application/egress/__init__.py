"""Exact registry of local and future egress capabilities."""

from .classification import (
    EGRESS_REGISTRY,
    EgressClass,
    EgressRegistration,
    FUTURE_EGRESS_STATES,
    FutureEgressState,
    classify_network_module,
)

__all__ = [
    "EGRESS_REGISTRY",
    "EgressClass",
    "EgressRegistration",
    "FUTURE_EGRESS_STATES",
    "FutureEgressState",
    "classify_network_module",
]
