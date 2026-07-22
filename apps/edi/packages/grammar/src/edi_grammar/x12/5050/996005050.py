from bots_core.infrastructure.config.botsconfig import *
from .records005050 import recorddefs

syntax = {
    "version": "00505",
    "functionalgroup": "FT",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "BGF", MIN: 1, MAX: 1},
            {ID: "K3", MIN: 1, MAX: 99999},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
