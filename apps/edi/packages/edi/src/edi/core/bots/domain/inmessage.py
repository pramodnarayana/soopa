# type: ignore
"""Reading/lexing/parsing/splitting an edifile."""
# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, duplicate-code, too-many-lines
# pylint: disable=too-many-branches, too-many-statements, attribute-defined-outside-init, consider-using-f-string
# pylint: disable=broad-exception-caught

# bots-modules
import time

import structlog

from edi.core.bots.domain import grammar, message, node
from edi.core.bots.domain.exceptions import (
    BotsImportError,
    InMessageError,
    TranslationNotFoundError,
    txtexc,
)

logger = structlog.get_logger(__name__)
from edi.core.bots.config.botsconfig import (
    ID,
    LIN,
    POS,
    VALUE,
)
from edi.core.bots.utils import botslib
from edi.core.bots.utils.botslib import gettext as _


def parse_edi_file(**ta_info):
    """
    Read, lex, parse edi-file. Dispatch function for Inmessage subclasses.
    Error handling: there are different types of errors.
    For all errors related to incoming messages: catch these.
    Try to extract the relevant information for the message.
     - unicode errors: charset is wrong.
    """
    # Deferred import to avoid circular dependency:
    # inmessage <- parsers.base <- inmessage
    from edi.core.bots.domain.parsers import READER_REGISTRY

    try:
        # get inmessage class to call (subclass of Inmessage)
        classtocall = READER_REGISTRY[ta_info["editype"]]
    except KeyError as exc:
        raise InMessageError(
            _("Unknown editype for incoming message: %(editype)s"), ta_info
        ) from exc
    ediobject = classtocall(ta_info)
    # read, lex, parse the incoming edi file
    # ALL errors are caught; these are 'fatal errors': processing has stopped.
    # get information from error/exception; format this into ediobject.errorfatal
    try:
        ediobject.initfromfile()
    except UnicodeError as exc:
        # ~ raise MessageError("")  # UNITTEST_CORRECTION
        content = botslib.get_relevant_text_for_UnicodeError(exc)
        # exc.encoding should contain encoding, but does not (think this is not OK for UNOA, etc)
        # pylint: disable=no-member  # pylint complain about exc.start ... this is in UnicodeError doc py 3.13
        ediobject.errorlist.append(
            str(
                InMessageError(
                    _(
                        "[A59]: incoming file has not allowed characters at/after file-position"
                        ' %(pos)s: "%(content)s".'
                    ),
                    {"pos": exc.start, "content": content},
                )
            )
        )
    except Exception:  # noqa: BLE001
        txt = txtexc()
        txt = txt.partition(": ")[2]
        ediobject.errorlist.append(txt)
    else:
        ediobject.errorfatal = False
    return ediobject


# *****************************************************************************
class Inmessage(message.Message):
    """
    abstract class for incoming ediobject (file or message).
    Can be initialised from a file or a tree.
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, ta_info):
        super().__init__(ta_info)
        # init list of lex_records
        self.lex_records = []
        # count chars in edi file. used in _lex,
        # plus for EDIFACT set in _sniff (as UNA is not lexed)
        # self.countpos = 0

    def messagegrammarread(self, typeofgrammarfile):
        """read grammar for a message/envelope."""
        self.defmessage = grammar.grammarread(
            self.ta_info["editype"], self.ta_info["messagetype"], typeofgrammarfile
        )
        botslib.updateunlessset(self.ta_info, self.defmessage.syntax)

    def initfromfile(self):
        """Initialisation from a edi file."""
        self.messagegrammarread(typeofgrammarfile="grammars")
        # **charset errors, lex errors
        # open file. variants: read with charset, read as binary & handled in sniff,
        # only opened and read in _lex.
        self._readcontent_edifile()
        # some hard-coded examination of edi file;
        # ta_info can be overruled by syntax-parameters in edi-file
        self._sniff()
        # start lexing
        self._lex()
        # lex preprocessing via user exit indicated in syntax
        preprocess_lex = self.ta_info["preprocess_lex"]
        if callable(preprocess_lex):
            preprocess_lex(lex=self.lex_records, ta_info=self.ta_info)
        if hasattr(self, "rawinput"):
            del self.rawinput
        self.set_syntax_used()
        # **breaking parser errors
        # make root Node None.
        self.root = node.Node()
        self.iternext_lex_record = iter(self.lex_records)
        leftover = self._parse(structure_level=self.defmessage.structure, inode=self.root)
        if leftover:
            # probably not reached with edifact/x12 because of mailbag processing.
            raise InMessageError(
                _(
                    "[A50] line %(line)s pos %(pos)s: Found non-valid data at end of edi file;"
                    " probably a problem with separators or message structure."
                ),
                {"line": leftover[0][LIN], "pos": leftover[0][POS]},
            )
        del self.lex_records
        # self.root is now root of a tree (of nodes).

        # **non-breaking parser errors
        self.checkenvelope()
        self.checkmessage(self.root, self.defmessage)
        # get queries-dict for parsed message; this is used to update in database
        if self.root.record:
            self.ta_info.update(self.root.queries)
        else:
            for childnode in self.root.children:
                self.ta_info.update(childnode.queries)
                break

    def set_syntax_used(self):
        """Update self.syntax dict depending on message type."""

    def handleconfirm(self, ta_fromfile, routedict, error):
        """end of edi file handling: writing of confirmations, etc."""

    def _formatfield(self, value, field_definition, structure_record, node_instance):  # noqa: C901
        """
        Format of a field is checked and converted if needed.
        Input: value (string), field definition.
        Output: the formatted value (string)
        Parameters of self.ta_info are used: triad, decimaal
        for fixed field: same handling; length is not checked.
        """
        if field_definition.bformat == "A":
            if len(value) > field_definition.length:
                self.add2errorlist(
                    _(
                        '[F05]%(linpos)s: Record "%(record)s" field "%(field)s"'
                        ' too big (max %(max)s): "%(content)s".\n'
                    )
                    % {
                        "linpos": node_instance.linpos(),
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "max": field_definition.length,
                    }
                )
            if len(value) < field_definition.min_length:
                self.add2errorlist(
                    _(
                        '[F06]%(linpos)s: Record "%(record)s" field "%(field)s"'
                        ' too small (min %(min)s): "%(content)s".\n'
                    )
                    % {
                        "linpos": node_instance.linpos(),
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "min": field_definition.min_length,
                    }
                )
        elif field_definition.bformat in "DT":
            lenght = len(value)
            if field_definition.bformat == "D":
                try:
                    if lenght == 6:
                        time.strptime(value, "%y%m%d")
                    elif lenght == 8:
                        time.strptime(value, "%Y%m%d")
                    else:
                        raise ValueError("To be catched")
                except ValueError:
                    self.add2errorlist(
                        _(
                            '[F07]%(linpos)s: Record "%(record)s" date field "%(field)s"'
                            ' not a valid date: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
            else:
                # field_definition.bformat == 'T':
                try:
                    if lenght == 4:
                        time.strptime(value, "%H%M")
                    elif lenght == 6:
                        time.strptime(value, "%H%M%S")
                    elif lenght in [7, 8]:
                        time.strptime(value[0:6], "%H%M%S")
                        if not value[6:].isdigit():
                            raise ValueError("To be catched")
                    else:
                        raise ValueError("To be catched")
                except ValueError:
                    self.add2errorlist(
                        _(
                            '[F08]%(linpos)s: Record "%(record)s" time field "%(field)s"'
                            ' not a valid time: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
        else:  # elif field_definition.bformat in 'RNI':  # numerics (R, N, I)
            if self.ta_info["lengthnumericbare"]:
                chars_not_counted = "-+" + self.ta_info["decimaal"]
                length = 0
                for char in value:
                    if char not in chars_not_counted:
                        length += 1
            else:
                length = len(value)
            if length > field_definition.length:
                self.add2errorlist(
                    _(
                        '[F10]%(linpos)s: Record "%(record)s" field "%(field)s"'
                        ' too big (max %(max)s): "%(content)s".\n'
                    )
                    % {
                        "linpos": node_instance.linpos(),
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "max": field_definition.length,
                    }
                )
            if length < field_definition.min_length:
                self.add2errorlist(
                    _(
                        '[F11]%(linpos)s: Record "%(record)s" field "%(field)s"'
                        ' too small (min %(min)s): "%(content)s".\n'
                    )
                    % {
                        "linpos": node_instance.linpos(),
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "min": field_definition.min_length,
                    }
                )
            if value[-1] == "-":
                # minus-sign at the end, put it in front.
                value = value[-1] + value[:-1]
            # strip triad-separators
            value = value.replace(self.ta_info["triad"], "")
            # replace decimal sign by canonical decimal sign
            value = value.replace(self.ta_info["decimaal"], ".", 1)
            if "E" in value or "e" in value:
                self.add2errorlist(
                    _(
                        '[F09]%(linpos)s: Record "%(record)s" field "%(field)s"'
                        ' has non-numerical content: "%(content)s".\n'
                    )
                    % {
                        "linpos": node_instance.linpos(),
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                    }
                )
            elif field_definition.bformat == "R":
                lendecimal = len(value.partition(".")[2])
                try:
                    # convert to float in order to check validity
                    valuedecimal = float(value)
                    value = "%.*F" % (lendecimal, valuedecimal)  # noqa: UP031
                except Exception:  # noqa: BLE001
                    self.add2errorlist(
                        _(
                            '[F16]%(linpos)s: Record "%(record)s" numeric field "%(field)s"'
                            ' has non-numerical content: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
            elif field_definition.bformat == "N":
                lendecimal = len(value.partition(".")[2])
                if lendecimal != field_definition.decimals:
                    self.add2errorlist(
                        _(
                            '[F14]%(linpos)s: Record "%(record)s" numeric field "%(field)s"'
                            ' has invalid nr of decimals: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
                try:
                    # convert to float in order to check validity
                    valuedecimal = float(value)
                    value = "%.*F" % (lendecimal, valuedecimal)  # noqa: UP031
                except Exception:  # noqa: BLE001
                    self.add2errorlist(
                        _(
                            '[F15]%(linpos)s: Record "%(record)s" numeric field "%(field)s"'
                            ' has non-numerical content: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
            elif field_definition.bformat == "I":
                if "." in value:
                    self.add2errorlist(
                        _(
                            '[F12]%(linpos)s: Record "%(record)s" field "%(field)s" has format "I"'
                            ' but contains decimal sign: "%(content)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
                else:
                    try:  # convert to float in order to check validity
                        valuedecimal = float(value)
                        valuedecimal = valuedecimal / 10**field_definition.decimals
                        value = "%.*F" % (field_definition.decimals, valuedecimal)  # noqa: UP031
                    except Exception:  # noqa: BLE001
                        self.add2errorlist(
                            _(
                                '[F13]%(linpos)s: Record "%(record)s" numeric field "%(field)s"'
                                ' has non-numerical content: "%(content)s".\n'
                            )
                            % {
                                "linpos": node_instance.linpos(),
                                "record": self.mpathformat(structure_record.mpath),
                                "field": field_definition.id,
                                "content": value,
                            }
                        )
        return value

    def _lex(self):
        """edi file->self.lex_records."""

    def _parsefields(self, lex_record, record_definition) -> dict:
        """Parse fields from one fixed message-record and check length of the fixed record."""

    def _parse(self, structure_level, inode):  # noqa: C901
        """
        This is the heart of the parsing of incoming messages (but not for xml, json)
        Read the lex_records one by one (self.iternext_lex_record, is an iterator)
         - parse the records.
         - identify record (lookup in structure)
         - identify fields in the record (use the record_definition from the grammar).
         - add grammar-info to records: field-tag,mpath.
        Parameters:
         - structure_level: current grammar/segmentgroup of the grammar-structure.
         - inode: parent node; all parsed records are added as children of inode
        2x recursive: SUBTRANSLATION and segmentgroups
        """
        # keep track of where we are in the structure_level
        structure_index = 0
        # number of occurences of current record in structure
        countnrofoccurences = 0
        structure_end = len(structure_level)
        # indicate if the next record should be fetched,
        # or if the current_lex_record is still being parsed.
        current_lex_record = None
        get_next_lex_record = True
        # it might seem logical to test here 'current_lex_record is None',
        # but this is already used to indicate 'no more records'.
        while True:
            if get_next_lex_record:
                try:
                    current_lex_record = next(self.iternext_lex_record)
                except StopIteration:
                    # catch when no more lex_record.
                    current_lex_record = None
                get_next_lex_record = False
            if (
                current_lex_record is None
                or structure_level[structure_index].id != current_lex_record[ID][VALUE]
            ):
                if structure_level[structure_index].min_occ and not countnrofoccurences:
                    # is record is required in structure_level, and countnrofoccurences==0: error;
                    # enough check here; message is validated more accurate later
                    try:
                        raise InMessageError(
                            self.messagetypetxt
                            + _(
                                '[S50]: Line:%(line)s pos:%(pos)s record:"%(record)s":'
                                " message has an error in its structure;"
                                " this record is not allowed here."
                                " Scanned in message definition until mandatory"
                                ' record: "%(looked)s".'
                            ),
                            {
                                "record": current_lex_record[ID][VALUE],
                                "line": current_lex_record[ID][LIN],
                                "pos": current_lex_record[ID][POS],
                                "looked": self.mpathformat(structure_level[structure_index].mpath),
                            },
                        )
                    except TypeError as exc:
                        # when no UNZ (edifact)
                        raise InMessageError(
                            self.messagetypetxt
                            + _('[S51]: Missing mandatory record "%(record)s".'),
                            {"record": self.mpathformat(structure_level[structure_index].mpath)},
                        ) from exc
                structure_index += 1
                if structure_index == structure_end:
                    # current_lex_record is not in this level. Go level up
                    # if on 'first level': give specific error
                    if (
                        current_lex_record is not None
                        and structure_level == self.defmessage.structure
                    ):
                        raise InMessageError(
                            self.messagetypetxt
                            + _(
                                '[S50]: Line:%(line)s pos:%(pos)s record:"%(record)s":'
                                " message has an error in its structure;"
                                " this record is not allowed here."
                                " Scanned in message definition until mandatory"
                                ' record: "%(looked)s".'
                            ),
                            {
                                "record": current_lex_record[ID][VALUE],
                                "line": current_lex_record[ID][LIN],
                                "pos": current_lex_record[ID][POS],
                                "looked": self.mpathformat(
                                    structure_level[structure_index - 1].mpath
                                ),
                            },
                        )
                    # return either None (no more lex_records to parse)
                    # or the last current_lex_record
                    # (the last current_lex_record is not found in this level)
                    return current_lex_record
                countnrofoccurences = 0
                # continue while-loop:
                # get_next_lex_record is false as no match with structure is made;
                # go and look at next record of structure
                continue
            # record is found in grammar
            countnrofoccurences += 1
            newnode = node.Node(
                record=self._parsefields(current_lex_record, structure_level[structure_index]),
                linpos_info=(current_lex_record[0][LIN], current_lex_record[0][POS]),
                is_array=(structure_level[structure_index].max_occ != 1),
            )
            # succes! append new node as a child to current (parent)node
            inode.append(newnode)
            if structure_level[structure_index].subtranslation:
                # start a SUBTRANSLATION; find the right messagetype, etc
                messagetype = newnode.enhancedget(structure_level[structure_index].subtranslation)
                if not messagetype:
                    raise TranslationNotFoundError(
                        _('Could not find SUBTRANSLATION "%(sub)s" in (sub)message.'),
                        {"sub": structure_level[structure_index].subtranslation},
                    )
                messagetype = self._manipulatemessagetype(messagetype, inode)
                try:
                    defmessage = grammar.grammarread(
                        self.__class__.__name__, messagetype, typeofgrammarfile="grammars"
                    )
                except BotsImportError as exc:
                    # could not find grammar via normal method.
                    raise TranslationNotFoundError(
                        _(
                            'No (valid) grammar for editype "%(editype)s"'
                            ' messagetype "%(messagetype)s".'
                        ),
                        {"editype": self.__class__.__name__, "messagetype": messagetype},
                    ) from exc
                # grammar is read.
                self.messagecount += 1
                self.messagetypetxt = _(f"Message nr {self.messagecount}, type {messagetype}, ")
                current_lex_record = self._parse(
                    structure_level=defmessage.structure[0].level, inode=newnode
                )
                # copy messagetype into 1st segment of subtranslation (eg UNH, ST)
                newnode.queries = {"messagetype": messagetype}
                newnode.queries.update(defmessage.syntax)
                # if using this line instead of previous 2: gives errors eg in incoming edifact...
                # do not understand why
                # ~ newnode.queries = defmessage.syntax.copy()
                # check the results of the subtranslation
                self.checkmessage(newnode, defmessage, subtranslation=True)
                # ~ end SUBTRANSLATION
                self.messagetypetxt = ""
                # get_next_lex_record is still False;
                # we are trying to match the last (not matched)
                # record from the SUBTRANSLATION (named 'current_lex_record').
            else:
                if structure_level[structure_index].level:
                    # if header, go parse segmentgroup (recursive)
                    current_lex_record = self._parse(
                        structure_level=structure_level[structure_index].level, inode=newnode
                    )
                    # get_next_lex_record is still False;
                    # the current_lex_record that was not matched in lower segmentgroups
                    # is still being parsed.
                else:
                    get_next_lex_record = True
                # accomodate for UNS = UNS construction
                if (
                    structure_level[structure_index].min_occ
                    == structure_level[structure_index].max_occ
                    == countnrofoccurences
                ):
                    if structure_index + 1 == structure_end:
                        pass
                    else:
                        structure_index += 1
                        countnrofoccurences = 0

    def _manipulatemessagetype(self, messagetype, inode):
        """default: just return messagetype."""
        # pylint: disable=unused-argument
        return messagetype

    def _readcontent_edifile(self):
        """read content of edi file to memory."""
        if "raw_edi" in self.ta_info:
            safe_info = {k: v for k, v in self.ta_info.items() if k != "raw_edi"}
            logger.debug("Read edi from raw_edi in memory.", safe_info)
            data = self.ta_info["raw_edi"]
            if isinstance(data, bytes):
                charset = self.ta_info.get("charset") or "utf-8"
                errors = self.ta_info.get("checkcharsetin") or "strict"
                self.rawinput = data.decode(charset, errors=errors)
            else:
                self.rawinput = data
        else:
            logger.debug('Read edi file "%(filename)s".', self.ta_info)
            self.rawinput = botslib.readdata(
                filename=self.ta_info["filename"],
                charset=self.ta_info["charset"],
                errors=self.ta_info["checkcharsetin"],
            )

    def _sniff(self):
        """
        sniffing: hard coded parsing of edi file.
        method is specified in subclasses.
        """

    def checkenvelope(self):
        pass

    def nextmessage(self):  # noqa: C901
        """Passes each 'message' to the mapping script."""
        # node preprocessing via user exit indicated in syntax
        preprocess_nodes = self.ta_info["preprocess_nodes"]
        if callable(preprocess_nodes):
            preprocess_nodes(thisnode=self)
        if self.defmessage.nextmessage is not None:
            # nextmessage defined in grammar: split up messages
            # first: count number of messages
            self.ta_info["total_number_of_messages"] = self.getcountoccurrences(
                *self.defmessage.nextmessage
            )
            # yield the messages, using nextmessage
            count = 0
            self.root.processqueries({}, len(self.defmessage.nextmessage))
            for eachmessage in self.getloop_including_mpath(*self.defmessage.nextmessage):
                # eachmessage is a list: [mpath,mpath, etc, node]
                count += 1  # noqa: SIM113
                ta_info = self.ta_info.copy()
                ta_info.update(eachmessage[-1].queries)
                ta_info["message_number"] = count
                # give mappingscript access to envelope
                ta_info["bots_accessenvelope"] = self.root
                yield self._initmessagefromnode(
                    eachmessage[-1], ta_info, self.syntax, eachmessage[:-1]
                )
            if self.defmessage.nextmessage2 is not None:
                # edifact uses nextmessage2 for UNB-UNG
                # first: count number of messages
                self.ta_info["total_number_of_messages"] = self.getcountoccurrences(
                    *self.defmessage.nextmessage2
                )
                # yield the messages, using nextmessage2
                self.root.processqueries({}, len(self.defmessage.nextmessage2))
                count = 0
                for eachmessage in self.getloop_including_mpath(*self.defmessage.nextmessage2):
                    # eachmessage is a list: [mpath,mpath, etc, node]
                    count += 1  # noqa: SIM113
                    ta_info = self.ta_info.copy()
                    ta_info.update(eachmessage[-1].queries)
                    ta_info["message_number"] = count
                    # give mappingscript access to envelope
                    ta_info["bots_accessenvelope"] = self.root
                    yield self._initmessagefromnode(
                        eachmessage[-1], ta_info, self.syntax, eachmessage[:-1]
                    )
        elif self.defmessage.nextmessageblock is not None:
            # for csv/fixed: nextmessageblock indicates which field(s) determines a message
            # --> as long as the field(s) has same value, it is the same message
            # note there is only one recordtype (as checked in grammar.py)
            # first: count number of messages
            count = 0
            for line in self.root.children:
                kriterium = line.enhancedget(self.defmessage.nextmessageblock)
                if not count:
                    count = 1
                    oldkriterium = kriterium
                elif kriterium != oldkriterium:
                    count += 1
                    oldkriterium = kriterium
            self.ta_info["total_number_of_messages"] = count
            # yield the messages, using nextmessageblock
            count = 0
            oldline = None
            for line in self.root.children:
                kriterium = line.enhancedget(self.defmessage.nextmessageblock)
                if not count:
                    count = 1
                    oldkriterium = kriterium
                    # make new empty root node.
                    newroot = node.Node()
                elif kriterium != oldkriterium:
                    count += 1
                    oldkriterium = kriterium
                    ta_info = self.ta_info.copy()
                    # update ta_info with information (from previous line) 20100905
                    ta_info.update(oldline.queries)
                    ta_info["message_number"] = count
                    yield self._initmessagefromnode(newroot, ta_info, self.syntax)
                    # make new empty root node.
                    newroot = node.Node()
                newroot.append(line)
                # save line 20100905
                oldline = line
            if count:
                # not if count is zero (that is, if there are no lines)
                ta_info = self.ta_info.copy()
                # update ta_info with information (from last line) 20100904
                ta_info.update(line.queries)
                ta_info["message_number"] = count
                # give mappingscript access to envelope
                ta_info["bots_accessenvelope"] = self.root
                yield self._initmessagefromnode(newroot, ta_info, self.syntax)
        else:
            # no split up is indicated in grammar.
            # Normally you really would...
            if self.root.record or self.ta_info.get("pass_all", False):
                # if contains root-record or explicitly indicated (csv): pass whole tree
                ta_info = self.ta_info.copy()
                ta_info.update(self.root.queries)
                ta_info["total_number_of_messages"] = 1
                ta_info["message_number"] = 1
                # give mappingscript access to envelop
                ta_info["bots_accessenvelope"] = self.root
                yield self._initmessagefromnode(self.root, ta_info, self.syntax)
            else:
                # pass nodes under root one by one
                # first: count number of messages
                total_number_of_messages = len(self.root.children)
                # yield the messages
                count = 0
                for child in self.root.children:
                    count += 1  # noqa: SIM113
                    ta_info = self.ta_info.copy()
                    ta_info.update(child.queries)
                    ta_info["total_number_of_messages"] = total_number_of_messages
                    ta_info["message_number"] = count
                    # give mappingscript access to envelope
                    ta_info["bots_accessenvelope"] = self.root
                    yield self._initmessagefromnode(child, ta_info, self.syntax)

    def _canonicaltree(self, node_instance, structure):
        """
        call the _canonicaltree for Message (check min/max, sort)
           do the QUERIES in the grammar structure.
        """
        super()._canonicaltree(node_instance, structure)
        if structure.queries:
            node_instance.get_queries_from_edi(structure)

    @classmethod
    def _initmessagefromnode(cls, inode, ta_info, syntax, envelope_content=None):
        """
        initialize a inmessage-object from node in tree.
        used in nextmessage.

        envelope data of incoming. list of dicts. example:
        [
            {
                '0020': 'UNB_ID',
                'S003.0007': '14',
                'S002.0007': '14',
                'S002.0004': 'PARTNER1',
                'S004.0017': '050824',
                'BOTSIDnr': '1',
                'S003.0010': 'PARTNER2',
                'S001.0002': '3',
                'S001.0001': 'UNOA',
                'BOTSID': 'UNB',
                'S004.0019': '1727',
            },
        ]
        """
        messagefromnode = cls(ta_info)
        messagefromnode.root = inode
        messagefromnode.syntax = syntax
        messagefromnode.envelope_content = envelope_content
        return messagefromnode
