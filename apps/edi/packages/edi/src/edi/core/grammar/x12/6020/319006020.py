from edi.core.bots.config.botsconfig import *

syntax = {
    "version": "00602",
    "functionalgroup": "SO",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "BA2", MIN: 1, MAX: 1},
            {ID: "CD1", MIN: 1, MAX: 999},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
