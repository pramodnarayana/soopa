"""
Base library for bots.
Botslib should not import code from other Bots-modules.
"""
# pylint: disable=missing-function-docstring, broad-exception-caught, too-many-lines

import codecs
import contextlib
import datetime as python_datetime
import gettext as std_gettext
import importlib
import logging
import os
import platform
import socket
import sys

from bots_core.domain.exceptions import (
    KillWholeFileException,
    PanicError,
    ParsePassthroughException,
    ScriptError,
    ScriptImportError,
    txtexc,
)
from bots_core.infrastructure.config.botsconfig import DONE, ERROR, FILEOUT, OK, PROCESS

gettext = std_gettext.gettext


class _BotsGlobalStub:
    routeid = None
    confirmrules = []

    class ini:
        @staticmethod
        def get(*args, **kwargs):
            return ""

        @staticmethod
        def getint(*args, **kwargs):
            return 0

        @staticmethod
        def getboolean(*args, **kwargs):
            return False

    version = ""
    db_port = None
    logger = logging.getLogger(__name__)

    class currentrun:
        @staticmethod
        def get_minta4query():
            return ""


botsglobal = _BotsGlobalStub()


def insertta(querystring, params=None):
    """Insert a transaction record into the database and return the inserted idta."""
    if botsglobal.db_port is None:
        # Fallback if no DB port is configured
        return 1
    return botsglobal.db_port.insertta(querystring, params)


try:
    import pickle
except ImportError:
    import cPickle as pickle


_ = gettext

MAXINT = (2**31) - 1

logger = logging.getLogger(__name__)


# **********************************************************/**
# ************* getters/setters for some globals ***********/**
# **********************************************************/**
def setrouteid(routeid):
    botsglobal.routeid = routeid


def getrouteid():
    return botsglobal.routeid


# **********************************************************/**
# ***************** class  Transaction *********************/**
# **********************************************************/**

# Per-execution context for process stack (moved out of class to avoid shared mutable state)
_processlist_stack = [0]


class _Transaction:
    """
    abstract class for db-ta.
    This class is used for communication with db-ta.
    """

    # filtering values for db handling to avoid unknown fields in db.
    filterlist = (
        "statust",
        "status",
        "divtext",
        "parent",
        "child",
        "script",
        "frompartner",
        "topartner",
        "fromchannel",
        "tochannel",
        "editype",
        "messagetype",
        "merge",
        "testindicator",
        "reference",
        "frommail",
        "tomail",
        "contenttype",
        "errortext",
        "filename",
        "charset",
        "alt",
        "idroute",
        "nrmessages",
        "retransmit",
        "confirmasked",
        "confirmed",
        "confirmtype",
        "confirmidta",
        "envelope",
        "botskey",
        "cc",
        "filesize",
        "numberofresends",
        "rsrv1",
        "rsrv2",
        "rsrv3",
        "rsrv4",
        "rsrv5",
    )
    idta = None

    @property
    def processlist(self):
        """Access the per-execution process stack."""
        return _processlist_stack

    def update(self, **ta_info):
        """
        Updates db-ta with named-parameters/dict.
        Use a filter to update only valid fields in db-ta
        """
        setstring = ",".join(key + "=%(" + key + ")s" for key in ta_info if key in self.filterlist)
        if not setstring:
            # nothing to update
            return
        ta_info["selfid"] = self.idta
        print(
            """UPDATE ta
               SET """
            + setstring
            + """
               WHERE idta=%(selfid)s""",
            ta_info,
        )

    def delete(self):
        """Deletes current transaction"""
        print(
            "DELETE FROM ta WHERE idta=%(idta)s",
            {"idta": self.idta},
        )

    def deletechildren(self):
        self.deleteonlychildren_core(self.idta)

    def deleteonlychildren_core(self, idta):
        for row in query("SELECT idta FROM ta WHERE parent=%(idta)s", {"idta": idta}):
            self.deleteonlychildren_core(row["idta"])
            print(
                """DELETE FROM ta WHERE idta=%(idta)s""",
                {"idta": row["idta"]},
            )

    def syn(self, *ta_vars):
        """access of attributes of transaction as ta.fromid, ta.filename etc"""
        varsstring = ",".join(ta_vars)
        for row in query(
            "SELECT "
            + varsstring
            + """
                 FROM ta WHERE idta=%(idta)s""",
            {"idta": self.idta},
        ):
            self.__dict__.update(dict(row))

    def synall(self):
        """access of attributes of transaction as ta.fromid, ta.filename etc"""
        for row in query("""SELECT * FROM ta WHERE idta=%(idta)s""", {"idta": self.idta}):
            self.__dict__.update(dict(row))

    def copyta(self, status, **ta_info):
        """
        copy old transaction, return new transaction.
        parameters for new transaction are in ta_info
        (new transaction is updated with these values).
        """
        script = _processlist_stack[-1]
        newidta = insertta(
            """INSERT INTO ta (
                script,status,parent,frompartner,topartner,fromchannel,tochannel,editype,messagetype,
                alt,merge,testindicator,reference,frommail,tomail,charset,contenttype,filename,idroute,
                nrmessages,botskey,envelope,rsrv3,cc)
            SELECT %(script)s,%(newstatus)s,idta,frompartner,topartner,fromchannel,tochannel,editype,messagetype,
                alt,merge,testindicator,reference,frommail,tomail,charset,contenttype,filename,idroute,nrmessages,
                botskey,envelope,rsrv3,cc
            FROM ta
            WHERE idta=%(idta)s""",
            {"idta": self.idta, "script": script, "newstatus": status},
        )
        newta = OldTransaction(newidta)
        newta.update(**ta_info)
        return newta


class OldTransaction(_Transaction):
    """Resurrect old transaction"""

    def __init__(self, idta):
        self.idta = idta


class NewTransaction(_Transaction):
    """Generate new transaction."""

    def __init__(self, **ta_info):
        # filter ta_info
        updatedict = dict((key, value) for key, value in ta_info.items() if key in self.filterlist)
        updatedict["script"] = _processlist_stack[-1]
        namesstring = ",".join(key for key in updatedict)
        varsstring = ",".join(f"%({key})s" for key in updatedict)
        self.idta = insertta(
            f"""INSERT INTO ta ({namesstring}) VALUES ({varsstring})""",
            updatedict,
        )


class NewProcess(NewTransaction):
    """
    Create a new process (which is very much like a transaction).
    Used in logging of processes.
    Each process is placed on stack processlist
    """

    def __init__(self, functionname=""):
        super().__init__(filename=functionname, status=PROCESS, idroute=getrouteid())
        _processlist_stack.append(self.idta)

    def update(self, **ta_info):
        """update process, delete from process-stack."""
        super().update(**ta_info)
        _processlist_stack.pop()


# **********************************************************/**
# ************************ Database ************************/**
# **********************************************************/**
def addinfocore(change, where, wherestring):
    """core function for add/changes information in db-ta's."""
    wherestring = " WHERE idta > %(rootidta)s AND " + wherestring
    # count the number of dbta changed
    counter = 0
    for row in query("""SELECT idta FROM ta """ + wherestring, where):
        counter += 1
        ta_from = OldTransaction(row["idta"])
        # make new ta from ta_from, using parameters from change
        ta_from.copyta(**change)
        # update 'old' ta
        ta_from.update(statust=DONE)
    return counter


def addinfo(change, where):
    """
    change ta's to new phase: ta's are copied to new ta.
    returns the number of db-ta that have been changed.
    change (dict): values to change.
    where (dict): selection.
    """
    where.setdefault("rootidta", botsglobal.currentrun.get_minta4query())
    # where.setdefault('statust', OK)
    # change.setdefault('statust', OK)

    # wherestring; does not use rootidta
    wherestring = " AND ".join(f"{key}=%({key})s " for key in where if key != "rootidta")
    return addinfocore(change=change, where=where, wherestring=wherestring)


def updateinfocore(change, where, wherestring=""):
    """
    update info in ta's.
    where (dict) selects ta's,
    change (dict) sets values;
    """
    wherestring = f" WHERE idta > %(rootidta)s AND {wherestring}"
    # change-dict: discard empty values.
    # Change keys: this is needed because same keys can be in where-dict
    change2 = [(key, value) for key, value in change.items() if value is not None]
    if not change2:
        return False
    changestring = ",".join(f"{key}=%(change_{key})s" for key, value in change2)
    where.update((f"change_{key}", value) for key, value in change2)
    return print(f"""UPDATE ta SET {changestring}{wherestring}""", where)


def updateinfo(change, where):
    """
    update ta's.
    returns the number of db-ta that have been changed.
    change (dict): values to change.
    where (dict): selection.
    """
    where.setdefault("rootidta", botsglobal.currentrun.get_minta4query())
    where.setdefault("statust", OK)
    change.setdefault("statust", OK)
    # wherestring for copy & done
    wherestring = " AND ".join(f"{key}=%({key})s " for key in where if key != "rootidta")
    return updateinfocore(change=change, where=where, wherestring=wherestring)


def changestatustinfo(change, where):
    return updateinfo({"statust": change}, where)


def query(querystring, *args):
    """general query. yields rows from query"""
    if botsglobal.db_port is None:
        raise PanicError("Database port is not initialized")
    yield from botsglobal.db_port.query(querystring, *args)


# **********************************************************/**
# ************** Logging, Error handling *******************/**
# **********************************************************/**
def sendbotserrorreport(subject, reporttext):
    """
    Send an email in case of errors or problems with bots-engine.
    Email is send to MANAGERS in config/settings.py.
    Email parameters are in config/settings.py (EMAIL_HOST, etc).
    """
    # pylint: disable=import-outside-toplevel
    if botsglobal.ini.getboolean(
        "settings", "sendreportiferror", False
    ) and not botsglobal.ini.getboolean("acceptance", "runacceptancetest", False):
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg.set_content(reporttext)
            msg["Subject"] = subject
            msg["From"] = botsglobal.ini.get("settings", "SERVER_EMAIL", "bots@localhost")
            msg["To"] = botsglobal.ini.get("settings", "MANAGERS", "admin@localhost")

            host = botsglobal.ini.get("settings", "EMAIL_HOST", "localhost")
            port = botsglobal.ini.getint("settings", "EMAIL_PORT", 25)

            with smtplib.SMTP(host, port) as server:
                server.send_message(msg)
        except Exception as exc:
            botsglobal.logger.warning("Error in sending error report: %(exc)s", {"exc": exc})


def sendbotsemail(partner, subject, reporttext) -> bool | None:
    """
    Send a simple email message to any bots partner.
    Mail is sent to all To: and cc: addresses for the partner (but send_mail does not support cc).
    Email parameters are in config/settings.py (EMAIL_HOST, etc).
    """
    # pylint: disable=import-outside-toplevel
    botsglobal.logger.warning("Sending email is not implemented natively yet.")
    return False


def log_session(func):
    """
    used as decorator.
    The decorated functions are logged as processes.
    Errors in these functions are caught and logged.
    """

    def wrapper(*args, **argv):
        try:
            ta_process = NewProcess(func.__name__)
        except Exception:
            botsglobal.logger.exception("System error - no new process made")
            raise
        try:
            terug = func(*args, **argv)
        except Exception:
            txt = txtexc()
            botsglobal.logger.error("Error in process: %(txt)s", {"txt": txt})
            ta_process.update(statust=ERROR, errortext=txt)
            return False

        ta_process.update(statust=DONE)
        return terug

    return wrapper


class ErrorProcess(NewTransaction):
    """
    Used in logging of errors in processes:
    communication.py to indicate errors in receiving files (files have not been received)
    """

    def __init__(self, functionname="", errortext="", channeldict=None):
        fromchannel = tochannel = ""
        if channeldict:
            if channeldict["inorout"] == "in":
                fromchannel = channeldict["idchannel"]
            else:
                tochannel = channeldict["idchannel"]
        super().__init__(
            filename=functionname,
            status=PROCESS,
            idroute=getrouteid(),
            statust=ERROR,
            errortext=errortext,
            fromchannel=fromchannel,
            tochannel=tochannel,
        )


# **********************************************************/**
# ************************ import **************************/**
# **********************************************************/**
def botsbaseimport(modulename):
    """
    Do a dynamic import.
    Errors/exceptions are handled in calling functions.
    """
    return importlib.import_module(modulename)
    return importlib.import_module(modulename.encode(sys.getfilesystemencoding()))


def botsimport(*args):
    """
    import modules from usersys.
    return: imported module, filename imported module;
    """
    # assemble import string
    modulepath = ".".join(("bots_core.usersys",) + args)
    modulefile = "/".join(args)

    try:
        module = botsbaseimport(modulepath)
    except Exception as exc:
        errs = [
            _('Error in import of module "%(modulefile)s":\n%(txt)s'),
            {"modulefile": modulefile, "txt": exc},
        ]
        logger.debug(*errs)
        _exception = ScriptImportError(*errs)
        _exception.__cause__ = None
        raise _exception from exc
    logger.debug('Imported "%(modulefile)s".', {"modulefile": modulefile})
    return module, modulefile


# **********************************************************/**
# ************** File handling os.path etc *****************/**
# **********************************************************/**
def join(*paths):
    """
    bots-specific join; path are relative to botsenv.
    For modern stateless mode, we just join them normally.
    """
    return os.path.normpath(os.path.join(*paths))


def dirshouldbethere(path: str) -> bool:
    """
    Create directory if path doesn't exist and return True
    :return:
        - True if one or several directory was created
        - False if path already exist
    """
    if path and not os.path.exists(path):
        os.makedirs(path)
        return True
    return False


def abspath(soort, filename):
    return filename


def abspathdata(filename):
    data_dir = botsglobal.ini.get("directories", "data", "")
    if not data_dir:
        return filename
    base_dir = os.path.abspath(data_dir)
    filepath = os.path.abspath(os.path.join(base_dir, filename))
    if not filepath.startswith(base_dir):
        raise ValueError(f"Path escape detected: {filename}")
    return filepath


def deldata(filename):
    """delete internal data file."""
    filename = abspathdata(filename)
    with contextlib.suppress(Exception):
        os.remove(filename)


def opendata(filename, mode, charset=None, errors="strict"):
    """open internal data file as unicode."""
    # pylint: disable=deprecated-method
    filename = abspathdata(filename)
    if "w" in mode:
        dirshouldbethere(os.path.dirname(filename))
    return codecs.open(filename, mode, charset, errors)


def readdata(filename, charset=None, errors="strict"):
    """read internal data file in memory as unicode."""
    with opendata(filename, "r", charset, errors) as filehandler:
        return filehandler.read()


def opendata_bin(filename, mode="rb"):
    """open internal data file as binary."""
    # pylint: disable=unspecified-encoding
    filename = abspathdata(filename)
    if "w" in mode:
        dirshouldbethere(os.path.dirname(filename))
    return open(filename, mode=mode)  # noqa: SIM115


def readdata_bin(filename):
    """read internal data file in memory as binary."""
    with open(abspathdata(filename), mode="rb") as filehandler:
        content = filehandler.read()
    return content


def readdata_pickled(filename):
    """
    pickle is a binary/byte stream
    WARNING: Only load pickles from trusted internal sources.
    This function should only be used for BOTS internal data files.
    """
    # Validate that filename is from a trusted internal path
    abs_filename = abspathdata(filename)
    # Only allow loading from internal data directories (basic safety check)
    # In production, consider replacing pickle entirely with JSON/msgpack
    if not abs_filename:
        raise ValueError("Cannot load pickle from untrusted path")

    filehandler = opendata_bin(filename, mode="rb")
    try:
        content = pickle.load(filehandler)
    finally:
        filehandler.close()
    return content


def writedata_pickled(filename, content):
    """pickle is a binary/byte stream"""


# **********************************************************/**
# ***************** calling modules, programs **************/**
# **********************************************************/**
def runscript(module, modulefile, functioninscript, **argv):
    """
    Execute userscript. Functioninscript is supposed to be there; if not AttributeError is raised.
    Often is checked in advance if Functioninscript does exist.
    """
    logger.debug(
        'Run userscript "%(functioninscript)s" in "%(modulefile)s".',
        {"functioninscript": functioninscript, "modulefile": modulefile},
    )
    functiontorun = getattr(module, functioninscript)
    try:
        if callable(functiontorun):
            return functiontorun(**argv)
        return functiontorun

    except (ParsePassthroughException, KillWholeFileException):
        # special cases; these exceptions are handled later in specific ways.
        raise

    except Exception as exc:
        txt = txtexc()
        _exception = ScriptError(
            _('Userscript "%(modulefile)s": "%(txt)s".'), {"modulefile": modulefile, "txt": txt}
        )
        # _exception.__cause__ = None
        raise _exception from exc


def tryrunscript(module, modulefile, functioninscript, **argv):
    if module and hasattr(module, functioninscript):
        runscript(module, modulefile, functioninscript, **argv)
        return True
    return False


def runscriptyield(module, modulefile, functioninscript, **argv):
    logger.debug(
        'Run userscript "%(functioninscript)s" in "%(modulefile)s".',
        {"functioninscript": functioninscript, "modulefile": modulefile},
    )
    functiontorun = getattr(module, functioninscript)
    try:
        yield from functiontorun(**argv)
    except (ParsePassthroughException, KillWholeFileException):
        # special cases; these exceptions are handled later in specific ways.
        raise
    except Exception as exc:
        txt = txtexc()
        _exception = ScriptError(
            _('Script file "%(modulefile)s": "%(txt)s".'), {"modulefile": modulefile, "txt": txt}
        )
        # _exception.__cause__ = None
        raise _exception from exc


# **********************************************************/**
# *************** confirmrules *****************************/**
# **********************************************************/**
_CONFIRMRULES = []


def prepare_confirmrules():
    """
    as confirmrules are often used, read these into memory. Reason: performance.
    additional notes:
     - there are only a few confirmrules (10 would be a lot I guess).
     - indexing is not helpfull for confirmrules,
       this means that each time the whole confirmrule-tabel is scanned.
     - as confirmrules are used for incoming and outgoing (x12, edifact, email)
       this will almost always lead to better performance.
    """
    _CONFIRMRULES.clear()
    for confirmdict in query(
        """SELECT confirmtype,
                ruletype,
                idroute,
                idchannel_id as idchannel,
                frompartner_id as frompartner,
                topartner_id as topartner,
                messagetype,negativerule
            FROM confirmrule
            WHERE active=%(active)s
            ORDER BY negativerule ASC
            """,
        {"active": True},
    ):
        _CONFIRMRULES.append(dict(confirmdict))


def set_asked_confirmrules(routedict, rootidta):
    """set 'ask confirmation/acknowledgements for x12 and edifact"""
    if not globalcheckconfirmrules("ask-x12-997") and not globalcheckconfirmrules(
        "ask-edifact-CONTRL"
    ):
        return
    for row in query(
        """SELECT parent,editype,messagetype,frompartner,topartner
               FROM ta
               WHERE idta>%(rootidta)s
               AND status=%(status)s
               AND statust=%(statust)s
               AND (editype='edifact' OR editype='x12') """,
        {"status": FILEOUT, "statust": OK, "rootidta": rootidta},
    ):
        if row["editype"] == "x12":
            if row["messagetype"][:3] in ["997", "999"]:
                continue
            confirmtype = "ask-x12-997"
        else:
            if row["messagetype"][:6] in ["CONTRL", "APERAK"]:
                continue
            confirmtype = "ask-edifact-CONTRL"
        if not checkconfirmrules(
            confirmtype,
            idroute=routedict["idroute"],
            idchannel=routedict["tochannel"],
            topartner=row["topartner"],
            frompartner=row["frompartner"],
            messagetype=row["messagetype"],
        ):
            continue
        print(
            """UPDATE ta
                   SET confirmasked=%(confirmasked)s, confirmtype=%(confirmtype)s
                   WHERE idta=%(parent)s """,
            {"parent": row["parent"], "confirmasked": True, "confirmtype": confirmtype},
        )


def globalcheckconfirmrules(confirmtype):
    """global check if confirmrules with this confirmtype is uberhaupt used."""
    return any(confirmdict["confirmtype"] == confirmtype for confirmdict in _CONFIRMRULES)


def checkconfirmrules(confirmtype, **kwargs):
    # pylint: disable=too-many-branches
    # boolean to return: confirm of not?
    confirm = False
    # confirmrules are evaluated one by one; first the positive rules, than the negative rules.
    # this make it possible to include first, than exclude. Eg: send for 'all', than exclude certain partners.
    for confirmdict in _CONFIRMRULES:
        if confirmdict["confirmtype"] != confirmtype:
            continue
        if confirmdict["ruletype"] == "all":
            confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "confirmasked":
            if kwargs.get("confirmasked") and confirmtype.startswith("send-"):
                confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "route":
            if "idroute" in kwargs and confirmdict["idroute"] == kwargs["idroute"]:
                confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "channel":
            if "idchannel" in kwargs and confirmdict["idchannel"] == kwargs["idchannel"]:
                confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "frompartner":
            if "frompartner" in kwargs and confirmdict["frompartner"] == kwargs["frompartner"]:
                confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "topartner":
            if "topartner" in kwargs and confirmdict["topartner"] == kwargs["topartner"]:
                confirm = not confirmdict["negativerule"]
        elif confirmdict["ruletype"] == "messagetype":
            if "messagetype" in kwargs and confirmdict["messagetype"] == kwargs["messagetype"]:
                confirm = not confirmdict["negativerule"]
    return confirm


# **********************************************************/**
# ***************###############  misc.   #############
# **********************************************************/**
def set_database_lock():
    try:
        print("""INSERT INTO mutex (mutexk) VALUES (1)""")
    except Exception:
        return False
    return True


def remove_database_lock():
    print("""DELETE FROM mutex WHERE mutexk=1""")


def check_if_other_engine_is_running():
    """
    bots-engine always connects to 127.0.0.1 port 28081 (or port as set in bots.ini).
    this  is a good way of detecting that another bots-engien is still running.
    problem is avoided anyway if using jobqueueserver.
    """
    try:
        engine_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = botsglobal.ini.getint("settings", "port", 28081)
        engine_socket.bind(("127.0.0.1", port))
    except OSError:
        engine_socket.close()
        raise
    return engine_socket


def trace_origin(ta, where=None):
    if where is None:
        where = {}
    """
    bots traces back all from the current step/ta.
    where is a dict that is used to indicate a condition.
    eg:  {'status':EXTERNIN}
    If bots finds a ta for which this is true, the ta is added to a list.
    The list is returned when all tracing is done, and contains all ta's for which 'where' is True
    """

    def trace_recurse(ta):
        """
        recursive
        walk over ta's backward (to origin).
        if condition is met, add the ta to a list
        """
        for idta in get_parent(ta):
            donelijst.append(idta)
            taparent = OldTransaction(idta=idta)
            taparent.synall()
            for key, value in where.items():
                if getattr(taparent, key) != value:
                    break
            else:
                # all where-criteria are true;
                teruglijst.append(taparent)
            trace_recurse(taparent)

    def get_parent(ta):
        """yields the parents of a ta"""
        if ta.parent:
            # parent via the normal parent-attribute
            if ta.parent not in donelijst:
                yield ta.parent
        else:
            # no parent via parent-link, so look via child-link
            for row in query(
                """SELECT idta
                    FROM ta
                    WHERE idta>%(minidta)s
                    AND idta<%(maxidta)s
                    AND child=%(idta)s""",
                {"idta": ta.idta, "minidta": ta.script, "maxidta": ta.idta},
            ):
                if row["idta"] in donelijst:
                    continue
                yield row["idta"]

    donelijst = []
    teruglijst = []
    ta.synall()
    trace_recurse(ta)
    return teruglijst


def countoutfiles(idchannel, rootidta):
    """counts the number of edifiles to be transmitted via outchannel."""
    for row in query(
        """SELECT COUNT(*) as count
               FROM ta
               WHERE idta>%(rootidta)s
               AND status=%(status)s
               AND statust=%(statust)s
               AND tochannel=%(tochannel)s
               """,
        {"status": FILEOUT, "statust": OK, "tochannel": idchannel, "rootidta": rootidta},
    ):
        return row["count"]


def botsinfo():
    db_settings = {}
    infos = [
        (_("webserver port"), botsglobal.ini.getint("webserver", "port", 8080)),
        (_("platform"), platform.platform()),
        (_("machine"), platform.machine()),
        (_("python version"), platform.python_version()),
        (_("bots version"), botsglobal.version),
        (_("bots installation path"), botsglobal.ini.get("directories", "botspath", "")),
        (_("botsenv path"), botsglobal.ini.get("directories", "botsenv", "")),
        (_("config path"), botsglobal.ini.get("directories", "config", "")),
        (_("botssys path"), botsglobal.ini.get("directories", "botssys", "")),
        (_("usersys path"), botsglobal.ini.get("directories", "usersysabs", "")),
    ]
    if db_settings.get("ENGINE"):
        infos.append(("DATABASE_ENGINE", db_settings["ENGINE"]))
    if db_settings.get("NAME"):
        infos.append(("DATABASE_NAME", db_settings["NAME"]))
    if db_settings.get("USER"):
        infos.append(("DATABASE_USER", db_settings["USER"]))
    if db_settings.get("HOST"):
        infos.append(("DATABASE_HOST", db_settings["HOST"]))
    if db_settings.get("PORT"):
        infos.append(("DATABASE_PORT", db_settings["PORT"]))
    if db_settings.get("OPTIONS"):
        infos.append(("DATABASE_OPTIONS", db_settings["OPTIONS"]))
    return infos


def botsinfo_display():
    """:return str: Display bots infos"""
    txt = f"{os.linesep}---------- [Bots Environment] ----------{os.linesep}"
    txt += os.linesep.join(
        [f"    {key:22}: {val}" for key, val in botsinfo() if key not in ["webserver port"]]
    )
    txt += os.linesep + "-" * 40
    return txt


def datetime():
    """
    for use in acceptance testing: returns pythons usual datetime
    - but frozen value for acceptance testing.
    """
    if botsglobal.ini.getboolean("acceptance", "runacceptancetest", False):
        return python_datetime.datetime(2013, 1, 23, 1, 23, 45)
    return python_datetime.datetime.today()


def strftime(timeformat):
    """
    for use in acceptance testing: returns pythons usual string with date/time
    - but frozen value for acceptance testing.
    """
    return datetime().strftime(timeformat)


def settimeout(milliseconds):
    """set a time-out for TCP-IP connections"""
    socket.setdefaulttimeout(milliseconds / 1000.0)


def updateunlessset(updatedict, fromdict):
    """
    # !! TODO !! when is this valid?
    Note: prevents setting charset from grammar
    """
    updatedict.update((key, value) for key, value in fromdict.items() if not updatedict.get(key))


def rreplace(org, old, new="", count=1):
    """
    string handling:
    replace old with new in org, max count times.
    with default values: remove last occurence of old in org.
    """
    lijst = org.rsplit(old, count)
    return new.join(lijst)


# pylint: disable=invalid-name
def get_relevant_text_for_UnicodeError(exc):
    """see python doc for details of UnicodeError"""
    start = exc.start - 10 if exc.start >= 10 else 0
    return exc.object[start : exc.end + 35]


def indent_xml(node, level=0, indentstring="    "):
    """Indent xml node"""
    text2indent = "\n" + level * indentstring
    if len(node):
        if not node.text or not node.text.strip():
            node.text = text2indent + indentstring
        for subnode in node:
            indent_xml(subnode, level + 1, indentstring=indentstring)
            if not subnode.tail or not subnode.tail.strip():
                subnode.tail = text2indent + indentstring
        if not node[-1].tail or not node[-1].tail.strip():
            node[-1].tail = text2indent
    else:
        if level and (not node.tail or not node.tail.strip()):
            node.tail = text2indent


class Uri:
    """
    generate uri from parts/components
    - different forms of uri (eg with/without password)
    - general layout like 'scheme://user:pass@hostname:80/path/filename?query=argument#fragment'
    - checks: 1. what is required; 2. all parameters need to be valid
    Notes:
    - no filename: path ends with '/'
    Usage: uri = Uri(scheme='http',username='hje',password='password',hostname='test.com',port='80', path='')
    Usage: uri = Uri(scheme='http',hostname='test.com',port='80', path='test')
    """

    def __init__(self, **kw):
        self._uri = {
            "scheme": "",
            "username": "",
            "password": "",
            "hostname": "",
            "port": "",
            "path": "",
            "filename": "",
            "query": {},
            "fragment": "",
        }
        self.update(**kw)

    def update(self, **kw):
        self._uri.update(**kw)

    def uri(self, **kw) -> str:
        """Return formated uri str"""
        self.update(**kw)
        return str(self)

    def __str__(self):
        scheme = self._uri["scheme"] + ":" if self._uri["scheme"] else ""
        password = ":" + self._uri["password"] if self._uri["password"] else ""
        userinfo = self._uri["username"] + password + "@" if self._uri["username"] else ""
        port = ":" + str(self._uri["port"]) if self._uri["port"] else ""
        fullhost = self._uri["hostname"] + port if self._uri["hostname"] else ""
        authority = terug = "//" + userinfo + fullhost if fullhost else ""
        path = self._uri["path"]
        if path:
            terug = "/".join([authority, path.lstrip("/")]) if authority else path
        if self._uri["filename"]:
            if terug:
                terug = terug.rstrip("/") + "/"
            terug += self._uri["filename"]
        terug = scheme + terug
        if self._uri.get("query"):
            query_val = self._uri["query"]
            if isinstance(query_val, dict):
                import urllib.parse

                query_val = urllib.parse.urlencode(query_val)
            terug += "?" + str(query_val)
        if self._uri.get("fragment"):
            terug += "#" + self._uri["fragment"]
        return terug
