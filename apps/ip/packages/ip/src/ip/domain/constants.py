"""Domain constants and ID prefixes for the Integration Platform."""

from enum import StrEnum


class IpDomainIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the Integration Platform bounded context."""

    CONNECTION = "ip_conn"
    CATALOG = "ip_cat"
    STREAM = "ip_strm"
    REPLICA = "ip_rep"
    INBOUND_RECORD = "ip_inb"
    TRACE = "ip_trc"
    GEM = "ip_gem"
    TIMELINE = "ip_tml"
