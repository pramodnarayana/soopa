from bots_core.infrastructure.config.botsconfig import *

from .records006030 import recorddefs

syntax = {
    "version": "00603",
    "functionalgroup": "EO",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "BGN", MIN: 1, MAX: 1},
            {
                ID: "N1",
                MIN: 0,
                MAX: 5,
                LEVEL: [
                    {ID: "N2", MIN: 0, MAX: 1},
                    {ID: "N3", MIN: 0, MAX: 1},
                    {ID: "N4", MIN: 0, MAX: 1},
                    {ID: "PER", MIN: 0, MAX: 1},
                ],
            },
            {
                ID: "N21",
                MIN: 1,
                MAX: 9999,
                LEVEL: [
                    {ID: "VEH", MIN: 0, MAX: 1},
                    {ID: "DTM", MIN: 0, MAX: 10},
                    {ID: "MEA", MIN: 0, MAX: 20},
                    {ID: "N9", MIN: 0, MAX: 20},
                    {ID: "LQ", MIN: 0, MAX: 20},
                    {ID: "YNQ", MIN: 0, MAX: 10},
                ],
            },
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
