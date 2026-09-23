"""Capital Flow Intelligence backend.

Layer rule (CLAUDE.md A2):
Observed Data → Metrics → Signals → Regime → AI Interpretation → User Decision.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cfi")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
