from edi.core.bots.config.botsconfig import *

syntax = {
    "version": "00403",  # version of ISA to send
    "functionalgroup": "BA",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "M10", MIN: 1, MAX: 1},
            {ID: "P4", MIN: 1, MAX: 1},
            {ID: "M20", MIN: 1, MAX: 999},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
