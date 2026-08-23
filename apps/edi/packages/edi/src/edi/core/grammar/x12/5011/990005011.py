from edi.core.bots.config.botsconfig import *

syntax = {
    "version": "00403",  # version of ISA to send
    "functionalgroup": "GF",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "B1", MIN: 1, MAX: 1},
            {ID: "L11", MIN: 0, MAX: 1},
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
