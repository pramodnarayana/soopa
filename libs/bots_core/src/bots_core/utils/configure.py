"""
Bots configure lib
"""
import os
import sys

from bots_core.infrastructure.config import botsinit, botsglobal
from bots_core.utils import botslib


def bots_info(configdir=None, **kwargs):
    """
    Display Bots Environment informations.
    """
    # Use configdir from parameter or kwargs
    if not configdir:
        configdir = kwargs.get('configdir')

    botsinit.generalinit(configdir)
    infos = f"{os.linesep}---------- [Bots Environment] ----------{os.linesep}"
    infos += os.linesep.join([f"    {key:22}: {value}" for key, value in botslib.botsinfo()])
    infos += os.linesep + "-" * 40
    if configdir:
        return infos
    return f"Bots env not configured for config dir: {configdir}"


def start():
    """
    Configure bots environement and display config.
    """
    usage = """
This is "%(name)s" version %(version)s,

    Usage:
        %(name)s [botsenv-option]

        --help|-h|?|/?                          Display this help.

    botsenv-option:
        -c<directory>|configdir=<directory>     Bots config directory of configuration files

    """ % {
        'name': os.path.basename(sys.argv[0]),
        'version': botsglobal.version,
    }
    configdir = None
    for arg in sys.argv[1:]:
        if arg.startswith('-c'):
            configdir = arg[2:]
        elif '=' in arg:
            key, val = arg.split('=', 1)
            if key == 'configdir':
                configdir = val
            else:
                print(usage)
                return
        elif arg in ['?', '/?', '-h', '--help']:
            print(usage)
            return

    if configdir:
        print(bots_info(configdir=configdir), file=sys.stderr)
    else:
        print(usage)
