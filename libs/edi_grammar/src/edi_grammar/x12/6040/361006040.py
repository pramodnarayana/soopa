from bots_core.infrastructure.config.botsconfig import *
from .records006040 import recorddefs

syntax = {
    "version": "00604",
    "functionalgroup": "SO",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "N1", MIN: 1, MAX: 1},
            {
                ID: "CI",
                MIN: 1,
                MAX: 9999,
                LEVEL: [
                    {ID: "K1", MIN: 0, MAX: 1},
                ],
            },
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
