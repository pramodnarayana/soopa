"""
parsers/edifact.py — EDIFACT reader and writer.

Contains:
  - ``edifact``: incoming EDIFACT parser  (formerly class edifact(var) in inmessage.py)
  - ``edifact_writer``: outgoing EDIFACT serialiser  (formerly class edifact(Outmessage) in outmessage.py)

Both are registered in parsers/__init__.py and injected into the dispatchers
in inmessage.py / outmessage.py via READER_REGISTRY / WRITER_REGISTRY.
"""
# pylint: disable=invalid-name, missing-function-docstring, too-many-branches
# pylint: disable=too-many-statements, attribute-defined-outside-init

import codecs

import structlog

from edi.core.bots.config.botsconfig import (
    SFIELD,
    VALUE,
)
from edi.core.bots.domain.exceptions import InMessageError
from edi.core.bots.domain.outmessage import Outmessage
from edi.core.bots.utils import botslib
from edi.core.bots.utils.botslib import gettext as _
from edi.domain.types import AstNode

from .base import var

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# EDIFACT Reader
# ---------------------------------------------------------------------------


class edifact(var):
    """Class for EDIFACT incoming message objects."""

    @staticmethod
    def _manipulatemessagetype(messagetype, inode):  # pylint: disable=unused-argument
        """Older EDIFACT messages have eg 90.1 as version — convert dots to underscores."""
        return messagetype.replace(".", "_")

    def _readcontent_edifile(self):
        """
        Read content of EDIFACT file into memory as binary.
        Charset is determined in _sniff(), then file is decoded.
        """
        if "raw_edi" in self.ta_info:
            safe_info = {k: v for k, v in self.ta_info.items() if k != "raw_edi"}
            logger.debug("Read edi from raw_edi in memory (binary for edifact).", safe_info)
            data = self.ta_info["raw_edi"]
            if isinstance(data, str):
                charset = self.ta_info.get("charset") or "utf-8"
                self.rawinput = data.encode(charset)
            else:
                self.rawinput = data
        else:
            logger.debug('Read edi file "%(filename)s".', self.ta_info)
            # read as binary
            self.rawinput = botslib.readdata_bin(filename=self.ta_info["filename"])

    def _sniff(self):
        """
        Examine the beginning of an EDIFACT file for syntax parameters and charset.
        If the beginning of the file is not correct: raise error.
        EDIFACT files are read as binary first; EDIFACT has several charsets (UNOA, UNOC, UNOY).
        Processing assumes: charset is ascii, utf-8, or some charset where 1char=1byte.
        """
        # check for BOM. BOM should not be there. But if it is, it gives a very confusing error.
        if self.rawinput.startswith(codecs.BOM_UTF8):
            raise InMessageError(_("[A68]: Edifact file starts with BOM."))
        # read first 100 bytes to do sniffing...
        rawinput = self.rawinput[0:99].decode("iso-8859-1")
        # find first non-whitespace character
        rawinput = rawinput.lstrip()
        # check if UNA
        if rawinput.startswith("UNA"):
            has_una_string = True
            # read UNA; set syntax parameters
            count = 3
            try:
                for field in [
                    "sfield_sep",
                    "field_sep",
                    "decimaal",
                    "escape",
                    "reserve",
                    "record_sep",
                ]:
                    self.ta_info[field] = rawinput[count]
                    count += 1
            except IndexError as exc:
                raise InMessageError(
                    _('[A53]: Edifact file contains "UNA" and than garbage.')
                ) from exc
            rawinput = rawinput[count:].lstrip()
        else:
            has_una_string = False
        # check if there is UNB
        if not rawinput.startswith("UNB"):
            raise InMessageError(
                _('[A54]: Found no "UNB" at the start of edifact file. Probably not be edifact.')
            )
        # get separators, charset, version.
        count = 0
        found_charset = ""
        for char in rawinput:
            if char in self.ta_info["skip_char"]:
                continue
            if count <= 3:
                if count == 3:
                    found_field_sep = char
            elif count <= 7:
                found_charset += char
            elif count == 8:
                found_sfield_sep = char
            else:
                self.ta_info["version"] = char
                break
            count += 1
        else:
            # if arrive here: too many <cr/lf>?
            raise InMessageError(_("[A55]: Problems with UNB-segment; too many <CR/LF>."))

        # set and/or verify separators
        if has_una_string:
            if (
                found_field_sep != self.ta_info["field_sep"]
                or found_sfield_sep != self.ta_info["sfield_sep"]
            ):
                raise InMessageError(
                    _(
                        "[A56]: Separators as used in edifact file are different"
                        " from values as in UNA-segment."
                    )
                )
        else:
            if found_field_sep == "+" and found_sfield_sep == ":":
                # assume standard/UNOA separators.
                self.ta_info["sfield_sep"] = ":"
                self.ta_info["field_sep"] = "+"
                self.ta_info["decimaal"] = "."
                self.ta_info["escape"] = "?"
                self.ta_info["reserve"] = "*"
                self.ta_info["record_sep"] = "'"
            elif found_field_sep == "\x1d" and found_sfield_sep == "\x1f":
                # check if UNOB separators are used
                self.ta_info["sfield_sep"] = "\x1f"
                self.ta_info["field_sep"] = "\x1d"
                self.ta_info["decimaal"] = "."
                self.ta_info["escape"] = ""
                self.ta_info["reserve"] = "*"
                self.ta_info["record_sep"] = "\x1c"
            else:
                raise InMessageError(
                    _(
                        "[A57]: Edifact file has non-standard separators."
                        " An UNA segment is required."
                    )
                )

        # decode the file (to unicode)
        self.ta_info["charset"] = found_charset

        charset_map = {
            "UNOA": "ascii",
            "UNOB": "ascii",
            "UNOC": "iso-8859-1",
            "UNOD": "iso-8859-2",
            "UNOE": "iso-8859-5",
            "UNOF": "iso-8859-7",
            "UNOY": "utf-8",
        }
        python_charset = charset_map.get(found_charset, found_charset)

        try:
            self.rawinput = self.rawinput[self.rawinput.find(b"UNB") :].decode(
                python_charset, self.ta_info["checkcharsetin"]
            )
        except LookupError as exc:
            raise InMessageError(
                _('[A58]: Edifact file has unknown characterset "%(charset)s".'),
                {"charset": found_charset},
            ) from exc
        except UnicodeDecodeError as exc:
            raise InMessageError(
                _(
                    "[A59]: Edifact file has not allowed characters at/after file-position %(content)s."
                ),
                {"content": exc.start},
            ) from exc

        if self.ta_info["version"] < "4" or self.ta_info["reserve"] == " ":
            # repetition separator only for version >= 4.
            # if version > 4 and repetition separator is space:
            # assume this is a mistake; use repetition separator
            self.ta_info["reserve"] = ""

        # extra checks for separators
        self.separatorcheck(
            self.ta_info["sfield_sep"]
            + self.ta_info["field_sep"]
            + self.ta_info["decimaal"]
            + self.ta_info["escape"]
            + self.ta_info["reserve"]
            + self.ta_info["record_sep"]
        )

    def checkenvelope(self):
        """Check envelopes (UNB-UNZ counters & references, UNH-UNT counters & references etc)."""
        # pylint: disable=too-many-locals
        for UNB in self.getloop({"BOTSID": "UNB"}):
            logger.debug("Start parsing edifact envelopes")
            unbreference = UNB.get({"BOTSID": "UNB", "0020": None})
            unzreference = UNB.get({"BOTSID": "UNB"}, {"BOTSID": "UNZ", "0020": None})
            if unbreference and unzreference and unbreference != unzreference:
                self.add2errorlist(
                    _(
                        '[E01]: UNB-reference is "%(unbreference)s";'
                        ' should be equal to UNZ-reference "%(unzreference)s".\n'
                    )
                    % {"unbreference": unbreference, "unzreference": unzreference}
                )
            unzcount = UNB.get({"BOTSID": "UNB"}, {"BOTSID": "UNZ", "0036": None})
            messagecount = len(UNB.children) - 1
            try:
                if int(unzcount) != messagecount:
                    self.add2errorlist(
                        _(
                            "[E02]: Count of messages in UNZ is %(unzcount)s;"
                            " should be equal to number of messages %(messagecount)s.\n"
                        )
                        % {"unzcount": unzcount, "messagecount": messagecount}
                    )
            except Exception:
                self.add2errorlist(
                    _('[E03]: Count of messages in UNZ is invalid: "%(count)s".\n')
                    % {"count": unzcount}
                )
            for nodeunh in UNB.getloop({"BOTSID": "UNB"}, {"BOTSID": "UNH"}):
                unhreference = nodeunh.get({"BOTSID": "UNH", "0062": None})
                untreference = nodeunh.get({"BOTSID": "UNH"}, {"BOTSID": "UNT", "0062": None})
                if unhreference and untreference and unhreference != untreference:
                    self.add2errorlist(
                        _(
                            '[E04]: UNH-reference is "%(unhreference)s";'
                            ' should be equal to UNT-reference "%(untreference)s".\n'
                        )
                        % {"unhreference": unhreference, "untreference": untreference}
                    )
                untcount = nodeunh.get({"BOTSID": "UNH"}, {"BOTSID": "UNT", "0074": None})
                segmentcount = nodeunh.getcount()
                try:
                    if int(untcount) != segmentcount:
                        self.add2errorlist(
                            _(
                                "[E05]: Segmentcount in UNT is %(untcount)s;"
                                " should be equal to number of segments %(segmentcount)s.\n"
                            )
                            % {"untcount": untcount, "segmentcount": segmentcount}
                        )
                except Exception:
                    self.add2errorlist(
                        _('[E06]: Count of segments in UNT is invalid: "%(count)s".\n')
                        % {"count": untcount}
                    )
            for nodeung in UNB.getloop({"BOTSID": "UNB"}, {"BOTSID": "UNG"}):
                ungreference = nodeung.get({"BOTSID": "UNG", "0048": None})
                unereference = nodeung.get({"BOTSID": "UNG"}, {"BOTSID": "UNE", "0048": None})
                if ungreference and unereference and ungreference != unereference:
                    self.add2errorlist(
                        _(
                            '[E07]: UNG-reference is "%(ungreference)s";'
                            ' should be equal to UNE-reference "%(unereference)s".\n'
                        )
                        % {"ungreference": ungreference, "unereference": unereference}
                    )
                unecount = nodeung.get({"BOTSID": "UNG"}, {"BOTSID": "UNE", "0060": None})
                groupcount = len(nodeung.children) - 1
                try:
                    if int(unecount) != groupcount:
                        self.add2errorlist(
                            _(
                                "[E08]: Groupcount in UNE is %(unecount)s;"
                                " should be equal to number of groups %(groupcount)s.\n"
                            )
                            % {"unecount": unecount, "groupcount": groupcount}
                        )
                except Exception:
                    self.add2errorlist(
                        _('[E09]: Groupcount in UNE is invalid: "%(count)s".\n')
                        % {"count": unecount}
                    )
                for nodeunh in nodeung.getloop({"BOTSID": "UNG"}, {"BOTSID": "UNH"}):
                    unhreference = nodeunh.get({"BOTSID": "UNH", "0062": None})
                    untreference = nodeunh.get({"BOTSID": "UNH"}, {"BOTSID": "UNT", "0062": None})
                    if unhreference and untreference and unhreference != untreference:
                        self.add2errorlist(
                            _(
                                '[E10]: UNH-reference is "%(unhreference)s";'
                                ' should be equal to UNT-reference "%(untreference)s".\n'
                            )
                            % {"unhreference": unhreference, "untreference": untreference}
                        )
                    untcount = nodeunh.get({"BOTSID": "UNH"}, {"BOTSID": "UNT", "0074": None})
                    segmentcount = nodeunh.getcount()
                    try:
                        if int(untcount) != segmentcount:
                            self.add2errorlist(
                                _(
                                    "[E11]: Segmentcount in UNT is %(untcount)s;"
                                    " should be equal to number of segments %(segmentcount)s.\n"
                                )
                                % {"untcount": untcount, "segmentcount": segmentcount}
                            )
                    except Exception:
                        self.add2errorlist(
                            _('[E12]: Count of segments in UNT is invalid: "%(count)s".\n')
                            % {"count": untcount}
                        )
            logger.debug("Parsing edifact envelopes is OK")

    def handleconfirm(self, ta_fromfile, routedict, error):
        """Done at end of EDIFACT file handling (generates CONTRL messages — or not)."""
        # pylint: disable=too-many-locals
        # for fatal errors there is no decent node tree
        if self.errorfatal:
            return

    def try_to_retrieve_info(self) -> None:
        """
        When edi-file is not correct, (try to) get info about eg partnerID's in message.
        For now: look around in lexed record.
        """
        if not hasattr(self, "lex_records"):
            return
        for lex_record in self.lex_records:
            if lex_record[0][VALUE] == "UNB":
                count_fields = 0
                for field in lex_record:
                    if not field[SFIELD]:
                        # if field (not subfield etc)
                        count_fields += 1
                        if count_fields == 3:
                            self.ta_info["frompartner"] = field[VALUE]
                        elif count_fields == 4:
                            self.ta_info["topartner"] = field[VALUE]
                        elif count_fields == 6:
                            self.ta_info["reference"] = field[VALUE]
                            return
                return

    def set_syntax_used(self) -> None:
        for key in ["record_sep", "field_sep", "sfield_sep", "reserve", "escape"]:
            self.syntax[key] = self.ta_info[key]


# ---------------------------------------------------------------------------
# EDIFACT Writer
# ---------------------------------------------------------------------------


class edifact_writer(Outmessage):
    """Outgoing EDIFACT message serialiser."""

    def _getescapechars(self) -> str:
        terug = (
            self.ta_info["record_sep"]
            + self.ta_info["field_sep"]
            + self.ta_info["sfield_sep"]
            + self.ta_info["escape"]
        )
        if self.ta_info["version"] >= "4":
            terug += self.ta_info["reserve"]
        return terug

    def _manipulatemessagetype(self, messagetype: str, inode: AstNode) -> str:
        return messagetype.replace(".", "_")
