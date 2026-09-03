import typing
import urllib.parse

"""
Base library for bots.
Botslib should not import code from other Bots-modules.
"""
# pylint: disable=missing-function-docstring, broad-exception-caught, too-many-lines

import contextlib
import datetime as python_datetime
import gettext as std_gettext
import importlib
import os
import platform
import socket

import structlog

from edi.core.bots.domain.exceptions import (
    ScriptImportError,
)
from edi.domain.enums import EdiStandard, EdiTransactionType

gettext = std_gettext.gettext


class _BotsGlobalStub:
    class ini:
        @staticmethod
        def get(*args: object, **kwargs: object) -> str:
            return ""

        @staticmethod
        def getint(*args: object, **kwargs: object) -> int:
            return 0

        @staticmethod
        def getboolean(*args: object, **kwargs: object) -> bool:
            return False

    version = ""
    logger = structlog.get_logger(__name__)


botsglobal = _BotsGlobalStub()

with contextlib.suppress(ImportError):
    pass


def _(m: str) -> str:
    return str(gettext(m))


MAXINT = (2**31) - 1

logger = structlog.get_logger(__name__)


# **********************************************************/**
# ************** Logging, Error handling *******************/**
# **********************************************************/**
def sendbotserrorreport(subject: str, reporttext: str) -> None:
    """
    Log an error report. Legacy email functionality has been removed in favor
    of enterprise observability (structlog).
    """
    botsglobal.logger.error("bots_error_report", subject=subject, report=reporttext)


def sendbotsemail(partner: str, subject: str, reporttext: str) -> bool:
    """
    Legacy partner email function. Removed.
    """
    botsglobal.logger.warning(
        "sendbotsemail_called", partner=partner, subject=subject, report=reporttext
    )
    return False


# Removed logging and error processes


# **********************************************************/**
# ************************ import **************************/**
# **********************************************************/**
def botsbaseimport(modulename: str) -> object:
    """
    Do a dynamic import.
    Errors/exceptions are handled in calling functions.
    """
    return importlib.import_module(modulename)


def botsimport(*args: str) -> tuple[object, str]:
    """
    import modules from usersys.
    return: imported module, filename imported module;
    """
    # assemble import string
    if args and args[0] == "grammars":
        if len(args) == 3 and args[1] == EdiStandard.X12 and args[2] != EdiTransactionType.ENVELOPE:
            # X12 transaction sets are named like 850004010. Version is the last 4 chars (e.g. 4010)
            grammarname = args[2]
            if len(grammarname) > 4:
                version = grammarname[-4:]
                modulepath = f"edi.core.grammar.x12.{version}.{grammarname}"
            else:
                modulepath = f"edi.core.grammar.x12.{grammarname}"
        else:
            modulepath = ".".join(("edi.core.grammar", *args[1:]))
    else:
        modulepath = ".".join(args)

    modulefile = "/".join(args)

    try:
        module = botsbaseimport(modulepath)
    except Exception as exc:
        errs_msg = _('Error in import of module "%(modulefile)s":\n%(txt)s')
        errs_dict = {"modulefile": str(modulefile), "txt": str(exc)}
        logger.debug(errs_msg, **errs_dict)
        _exception = ScriptImportError(errs_msg, errs_dict)
        _exception.__cause__ = None
        raise _exception from exc
    logger.debug('Imported "%(modulefile)s".', {"modulefile": modulefile})
    return module, modulefile


# **********************************************************/**
# ************** File handling os.path etc *****************/**
# **********************************************************/**
def join(*paths: str) -> str:
    """
    bots-specific join; path are relative to botsenv.
    For modern stateless mode, we just join them normally.
    """
    return os.path.normpath(os.path.join(*paths))


def readdata(filename: str, charset: str = "utf-8", errors: str = "strict") -> str:
    with open(filename, encoding=charset, errors=errors) as f:
        return f.read()


def readdata_bin(filename: str) -> bytes:
    with open(filename, "rb") as f:
        return f.read()


def opendata(filename: str, mode: str, charset: str = "utf-8", errors: str = "strict") -> typing.IO:
    if "b" in mode:
        return open(filename, mode)
    return open(filename, mode, encoding=charset, errors=errors)


# **********************************************************/**
# ***************** calling modules, programs **************/**
# Removed runscript, confirmrules, database locks, and tracing logic


def botsinfo() -> list[tuple[str, str | int]]:
    db_settings: dict[str, str | int] = {}
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


def botsinfo_display() -> str:
    """:return str: Display bots infos"""
    txt = f"{os.linesep}---------- [Bots Environment] ----------{os.linesep}"
    txt += os.linesep.join(
        [f"    {key:22}: {val}" for key, val in botsinfo() if key not in ["webserver port"]]
    )
    txt += os.linesep + "-" * 40
    return txt


def datetime() -> python_datetime.datetime:
    """
    for use in acceptance testing: returns pythons usual datetime
    - but frozen value for acceptance testing.
    """
    if botsglobal.ini.getboolean("acceptance", "runacceptancetest", False):
        return python_datetime.datetime(2013, 1, 23, 1, 23, 45)
    return python_datetime.datetime.today()


def strftime(timeformat: str) -> str:
    """
    for use in acceptance testing: returns pythons usual string with date/time
    - but frozen value for acceptance testing.
    """
    return datetime().strftime(timeformat)


def settimeout(milliseconds: int) -> None:
    """set a time-out for TCP-IP connections"""
    socket.setdefaulttimeout(milliseconds / 1000.0)


def updateunlessset(updatedict: dict[str, object], fromdict: dict[str, object]) -> None:
    """
    # !! TODO !! when is this valid?
    Note: prevents setting charset from grammar
    """
    updatedict.update((key, value) for key, value in fromdict.items() if not updatedict.get(key))


def rreplace(org: str, old: str, new: str = "", count: int = 1) -> str:
    """
    string handling:
    replace old with new in org, max count times.
    with default values: remove last occurence of old in org.
    """
    lijst = org.rsplit(old, count)
    return new.join(lijst)


# pylint: disable=invalid-name
def get_relevant_text_for_UnicodeError(exc: UnicodeError) -> str:
    """see python doc for details of UnicodeError"""
    start = exc.start - 10 if exc.start >= 10 else 0
    return exc.object[start : exc.end + 35]


def indent_xml(node: object, level: int = 0, indentstring: str = "    ") -> None:
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

    def __init__(self, **kw: object) -> None:
        self._uri: dict[str, object] = {
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

    def update(self, **kw: object) -> None:
        self._uri.update(**kw)

    def uri(self, **kw: object) -> str:
        """Return formated uri str"""
        self.update(**kw)
        return str(self)

    def __str__(self) -> str:
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
                query_val = urllib.parse.urlencode(query_val)
            terug += "?" + str(query_val)
        if self._uri.get("fragment"):
            terug += "#" + self._uri["fragment"]
        return terug
