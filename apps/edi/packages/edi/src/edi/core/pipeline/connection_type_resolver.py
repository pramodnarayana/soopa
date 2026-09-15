"""
Connection Type Resolver
========================

Domain Service: resolves the EDI connection type from a route configuration.
"""

from edi.domain.enums import EdiConnectionType
from edi.domain.exceptions import UnresolvableConnectionTypeError
from edi.domain.types import JsonDict


class ConnectionTypeResolver:
    """
    Pure domain service that determines the outbound connection type
    (e.g. AS2, SFTP) from a given route configuration and database record.
    """

    # O(1) strategy mapping for dynamic fields on the OutboundRoute model
    _FIELD_TO_CONNECTION_TYPE = {
        "as2_partner_id": EdiConnectionType.AS2,
        "sftp_partner_id": EdiConnectionType.SFTP,
    }

    @classmethod
    def resolve(cls, route_config: JsonDict, outbound_route: JsonDict) -> EdiConnectionType:
        """
        Resolve the connection type for the given route via a strict, ordered cascade.
        """
        raw_type = route_config.get("connection_type")
        if raw_type:
            # Assumes the raw type is a valid string representation of EdiConnectionType
            return EdiConnectionType(str(raw_type).upper())

        if outbound_route:
            # OCP-compliant O(1) lookup
            for field, connection_type in cls._FIELD_TO_CONNECTION_TYPE.items():
                if outbound_route.get(field):
                    return connection_type

        raise UnresolvableConnectionTypeError(
            "Unresolvable connection type from route configuration."
        )
