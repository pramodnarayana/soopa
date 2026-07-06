from bots_core.infrastructure.config.botsconfig import *
from .records006020 import recorddefs

syntax = {
    "version": "00602",
    "functionalgroup": "D4",
}

structure = [
    {
        ID: "ST",
        MIN: 1,
        MAX: 1,
        LEVEL: [
            {ID: "CTH", MIN: 1, MAX: 1},
            {ID: "CUR", MIN: 0, MAX: 1},
            {ID: "DTM", MIN: 0, MAX: 10},
            {ID: "MTX", MIN: 0, MAX: 1},
            {ID: "REF", MIN: 0, MAX: 99999},
            {ID: "SAC", MIN: 0, MAX: 99999},
            {
                ID: "NM1",
                MIN: 0,
                MAX: 99999,
                LEVEL: [
                    {ID: "NX1", MIN: 0, MAX: 1},
                    {ID: "PPR", MIN: 0, MAX: 99999},
                    {ID: "N2", MIN: 0, MAX: 2},
                    {ID: "N3", MIN: 0, MAX: 2},
                    {ID: "N4", MIN: 0, MAX: 1},
                    {ID: "PER", MIN: 0, MAX: 99999},
                    {
                        ID: "N1",
                        MIN: 0,
                        MAX: 99999,
                        LEVEL: [
                            {ID: "N2", MIN: 0, MAX: 2},
                            {ID: "N3", MIN: 0, MAX: 2},
                            {ID: "N4", MIN: 0, MAX: 1},
                            {ID: "PER", MIN: 0, MAX: 99999},
                        ],
                    },
                ],
            },
            {
                ID: "AMT",
                MIN: 0,
                MAX: 99999,
                LEVEL: [
                    {ID: "MTX", MIN: 0, MAX: 1},
                ],
            },
            {
                ID: "QTY",
                MIN: 0,
                MAX: 99999,
                LEVEL: [
                    {ID: "MTX", MIN: 0, MAX: 1},
                ],
            },
            {
                ID: "LS",
                MIN: 0,
                MAX: 1,
                LEVEL: [
                    {
                        ID: "N1",
                        MIN: 1,
                        MAX: 3,
                        LEVEL: [
                            {ID: "DTM", MIN: 1, MAX: 2},
                            {ID: "TBP", MIN: 0, MAX: 1},
                        ],
                    },
                    {ID: "LE", MIN: 1, MAX: 1},
                ],
            },
            {
                ID: "CPL",
                MIN: 0,
                MAX: 99999,
                LEVEL: [
                    {ID: "REF", MIN: 0, MAX: 99999},
                    {ID: "PPR", MIN: 0, MAX: 99999},
                    {ID: "MTX", MIN: 0, MAX: 1},
                    {
                        ID: "DTM",
                        MIN: 0,
                        MAX: 99999,
                        LEVEL: [
                            {ID: "TBP", MIN: 0, MAX: 1},
                            {ID: "N1", MIN: 0, MAX: 99999},
                        ],
                    },
                    {
                        ID: "AMT",
                        MIN: 0,
                        MAX: 99999,
                        LEVEL: [
                            {ID: "MEA", MIN: 0, MAX: 2},
                            {ID: "TBP", MIN: 0, MAX: 1},
                        ],
                    },
                    {
                        ID: "LS",
                        MIN: 0,
                        MAX: 1,
                        LEVEL: [
                            {
                                ID: "N1",
                                MIN: 1,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "QTY", MIN: 0, MAX: 1},
                                    {ID: "AMT", MIN: 0, MAX: 1},
                                    {ID: "MTX", MIN: 0, MAX: 1},
                                    {ID: "PSG", MIN: 0, MAX: 99999},
                                    {ID: "CPI", MIN: 0, MAX: 1},
                                    {
                                        ID: "SEF",
                                        MIN: 0,
                                        MAX: 1,
                                        LEVEL: [
                                            {
                                                ID: "DTM",
                                                MIN: 0,
                                                MAX: 99999,
                                                LEVEL: [
                                                    {ID: "MTX", MIN: 0, MAX: 1},
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                            {ID: "LE", MIN: 1, MAX: 1},
                        ],
                    },
                    {
                        ID: "LX",
                        MIN: 0,
                        MAX: 99999,
                        LEVEL: [
                            {ID: "MTX", MIN: 0, MAX: 1},
                            {
                                ID: "FX2",
                                MIN: 0,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "AMT", MIN: 0, MAX: 1},
                                    {ID: "QTY", MIN: 0, MAX: 1},
                                    {ID: "FX6", MIN: 0, MAX: 99999},
                                    {ID: "FX7", MIN: 0, MAX: 99999},
                                ],
                            },
                            {
                                ID: "FX3",
                                MIN: 0,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "FU3", MIN: 0, MAX: 1},
                                    {ID: "FU4", MIN: 0, MAX: 1},
                                    {ID: "FU5", MIN: 0, MAX: 1},
                                    {ID: "AMT", MIN: 0, MAX: 1},
                                    {ID: "QTY", MIN: 0, MAX: 1},
                                ],
                            },
                            {
                                ID: "FU1",
                                MIN: 0,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "FU2", MIN: 1, MAX: 1},
                                ],
                            },
                            {
                                ID: "FX4",
                                MIN: 0,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "REF", MIN: 0, MAX: 2},
                                    {ID: "N1", MIN: 1, MAX: 99999},
                                    {ID: "DTM", MIN: 0, MAX: 99999},
                                    {ID: "ECS", MIN: 0, MAX: 1},
                                ],
                            },
                            {
                                ID: "FX5",
                                MIN: 0,
                                MAX: 99999,
                                LEVEL: [
                                    {ID: "N1", MIN: 1, MAX: 99999},
                                    {ID: "DTM", MIN: 0, MAX: 99999},
                                    {ID: "QTY", MIN: 0, MAX: 1},
                                    {ID: "ECS", MIN: 0, MAX: 1},
                                    {
                                        ID: "FX4",
                                        MIN: 0,
                                        MAX: 99999,
                                        LEVEL: [
                                            {ID: "REF", MIN: 0, MAX: 2},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {ID: "SE", MIN: 1, MAX: 1},
        ],
    }
]
