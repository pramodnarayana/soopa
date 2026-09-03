from dataclasses import dataclass, field


@dataclass
class FieldDefinition:
    """
    Enterprise model for EDI Field/Composite definition.
    Replaces the legacy BOTS list structure.
    """

    id: str
    mandatory: str | int
    length: int | tuple | float | list
    format: str
    is_field: bool
    decimals: int
    min_length: int
    bformat: str
    max_repeat: int

    # Subfields are only used if is_field is False (it's a composite)
    subfields: list["FieldDefinition"] = field(default_factory=list)

    @property
    def is_mandatory(self) -> bool:
        return self.mandatory == 1 or self.mandatory == "M"


@dataclass
class StructureNode:
    """
    Enterprise model for EDI Structure definition.
    Replaces the legacy BOTS dict structure.
    """

    id: str
    min_occ: int
    max_occ: int
    count: int = 0
    level: list["StructureNode"] | None = None
    mpath: list[str] = field(default_factory=list)
    fields: list[FieldDefinition] = field(default_factory=list)
    queries: dict[str, object] | None = None
    subtranslation: list[object] | None = None
    botsidnr: str | None = None
    fixed_record_length: int | None = None


def create_field_definition(field_list: list) -> FieldDefinition:
    is_field = field_list[4]
    return FieldDefinition(
        id=field_list[0],
        mandatory=field_list[1],
        length=field_list[2] if is_field else 0,
        format=field_list[3],
        is_field=is_field,
        decimals=field_list[5],
        min_length=field_list[6],
        bformat=field_list[7],
        max_repeat=field_list[8],
        subfields=[]
        if is_field
        else [
            (create_field_definition(sf) if isinstance(sf, list) else sf) for sf in field_list[2]
        ],
    )


def create_structure_node(node_dict: dict) -> StructureNode:
    return StructureNode(
        id=node_dict.get(0, ""),
        min_occ=node_dict.get(1, 0),
        max_occ=node_dict.get(2, 0),
        count=node_dict.get(3, 0),
        level=node_dict.get(4),
        mpath=node_dict.get(5, []),
        fields=node_dict.get(6, []),
        queries=node_dict.get(7),
        subtranslation=node_dict.get(8),
        botsidnr=node_dict.get(9),
        fixed_record_length=node_dict.get(10),
    )
