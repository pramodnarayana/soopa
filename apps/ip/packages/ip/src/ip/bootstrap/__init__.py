"""Bootstrap and IoC Container for the Integration Platform (IP) bounded context."""

from ip.bootstrap.container import Container
from ip.bootstrap.lifespan import shutdown, startup

__all__ = ["Container", "shutdown", "startup"]
