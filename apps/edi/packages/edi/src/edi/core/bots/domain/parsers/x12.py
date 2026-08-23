# type: ignore
"""
parsers/x12.py — X12 reader and writer.

Contains:
  - ``x12``: incoming X12 parser  (formerly class x12(var) in inmessage.py)
  - ``x12_writer``: outgoing X12 serialiser  (formerly class x12(Outmessage) in outmessage.py)

Both are registered in parsers/__init__.py and injected into the dispatchers
in inmessage.py / outmessage.py via READER_REGISTRY / WRITER_REGISTRY.
"""
# pylint: disable=invalid-name, missing-function-docstring, too-many-branches
# pylint: disable=too-many-statements, attribute-defined-outside-init

import structlog

from edi.core.bots.config.botsconfig import VALUE
from edi.core.bots.domain.exceptions import InMessageError
from edi.core.bots.domain.outmessage import Outmessage
from edi.core.bots.utils.botslib import gettext as _

from .base import var

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# X12 Reader
# ---------------------------------------------------------------------------


class x12(var):
    """Class for X12 incoming message objects."""

    def _parsefields(self, lex_record, record_definition) -> dict:
        """Parse fields from one variable message-record. ISA gets special no-strip treatment."""
        if record_definition.id != "ISA":
            return super()._parsefields(lex_record, record_definition)
        # x12 ISA is an exception: no strip()
        strip_value = self.ta_info["strip_value"]
        self.ta_info["strip_value"] = False
        try:
            record2build = super()._parsefields(lex_record, record_definition)
            return record2build
        finally:
            self.ta_info["strip_value"] = strip_value

    def _manipulatemessagetype(self, messagetype, inode):
        """X12 also needs the GS08 field to identify the correct messagetype (e.g. 850 + 004010)."""
        version = inode.record.get("GS08", "")
        if not version:
            isa_version = self.ta_info.get("version", "")
            if len(isa_version) == 5:  # noqa: SIM108
                version = isa_version + "0"
            else:
                version = isa_version
        return messagetype + version

    def _sniff(self):  # noqa: C901
        """
        Examine a file for X12 syntax parameters and correctness of protocol.
        Parse ISA, get charset and version.
        """
        count = 0
        version = ""
        recordID = ""
        rawinput = self.rawinput[:200].lstrip()
        for char in rawinput:
            if char in "\r\n" and count != 105:  # pos 105: is record_sep, could be \r\n
                continue
            count += 1
            if count <= 3:
                recordID += char
            elif count == 4:
                self.ta_info["field_sep"] = char
                if recordID != "ISA":
                    # not with mailbag
                    raise InMessageError(
                        _('[A60]: Expect "ISA", found "%(content)s". Probably no x12?'),
                        {"content": self.rawinput[:7]},
                    )
            elif count in [7, 18, 21, 32, 35, 51, 54, 70]:  # extra checks for fixed ISA.
                if char != self.ta_info["field_sep"]:
                    raise InMessageError(
                        _(
                            "[A63]: Non-valid ISA header;"
                            ' position %(pos)s of ISA is "%(foundchar)s",'
                            ' expect here element separator "%(field_sep)s".'
                        ),
                        {
                            "pos": str(count),
                            "foundchar": char,
                            "field_sep": self.ta_info["field_sep"],
                        },
                    )
            elif count == 83:
                self.ta_info["reserve"] = char
            elif count < 85:
                continue
            elif count <= 89:
                version += char
            elif count == 105:
                self.ta_info["sfield_sep"] = char
            elif count == 106:
                self.ta_info["record_sep"] = char
                break
        else:
            # if arrive here: did not reach count == 106.
            if count == 0:
                # not with mailbag
                raise InMessageError(_("[A61]: Edi file contains only whitespace."))
            raise InMessageError(_("[A62]: Expect X12 file but envelope is not right."))
        # Note: reserve=repeating separator.
        # Since ISA version 00403 used as repeat sep.
        # Some partners use ISA version above 00403 but do not use repeats.
        # Then this char is eg 'U' (as in older ISA versions).
        # This wrong usage is caught by checking if the char is alphanumeric;
        # if so assume wrong usage (and do not use repeat sep.)
        if version < "00403":
            self.ta_info["reserve"] = ""
        elif self.ta_info["reserve"].isalnum() and not self.ta_info["strict_syntax_check"]:
            # if version >= '00403' and repetition separator is alphanum
            # and no strict checking: assume mistake.
            # If strict checking: error is caught in separatorcheck.
            self.ta_info["reserve"] = ""

        # if <CR> is segment terminator: cannot be in the skip_char-string!
        self.ta_info["skip_char"] = self.ta_info["skip_char"].replace(
            self.ta_info["record_sep"], ""
        )
        # extra checks for separators
        self.separatorcheck(
            self.ta_info["sfield_sep"]
            + self.ta_info["field_sep"]
            + self.ta_info["reserve"]
            + self.ta_info["record_sep"]
        )

    def checkenvelope(self):  # noqa: C901
        """Check X12 envelopes and gather information to generate 997."""
        # pylint: disable=too-many-locals
        for nodeisa in self.getloop({"BOTSID": "ISA"}):
            logger.debug("Start parsing X12 envelopes")
            isareference = nodeisa.get({"BOTSID": "ISA", "ISA13": None})
            ieareference = nodeisa.get({"BOTSID": "ISA"}, {"BOTSID": "IEA", "IEA02": None})
            if isareference and ieareference and isareference != ieareference:
                self.add2errorlist(
                    _(
                        '[E13]: ISA-reference is "%(isareference)s";'
                        ' should be equal to IEA-reference "%(ieareference)s".\n'
                    )
                    % {"isareference": isareference, "ieareference": ieareference}
                )
            ieacount = nodeisa.get({"BOTSID": "ISA"}, {"BOTSID": "IEA", "IEA01": None})
            groupcount = nodeisa.getcountoccurrences({"BOTSID": "ISA"}, {"BOTSID": "GS"})
            try:
                if int(ieacount) != groupcount:
                    self.add2errorlist(
                        _(
                            "[E14]: Count in IEA-IEA01 is %(ieacount)s;"
                            " should be equal to number of groups %(groupcount)s.\n"
                        )
                        % {"ieacount": ieacount, "groupcount": groupcount}
                    )
            except Exception:  # noqa: BLE001
                self.add2errorlist(
                    _('[E15]: Count of messages in IEA is invalid: "%(count)s".\n')
                    % {"count": ieacount}
                )
            for nodegs in nodeisa.getloop({"BOTSID": "ISA"}, {"BOTSID": "GS"}):
                gsreference = nodegs.get({"BOTSID": "GS", "GS06": None})
                gereference = nodegs.get({"BOTSID": "GS"}, {"BOTSID": "GE", "GE02": None})
                if gsreference and gereference and gsreference != gereference:
                    self.add2errorlist(
                        _(
                            '[E16]: GS-reference is "%(gsreference)s";'
                            ' should be equal to GE-reference "%(gereference)s".\n'
                        )
                        % {"gsreference": gsreference, "gereference": gereference}
                    )
                gecount = nodegs.get({"BOTSID": "GS"}, {"BOTSID": "GE", "GE01": None})
                messagecount = len(nodegs.children) - 1
                try:
                    if int(gecount) != messagecount:
                        self.add2errorlist(
                            _(
                                "[E17]: Count in GE-GE01 is %(gecount)s;"
                                " should be equal to number of transactions: %(messagecount)s.\n"
                            )
                            % {"gecount": gecount, "messagecount": messagecount}
                        )
                except Exception:  # noqa: BLE001
                    self.add2errorlist(
                        _('[E18]: Count of messages in GE is invalid: "%(count)s".\n')
                        % {"count": gecount}
                    )
                for nodest in nodegs.getloop({"BOTSID": "GS"}, {"BOTSID": "ST"}):
                    streference = nodest.get({"BOTSID": "ST", "ST02": None})
                    sereference = nodest.get({"BOTSID": "ST"}, {"BOTSID": "SE", "SE02": None})
                    # referencefields are numerical; should I compare values??
                    if streference and sereference and streference != sereference:
                        self.add2errorlist(
                            _(
                                '[E19]: ST-reference is "%(streference)s";'
                                ' should be equal to SE-reference "%(sereference)s".\n'
                            )
                            % {"streference": streference, "sereference": sereference}
                        )
                    secount = nodest.get({"BOTSID": "ST"}, {"BOTSID": "SE", "SE01": None})
                    segmentcount = nodest.getcount()
                    try:
                        if int(secount) != segmentcount:
                            self.add2errorlist(
                                _(
                                    "[E20]: Count in SE-SE01 is %(secount)s;"
                                    " should be equal to number of segments %(segmentcount)s.\n"
                                )
                                % {"secount": secount, "segmentcount": segmentcount}
                            )
                    except Exception:  # noqa: BLE001
                        self.add2errorlist(
                            _('[E21]: Count of segments in SE is invalid: "%(count)s".\n')
                            % {"count": secount}
                        )
            logger.debug("Parsing X12 envelopes is OK")

    def try_to_retrieve_info(self):
        """
        When edi-file is not correct, (try to) get info about eg partnerID's in message.
        For now: look around in lexed record.
        """
        if not hasattr(self, "lex_records"):
            return
        for lex_record in self.lex_records:
            if lex_record[0][VALUE] == "ISA":
                count_fields = 0
                for field in lex_record:
                    count_fields += 1  # noqa: SIM113
                    if count_fields == 7:
                        self.ta_info["frompartner"] = field[VALUE]
                    elif count_fields == 9:
                        self.ta_info["topartner"] = field[VALUE]
                    elif count_fields == 14:
                        self.ta_info["reference"] = field[VALUE]
                        return
                return

    def set_syntax_used(self):
        for key in ["record_sep", "field_sep", "sfield_sep", "reserve"]:
            self.syntax[key] = self.ta_info[key]


# ---------------------------------------------------------------------------
# X12 Writer
# ---------------------------------------------------------------------------


class x12_writer(Outmessage):
    """Outgoing X12 message serialiser."""

    def _getescapechars(self):
        terug = self.ta_info["record_sep"] + self.ta_info["field_sep"] + self.ta_info["sfield_sep"]
        if self.ta_info["version"] >= "00403":
            terug += self.ta_info["reserve"]
        return terug

    def _manipulatemessagetype(self, messagetype, inode):
        """X12 needs version to identify correct messagetype (e.g. 850 + 004010)."""
        version = inode.record.get("GS08", "")
        if not version:
            isa_version = self.ta_info.get("version", "")
            if len(isa_version) == 5:  # noqa: SIM108
                version = isa_version + "0"
            else:
                version = isa_version
        return messagetype + version
