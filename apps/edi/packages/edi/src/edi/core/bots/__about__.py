"""
Bots EDI Translator __about__.py
"""

from importlib import metadata

__all__ = [
    "__author__",
    "__email__",
    "__license__",
    "__summary__",
    "__title__",
    "__url__",
    "__version__",
    "__version_info__",
]

__title__ = "bots-core"

__version__ = metadata.version(__title__)
__version_info__ = __version__.split(".")

__summary__ = """Bots EDI Translator"""

__license__ = "GNU General Public License (GPL v3.0)"

__author__ = "The Bots developers"
__email__ = "ludovic.watteaux@gmail.com"

__url__ = "https://gitlab.com/bots-ediint/bots"
