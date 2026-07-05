from bots_core.infrastructure.config.botsconfig import *

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
            {ID: "DR", MIN: 1, MAX: 1},
            {ID: "PI", MIN: 0, MAX: 1},
            {ID: "SA", MIN: 1, MAX: 1},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
