"""
Bots init lib
"""

import codecs
import configparser
import encodings
import logging
import logging.handlers
import os
import shutil
import sys



# bots-modules
from bots_core.infrastructure.config import botsglobal
from bots_core.utils import botslib
from bots_core.domain import node
from bots_core.domain.exceptions import (
    BotsError,
    BotsImportError,
    PanicError,
)

LOG_FORMAT = '%(asctime)s %(levelname)-9s [%(name)s] %(message)s'
LOG_DT_FORMAT = '%Y.%m.%d %H:%M:%S'
LOG_CONSOLE_FORMAT = LOG_FORMAT


class BotsConfig(configparser.RawConfigParser):
    """As ConfigParser, but with defaults."""
    # pylint: disable=arguments-differ

    def get(self, section, option, default='', **kwargs):
        if self.has_option(section, option):
            result = super().get(section, option, **kwargs)
            return result or default
        if default == '':
            raise BotsError(f'No entry "{option}" in section "{section}" in "bots.ini"')
        return default

    def getint(self, section, option, default, **kwargs):
        if self.has_option(section, option):
            return configparser.RawConfigParser.getint(self, section, option, **kwargs)
        return default

    def getboolean(self, section, option, default, **kwargs):
        if self.has_option(section, option):
            return configparser.RawConfigParser.getboolean(self, section, option, **kwargs)
        return default





def generalinit(configdir=None):
    """Load bots config from config dir.

    :param configdir: Path to bots config directory

    """
    # pylint: disable=too-many-branches, too-many-statements
    botsenv_path = ""
    if not configdir:
        if os.environ.get('BOTS_CONFIG_DIR'):
            # config dir set from env var $BOTS_CONFIG_DIR
            configdir = os.path.normpath(os.environ.get('BOTS_CONFIG_DIR'))
            botsenv_path = os.path.dirname(configdir.rstrip(os.sep))
        else:
            # config dir set from $BOTSENV in user space ~/.bots/env/$BOTSENV/config
            botsenv = os.environ.get("BOTSENV") or "default"
            botsenv_path = os.path.join(os.path.expanduser('~'), '.bots', 'env', botsenv)
            configdir = os.path.join(botsenv_path, 'config')
            pass
    botsglobal.configdir = configdir = configdir.rstrip(os.path.sep)
    configdirectory = configdir

    # In a fully native integration, bots.ini is not loaded from file
    # but the BotsConfig is constructed and populated by the adapter.
    # For now, we stub out the config initialization here so the rest of the engine can assume it's set.
    botsglobal.ini = BotsConfig()

    # 'directories','botspath': absolute path for bots directory
    botsglobal.ini.set('directories', 'botspath', os.path.abspath(os.path.dirname(__file__)))
    # 'directories','config': absolute path for config directory
    botsglobal.ini.set('directories', 'config', configdirectory)
    # set config as originally received; used in starting engine via bots-monitor
    botsglobal.ini.set('directories', 'config_org', configdir)
    # "directories", "botsenv": absolute path to bots user env directory
    botsglobal.ini.set("directories", "botsenv", botsenv_path or os.path.dirname(configdirectory.rstrip(os.sep)))
    ###########################################################################
    # Usersys #################################################################
    # usersys MUST be importable. So usersys is relative to PYTHONPATH.
    # Try several options for this import.
    usersys = os.path.normpath(botsglobal.ini.get('directories', 'usersys', 'usersys'))
    try:
        # usersys outside bots-directory: import usersys
        importnameforusersys = usersys.replace(os.sep, '.')
        importedusersys = botslib.botsbaseimport(importnameforusersys)
    except ImportError:
        try:
            # usersys is in bots directory: import bots.usersys
            importnameforusersys = os.path.join('bots', usersys).replace(os.sep, '.')
            importedusersys = botslib.botsbaseimport(importnameforusersys)
        except ImportError as exc:
            # set pythonpath to usersys directory first
            if not os.path.exists(usersys):  # check if configdir exists.
                raise PanicError(f'In initilisation: path to configuration does not exists: "{usersys}"') from exc
            # Usersys directory is absolute path
            addtopythonpath = os.path.abspath(os.path.dirname(usersys))
            importnameforusersys = os.path.basename(usersys)
            if addtopythonpath not in sys.path:
                sys.path.append(addtopythonpath)
            importedusersys = botslib.botsbaseimport(importnameforusersys)

    # 'directories', 'usersysabs': absolute path for config usersysabs
    # Find pathname usersys using imported usersys
    botsglobal.ini.set('directories', 'usersysabs', importedusersys.__path__[0])
    # botsglobal.usersysimportpath: used for imports from usersys
    botsglobal.usersysimportpath = importnameforusersys
    botsglobal.ini.set(
        'directories', 'templatehtml', botslib.join(
            botsglobal.ini.get('directories', 'usersysabs'),
            'grammars/templatehtml/templates'
        )
    )

    ############################################################################
    # Botssys ##################################################################
    # 'directories','botssys': absolute path for config botssys
    botssys = botsglobal.ini.get('directories', 'botssys', 'botssys')
    # store original botssys setting
    botsglobal.ini.set('directories', 'botssys_org', botssys)
    # use absolute path
    botsglobal.ini.set('directories', 'botssys', botslib.join(botssys))
    botsglobal.ini.set('directories', 'data', botslib.join(botssys, 'data'))
    botsglobal.ini.set('directories', 'logging', botslib.join(botssys, 'logging'))
    botsglobal.ini.set('directories', 'users', botslib.join(botssys, '.users'))
    # dirmonitor trigger
    botsglobal.ini.set('dirmonitor', 'trigger', botslib.join(botssys, '.dirmonitor.trigger'))
    botsglobal.ini.set('settings', 'log_when', botsglobal.ini.get('settings', 'log_when', 'report'))
    # Django is disabled
    # values in bots.ini are also used in setting up cherrypy
    if botsglobal.ini.get('webserver', 'environment', 'development') != 'development':
        # during production: if errors occurs in writing to log: ignore error.
        # (leads to a missing log line, better than error;-).
        logging.raiseExceptions = 0

    botslib.dirshouldbethere(botsglobal.ini.get('directories', 'data'))
    botslib.dirshouldbethere(botsglobal.ini.get('directories', 'logging'))
    # initialise bots charsets
    initbotscharsets()
    node.Node.checklevel = botsglobal.ini.getint('settings', 'get_checklevel', 1)
    botslib.settimeout(botsglobal.ini.getint('settings', 'globaltimeout', 10))




# **********************************************************************************
# *** bots specific handling of character-sets (eg UNOA charset) *******************
def initbotscharsets():
    """set up right charset handling for specific charsets (UNOA, UNOB, UNOC, etc)."""
    # tell python how to search a codec defined by bots. Bots searches for this in usersys/charset
    codecs.register(codec_search_function)
    # syntax has parameters checkcharsetin or checkcharsetout. These can have value 'botsreplace'
    # eg: 'checkcharsetin':'botsreplace',  #strict, ignore or botsreplace
    # in case of errors: the 'wrong' character is replaced with char as set in bots.ini.
    # Default value in bots.ini is ' ' (space)
    botsglobal.botsreplacechar = str(botsglobal.ini.get("settings", "botsreplacechar", " "))
    # need to register the handler for botsreplacechar
    codecs.register_error('botsreplace', botsreplacechar_handler)
    # set aliases for the charsets in bots.ini
    for key, value in botsglobal.ini.items('charsets'):
        encodings.aliases.aliases[key] = value


def codec_search_function(encoding):
    """Try import charset"""
    try:
        module, _filename = botslib.botsimport('charsets', encoding)
    except BotsImportError:
        # charsetscript not there; other errors like syntax errors are not catched
        return None
    if hasattr(module, 'getregentry'):
        return module.getregentry()
    return None


def botsreplacechar_handler(info):
    """
    replaces an char outside a charset by a user defined char.
    Useful eg for fixed records: recordlength does not change.
    """
    return (botsglobal.botsreplacechar, info.start + 1)


# *** end of bots specific handling of character-sets ******************************
# **********************************************************************************





# *******************************************************************
# *** init logging **************************************************
# *******************************************************************
STARTINFO = 28
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'STDOUT': 11,  # coms & jobqueue-server job stdout
    'STDERR': 12,  # coms & jobqueue-server job stderr
    'INFO': logging.INFO,
    'COM': 25,
    'DONE': 26,
    'START': 27,
    'STARTINFO': STARTINFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}
logging.addLevelName(LOG_LEVELS['STARTINFO'], 'STARTINFO')
logging.addLevelName(LOG_LEVELS['STDOUT'], 'STDOUT')
logging.addLevelName(LOG_LEVELS['STDERR'], 'STDERR')
logging.addLevelName(LOG_LEVELS['START'], 'START')
logging.addLevelName(LOG_LEVELS['DONE'], 'DONE')


def initenginelogging(logname):
    """initialise engine logging: create engine logger."""
    logger = logging.getLogger(logname)
    proc_name = logname.replace(f"{__package__}.", "")
    logdir = os.path.join(botsglobal.ini.get('directories', 'logging'), proc_name)
    botslib.dirshouldbethere(logdir)
    log_when = botsglobal.ini.get('settings', 'log_when', None)
    if log_when == 'daily':
        handler = logging.handlers.TimedRotatingFileHandler(
            os.path.join(logdir, proc_name + '.log'),
            encoding="utf-8",
            when='midnight',
            backupCount=botsglobal.ini.getint('settings', 'log_file_number', 30),
        )
    else:
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(logdir, proc_name + '.log'),
            encoding="utf-8",
            backupCount=botsglobal.ini.getint('settings', 'log_file_number', 10),
        )
        if log_when is None:
            # each run a new log file is used; old one is rotated
            handler.doRollover()
    fileformat = logging.Formatter(LOG_FORMAT, LOG_DT_FORMAT)
    handler.setFormatter(fileformat)
    handler.setLevel(botsglobal.ini.get('settings', 'log_file_level', 'INFO'))
    logger.addHandler(handler)

    # initialise file logging: logger for trace of mapping;
    # tried to use filters but got this not to work ...
    botsglobal.logmap = logging.getLogger('engine.map')
    if not botsglobal.ini.getboolean('settings', 'mappingdebug', False):
        botsglobal.logmap.setLevel(logging.CRITICAL)
    # logger for reading edifile. is now used only very limited (1 place); is done with 'if'
    # botsglobal.ini.getboolean('settings', 'readrecorddebug', False)

    # initialise console/screen logging
    if botsglobal.ini.getboolean('settings', 'log_console', True):
        console = logging.StreamHandler()
        consoleformat = logging.Formatter(LOG_CONSOLE_FORMAT, LOG_DT_FORMAT)
        # add formatter to console
        console.setFormatter(consoleformat)
        # Set console log level
        console.setLevel(botsglobal.ini.get('settings', 'log_console_level', 'INFO'))
        # add console to logger
        logger.addHandler(console)

    # Global Bots LOG LEVEL: bots.engine, bots.engine2
    logger.setLevel(botsglobal.ini.get('settings', 'log_level', 'INFO'))
    if not botsglobal.ini.get('settings', 'log_level', None):
        for handler in logger.handlers:
            if handler.level < logger.level:
                logger.setLevel(handler.level)
    return logger


def initserverlogging(logname):
    """initialise file logging"""
    logger = logging.getLogger(logname)
    proc_name = logname.replace(f"{__package__}.", "").replace("jobqueueserver", "jobqueue")
    logdir = os.path.join(botsglobal.ini.get('directories', 'logging'), proc_name)
    botslib.dirshouldbethere(logdir)
    handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(logdir, proc_name + '.log'),
        encoding="utf-8",
        when='midnight',
        backupCount=botsglobal.ini.getint(
            proc_name, 'log_file_number', botsglobal.ini.getint('settings', 'log_file_number', 30)),
    )
    fileformat = logging.Formatter(LOG_FORMAT, LOG_DT_FORMAT)
    handler.setFormatter(fileformat)
    handler.setLevel(botsglobal.ini.get(proc_name, 'log_file_level', 'INFO'))
    logger.addHandler(handler)

    # initialise console/screen logging
    if botsglobal.ini.getboolean(proc_name, 'log_console', True):
        console = logging.StreamHandler()
        consoleformat = logging.Formatter(LOG_CONSOLE_FORMAT, LOG_DT_FORMAT)
        # add formatter to console
        console.setFormatter(consoleformat)
        # Set console log level
        console.setLevel(botsglobal.ini.get(proc_name, 'log_console_level', 'STARTINFO'))
        # add console to logger
        logger.addHandler(console)

    # Bots server(s) LOG LEVEL: bots.jobqueue, bots.dirmonitor, bots.webserver
    logger.setLevel(botsglobal.ini.get(proc_name, 'log_level', 'INFO'))
    if not botsglobal.ini.get(proc_name, 'log_level', None):
        for handler in logger.handlers:
            if handler.level < logger.level:
                logger.setLevel(handler.level)
    return logger
