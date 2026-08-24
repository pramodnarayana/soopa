"""
Bots Exception classes
"""
# pylint: disable=missing-class-docstring, broad-exception-caught

import collections
import traceback
from typing import Any


def safe_unicode(value: Any) -> str:
    """For errors: return best possible unicode...should never lead to errors."""
    # print("safe_unicode00")
    try:
        if isinstance(value, str):
            # is already unicode, just return
            return value
        if isinstance(value, bytes):
            # string/bytecode, encoding unknown.
            for charset in ["utf_8", "latin_1"]:
                try:
                    # decode strict
                    return value.decode(charset, "strict")
                except Exception:
                    pass
            # should never get here?
            print("safe_unicode33")
            # decode as if it is utf-8, ignore errors.
            return value.decode("utf_8", "ignore")
        # print("safe_unicode11",type(value))
        return str(value)
    except Exception as exc:
        print("safe_unicode22", exc)
        try:
            return str(repr(value))
        except Exception:
            return "Error while displaying error"


def txtexc(limit: int = 0) -> str:
    """
    Process last exception, get an errortext.
    Errortext should be valid unicode.
    """
    terug = safe_unicode(traceback.format_exc(limit=None))
    if limit is None:
        return terug
    terug = safe_unicode(traceback.format_exc(limit=limit))
    terug = terug.replace("Traceback (most recent call last):\n", "")
    terug = terug.replace("bots.botslib.", "")
    return terug


class BotsError(Exception):
    """
    formats the error messages. Under all circumstances: give (reasonable) output, no errors.
    input (exc,*args,**kwargs) can be anything: strings (any charset), unicode, objects.
    Note that these are errors, so input can be 'not valid'!
    to avoid the risk of 'errors during errors' catch-all solutions are used.

    2 ways to raise Exceptions:
      # this one is preferred!!
    - BotsError('tekst %(var1)s %(var2)s',{'var1':'value1','var2':'value2'})

    - BotsError('tekst %(var1)s %(var2)s',var1='value1',var2='value2')
    """

    def __init__(self, exc: Any, *args: Any, **kwargs: Any) -> None:
        self.exc = safe_unicode(exc)
        if args:
            # expect args[0] to be a dict
            xxx = args[0] if isinstance(args[0], dict) else {}
        else:
            xxx = kwargs
        self.xxx = collections.defaultdict(str)
        for key, value in xxx.items():
            self.xxx[safe_unicode(key)] = safe_unicode(value)

    def __str__(self) -> str:
        try:
            # this is already unicode
            return self.exc % (self.xxx)
        except Exception:
            print("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX11")
            # errors in self.exc; non supported format codes. Don't think this happen...
            return self.exc


class CodeConversionError(BotsError):
    pass


class CommunicationError(BotsError):
    pass


class CommunicationInError(CommunicationError):
    pass


class CommunicationOutError(CommunicationError):
    pass


class EanError(BotsError):
    pass


class GrammarError(BotsError):
    pass


class GrammarPartMissing(BotsError):
    pass


class InMessageError(BotsError):
    pass


class LockedFileError(BotsError):
    pass


class MessageError(BotsError):
    pass


class MessageRootError(BotsError):
    pass


class MappingRootError(BotsError):
    pass


class MappingFormatError(BotsError):
    pass


class OutMessageError(BotsError):
    pass


class PanicError(BotsError):
    pass


class PersistError(BotsError):
    pass


class PluginError(BotsError):
    pass


class BotsImportError(BotsError):
    """import script or recursivly imported scripts not there"""


class ScriptImportError(BotsError):
    """import errors in userscript; userscript is there"""


class ScriptError(BotsError):
    """runtime errors in a userscript"""


class TraceError(BotsError):
    pass


class TranslationNotFoundError(BotsError):
    pass


class ParsePassthroughException(BotsError):
    """
    to handle Parse and passthrough.
    Can be via translationrule or in mapping.
    """


class DummyException(BotsError):
    """sometimes it is simplest to raise an error, and catch it rightaway. Like a goto ;-)"""


class KillWholeFileException(BotsError):
    """used to error whole edi-file out (instead of only a message)"""


class FileTooLargeError(BotsError):
    pass


class DirmonitorError(BotsError):
    """Bots exception raised by bots-dirmonitor"""


class AcceptanceTestError(BotsError):
    """Bots acceptance test error"""
