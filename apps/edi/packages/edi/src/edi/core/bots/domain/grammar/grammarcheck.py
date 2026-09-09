"""
Bots grammar check
"""
# pylint: disable=broad-exception-caught

import glob
import os
import sys

# Bots-modules
import structlog

from edi.core.bots.domain import grammar

logger = structlog.get_logger(__name__)


def startmulti(grammardir, editype):
    """
    specialized tool for bulk checking of grammars while developing botsgrammars
    grammardir: directory with gramars (eg bots/usersys/grammars/edifact)
    editype: eg edifact
    """
    # find locating of bots, configfiles, init paths etc.
    # logger is set up at module level

    search_pattern = os.path.join(grammardir, "*.py") if os.path.isdir(grammardir) else grammardir
    errors = []
    for filename in glob.iglob(search_pattern):
        filename_basename = os.path.basename(filename)
        if filename_basename in ["__init__.py", "envelope.py"]:
            continue
        if filename_basename.startswith(("edifact", "records")) or filename_basename.endswith(
            "records.py"
        ):
            continue
        if filename_basename.endswith("pyc"):
            continue
        filename_noextension = os.path.splitext(filename_basename)[0]
        try:
            grammar.grammarread(editype, filename_noextension, typeofgrammarfile="grammars")
        except Exception as exc:
            errors.append(exc)
            logger.exception(
                "grammar_validation_failed",
                filename=filename,
                error=str(exc),
            )

    if errors:
        raise SystemExit(1)


def start():
    """
    Start bots grammar checking
    """
    """
    This is "{name}" version {version}, part of Bots open source edi translator (https://bots-edi.org).
    Checks a Bots grammar. Same checks are used as in translations with bots-engine. Searches for grammar in
    regular place: bots/usersys/grammars/<editype>/<messagetype>.py  (even if a path is passed).

    Usage:  {name}  <editype> <messagetype>
       or   {name}  <path to grammar>
    Examples:
        {name}  edifact  ORDERSD96AUNEAN008
        {name}  C:/python27/lib/site-packages/bots/usersys/grammars/edifact/ORDERSD96AUNEAN008.py

    """.format(
        name=os.path.basename(sys.argv[0]),
        version="1.0",
    )
    editype = ""
    messagetype = ""
    for arg in sys.argv[1:]:
        if arg in ["?", "/?", "-h", "--help"]:
            sys.exit(0)
        elif arg.startswith("-"):
            sys.exit(1)
        else:
            if os.path.isfile(arg):
                p1, p2 = os.path.split(arg)
                editype = os.path.basename(p1)
                messagetype, _ext = os.path.splitext(p2)
                messagetype = str(messagetype)
            elif not editype:
                editype = arg
            elif not messagetype:
                messagetype = arg
            else:
                sys.exit(1)
    if not (editype and messagetype):
        sys.exit(1)
    # ***end handling command line arguments**************************

    # find locating of bots, configfiles, init paths etc.
    # logger is set up at module level

    try:
        grammar.grammarread(editype, messagetype, typeofgrammarfile="grammars")
    except Exception:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    start()
