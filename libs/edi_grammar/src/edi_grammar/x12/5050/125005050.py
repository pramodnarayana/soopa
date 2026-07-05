from bots_core.infrastructure.config.botsconfig import *

syntax = {
    "version": "00505",
    "functionalgroup": "MR",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "BMM", MIN: 1, MAX: 1},
            {ID: "G62", MIN: 1, MAX: 1},
            {ID: "N7", MIN: 1, MAX: 1},
            {ID: "VC", MIN: 0, MAX: 21},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
