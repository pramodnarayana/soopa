from bots_core.infrastructure.config.botsconfig import *
from .records006010 import recorddefs

syntax = {
    "version": "00601",
    "functionalgroup": "SO",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "M10", MIN: 0, MAX: 1},
            {ID: "P4", MIN: 0, MAX: 1},
            {ID: "CM", MIN: 0, MAX: 1},
            {
                ID: "M15",
                MIN: 1,
                MAX: 9999,
                LEVEL: [
                    {ID: "M7A", MIN: 0, MAX: 22},
                    {ID: "V1", MIN: 0, MAX: 1},
                    {ID: "V2", MIN: 0, MAX: 1},
                    {ID: "MEA", MIN: 0, MAX: 1},
                    {ID: "K1", MIN: 0, MAX: 4},
                ],
            },
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
