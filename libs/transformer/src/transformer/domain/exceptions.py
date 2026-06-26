class TransformerError(Exception):
    """Base exception for all transformer domain errors."""

    pass


class TranslationError(TransformerError):
    """Raised when the underlying EDI engine fails to parse the document."""

    pass


class ComplianceError(TransformerError):
    """Raised when the document parses but violates business or EDI compliance rules."""

    pass


class MappingError(TransformerError):
    """Raised when the parsed EDI fails to map into the target schema."""

    pass
