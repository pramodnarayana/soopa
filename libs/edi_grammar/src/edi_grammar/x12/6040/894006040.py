from bots_core.infrastructure.config.botsconfig import *

syntax = {
    'version': '00604',
    'functionalgroup': 'DX',
}

structure = [
{ID: 'ST', MIN: 1, MAX: 1, LEVEL: [
    {ID: 'G82', MIN: 1, MAX: 1},
    {ID: 'N9', MIN: 0, MAX: 99999},
    {ID: 'MTX', MIN: 0, MAX: 5},
    {ID: 'LS', MIN: 0, MAX: 1, LEVEL: [
        {ID: 'G83', MIN: 1, MAX: 9999, LEVEL: [
            {ID: 'SLN', MIN: 0, MAX: 1},
            {ID: 'MTX', MIN: 0, MAX: 5},
            {ID: 'G22', MIN: 0, MAX: 1},
            {ID: 'G72', MIN: 0, MAX: 10},
            {ID: 'G23', MIN: 0, MAX: 20},
            {ID: 'DTM', MIN: 0, MAX: 5},
            {ID: 'N9', MIN: 0, MAX: 5},
        ]},
        {ID: 'LE', MIN: 1, MAX: 1},
    ]},
    {ID: 'G72', MIN: 0, MAX: 20},
    {ID: 'G23', MIN: 0, MAX: 20},
    {ID: 'G84', MIN: 1, MAX: 1},
    {ID: 'G86', MIN: 1, MAX: 1},
    {ID: 'G85', MIN: 1, MAX: 1},
    {ID: 'SE', MIN: 1, MAX: 1},
]}
]
