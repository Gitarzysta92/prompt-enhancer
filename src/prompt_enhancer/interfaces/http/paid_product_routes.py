"""Private, read-only readiness surface for the optional paid-product boundary."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Response

from ...application.paid_product.contracts import ProductReadiness


_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


def create_paid_product_readiness_router(
    require_local_token: Callable[..., None],
    readiness: ProductReadiness,
) -> APIRouter:
    """Expose capability gaps without mounting identity, billing, or job APIs."""

    router = APIRouter(
        prefix="/v1/paid-product",
        tags=["paid-product-readiness"],
        dependencies=[Depends(require_local_token)],
    )

    @router.get(
        "/readiness",
        response_model=ProductReadiness,
    )
    def product_readiness(response: Response) -> ProductReadiness:
        for name, value in _PRIVATE_HEADERS.items():
            response.headers[name] = value
        return readiness

    return router


__all__ = ["create_paid_product_readiness_router"]
