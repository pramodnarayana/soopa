from edi.core.bots.config.botsconfig import (
    ID,
    LEVEL,
    MAX,
    MIN,
    SUBTRANSLATION,
)

syntax = {
    "version": "00401",
    "charset": "us-ascii",
    "record_sep": "~",
    "field_sep": "*",
    "sfield_sep": ">",
    "escape": "",
    "reserve": "^",
    "skip_char": "\r\n",
    "forceqs": False,
    "decimaal": ".",
}

structure = [
    {
        ID: "ISA",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {
                ID: "GS",
                MIN: 1,
                MAX: 99999,
                LEVEL: [
                    {
                        ID: "ST",
                        MIN: 1,
                        MAX: 99999,
                        SUBTRANSLATION: [{"BOTSID": "ST", "ST01": None}],
                        LEVEL: [],
                    },
                    {ID: "GE", MIN: 1, MAX: 1},
                ],
            },
            {ID: "IEA", MIN: 1, MAX: 1},
        ],
    }
]

recorddefs = {
    "ISA": [
        ["BOTSID", "M", 3, "AN"],
        ["ISA01", "M", 2, "ID"],
        ["ISA02", "M", 10, "AN"],
        ["ISA03", "M", 2, "ID"],
        ["ISA04", "M", 10, "AN"],
        ["ISA05", "M", 2, "ID"],
        ["ISA06", "M", 15, "AN"],
        ["ISA07", "M", 2, "ID"],
        ["ISA08", "M", 15, "AN"],
        ["ISA09", "M", 6, "DT"],
        ["ISA10", "M", 4, "TM"],
        ["ISA11", "M", 1, "ID"],
        ["ISA12", "M", 5, "ID"],
        ["ISA13", "M", 9, "N0"],
        ["ISA14", "M", 1, "ID"],
        ["ISA15", "M", 1, "ID"],
        [
            "ISA16",
            "C",
            [
                ["ISA16.01", "C", 1, "AN"],
                ["ISA16.02", "C", 1, "AN"],
            ],
        ],
    ],
    "GS": [
        ["BOTSID", "M", 2, "AN"],
        ["GS01", "M", 2, "ID"],
        ["GS02", "M", 15, "AN"],
        ["GS03", "M", 15, "AN"],
        ["GS04", "M", 8, "DT"],
        ["GS05", "M", 8, "TM"],
        ["GS06", "M", 9, "N0"],
        ["GS07", "M", 2, "ID"],
        ["GS08", "M", 12, "AN"],
    ],
    "GE": [
        ["BOTSID", "M", 2, "AN"],
        ["GE01", "M", 1, "N0"],
        ["GE02", "M", 9, "N0"],
    ],
    "ST": [
        ["BOTSID", "M", 2, "AN"],
        ["ST01", "M", 3, "AN"],
        ["ST02", "M", 9, "AN"],
    ],
    "IEA": [
        ["BOTSID", "M", 3, "AN"],
        ["IEA01", "M", 5, "N0"],
        ["IEA02", "M", 9, "N0"],
    ],
}
