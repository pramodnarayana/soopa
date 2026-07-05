from bots_core.infrastructure.config.botsconfig import *

syntax = {
    "version": "00505",
    "functionalgroup": "MY",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "SCP", MIN: 1, MAX: 1},
            {ID: "L11", MIN: 0, MAX: 5},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
