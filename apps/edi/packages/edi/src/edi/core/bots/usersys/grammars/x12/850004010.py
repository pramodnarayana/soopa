from edi.core.bots.config.botsconfig import ID, LEVEL, MAX, MIN

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
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "BEG", MIN: 1, MAX: 1},
            {ID: "PO1", MIN: 0, MAX: 99999},
            {ID: "CTT", MIN: 1, MAX: 1},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]

recorddefs = {
    "ST": [
        ["BOTSID", "M", 3, "AN"],
        ["ST01", "M", 3, "ID"],
        ["ST02", "M", 9, "AN"],
    ],
    "BEG": [
        ["BOTSID", "M", 3, "AN"],
        ["BEG01", "M", 2, "ID"],
        ["BEG02", "M", 2, "ID"],
        ["BEG03", "M", 22, "AN"],
    ],
    "PO1": [
        ["BOTSID", "M", 3, "AN"],
        ["PO101", "M", 20, "AN"],
        ["PO102", "M", 15, "R"],
        ["PO103", "M", 2, "ID"],
        ["PO104", "M", 17, "R"],
    ],
    "CTT": [
        ["BOTSID", "M", 3, "AN"],
        ["CTT01", "M", 6, "N0"],
    ],
    "SE": [
        ["BOTSID", "M", 2, "AN"],
        ["SE01", "M", 10, "N0"],
        ["SE02", "M", 9, "AN"],
    ],
}
