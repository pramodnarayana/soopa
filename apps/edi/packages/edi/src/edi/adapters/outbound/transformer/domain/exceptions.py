from edi.domain.exceptions import EdiTransformationError


class TransformerError(Exception):
    """Base exception for all transformer domain errors."""


class TransformationError(TransformerError, EdiTransformationError):
    """Raised when the underlying EDI engine fails to parse the document."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        EdiTransformationError.__init__(self, message=message, errors=errors)


class ComplianceError(TransformerError):
    """Raised when the document parses but violates business or EDI compliance rules."""


class MappingError(TransformerError):
    """Raised when the parsed EDI fails to map into the target schema."""
