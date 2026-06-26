"""
Bots grammar check
"""
# pylint: disable=broad-exception-caught

import atexit
import glob

# Bots-modules
import logging
import os
import sys

from bots_core.domain.exceptions import txtexc
from bots_core.domain.grammar import grammar

logger = logging.getLogger(__name__)


def startmulti(grammardir, editype):
    """
    specialized tool for bulk checking of grammars while developing botsgrammars
    grammardir: directory with gramars (eg bots/usersys/grammars/edifact)
    editype: eg edifact
    """
    configdir = None
    # find locating of bots, configfiles, init paths etc.
    # logger is set up at module level
    atexit.register(logging.shutdown)

    search_pattern = os.path.join(grammardir, "*.py") if os.path.isdir(grammardir) else grammardir
    for filename in glob.iglob(search_pattern):
        filename_basename = os.path.basename(filename)
        if filename_basename in ["__init__.py", "envelope.py"]:
            continue
        if (
            filename_basename.startswith("edifact")
            or filename_basename.startswith("records")
            or filename_basename.endswith("records.py")
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

    Usage:  {name}  -c<directory> <editype> <messagetype>
       or   {name}  -c<directory> <path to grammar>
    Options:
        -c<directory>   directory for configuration files (default: config).
    Examples:
        {name} -cconfig  edifact  ORDERSD96AUNEAN008
        {name} -cconfig  C:/python27/lib/site-packages/bots/usersys/grammars/edifact/ORDERSD96AUNEAN008.py

    """.format(
        name=os.path.basename(sys.argv[0]),
        version="1.0",
    )
    configdir = None
    editype = ""
    messagetype = ""
    for arg in sys.argv[1:]:
        if arg.startswith("-c"):
            configdir = arg[2:]
            if not configdir:
                print(usage)
                print("Error: configuration directory indicated, but no directory name.")
                sys.exit(1)
        elif arg in ["?", "/?", "-h", "--help"] or arg.startswith("-"):
            print(usage)
            sys.exit(0)
        else:
            if os.path.isfile(arg):
                p1, p2 = os.path.split(arg)
                editype = os.path.basename(p1)
                messagetype, _ext = os.path.splitext(p2)
                messagetype = str(messagetype)
            elif not editype:
                editype = arg
            else:
                messagetype = arg
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
