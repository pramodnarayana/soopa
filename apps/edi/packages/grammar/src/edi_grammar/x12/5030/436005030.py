from bots_core.infrastructure.config.botsconfig import *

from .records005030 import recorddefs

syntax = {
    "version": "00503",
    "functionalgroup": "LI",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "LFI", MIN: 1, MAX: 1},
            {ID: "N7", MIN: 1, MAX: 1},
            {ID: "K3", MIN: 0, MAX: 3},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
