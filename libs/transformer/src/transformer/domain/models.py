from dataclasses import dataclass

from pydantic import BaseModel, Field


class TransactionSet(BaseModel):
    """Represents a single EDI document/transaction set (e.g., an 850 or 810)."""

    transaction_type: str = Field(
        ..., description="The EDI transaction type, e.g., '850', '810', 'ORDERS'"
    )
    control_number: str = Field(..., description="The transaction set control number")
    data: dict[str, object] = Field(
        ..., description="The hierarchical JSON representation of the transaction"
    )


class ParsedEdiPayload(BaseModel):
    """Represents the complete parsed result of an inbound raw EDI file."""

    sender_id: str = Field(..., description="Interchange sender ID")
    receiver_id: str = Field(..., description="Interchange receiver ID")
    interchange_control_number: str = Field(..., description="ISA/UNB control number")
    transactions: list[TransactionSet] = Field(
        default_factory=list, description="List of transaction sets in this interchange"
    )


@dataclass
class MappingRule:
    """Represents a rule for transforming raw JSON to business JSON."""

    source_path: str
    target_path: str
    transformation_type: str = "DIRECT"
