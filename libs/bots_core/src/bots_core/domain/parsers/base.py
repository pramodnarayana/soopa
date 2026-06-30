"""
parsers/base.py — Abstract variable-length EDI lexer.

Contains the ``var`` class, which provides the ``_lex`` and ``_parsefields``
methods shared by all variable-length EDI formats (EDIFACT, X12).
Extracted from the monolithic inmessage.py.
"""
# pylint: disable=invalid-name, missing-function-docstring, too-many-branches
# pylint: disable=too-many-statements, attribute-defined-outside-init
# pylint: disable=broad-exception-caught

import logging

from bots_core.domain.exceptions import InMessageError
from bots_core.domain.inmessage import Inmessage
from bots_core.infrastructure.config.botsconfig import (
    LIN,
    POS,
    SFIELD,
    VALUE,
)
from bots_core.utils.botslib import gettext as _

logger = logging.getLogger(__name__)


class var(Inmessage):
    """Abstract class for EDI objects with records of variable length."""

    def _lex(self):
        """
        Lex file with variable records to list of lex_records,
        fields and subfields (build self.lex_records).
        """
        # pylint: disable=too-many-locals, line-too-long
        # flake8: noqa:E501
        record_sep = self.ta_info["record_sep"]
        mode_inrecord = 0  # 1 indicates: lexing in record, 0 is lexing 'between records'.
        field_sep = (
            self.ta_info["field_sep"] + self.ta_info["record_tag_sep"]
        )  # for tradacoms; field_sep and record_tag_sep have same function.
        sfield_sep = self.ta_info["sfield_sep"]
        rep_sep = self.ta_info["reserve"]
        strict_syntax_check = self.ta_info["strict_syntax_check"]
        sfield = 0  # 1: subfield, 0: not a subfield, 2:repeat
        quote_char = self.ta_info[
            "quote_char"
        ]  # typical for csv. example with quote_char ":  ,"1523",TEXT,"123",
        mode_quote = 0  # 0=not in quote, 1=in quote
        mode_2quote = 0  # status within mode_quote. 0=just another char within quote, 1=met 2nd quote char; might be end of quote OR escaping of another quote-char.
        escape = self.ta_info["escape"]  # char after escape-char is not interpreted as separator
        mode_escape = 0  # 0=not escaping, 1=escaping
        skip_char = self.ta_info[
            "skip_char"
        ]  # chars to ignore/skip/discard. eg edifact: if wrapped to 80pos lines and <CR/LF> at end of segment
        lex_record = []  # gather the content of a record
        value = ""  # gather the content of (sub)field; the current token
        valueline = 1  # record line of token
        valuepos = 1  # record position of token in line
        countline = 1  # count number of lines; start with 1
        countpos = 0  # count position/number of chars within line
        sep = field_sep + sfield_sep + record_sep + escape + rep_sep

        for char in self.rawinput:
            # get next char
            if char == "\n":
                # count number lines/position; no action.
                countline += 1  # count line
                countpos = 0  # position back to 0
            else:
                countpos += 1  # position within line
            if mode_quote:
                # lexing within a quote; note that quote-char works as escape-char within a quote
                if mode_2quote:
                    mode_2quote = 0
                    if char == quote_char:
                        # after quote-char another quote-char: used to escape quote_char:
                        # append quote_char
                        value += char
                        continue
                    # quote is ended:
                    mode_quote = 0
                    # continue parsing of this char
                elif mode_escape:
                    # tricky: escaping a quote char
                    mode_escape = 0
                    value += char
                    continue
                elif char == quote_char:
                    # either end-quote or escaping quote_char, we do not know yet
                    mode_2quote = 1
                    continue
                elif char == escape:
                    mode_escape = 1
                    continue
                else:
                    # we are in quote, just append char to token
                    value += char
                    continue
            if char in skip_char:
                # char is skipped. In csv these chars could be in a quote;
                # in eg edifact chars will be skipped, even if after escape sign.
                continue
            if not mode_inrecord:
                # get here after record-separator is found. we are 'between' records.
                # some special handling for whitespace characters; for other chars: go on lexing
                if char.isspace():
                    if strict_syntax_check:
                        # for strict checks: no spaces between records
                        raise InMessageError(
                            _(
                                "[A67]: Found space characters between segments."
                                " Line %(countline)s, position %(pos)s, position %(countpos)s."
                            ),
                            {"countline": countline, "countpos": countpos},
                        )
                    else:
                        # ignore whitespace character; continue for-loop with next character
                        continue
                # not whitespace - a new record has started
                mode_inrecord = 1
            if mode_escape:
                # in escaped_mode: char after escape sign is appended to token
                mode_escape = 0
                value += char
                continue
            if not value:
                # no char in token: this is a new token, get line and pos for (new) token
                valueline = countline
                valuepos = countpos
            if char == quote_char and (not value or value.isspace()):
                # for csv: handle new quote value. New quote value only makes sense
                # for new field (value is empty) or field contains only whitespace
                mode_quote = 1
                continue
            if char not in sep:
                # just a char: append char to value
                value += char
                continue
            if char in field_sep:
                # end of (sub)field. Note: first field of composite is marked as 'field'
                # write current value to lex_record
                lex_record.append({VALUE: value, SFIELD: sfield, LIN: valueline, POS: valuepos})
                value = ""
                sfield = 0  # new token is field
                continue
            if char == sfield_sep:
                # end of (sub)field. Note: first field of composite is marked as 'field'
                # write current value to lex_record
                lex_record.append({VALUE: value, SFIELD: sfield, LIN: valueline, POS: valuepos})
                value = ""
                sfield = 1  # new token is sub-field
                continue
            if char in record_sep:  # end of record
                if strict_syntax_check and not lex_record:
                    # check for 'double' record separator.
                    raise InMessageError(
                        _(
                            "[A69]: Found double record seperator. Line %(countline)s,"
                            " position %(pos)s, position %(countpos)s."
                        ),
                        {"countline": countline, "countpos": countpos},
                    )
                # write current value to lex_record
                lex_record.append({VALUE: value, SFIELD: sfield, LIN: valueline, POS: valuepos})
                # write lex_record to self.lex_records
                self.lex_records.append(lex_record)
                lex_record = []
                value = ""
                # new token is field
                sfield = 0
                # we are not in a record
                mode_inrecord = 0
                continue
            if char == escape:
                mode_escape = 1
                continue
            if char == rep_sep:
                # write current value to lex_record
                lex_record.append({VALUE: value, SFIELD: sfield, LIN: valueline, POS: valuepos})
                value = ""
                # new token is repeating
                sfield = 2
                continue
        # end of for-loop. all characters have been processed.

        # in a perfect world, value should always be empty now, but:
        # it appears a csv record is not always closed properly,
        # so force the closing of the last record of csv file:
        if mode_inrecord and self.ta_info.get("allow_lastrecordnotclosedproperly", False):
            # append element in record
            lex_record.append({VALUE: value, SFIELD: sfield, LIN: valueline, POS: valuepos})
            self.lex_records.append(lex_record)
        else:
            leftover = value.strip("\x00\x1a")
            if leftover:
                raise InMessageError(
                    _(
                        "[A51]: Found non-valid data at end of edi file;"
                        ' probably a problem with separators or message structure: "%(leftover)s".'
                    ),
                    {"leftover": leftover},
                )

    def _parsefields(self, lex_record, record_definition) -> dict:
        """
        Identify the fields in inmessage-record using the record_definition from the grammar.
        Build a record (dictionary; field-IDs are unique within record) and return this.
        """
        list_of_fields_in_record_definition = record_definition.fields
        # record that is built from lex_record using ID's from record_definition
        record2build = {}
        tindex = -1
        # elementcounter; composites count as one
        # This init is for error (field is lexed as subfield but is not.)
        # 20130222: catch UnboundLocalError now

        # loop over all fields present in this record of edi file
        # identify the lexed fields in grammar, and build a dict with (fieldID:value)
        for lex_field in lex_record:
            value = lex_field[VALUE].strip() if self.ta_info["strip_value"] else lex_field[VALUE][:]
            # use info of lexer: what is preceding separator (field, sub-field, repeat)
            if not lex_field[SFIELD]:
                # preceded by field-separator
                try:
                    # use next field
                    tindex += 1
                    field_definition = list_of_fields_in_record_definition[tindex]
                except IndexError:
                    self.add2errorlist(
                        _(
                            '[F19] line %(line)s pos %(pos)s: Record "%(record)s"'
                            " too many fields in record;"
                            ' unknown field "%(content)s".\n'
                        )
                        % {
                            "content": lex_field[VALUE],
                            "line": lex_field[LIN],
                            "pos": lex_field[POS],
                            "record": self.mpathformat(record_definition.mpath),
                        }
                    )
                    continue
                if field_definition.max_repeat == 1:
                    # definition says: not repeating
                    if field_definition.is_field:
                        # definition says: field       +E+
                        if value:
                            record2build[field_definition.id] = value
                    else:
                        # definition says: subfield    +E:S+
                        tsubindex = 0
                        list_of_subfields_in_record_definition = (
                            list_of_fields_in_record_definition[tindex].subfields
                        )
                        sub_field_in_record_definition = list_of_subfields_in_record_definition[
                            tsubindex
                        ]
                        if value:
                            record2build[sub_field_in_record_definition.id] = value
                else:
                    # definition says: repeating
                    if field_definition.is_field:
                        # definition says: field      +E*R+
                        record2build[field_definition.id] = [value]
                    else:
                        # definition says: subfield   +E:S*R:S+
                        tsubindex = 0
                        list_of_subfields_in_record_definition = (
                            list_of_fields_in_record_definition[tindex].subfields
                        )
                        sub_field_in_record_definition = list_of_subfields_in_record_definition[
                            tsubindex
                        ]
                        record2build[field_definition.id] = [
                            {sub_field_in_record_definition.id: value}
                        ]
            elif lex_field[SFIELD] == 1:
                # preceded by sub-field separator
                try:
                    tsubindex += 1
                    sub_field_in_record_definition = list_of_subfields_in_record_definition[
                        tsubindex
                    ]
                except (TypeError, UnboundLocalError):
                    # field has no SUBFIELDS, or unexpected subfield
                    self.add2errorlist(
                        _(
                            '[F17] line %(line)s pos %(pos)s: Record "%(record)s"'
                            ' expect field but "%(content)s" is a subfield.\n'
                        )
                        % {
                            "content": lex_field[VALUE],
                            "line": lex_field[LIN],
                            "pos": lex_field[POS],
                            "record": self.mpathformat(record_definition.mpath),
                        }
                    )
                    continue
                except IndexError:
                    # tsubindex is not in the subfields
                    self.add2errorlist(
                        _(
                            '[F18] line %(line)s pos %(pos)s: Record "%(record)s"'
                            " too many subfields in composite;"
                            ' unknown subfield "%(content)s".\n'
                        )
                        % {
                            "content": lex_field[VALUE],
                            "line": lex_field[LIN],
                            "pos": lex_field[POS],
                            "record": self.mpathformat(record_definition.mpath),
                        }
                    )
                    continue
                if field_definition.max_repeat == 1:
                    # definition says: not repeating   +E:S+
                    if value:
                        record2build[sub_field_in_record_definition.id] = value
                else:
                    # definition says: repeating       +E:S*R:S+
                    record2build[field_definition.id][-1][sub_field_in_record_definition.id] = value
            else:
                # preceded by repeat separator
                # check if repeating!
                if field_definition.max_repeat == 1:
                    if (
                        self.mpathformat(record_definition.mpath) == "ISA"
                        and field_definition.id == "ISA11"
                    ):
                        # exception for ISA
                        pass
                    else:
                        self.add2errorlist(
                            _(
                                "[F40] line %(line)s pos %(pos)s:"
                                ' Record "%(record)s" expect not-repeating element,'
                                ' but "%(content)s" is repeating.\n'
                            )
                            % {
                                "content": lex_field[VALUE],
                                "line": lex_field[LIN],
                                "pos": lex_field[POS],
                                "record": self.mpathformat(record_definition.mpath),
                            }
                        )
                    continue

                if field_definition.is_field:
                    # definition says: field      +E*R+
                    record2build[field_definition.id].append(value)
                else:
                    # definition says: first subfield   +E:S*R:S+
                    tsubindex = 0
                    list_of_subfields_in_record_definition = list_of_fields_in_record_definition[
                        tindex
                    ].subfields
                    sub_field_in_record_definition = list_of_subfields_in_record_definition[
                        tsubindex
                    ]
                    record2build[field_definition.id].append(
                        {sub_field_in_record_definition.id: value}
                    )
        record2build["BOTSIDnr"] = record_definition.botsidnr
        return record2build

    @staticmethod
    def separatorcheck(separatorstring):
        """Check if separators are 'reasonable'."""
        # test uniqueness
        if len(separatorstring) != len(set(separatorstring)):
            raise InMessageError(
                _("[A64]: Separator problem in edi file: same separator is used twice.")
            )
        # test if a space
        if " " in separatorstring:
            raise InMessageError(
                _("[A65]: Separator problem in edi file: space is used as separator.")
            )
        # check if separators are alfanumeric
        for sep in separatorstring:
            if sep.isalnum():
                raise InMessageError(
                    _("[A66]: Separator problem in edi file: separator is alfanumeric.")
                )
