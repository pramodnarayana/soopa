"""
Bots outmessage lib
"""
# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, duplicate-code, too-many-lines
# pylint: disable=too-many-branches, too-many-statements, attribute-defined-outside-init, consider-using-f-string

import decimal

# bots-modules
import logging
import time

from bots_core.domain import grammar, message, node
from bots_core.domain.exceptions import BotsImportError, OutMessageError

logger = logging.getLogger(__name__)
from bots_core.infrastructure.config.botsconfig import (
    FORMATFROMGRAMMAR,
    SFIELD,
    VALUE,
)
from bots_core.utils import botslib
from bots_core.utils.botslib import gettext as _

NODECIMAL = decimal.Decimal(1)


def outmessage_init(**ta_info):
    """
    Dispatch function for Outmessage subclasses.
    ta_info: needed is editype, messagetype, filename, charset, merge
    """
    # Deferred import to avoid circular dependency:
    # outmessage <- parsers.edifact/x12 <- outmessage
    from bots_core.domain.parsers import WRITER_REGISTRY  # noqa: PLC0415

    try:
        classtocall = WRITER_REGISTRY[ta_info["editype"]]
    except KeyError as exc:
        raise OutMessageError(
            _("Unknown editype for outgoing message: %(editype)s"), ta_info
        ) from exc
    return classtocall(ta_info)


class Outmessage(message.Message):
    """
    abstract class; represents a outgoing edi message.
    subclassing is necessary for the editype (csv, edi, x12, etc)
    A tree of nodes is build form the mpaths received from put()or putloop().
    tree starts at self.root.
    Put() recieves mpaths from mappingscript
    The next algorithm is used to 'map' a mpath into the tree:
        For each part of a mpath: search node in 'current' level of tree
            If part already as a node:
                recursively search node-children
            If part not as a node:
                append new node to tree;
                recursively append next parts to tree
    After the mappingscript is finished, the resulting tree is converted to self.lex_records.
    These lex_records are written to file.
    """

    # pylint: disable=attribute-defined-outside-init

    def __init__(self, ta_info):
        super().__init__(ta_info)
        # message tree; build via put()-interface in mappingscript. Initialise with empty dict
        self.root = node.Node(record={})
        self.envelope_content = [{}, {}, {}, {}]

    def messagegrammarread(self, typeofgrammarfile):
        """
        read grammar for a message/envelope.
        (try to) read the topartner dependent grammar syntax.
        """
        # read grammar for message.
        self.defmessage = grammar.grammarread(
            self.ta_info["editype"], self.ta_info["messagetype"], typeofgrammarfile
        )

        # read partner-syntax. Use this to always overrule values in self.ta_info
        if self.ta_info.get("frompartner"):
            try:
                partnersyntax = grammar.grammarread(
                    self.ta_info["editype"],
                    self.ta_info["frompartner"],
                    typeofgrammarfile="partners",
                )
                # partner syntax overrules!
                self.defmessage.syntax.update(partnersyntax.syntax)
                logger.debug(
                    'Partner syntax imported "%(filename)s".', partnersyntax.module.__file__
                )

            except BotsImportError:
                # No partner specific syntax found (is not an error).
                pass

        if self.ta_info.get("topartner"):
            try:
                partnersyntax = grammar.grammarread(
                    self.ta_info["editype"], self.ta_info["topartner"], typeofgrammarfile="partners"
                )
                # partner syntax overrules!
                self.defmessage.syntax.update(partnersyntax.syntax)
                logger.debug(
                    'Partner syntax imported "%(filename)s".', partnersyntax.module.__file__
                )

            except BotsImportError:
                # No partner specific syntax found (is not an error).
                pass

        # write values from grammar syntax to self.ta_info
        # unless these values are already set (eg by mappingscript)
        botslib.updateunlessset(self.ta_info, self.defmessage.syntax)
        self.ta_info.update(self.syntax)

    def writeall(self):
        """
        writeall is called for writing all 'real' outmessage objects; but not for envelopes.
        writeall is call from transform.translate()
        """
        self.messagegrammarread(typeofgrammarfile="grammars")
        self.checkmessage(self.root, self.defmessage)
        self.checkforerrorlist()
        self.nrmessagewritten = 0
        if self.root.record:
            # root record contains information; write whole tree in one time
            self.multiplewrite = False
            self._initwrite()
            self._write(self.root)
            self.nrmessagewritten = 1
            self.ta_info["nrmessages"] = self.nrmessagewritten
            self._closewrite()
        elif not self.root.children:
            # then there is nothing to write...
            raise OutMessageError(_("No outgoing message"))
        else:
            self.multiplewrite = True
            self._initwrite()
            for childnode in self.root.children:
                self._write(childnode)
                self.nrmessagewritten += 1
            # 'write back' the number of messages.
            # Tricky thing here is that sometimes such a structure is indeed one message:
            #   eg csv without BOTS iD.
            # in general: when only one type of record in recorddefs
            # (mind: for xml this is not useful) no not writeback the count as nrofmessages
            # for now: always write back unless csv of fixed.
            self.ta_info["nrmessages"] = self.nrmessagewritten
            self._closewrite()

    def _initwrite(self):
        logger.debug('Start writing to file "%(filename)s".', self.ta_info)
        self._outstream = botslib.opendata(
            self.ta_info["filename"],
            "w",
            charset=self.ta_info["charset"],
            errors=self.ta_info["checkcharsetout"],
        )

    def _closewrite(self):
        logger.debug('End writing to file "%(filename)s".', self.ta_info)
        self._outstream.close()

    def _write(self, node_instance):
        """
        the write method for most classes.
        tree is serialised to lex_records;
        lex_records are written to file.
        Classses that write using other libraries (xml, json, template, db)
        use specific write methods.
        """
        self.tree2records(node_instance)
        value = self.record2string(self.lex_records)
        wrap_length = int(self.ta_info.get("wrap_length", 0))
        if wrap_length:
            try:
                for i in range(0, len(value), wrap_length):
                    # split in fixed lengths
                    self._outstream.write(value[i : i + wrap_length] + "\r\n")
            except UnicodeError as exc:
                content = botslib.get_relevant_text_for_UnicodeError(exc)
                raise OutMessageError(
                    _('[F50]: Characters not in character-set "%(char)s": %(content)s'),
                    {"char": self.ta_info["charset"], "content": content},
                ) from exc
        else:
            try:
                self._outstream.write(value)
            except UnicodeError as exc:
                content = botslib.get_relevant_text_for_UnicodeError(exc)
                raise OutMessageError(
                    _('[F50]: Characters not in character-set "%(char)s": %(content)s'),
                    {"char": self.ta_info["charset"], "content": content},
                ) from exc

    def tree2records(self, node_instance):
        self.lex_records = []  # tree of nodes is flattened to these lex_records
        self._tree2recordscore(node_instance, self.defmessage.structure[0])

    def _tree2recordscore(self, node_instance, structure):
        """
        Write tree of nodes to flat lex_records.
        The nodes are already sorted
        """
        # write node->lex_record
        self._tree2recordfields(node_instance.record, structure)
        for childnode in node_instance.children:
            # speed up: use local var
            botsid_childnode = childnode.record["BOTSID"].strip()
            # speed up: use local var
            botsidnr_childnode = childnode.record["BOTSIDnr"]
            # for structure_record of this level in grammar
            for structure_record in structure.level:
                # check if it is the right node
                if (
                    botsid_childnode == structure_record.id
                    and botsidnr_childnode == structure_record.botsidnr
                ):
                    # check if it triggers a subtranslation
                    if structure_record.subtranslation:
                        messagetype = childnode.enhancedget(structure_record.subtranslation)
                        if not messagetype:
                            raise OutMessageError(
                                _('Could not find SUBTRANSLATION "%(sub)s" in (sub)message.'),
                                {"sub": structure_record.subtranslation},
                            )
                        # Ensure we get a string messagetype
                        if isinstance(messagetype, (dict, list)):
                            pass  # enhancedget might return complex types if misconfigured, assume simple string

                        messagetype = self._manipulatemessagetype(messagetype, node_instance)

                        # Load the subgrammar dynamically
                        try:
                            subdefmessage = grammar.grammarread(
                                self.ta_info["editype"], messagetype, typeofgrammarfile="grammars"
                            )
                            # use rest of index in deeper level for subgrammar
                            self._tree2recordscore(childnode, subdefmessage.structure[0])
                        except BotsImportError as exc:
                            raise OutMessageError(
                                _(
                                    'No (valid) grammar for editype "%(editype)s"'
                                    ' messagetype "%(messagetype)s".'
                                ),
                                {"editype": self.ta_info["editype"], "messagetype": messagetype},
                            ) from exc
                    else:
                        # use rest of index in deeper level
                        self._tree2recordscore(childnode, structure_record)
                    # childnode was found and used; break to go to next child node
                    break

    def _tree2recordfields(self, noderecord, structure_record):
        """
        from noderecord->lex_record; use structure_record as guide.
        complex because is is used for: editypes that have compression rules (edifact),
        var editypes without compression, fixed protocols
        """
        # pylint: disable=too-many-nested-blocks
        # the record build; list (=record) of dicts (=fields).
        lex_record = []
        recordbuffer = []
        # loop all fields in grammar-definition
        for field_definition in structure_record.fields:
            if field_definition.is_field:
                # field (no composite)
                if field_definition.max_repeat == 1:
                    # non-repeating
                    field_has_data = False
                    if field_definition.id in noderecord and noderecord[field_definition.id]:
                        # field exists in outgoing message and has data
                        field_has_data = True
                        recordbuffer.append(
                            {
                                VALUE: noderecord[field_definition.id],
                                SFIELD: 0,
                                FORMATFROMGRAMMAR: field_definition.format,
                            }
                        )
                    elif self.ta_info["stripfield_sep"]:
                        # no data and field not needed: write new empty field to recordbuffer;
                        recordbuffer.append(
                            {VALUE: "", SFIELD: 0, FORMATFROMGRAMMAR: field_definition.format}
                        )
                    else:
                        # no data but field is needed: initialise empty field.
                        # For eg fixed and csv: all fields have to be present
                        field_has_data = True
                        value = self._initfield(field_definition)
                        recordbuffer.append(
                            {VALUE: value, SFIELD: 0, FORMATFROMGRAMMAR: field_definition.format}
                        )
                    if field_has_data:
                        # write recordbuffer to lex_record
                        lex_record += recordbuffer
                        # clear recordbuffer
                        recordbuffer = []
                else:
                    # repeating field
                    field_has_data = False
                    if field_definition.id in noderecord:
                        # field exists in outgoing message
                        # first field in repeat is marked as a field (not as repeat).
                        type_of_field = 0
                        # buffer for this repeating field.
                        fieldbuffer = []
                        for field in noderecord[field_definition.id]:
                            if field:
                                field_has_data = True
                                fieldbuffer.append(
                                    {
                                        VALUE: field,
                                        SFIELD: type_of_field,
                                        FORMATFROMGRAMMAR: field_definition.format,
                                    }
                                )
                                recordbuffer += fieldbuffer
                                fieldbuffer = []
                            else:
                                fieldbuffer.append(
                                    {
                                        VALUE: "",
                                        SFIELD: type_of_field,
                                        FORMATFROMGRAMMAR: field_definition.format,
                                    }
                                )
                            # mark rest of repeats as repeat.
                            type_of_field = 2
                    if field_has_data:
                        # write recordbuffer to lex_record
                        lex_record += recordbuffer
                        # clear recordbuffer
                        recordbuffer = []
                    else:
                        recordbuffer.append(
                            {VALUE: "", SFIELD: 0, FORMATFROMGRAMMAR: field_definition.format}
                        )
            else:
                # composite
                if field_definition.max_repeat == 1:
                    # if non-repeating
                    field_has_data = False
                    # first subfield in composite is marked as a field (not a subfield).
                    type_of_field = 0
                    # buffer for this composite.
                    fieldbuffer = []
                    for grammarsubfield in field_definition.subfields:
                        # loop subfields
                        if grammarsubfield.id in noderecord and noderecord[grammarsubfield.id]:
                            # field exists in outgoing message and has data
                            field_has_data = True
                            # append field
                            fieldbuffer.append(
                                {
                                    VALUE: noderecord[grammarsubfield.id],
                                    SFIELD: type_of_field,
                                    FORMATFROMGRAMMAR: grammarsubfield.format,
                                }
                            )
                            recordbuffer += fieldbuffer
                            fieldbuffer = []
                        else:
                            # append new empty to buffer;
                            fieldbuffer.append(
                                {
                                    VALUE: "",
                                    SFIELD: type_of_field,
                                    FORMATFROMGRAMMAR: grammarsubfield.format,
                                }
                            )
                        type_of_field = 1
                    if field_has_data:
                        # write recordbuffer to lex_record
                        lex_record += recordbuffer
                        # clear recordbuffer
                        recordbuffer = []
                    else:
                        # composite has no data: write empty field
                        recordbuffer.append(
                            {VALUE: "", SFIELD: 0, FORMATFROMGRAMMAR: field_definition.format}
                        )
                else:
                    # repeating composite
                    # receive list, including empty members
                    field_has_data = False
                    if field_definition.id in noderecord:
                        # field exists in outgoing message
                        # first subfield in composite is marked as a field (not a subfield).
                        type_of_field = 0
                        # buffer for this composite.
                        fieldbuffer = []
                        for comp_dict in noderecord[field_definition.id]:
                            # comp_dict can be empty
                            composite_has_data = False
                            # buffer for this composite.
                            compositebuffer = []
                            if comp_dict:
                                for grammarsubfield in field_definition.subfields:
                                    # loop subfields
                                    if (
                                        grammarsubfield.id in comp_dict
                                        and comp_dict[grammarsubfield.id]
                                    ):
                                        # field exists in outgoing message and has data
                                        composite_has_data = True
                                        compositebuffer.append(
                                            {
                                                VALUE: comp_dict[grammarsubfield.id],
                                                SFIELD: type_of_field,
                                                FORMATFROMGRAMMAR: grammarsubfield.format,
                                            }
                                        )
                                        fieldbuffer += compositebuffer
                                        compositebuffer = []
                                    else:
                                        compositebuffer.append(
                                            {
                                                VALUE: "",
                                                SFIELD: type_of_field,
                                                FORMATFROMGRAMMAR: grammarsubfield.format,
                                            }
                                        )
                                    type_of_field = 1
                            if composite_has_data:
                                field_has_data = True
                                recordbuffer += fieldbuffer
                                fieldbuffer = []
                            else:
                                fieldbuffer.append(
                                    {
                                        VALUE: "",
                                        SFIELD: type_of_field,
                                        FORMATFROMGRAMMAR: field_definition.format,
                                    }
                                )
                            type_of_field = 2
                    if field_has_data:
                        # write recordbuffer to lex_record
                        lex_record += recordbuffer
                        # clear recordbuffer
                        recordbuffer = []
                    else:
                        # no data: write placeholder to recordbuffer;
                        recordbuffer.append(
                            {VALUE: "", SFIELD: 0, FORMATFROMGRAMMAR: field_definition.format}
                        )

        self.lex_records.append(lex_record)

    def _formatfield(self, value, field_definition, structure_record, node_instance):
        """
        Input: value (normally a string, except for putraw() under JSON) and field definition.
        Some parameters of self.syntax are used, eg decimaal
        Format is checked and converted (if needed).

        :param value:
        :param field_definition:
        :param structure_record:

        :return formatted value:
        """
        # pylint: disable=unused-argument
        if field_definition.bformat == "A":
            # check length fields in variable records
            if len(value) > field_definition.length:
                self.add2errorlist(
                    _(
                        '[F20]: Record "%(record)s" field "%(field)s"'
                        ' too big (max %(max)s): "%(content)s".\n'
                    )
                    % {
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "max": field_definition.length,
                    }
                )
            if len(value) < field_definition.min_length:
                self.add2errorlist(
                    _(
                        '[F21]: Record "%(record)s" field "%(field)s"'
                        ' too small (min %(min)s): "%(content)s".\n'
                    )
                    % {
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                        "min": field_definition.min_length,
                    }
                )
        elif field_definition.bformat == "B":
            # Boolean (json)
            if not isinstance(value, bool):
                self.add2errorlist(
                    _('[F35]: Record "%(record)s" field "%(field)s" is not of type bool.\n')
                    % {
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
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
                            '[F22]: Record "%(record)s" date field "%(field)s"'
                            ' not a valid date: "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
                if lenght > field_definition.length:
                    self.add2errorlist(
                        _(
                            '[F31]: Record "%(record)s" date field "%(field)s"'
                            ' too big (max %(max)s): "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                            "max": field_definition.length,
                        }
                    )
                if lenght < field_definition.min_length:
                    self.add2errorlist(
                        _(
                            '[F32]: Record "%(record)s" date field "%(field)s"'
                            ' too small (min %(min)s): "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                            "min": field_definition.min_length,
                        }
                    )
            else:  # if field_definition.bformat == 'T':
                try:
                    if lenght == 4:
                        time.strptime(value, "%H%M")
                    elif lenght == 6:
                        time.strptime(value, "%H%M%S")
                    else:
                        raise ValueError("To be catched")
                except ValueError:
                    self.add2errorlist(
                        _(
                            '[F23]: Record "%(record)s" time field "%(field)s"'
                            ' not a valid time: "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                        }
                    )
                if lenght > field_definition.length:
                    self.add2errorlist(
                        _(
                            '[F33]: Record "%(record)s" time field "%(field)s"'
                            ' too big (max %(max)s): "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                            "max": field_definition.length,
                        }
                    )
                if lenght < field_definition.min_length:
                    self.add2errorlist(
                        _(
                            '[F34]: Record "%(record)s" time field "%(field)s"'
                            ' too small (min %(min)s): "%(content)s".\n'
                        )
                        % {
                            "record": self.mpathformat(structure_record.mpath),
                            "field": field_definition.id,
                            "content": value,
                            "min": field_definition.min_length,
                        }
                    )
        elif isinstance(value, str):
            # numerics
            # only if text, not when a raw numeric value is given (putraw() json)
            # if value[0] == "-":
            #     minussign = "-"
            #     absvalue = value[1:]
            # else:
            #     minussign = ""
            #     absvalue = value
            # digits, decimalsign, decimals = absvalue.partition(".")
            # if not digits:
            #     digits = "0"
            #     if not decimals:# and decimalsign:
            #         self.add2errorlist(_(
            #              '[F24]: Record "%(record)s" field "%(field)s" '
            #              ' numerical format not valid: "%(content)s".\n') % {
            #              "field": field_definition.id, "content": value,
            #              "record": self.mpathformat(structure_record.mpath)})

            # for some formats (if self.ta_info['lengthnumericbare']=True; eg edifact)
            # length is calculated without decimal sing and/or minus sign.
            lengthcorrection = 0
            if field_definition.bformat == "R":
                if not value:
                    value = "0"
                # floating point: use all decimals received
                try:
                    dec_value = decimal.Decimal(value)
                    if self.ta_info.get("json_write_numericals"):
                        if dec_value == dec_value.to_integral_exact():
                            return int(dec_value)
                        return float(dec_value)
                    value = str(dec_value)
                except decimal.InvalidOperation:
                    self.add2errorlist(
                        _(
                            '[F25]: Record "%(record)s" field "%(field)s"'
                            ' numerical format not valid: "%(content)s".\n'
                        )
                        % {
                            "field": field_definition.id,
                            "content": value,
                            "record": self.mpathformat(structure_record.mpath),
                        }
                    )
                if self.ta_info["lengthnumericbare"]:
                    if value[0] == "-":
                        lengthcorrection += 1
                    if "." in value:
                        lengthcorrection += 1
                if field_definition.format == "RL":
                    # field format is numeric left aligned
                    value = value.ljust(field_definition.min_length + lengthcorrection)
                elif field_definition.format == "RR":
                    # field format is numeric right aligned
                    value = value.rjust(field_definition.min_length + lengthcorrection)
                else:
                    value = value.zfill(field_definition.min_length + lengthcorrection)
                # replace '.' by required decimal sep.
                value = value.replace(".", self.ta_info["decimaal"], 1)
            elif field_definition.bformat == "N":
                if not value:
                    value = "0"
                # fixed decimals; round
                try:
                    dec_value = decimal.Decimal(value)
                    dec_value = dec_value.quantize(
                        decimal.Decimal(f"10e-{field_definition.decimals}")
                    )
                    if self.ta_info.get("json_write_numericals"):
                        if field_definition.decimals == 0:
                            return int(dec_value)
                        return float(dec_value)
                    value = str(dec_value)
                except decimal.InvalidOperation:
                    self.add2errorlist(
                        _(
                            '[F26]: Record "%(record)s" field "%(field)s"'
                            ' numerical format not valid: "%(content)s".\n'
                        )
                        % {
                            "field": field_definition.id,
                            "content": value,
                            "record": self.mpathformat(structure_record.mpath),
                        }
                    )
                if self.ta_info["lengthnumericbare"]:
                    if value[0] == "-":
                        lengthcorrection += 1
                    if field_definition.decimals:
                        lengthcorrection += 1
                if field_definition.format == "NL":
                    # field format is numeric left aligned
                    value = value.ljust(field_definition.min_length + lengthcorrection)
                elif field_definition.format == "NR":
                    # field format is numeric right aligned
                    value = value.rjust(field_definition.min_length + lengthcorrection)
                else:
                    value = value.zfill(field_definition.min_length + lengthcorrection)
                value = value.replace(".", self.ta_info["decimaal"], 1)
                # replace '.' by required decimal sep.
            elif field_definition.bformat == "I":
                if not value:
                    value = "0"
                # implicit decimals
                if self.ta_info["lengthnumericbare"] and value[0] == "-":
                    lengthcorrection += 1
                try:
                    dec_value = decimal.Decimal(value).shift(field_definition.decimals)
                    value = str(dec_value.quantize(NODECIMAL))
                except decimal.InvalidOperation:
                    self.add2errorlist(
                        _(
                            '[F27]: Record "%(record)s" field "%(field)s"'
                            ' numerical format not valid: "%(content)s".\n'
                        )
                        % {
                            "field": field_definition.id,
                            "content": value,
                            "record": self.mpathformat(structure_record.mpath),
                        }
                    )
                value = value.zfill(field_definition.min_length + lengthcorrection)

            if len(value) - lengthcorrection > field_definition.length:
                self.add2errorlist(
                    _('[F28]: Record "%(record)s" field "%(field)s" too big: "%(content)s".\n')
                    % {
                        "record": self.mpathformat(structure_record.mpath),
                        "field": field_definition.id,
                        "content": value,
                    }
                )
        return value

    def _initfield(self, field_definition):
        """
        for some editypes like fixed fields without date have specific initalisation.
        this is controlled by the 'stripfield_sep' parameter in grammar.
        """
        if field_definition.bformat in "ADT":
            value = ""
        else:
            # numerics
            value = "0"
            if field_definition.bformat == "R":
                # floating point: use all decimals received
                value = value.zfill(field_definition.min_length)
            elif field_definition.bformat == "N":
                # fixed decimals; round
                value = str(
                    decimal.Decimal(value).quantize(
                        decimal.Decimal(f"10e-{field_definition.decimals}")
                    )
                )
                value = value.zfill(field_definition.min_length)
                # replace '.' by required decimal sep.
                value = value.replace(".", self.ta_info["decimaal"], 1)
            elif field_definition.bformat == "I":
                # implicit decimals
                value = value.zfill(field_definition.min_length)
        return value

    def record2string(self, lex_records):
        """
        write lex_records to a file.
        using the right editype (edifact, x12, etc) and charset.
        write (all fields of) each record using the right separators, escape etc
        """
        # pylint: disable=too-many-locals, too-many-nested-blocks
        sfield_sep = self.ta_info["sfield_sep"]
        if self.ta_info.get("record_tag_sep"):
            record_tag_sep = self.ta_info["record_tag_sep"]
        elif self.ta_info.get("editype") == "x12":
            record_tag_sep = self.ta_info["field_sep"]
        else:
            record_tag_sep = ""
        field_sep = self.ta_info["field_sep"]
        quote_char = self.ta_info["quote_char"]
        escape = self.ta_info["escape"]
        record_sep = self.ta_info["record_sep"] + self.ta_info["add_crlfafterrecord_sep"]
        forcequote = self.ta_info["forcequote"]
        escapechars = self._getescapechars()
        noBOTSID = self.ta_info.get("noBOTSID", False)
        rep_sep = self.ta_info["reserve"]

        lijst = []
        for lex_record in lex_records:
            if noBOTSID:
                # for csv/fixed: do not write BOTSID so remove it
                del lex_record[0]
            fieldcount = 0
            mode_quote = False
            # to collect the formatted record-string.
            value = ""
            for field in lex_record:
                # loop all fields in lex_record
                if not field[SFIELD]:
                    # is a field:
                    if fieldcount == 0:
                        # do nothing because first field in lex_record
                        # is not preceded by a separator
                        fieldcount = 1
                    elif fieldcount == 1:
                        value += record_tag_sep
                        fieldcount = 2
                    else:
                        value += field_sep
                elif field[SFIELD] == 1:
                    # is a subfield:
                    value += sfield_sep
                else:
                    # repeat
                    value += rep_sep
                if quote_char:
                    # quote char only used for csv
                    start_to__quote = False
                    if forcequote == 2:
                        if field[FORMATFROMGRAMMAR] in ["AN", "A", "AR"]:
                            start_to__quote = True
                    elif forcequote:
                        # always quote; this catches values 1, '1', '0'
                        start_to__quote = True
                    else:
                        if (
                            field_sep in field[VALUE]
                            or quote_char in field[VALUE]
                            or record_sep in field[VALUE]
                        ):
                            start_to__quote = True
                    if start_to__quote:
                        value += quote_char
                        mode_quote = True
                # use escape (edifact, tradacom).
                # For x12 is warned if content contains separator
                for char in field[VALUE]:
                    if char in escapechars:
                        if type(self).__name__ == "x12":
                            if not self.ta_info["replacechar"]:
                                raise OutMessageError(
                                    _(
                                        '[F51]: Character "%(char)s" is used as separator'
                                        " in this x12 file, so it can not be used in content."
                                        ' Field: "%(content)s".'
                                    ),
                                    {"char": char, "content": field[VALUE]},
                                )
                            char = self.ta_info["replacechar"]
                        else:
                            value += escape
                    elif mode_quote and char == quote_char:
                        value += quote_char
                    value += char
                if mode_quote:
                    value += quote_char
                    mode_quote = False
            value += record_sep
            lijst.append(value)
        return "".join(lijst)

    def _getescapechars(self):
        return ""
