"""
Base library for bots.
Botslib should not import code from other Bots-modules.
"""
# pylint: disable=missing-function-docstring, broad-exception-caught, too-many-lines

import datetime as python_datetime
import gettext as std_gettext
import importlib
import logging
import os
import platform
import socket
import sys

from bots_core.domain.exceptions import (
    ScriptImportError,
)

gettext = std_gettext.gettext


class _BotsGlobalStub:
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
    logger = logging.getLogger(__name__)


botsglobal = _BotsGlobalStub()

try:
    import pickle

    _ = pickle
except ImportError:
    pass


_ = gettext

MAXINT = (2**31) - 1

logger = logging.getLogger(__name__)


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


# Removed logging and error processes


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
    if args and args[0] == "grammars":
        if len(args) == 3 and args[1] == "x12" and args[2] != "envelope":
            # X12 transaction sets are named like 850004010. Version is the last 4 chars (e.g. 4010)
            grammarname = args[2]
            if len(grammarname) > 4:
                version = grammarname[-4:]
                modulepath = f"edi_grammar.x12.{version}.{grammarname}"
            else:
                modulepath = f"edi_grammar.x12.{grammarname}"
        else:
            modulepath = ".".join(("edi_grammar",) + args[1:])
    else:
        modulepath = ".".join(args)

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


# **********************************************************/**
# ***************** calling modules, programs **************/**
# Removed runscript, confirmrules, database locks, and tracing logic


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
