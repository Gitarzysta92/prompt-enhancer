"""Content-free paid-product failures."""

from __future__ import annotations

from .contracts import PaidReasonCode


class PaidProductError(RuntimeError):
    def __init__(self, reason: PaidReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


class PaidAuthorizationError(PaidProductError):
    pass


class BillingWebhookError(PaidProductError):
    pass


class SpendLimitError(PaidProductError):
    pass


class ApprovalError(PaidProductError):
    pass


class ProviderInvocationError(PaidProductError):
    pass


__all__ = [
    "ApprovalError",
    "BillingWebhookError",
    "PaidAuthorizationError",
    "PaidProductError",
    "ProviderInvocationError",
    "SpendLimitError",
]
