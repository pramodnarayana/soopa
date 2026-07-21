from bots_core.infrastructure.config.botsconfig import *
from .records005050 import recorddefs

syntax = {
    "version": "00505",
    "functionalgroup": "AL",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "ZD", MIN: 1, MAX: 1},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
