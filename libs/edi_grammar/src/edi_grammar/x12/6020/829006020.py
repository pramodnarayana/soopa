from bots_core.infrastructure.config.botsconfig import *

syntax = {
    "version": "00602",
    "functionalgroup": "PY",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "PCR", MIN: 1, MAX: 1},
            {ID: "TRN", MIN: 0, MAX: 2},
            {ID: "DTM", MIN: 1, MAX: 10},
            {ID: "REF", MIN: 0, MAX: 10},
            {ID: "QTY", MIN: 0, MAX: 10},
            {ID: "AMT", MIN: 0, MAX: 10},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
