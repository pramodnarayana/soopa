from edi.core.bots.config.botsconfig import *

syntax = {
    "version": "00603",
    "functionalgroup": "TP",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "REN", MIN: 1, MAX: 1},
            {
                ID: "DK",
                MIN: 1,
                MAX: 100,
                LEVEL: [
                    {ID: "PI", MIN: 0, MAX: 1},
                    {ID: "JL", MIN: 0, MAX: 1},
                    {ID: "K1", MIN: 0, MAX: 100},
                ],
            },
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
