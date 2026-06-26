"""Start bots-engine."""

import atexit
import logging
import os
import socket
import sys
import time
import warnings

# bots-modules
from bots_core.infrastructure.config import botsglobal
from bots_core.infrastructure.config import botsinit
from bots_core.utils import botslib
from bots_core.application.use_cases import router
from bots_core.utils.botslib import gettext as _
from bots_core.domain.exceptions import BotsImportError


def logging_exit():
    """Shutown logging and move log file if requested"""
    logging.shutdown()
    if botsglobal.ini.get('settings', 'log_when', None) == 'report' \
            and getattr(botsglobal.currentrun, 'minta4query', None):
        # Not for classic logging, dailly or rotating
        # Rename engine.log with "botsglobal.currentrun.minta4query
        os.rename(
            botsglobal.logger.handlers[0].baseFilename,
            os.path.join(
                botsglobal.ini.get('directories', 'logging'),
                botsglobal.logger.name.replace(f"{__package__}.", ""),
                str(botsglobal.currentrun.minta4query)
            )
        )


def start():
    """
    Start Bots engine

    sysexit codes:
    0: OK, no errors
    1: (system) errors incl parsing of command line arguments
    2: bots ran OK, but there are errors/process errors  in the run
    3: Database is locked, but "maxruntime" has not been exceeded.
    """
    # pylint: disable=too-many-locals, too-many-branches, too-many-statements, broad-exception-caught
    # ********command line arguments**************************
    usage = """
    This is "%(name)s" version %(version)s,
    part of Bots open source edi translator (https://bots-edi.org).
    Does the actual translations and communications; it's the workhorse.
    It does not have a fancy interface.

    Usage:
        %(name)s  [run-options] [config-option] [routes]
    Run-options (can be combined):
        --new                receive new edi files (default: if no run-option given: run as new).
        --resend             resend as indicated by user.
        --rereceive          rereceive as indicated by user.
        --automaticretrycommunication - automatically retry outgoing communication.
    Config-option:
        -c<directory>        directory for configuration files (default: config).
    Routes: list of routes to run. Default: all active routes (in the database)

    """ % {
        'name': os.path.basename(sys.argv[0]),
        'version': botsglobal.version,
    }
    configdir = None
    commandspossible = ['--automaticretrycommunication', '--resend', '--rereceive', '--new']
    commandstorun = []
    # list with routes to run
    routestorun = []
    for arg in sys.argv[1:]:
        if arg.startswith('-c'):
            configdir = arg[2:]
            if not configdir:
                print('Error: configuration directory indicated, but no directory name.')
                sys.exit(1)
        elif arg in commandspossible:
            commandstorun.append(arg)
        elif arg in ['?', '/?', '-h', '--help'] or arg.startswith('-'):
            print(usage)
            sys.exit(0)
        else:
            # pick up names of routes to run
            routestorun.append(arg)
    if not commandstorun:
        # no command on command line, use new (default)
        commandstorun = ['--new']
    # sort commands
    commandstorun = [command[2:] for command in commandspossible if command in commandstorun]
    # ***********end handling command line arguments**************************

    # find locating of bots, configfiles, init paths etc.
    botsinit.generalinit(configdir)
    # set working directory to bots installation. advantage:
    #   when using relative paths it is clear that this point paths within bots installation.
    os.chdir(botsglobal.ini.get("directories", "botsenv"))

    # **************check if another instance of bots-engine is running/if port is free************
    try:
        engine_socket = botslib.check_if_other_engine_is_running()
    except socket.error:
        sys.exit(3)
    else:
        atexit.register(engine_socket.close)

    # **************initialise logging******************************
    botsglobal.logger = botsinit.initenginelogging(__name__)
    atexit.register(logging_exit)
    if botsglobal.ini.get('settings', 'log_when', None) != 'daily':
        botsglobal.logger.info(botslib.botsinfo_display())

    # **************connect to database**********************************
    try:
        botsinit.connect()
    except Exception as exc:
        botsglobal.logger.exception(
            _(
                'Could not connect to database. Database settings are in bots/config/settings.py.'
                ' Error: "%(exc)s".'
            ),
            {'exc': exc},
        )
        sys.exit(1)
    else:
        botsglobal.logger.info(_('Connected to database.'))
        atexit.register(botsglobal.db.close)
    # ************initialise user exits for the whole bots-engine*************************
    try:
        userscript, scriptname = botslib.botsimport('routescripts', 'botsengine')
    except BotsImportError:
        # userscript is not there; other errors like syntax errors are not catched
        userscript = scriptname = None
    # ***acceptance tests: initialiase acceptance user script******************************
    acceptance_userscript = acceptance_scriptname = None
    if botsglobal.ini.getboolean('acceptance', 'runacceptancetest', False):
        botsglobal.logger.info(
            _(
                'This run is an acceptance test - as indicated in option "runacceptancetest"'
                ' in bots.ini.'
            )
        )
        try:
            acceptance_userscript, acceptance_scriptname = botslib.botsimport(
                'routescripts', 'bots_acceptancetest'
            )
        except BotsImportError:
            botsglobal.logger.info(
                _(
                    'In acceptance test there is no script file "bots_acceptancetest.py"'
                    ' to check the results of the acceptance test.'
                )
            )

    # **************handle database lock****************************************
    # set a lock on the database;
    # if not possible, the database is locked:
    #   an earlier instance of bots-engine was terminated unexpectedly.
    if not botslib.set_database_lock():
        # for SQLite: do a integrity check on the database
        db = botsglobal.ini.get("settings", "django_db_connection", "default")
        if botsglobal.settings.DATABASES[db]["ENGINE"] == "django.db.backends.sqlite3":
            cursor = botsglobal.db.cursor()
            cursor.execute("""PRAGMA integrity_check""")
            result = cursor.fetchone()
            cursor.close()
            if result[0] != 'ok':
                warn = _(
                    '!Bots database is locked!\n'
                    'Bots did an integrity check on the database, but database was not OK.\n'
                    'Manual action is needed!\n'
                    'Bots has stopped processing EDI files.'
                )
                botsglobal.logger.critical(warn)
                botslib.sendbotserrorreport(_('[Bots severe error]Database is damaged'), warn)
                sys.exit(1)
        warn = _(
            '!Bots database is locked!\n'
            'Bots-engine has ended in an unexpected way during the last run.\n'
            'Most likely causes: sudden power-down, system crash, problems with disk I/O,'
            ' bots-engine terminated by user, etc.\n'
            'Bots will do an automatic crash recovery now.'
        )
        botsglobal.logger.critical(warn)
        botslib.sendbotserrorreport(_('[Bots severe error]Database is locked'), warn)
        # there is a database lock. Add a crashrecovery as first command to run.
        commandstorun.insert(0, 'crashrecovery')
    atexit.register(botslib.remove_database_lock)

    warnings.simplefilter('error', UnicodeWarning)

    # **************run the routes**********************************************
    # commandstorun determines the type(s) of run. eg: ['automaticretrycommunication','new']
    try:
        botslib.prepare_confirmrules()
        # in acceptance tests: run a user script before running eg to clean output directories
        botslib.tryrunscript(
            acceptance_userscript, acceptance_scriptname, 'pretest', routestorun=routestorun
        )
        botslib.tryrunscript(
            userscript, scriptname, 'pre', commandstorun=commandstorun, routestorun=routestorun
        )
        # detect if there has been some error.
        # Only used for correct exit() code
        errorinrun = 0
        first_command_2_run = True
        for command in commandstorun:
            # if multiple commands in run: reports etc are based on timestamp;
            # so there needs to be at least one second between these runs.
            if first_command_2_run:
                first_command_2_run = False
            else:
                time.sleep(1)
            botsglobal.logger.info(_('Run "%(command)s".'), {'command': command})
            # ************get list of routes to run*******************************
            if routestorun:
                use_routestorun = routestorun[:]
                botsglobal.logger.info(
                    _('Run routes from command line: "%(routes)s".'),
                    {"routes": str(use_routestorun)},
                )
            elif command == 'new':
                # fetch all active routes from database unless 'not in default run' or not active.
                use_routestorun = []
                for row in botslib.query(
                        """SELECT DISTINCT idroute
                           FROM routes
                           WHERE active=%(active)s
                           AND (notindefaultrun=%(notindefaultrun)s OR notindefaultrun IS NULL)
                           ORDER BY idroute """,
                        {'active': True, 'notindefaultrun': False}):
                    use_routestorun.append(row["idroute"])
                botsglobal.logger.info(
                    _('Run active routes from database that are in default run: "%(routes)s".'),
                    {"routes": str(use_routestorun)},
                )
            else:
                # for command other than 'new': use all active routes.
                use_routestorun = []
                for row in botslib.query(
                        """SELECT DISTINCT idroute
                           FROM routes
                           WHERE active=%(active)s
                           ORDER BY idroute """,
                        {'active': True}):
                    use_routestorun.append(row["idroute"])
                botsglobal.logger.info(
                    _('Run all active routes from database: "%(routes)s".'),
                    {"routes": str(use_routestorun)},
                )
            # ************run routes for this command******************************
            botslib.tryrunscript(
                userscript, scriptname, 'pre' + command, routestorun=use_routestorun
            )
            errorinrun += router.rundispatcher(command, use_routestorun)
            botslib.tryrunscript(
                userscript, scriptname, 'post' + command, routestorun=use_routestorun
            )
            # *********finished running routes for this command****************************
        # *********finished all commands****************************************

        botslib.tryrunscript(
            userscript, scriptname, 'post', commandstorun=commandstorun, routestorun=routestorun
        )
        try:
            # in acceptance tests: run a user script.
            # no good reporting of errors/results in post-test script.
            # Reason: this is after automaticmaintence.
            botslib.tryrunscript(
                acceptance_userscript,
                acceptance_scriptname,
                'posttest',
                routestorun=routestorun,
            )
        except Exception as exc:
            print(str(exc))

    except Exception as exc:
        # of course this 'should' not happen.
        botsglobal.logger.exception(
            _("Severe error in bots system:\n%(exc)s"), {"exc": str(exc)}
        )
        sys.exit(1)
    else:
        if errorinrun:
            # indicate: error(s) in run(s)
            sys.exit(2)
        else:
            # OK
            sys.exit(0)


if __name__ == '__main__':
    start()
