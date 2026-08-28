"""Sales-data connectors: pull a retailer's own order history from the tools they use.

See :mod:`app.services.connectors.registry` for the two rules this package holds
to -- no mocked data behind any logo, and missing credentials are named rather
than hidden.
"""

from app.services.connectors.base import (
    ConnectorError,
    ProviderSpec,
    SalesConnector,
    SyncResult,
)
from app.services.connectors.registry import PROVIDERS

__all__ = ["PROVIDERS", "ConnectorError", "ProviderSpec", "SalesConnector", "SyncResult"]
