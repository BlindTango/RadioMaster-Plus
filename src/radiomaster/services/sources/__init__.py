"""Multi-source station catalog: sources package.

See base.py for the contract every source implements, registry.py for
the single place the UI asks which sources exist and are enabled.
"""

from radiomaster.services.sources.base import (
    SourceCapabilities,
    SourceNode,
    SourceUnavailable,
    StationRef,
    StationSource,
    describe_source,
)
from radiomaster.services.sources.registry import (
    CONFIG_KEY,
    DEFAULT_ENABLED,
    SourceRegistry,
)

__all__ = [
    "SourceCapabilities",
    "SourceNode",
    "SourceUnavailable",
    "StationRef",
    "StationSource",
    "describe_source",
    "CONFIG_KEY",
    "DEFAULT_ENABLED",
    "SourceRegistry",
]