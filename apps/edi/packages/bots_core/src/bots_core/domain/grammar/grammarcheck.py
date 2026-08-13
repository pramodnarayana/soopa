"""
Bots grammar check
"""
# pylint: disable=broad-exception-caught

import atexit
import glob
import os
import sys

# Bots-modules
import structlog

from bots_core.domain import grammar
from bots_core.domain.exceptions import txtexc

logger = structlog.get_logger(__name__)


def startmulti(grammardir, editype):
    """
    specialized tool for bulk checking of grammars while developing botsgrammars
    grammardir: directory with gramars (eg bots/usersys/grammars/edifact)
    editype: eg edifact
    """
    # find locating of bots, configfiles, init paths etc.
    # logger is set up at module level
    atexit.register(logging.shutdown)

    search_pattern = os.path.join(grammardir, "*.py") if os.path.isdir(grammardir) else grammardir
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
        except Exception:
            print(txtexc(), end="\n\n")
        else:
            print("OK - no error found in grammar", filename, end="\n\n")


def start():
    """
    Start bots grammar checking
    """
    usage = """
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
            print(usage)
            sys.exit(0)
        elif arg.startswith("-"):
            print(usage)
            print(f"Error: unknown option '{arg}'.")
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
                print(usage)
                print(f"Error: unexpected extra argument '{arg}'.")
                sys.exit(1)
    if not (editype and messagetype):
        print(usage)
        print("Error: both editype and messagetype, or a file path, are required.")
        sys.exit(1)
    print("grammarcheck", editype, messagetype)
    # ***end handling command line arguments**************************

    # find locating of bots, configfiles, init paths etc.
    # logger is set up at module level
    atexit.register(logging.shutdown)

    try:
        grammar.grammarread(editype, messagetype, typeofgrammarfile="grammars")
    except Exception:
        print("Found error in grammar: ", txtexc())
        sys.exit(1)
    else:
        print("OK - no error found in grammar")
        sys.exit(0)


if __name__ == "__main__":
    start()
