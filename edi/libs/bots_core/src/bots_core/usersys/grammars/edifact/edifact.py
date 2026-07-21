from bots_core.infrastructure.config.botsconfig import ID, LEVEL, MAX, MIN

syntax = {
    "version": "3",
    "charset": "utf-8",
    "decimaal": ".",
    "escape": "?",
    "record_sep": "'",
    "field_sep": "+",
    "sfield_sep": ":",
    "reserve": "*",
    "skip_char": "\r\n",
    "forceqs": False,
}

structure = [
    {
        ID: "UNB",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {
                ID: "UNH",
                MIN: 1,
                MAX: 9999,
                LEVEL: [
                    {ID: "BGM", MIN: 1, MAX: 1},
                    {ID: "DTM", MIN: 0, MAX: 35},
                    {ID: "UNT", MIN: 1, MAX: 1},
                ],
            },
            {ID: "UNZ", MIN: 1, MAX: 1},
        ],
    }
]

recorddefs = {
    "UNA": [
        ["BOTSID", "M", 3, "A"],
        ["UNA1", "M", 1, "A"],
        ["UNA2", "M", 1, "A"],
        ["UNA3", "M", 1, "A"],
        ["UNA4", "M", 1, "A"],
        ["UNA5", "M", 1, "A"],
        ["UNA6", "M", 1, "A"],
    ],
    "UNB": [
        ["BOTSID", "M", 3, "A"],
        [
            "S001",
            "M",
            [
                ["S001.0001", "M", 4, "A"],
                ["S001.0002", "M", 1, "AN"],
            ],
        ],
        [
            "S002",
            "M",
            [
                ["S002.0004", "M", 35, "AN"],
                ["S002.0007", "C", 35, "AN"],
            ],
        ],
        [
            "S003",
            "M",
            [
                ["S003.0010", "M", 35, "AN"],
                ["S003.0008", "C", 35, "AN"],
            ],
        ],
        [
            "S004",
            "M",
            [
                ["S004.0017", "M", 6, "N"],
                ["S004.0019", "M", 4, "N"],
            ],
        ],
        ["0020", "M", 14, "AN"],
    ],
    "UNH": [
        ["BOTSID", "M", 3, "A"],
        ["0062", "M", 14, "AN"],
        [
            "S009",
            "M",
            [
                ["S009.0065", "M", 6, "AN"],
                ["S009.0052", "M", 3, "AN"],
                ["S009.0054", "M", 3, "AN"],
                ["S009.0051", "M", 2, "AN"],
            ],
        ],
    ],
    "BGM": [
        ["BOTSID", "M", 3, "A"],
        [
            "C002",
            "C",
            [
                ["C002.1001", "C", 3, "AN"],
                ["C002.1131", "C", 17, "AN"],
            ],
        ],
        [
            "C106",
            "C",
            [
                ["C106.1004", "C", 35, "AN"],
                ["C106.1056", "C", 9, "AN"],
            ],
        ],
        ["1225", "C", 3, "AN"],
    ],
    "DTM": [
        ["BOTSID", "M", 3, "A"],
        [
            "C507",
            "M",
            [
                ["C507.2005", "M", 3, "AN"],
                ["C507.2380", "C", 35, "AN"],
                ["C507.2379", "C", 3, "AN"],
            ],
        ],
    ],
    "UNT": [
        ["BOTSID", "M", 3, "A"],
        ["0074", "M", 6, "N"],
        ["0062", "M", 14, "AN"],
    ],
    "UNZ": [
        ["BOTSID", "M", 3, "A"],
        ["0036", "M", 6, "N"],
        ["0020", "M", 14, "AN"],
    ],
}
