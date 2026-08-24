"""
Bots message lib
"""
# pylint: disable=missing-function-docstring

# bots-modules
import structlog

from edi.core.bots.config.botsconfig import (
    SFIELD,
    VALUE,
)
from edi.core.bots.domain import grammar, node
from edi.core.bots.domain.exceptions import (
    BotsImportError,
    MappingFormatError,
    MappingRootError,
    MessageError,
    MessageRootError,
)
from edi.core.bots.utils.botslib import gettext as _

logger = structlog.get_logger(__name__)


class Message:
    """
    abstract class; represents a edi message.
    is subclassed as outmessage or inmessage object.
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, ta_info):
        self.ta_info = ta_info  # here ta_info is only filled with parameters from db-ta
        self.errorlist = []  # collect non-fatal errors in the edi file; used in reporting errors.
        self.errorfatal = True  # store fatal errors: errors that stop the processing of the file
        self.messagetypetxt = ""  # used in reporting errors.
        self.messagecount = 0  # count messages in edi file; used in reporting errors.
        self.root = None  # Add lwx 20190917
        self.defmessage = None
        self.syntax = {}
        self.lexer = None

    def _manipulatemessagetype(self, messagetype, inode):
        """
        Default implementation for manipulating messagetype.
        Can be overridden by subclasses (e.g., x12) to append version information.
        """
        return messagetype

    def add2errorlist(self, errortxt):
        """Handle non-fatal parse errors"""
        # UNITTEST_CORRECTION
        # raise MessageError("For unit format test")
        # if more than max_number_errors: stop adding new errors to list.
        if len(self.errorlist) < 10:
            self.errorlist.append(self.messagetypetxt + errortxt)
        elif len(self.errorlist) == 10:
            self.errorlist.append(_("[A51]: too many errors in message."))

    def checkforerrorlist(self):
        """examine the message-object for errors"""
        if self.errorfatal:  # for fatal errors: (try to) get information like partners for edi file
            self.try_to_retrieve_info()
        if self.errorlist:
            raise MessageError("".join(self.errorlist))

    def try_to_retrieve_info(self):
        """
        when edi-file is not correct, (try to) get info about eg partnerID's in message
        method is specified in subclasses.
        """

    @staticmethod
    def display(lex_records):
        """for debugging: display lexed records."""
        # pylint: disable=consider-using-f-string
        for lex_record in lex_records:
            counter = 0
            for veld in lex_record:
                if counter == 0:
                    print(f"{veld[VALUE]}    (Record-id)")
                else:
                    if veld[SFIELD] == 0:
                        print(f"    {veld[VALUE]}    (field)")
                    elif veld[SFIELD] == 1:
                        print(f"        {veld[VALUE]}    (sub)")
                    elif veld[SFIELD] == 2:
                        print(f"        {veld[VALUE]}    (rep)")
                    else:
                        print(f"    {veld[VALUE]}    (???)")
                counter += 1

    @staticmethod
    def mpathformat(mpath):
        """mpath is eg: ['UNH', 'NAD'], formatted is: 'UNH-NAD'."""
        return "-".join(mpath)

    def checkmessage(self, node_instance, defmessage, subtranslation=False):
        """
        The node tree is check, sorted, fields are formatted etc against grammar.
        (so far only minimal tests have been done during processing)

        For checking translation & subtranslation
        parameter 'subtranslation' only used for reporting
        some different cases:
        - empy root.record, root.children filled:
        - edifact, x12, tradacoms: each child is an envelope. Check each envelope.
          (use mailbag to have one UNB per node-tree here)
        - csv nobotsid: each child is a record. Check all records in one check
        - xml, json:
        root.record filled, root.children filled: outgoing messages.
        """
        if not self.ta_info["has_structure"]:
            return
        if node_instance.record:
            # root record contains information; so one message
            count = 1
            self._checkonemessage(node_instance, defmessage, subtranslation)
        else:
            count = 0
            for childnode in node_instance.children:
                count += 1
                self._checkonemessage(childnode, defmessage, subtranslation)
        if count < defmessage.structure[0].min_occ:
            self.add2errorlist(
                _('[S03] Root record "%(mpath)s" occurs %(count)d times, min is %(mincount)d.\n')
                % {
                    "mpath": defmessage.structure[0].id,
                    "count": count,
                    "mincount": defmessage.structure[0].min_occ,
                }
            )
        if count > defmessage.structure[0].max_occ:
            self.add2errorlist(
                _('[S04] Root record "%(mpath)s" occurs %(count)d times, max is %(maxcount)d.\n')
                % {
                    "mpath": defmessage.structure[0].id,
                    "count": count,
                    "maxcount": defmessage.structure[0].max_occ,
                }
            )

    def _checkonemessage(self, node_instance, defmessage, subtranslation):
        structure = defmessage.structure
        if node_instance.record["BOTSID"] != structure[0].id:
            raise MessageRootError(
                _(
                    '[G50]: Grammar "%(grammar)s" starts with record "%(grammarroot)s";'
                    ' but in edi-file found start-record "%(root)s".'
                ),
                {
                    "root": node_instance.record["BOTSID"],
                    "grammarroot": structure[0].id,
                    "grammar": defmessage.grammarname,
                },
            )
        self._checkifrecordsingrammar(node_instance, structure[0], defmessage.grammarname)
        self._canonicaltree(node_instance, structure[0])
        # should the content of the message (the records read) be logged.
        if False:
            self._logmessagecontent(node_instance)

    def _checkifrecordsingrammar(self, node_instance, structure, grammarname):
        """check for every node if in grammar recursive"""
        # list of records not in the grammar; these records are deleted at end of function
        deletelist = []
        # check if fields are known in grammar
        self._checkiffieldsingrammar(node_instance, structure)
        if "messagetype" in node_instance.queries:
            # SUBTRANSLATION starts; already checked during parse
            return

        if node_instance.children and not structure.level:
            # record has children, but these are not in the grammar
            if getattr(structure, "subtranslation", None):
                # The children belong to the subgrammar, so bypass this error check.
                pass
            else:
                if self.ta_info["checkunknownentities"]:
                    self.add2errorlist(
                        _(
                            '[S01]%(linpos)s: Record "%(record)s" in message has children,'
                            ' but these are not in grammar "%(grammar)s". Found record "%(xx)s".\n'
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "record": node_instance.record["BOTSID"],
                            "grammar": grammarname,
                            "xx": node_instance.children[0].record["BOTSID"],
                        }
                    )
                node_instance.children = []
                return

        for childnode in node_instance.children:
            # for every record/childnode:
            if not structure.level:
                continue

            for record_definition in structure.level:
                # search in grammar-records
                if childnode.record["BOTSID"] == record_definition.id:
                    # check if this record triggers a subtranslation
                    if record_definition.subtranslation:
                        messagetype = childnode.enhancedget(record_definition.subtranslation)
                        if not messagetype:
                            raise MessageError(
                                _('Could not find SUBTRANSLATION "%(sub)s" in (sub)message.')
                                % {"sub": record_definition.subtranslation}
                            )
                        if isinstance(messagetype, (dict, list)):
                            pass

                        # Use the parent node_instance to extract version info (like GS08)
                        messagetype = self._manipulatemessagetype(messagetype, node_instance)

                        try:
                            subdefmessage = grammar.grammarread(
                                self.ta_info.get("editype", "x12"),
                                messagetype,
                                typeofgrammarfile="grammars",
                            )
                            # Now we validate the subtranslation node against the outer grammar
                            self._checkifrecordsingrammar(childnode, record_definition, grammarname)

                            # Mark as subtranslation start so the recursive check doesn't try to validate its children against the outer grammar
                            childnode.queries = {"messagetype": messagetype}

                            # Validate the children of the subtranslation node
                            for subchild in childnode.children:
                                for sub_record_definition in subdefmessage.structure[0].level:
                                    if subchild.record["BOTSID"] == sub_record_definition.id:
                                        self._checkifrecordsingrammar(
                                            subchild,
                                            sub_record_definition,
                                            subdefmessage.grammarname,
                                        )
                                        break
                                else:
                                    if self.ta_info.get("checkunknownentities", True):
                                        self.add2errorlist(
                                            _(
                                                '[S02]%(linpos)s: Unknown record "%(record)s" in message.\n'
                                            )
                                            % {
                                                "linpos": subchild.linpos(),
                                                "record": subchild.record["BOTSID"],
                                            }
                                        )
                                        deletelist.append(subchild)
                        except BotsImportError as exc:
                            raise MessageError(
                                _('No (valid) grammar for messagetype "%(messagetype)s".')
                                % {"messagetype": messagetype}
                            ) from exc
                    else:
                        # Normal recursive check
                        self._checkifrecordsingrammar(childnode, record_definition, grammarname)
                    break
            else:
                # record/childnode is not in grammar
                if self.ta_info["checkunknownentities"]:
                    self.add2errorlist(
                        _('[S02]%(linpos)s: Unknown record "%(record)s" in message.\n')
                        % {"linpos": node_instance.linpos(), "record": childnode.record["BOTSID"]}
                    )
                deletelist.append(childnode)
        for child in deletelist:
            node_instance.children.remove(child)

    def _checkiffieldsingrammar(self, node_instance, record_definition):
        """
        checks for every field in record if field exists in record_definition (from grammar).
        for inmessage of type (var,fixed,??) this is not needed
        """
        # pylint: disable=too-many-branches, too-many-nested-blocks
        # check every field in the record
        for field in list(node_instance.record.keys()):
            if field == "BOTSIDnr":
                # BOTSIDnr is not in grammar, so skip check
                continue
            for field_definition in record_definition.fields:
                if field_definition.is_field:
                    # field (no composite)
                    if field == field_definition.id:
                        # OK!
                        break
                else:
                    # if composite
                    if field_definition.max_repeat == 1:
                        # non-repeating composite
                        # loop subfields
                        for grammarsubfield in field_definition.subfields:
                            if field == grammarsubfield.id:
                                # break out of grammarsubfield-for-loop
                                # ->goto break out of field_definition-for-loop
                                break
                        else:
                            # nothing found; continue with next gammarfield
                            continue
                        # break out of field_definition-for-loop
                        break
                    # repeating composite
                    if field == field_definition.id:
                        # OK. Contents is a list of dicts;
                        # TODO: check for each dict if sub-fields exist in grammar.
                        break
            else:
                # field not found in grammar
                if self.ta_info["checkunknownentities"]:
                    self.add2errorlist(
                        _('[F01]%(linpos)s: Record: "%(mpath)s" has unknown field "%(field)s".\n')
                        % {
                            "linpos": node_instance.linpos(),
                            "field": field,
                            "mpath": self.mpathformat(record_definition.mpath),
                        }
                    )
                del node_instance.record[field]

    def _formatfield(self, value, field_definition, structure_record, node_instance):
        """
        Format of a field is checked and converted if needed.
        Input: value (string), field definition.
        Output: the formatted value (string)
        Parameters of self.ta_info are used: triad, decimaal
        for fixed field: same handling; length is not checked.
        """
        # pylint: disable=unused-argument
        return value

    def _canonicaltree(self, node_instance, structure):
        """
        For nodes: check min and max occurence;
        sort the records conform grammar
        """
        sortednodelist = []
        if "messagetype" in node_instance.queries:
            # SUBTRANSLATION starts; children are already canonicalized by the inner checkmessage call.
            return
        # handle fields of this record
        self._canonicalfields(node_instance, structure)
        if node_instance.structure is None:
            node_instance.structure = structure
        if structure.level:
            # for every record_definition (in grammar) of this level
            for record_definition in structure.level:
                # count number of occurences of record
                count = 0
                # for every node in mpathtree; SPEED: delete nodes from list when found
                for childnode in node_instance.children:
                    # if it is not the right NODE":
                    if (
                        childnode.record["BOTSID"] != record_definition.id
                        or childnode.record["BOTSIDnr"] != record_definition.botsidnr
                    ):
                        continue
                    count += 1
                    # use rest of index in deeper level
                    self._canonicaltree(childnode, record_definition)
                    sortednodelist.append(childnode)
                if record_definition.min_occ > count:
                    self.add2errorlist(
                        _(
                            '[S03]%(linpos)s: Record "%(mpath)s" occurs %(count)d times,'
                            " min is %(mincount)d.\n"
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "mpath": self.mpathformat(record_definition.mpath),
                            "count": count,
                            "mincount": record_definition.min_occ,
                        }
                    )
                if record_definition.max_occ < count:
                    self.add2errorlist(
                        _(
                            '[S04]%(linpos)s: Record "%(mpath)s" occurs %(count)d times,'
                            " max is %(maxcount)d.\n"
                        )
                        % {
                            "linpos": node_instance.linpos(),
                            "mpath": self.mpathformat(record_definition.mpath),
                            "count": count,
                            "maxcount": record_definition.max_occ,
                        }
                    )
            node_instance.children = sortednodelist

    def _canonicalfields(self, node_instance, record_definition):
        """
        For all fields: check M/C, format.
        Fields are not sorted (a dict can not be sorted).
        Fields are never added.
        """
        # pylint: disable=too-many-branches, too-many-nested-blocks, too-many-statements
        noderecord = node_instance.record
        # loop over fields in grammar
        for field_definition in record_definition.fields:
            if field_definition.is_field:
                # field (no composite)
                if field_definition.max_repeat == 1:
                    # non-repeating
                    value = noderecord.get(field_definition.id)
                    if not value and (value is None or isinstance(value, str)):
                        # Skip json raw values (not isinstance(value, (bool, int, float)))
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F02]%(linpos)s: Record "%(mpath)s" field "%(field)s"'
                                    " is mandatory.\n"
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )

                        continue
                    noderecord[field_definition.id] = self._formatfield(
                        value, field_definition, record_definition, node_instance
                    )
                else:
                    # repeating field;
                    # a list of values; values can be empty or None;
                    # at least one field should have value, else dropped
                    valuelist = noderecord.get(field_definition.id)
                    if valuelist is None:
                        # empty lists are already catched in node.put()
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F41]%(linpos)s: Record "%(mpath)s" repeating field'
                                    ' "%(field)s" is mandatory.\n'
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )
                        continue
                    if not isinstance(valuelist, list):
                        raise MappingFormatError(
                            _("Repeating field: must be a list: put(%(mpath)s)"),
                            {"mpath": valuelist},
                        )
                    if len(valuelist) > field_definition.max_repeat:
                        self.add2errorlist(
                            _(
                                '[F42]%(linpos)s: Record "%(mpath)s" repeating field "%(field)s"'
                                " occurs %(occurs)s times, max is %(max)s.\n"
                            )
                            % {
                                "linpos": node_instance.linpos(),
                                "mpath": self.mpathformat(record_definition.mpath),
                                "field": field_definition.id,
                                "occurs": len(valuelist),
                                "max": field_definition.max_repeat,
                            }
                        )
                    newlist = []
                    repeating_field_has_data = False
                    for value in valuelist:
                        if value is None:
                            value = ""
                        else:
                            value = str(value).strip()
                            if value:
                                repeating_field_has_data = True
                        newlist.append(
                            self._formatfield(
                                value, field_definition, record_definition, node_instance
                            )
                        )
                    if not repeating_field_has_data:
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F43]%(linpos)s: Record "%(mpath)s" repeating field'
                                    ' "%(field)s" is mandatory.\n'
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )
                        del noderecord[field_definition.id]
                        continue
                    noderecord[field_definition.id] = newlist
            else:
                # composite
                if field_definition.max_repeat == 1:
                    # non-repeating compostie
                    # first check if there is any data att all in this composite
                    for grammarsubfield in field_definition.subfields:
                        if noderecord.get(grammarsubfield.id):
                            # composite has data.
                            break
                    else:
                        # composite has no data
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F03]%(linpos)s: Record "%(mpath)s" composite "%(field)s"'
                                    " is mandatory.\n"
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )
                        # there is no data in composite, so do nothing
                        continue
                    # there is data in the composite!
                    # loop subfields
                    for grammarsubfield in field_definition.subfields:
                        value = noderecord.get(grammarsubfield.id)
                        if not value:
                            if grammarsubfield.is_mandatory:
                                self.add2errorlist(
                                    _(
                                        '[F04]%(linpos)s: Record "%(mpath)s" subfield "%(field)s"'
                                        " is mandatory.\n"
                                    )
                                    % {
                                        "linpos": node_instance.linpos(),
                                        "mpath": self.mpathformat(record_definition.mpath),
                                        "field": grammarsubfield.id,
                                    }
                                )
                            continue
                        noderecord[grammarsubfield.id] = self._formatfield(
                            value, grammarsubfield, record_definition, node_instance
                        )
                else:  # if repeating composite: list of dicts
                    valuelist = noderecord.get(field_definition.id)
                    # empty lists are caught in node.put()
                    if valuelist is None:
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F44]%(linpos)s: Record "%(mpath)s" repeating composite'
                                    ' "%(field)s" is mandatory.\n'
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )
                        continue
                    if not isinstance(valuelist, list):
                        raise MappingFormatError(
                            _("Repeating composite: must be a list: put(%(mpath)s)"),
                            {"mpath": valuelist},
                        )
                    if len(valuelist) > field_definition.max_repeat:
                        self.add2errorlist(
                            _(
                                '[F45]%(linpos)s: Record "%(mpath)s" repeating composite'
                                ' "%(field)s" occurs %(occurs)s times, max is %(max)s.\n'
                            )
                            % {
                                "linpos": node_instance.linpos(),
                                "mpath": self.mpathformat(record_definition.mpath),
                                "field": field_definition.id,
                                "occurs": len(valuelist),
                                "max": field_definition.max_repeat,
                            }
                        )
                    # is a list of composites; each composite is a dict.
                    # loop over composites/dicts, create a new list
                    # - dict can be empty: {}. check if: composite contains data or is empty
                    # - if composite is not-empty, check M/C of elements in composite
                    # - keys should be str.
                    # - convert values to unicode
                    # - check if there is data for whole repeating composite
                    newlist = []
                    repeating_composite_has_data = False
                    for comp in valuelist:
                        if not isinstance(comp, dict):
                            raise MappingFormatError(
                                _(
                                    "Repeating composite: each composite must be a dict:"
                                    " put(%(mpath)s)"
                                ),
                                {"mpath": valuelist},
                            )
                        # check each dict, convert values to unicode
                        # also: check if dict has data at all
                        composite_has_data = False
                        for key, value in comp.items():
                            if not isinstance(key, str):
                                raise MappingFormatError(
                                    _("Repeating composite: keys must be strings: put(%(mpath)s)"),
                                    {"mpath": valuelist},
                                )
                            if value is None:
                                comp[key] = ""
                            else:
                                # leading and trailing spaces are stripped from the values
                                comp[key] = str(value).strip()
                                if comp[key]:
                                    composite_has_data = True
                        if composite_has_data:
                            repeating_composite_has_data = True
                            # loop subfields
                            for grammarsubfield in field_definition.subfields:
                                value = comp.get(grammarsubfield.id)
                                if not value:
                                    if grammarsubfield.is_mandatory:
                                        self.add2errorlist(
                                            _(
                                                '[F46]%(linpos)s: Record "%(mpath)s" subfield'
                                                ' "%(field)s" in repeating composite'
                                                " is mandatory.\n"
                                            )
                                            % {
                                                "linpos": node_instance.linpos(),
                                                "mpath": self.mpathformat(record_definition.mpath),
                                                "field": grammarsubfield.id,
                                            }
                                        )
                                    continue
                                comp[grammarsubfield.id] = self._formatfield(
                                    value, grammarsubfield, record_definition, node_instance
                                )
                        else:
                            comp = {}
                        newlist.append(comp)
                    if not repeating_composite_has_data:
                        if field_definition.is_mandatory:
                            self.add2errorlist(
                                _(
                                    '[F47]%(linpos)s: Record "%(mpath)s" repeating composite'
                                    ' "%(field)s" is mandatory.\n'
                                )
                                % {
                                    "linpos": node_instance.linpos(),
                                    "mpath": self.mpathformat(record_definition.mpath),
                                    "field": field_definition.id,
                                }
                            )

                        del noderecord[field_definition.id]
                    else:
                        noderecord[field_definition.id] = newlist

    def _logmessagecontent(self, node_instance):
        logger.debug('Record "%(BOTSID)s":', node_instance.record)
        # handle fields of this record
        self._logfieldcontent(node_instance.record)
        for child in node_instance.children:
            self._logmessagecontent(child)

    @staticmethod
    def _logfieldcontent(noderecord):
        logger.debug('Record "%(BOTSID)s":', noderecord)
        for key, value in noderecord.items():
            if key != "BOTSID":
                logger.debug('    "%(key)s" : "%(value)s"', {"key": key, "value": value})

    # ***************************************************************************
    # * methods below pass call to node.Node ************************************
    # ***************************************************************************
    def getrecord(self, *mpaths):
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'getrecord(%(mpath)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.getrecord(*mpaths)

    def change(self, where, change):
        """
        query tree (self.root) with where;
        if found replace with change;

        :return: True if change, False if not changed.
        """
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'change(%(where)s,%(change)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"where": where, "change": change},
            )
        return self.root.change(where, change)

    def delete(self, *mpaths):
        """
        query tree (self.root) with mpath;delete if found.

        :return: True if deleted, False if not deleted.
        """
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'delete(%(mpath)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.delete(*mpaths)

    def get(self, *mpaths):
        """query tree (self.root) with mpath; get value (string); get None if not found."""
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'get(%(mpath)s): "root" of incoming message is empty; either split messages'
                    " or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.get(*mpaths)

    def getnozero(self, *mpaths):
        """like get, returns None is value is zero (0) or not numeric.
        Is sometimes useful in mapping."""
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'getnozero(%(mpath)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.getnozero(*mpaths)

    def getdecimal(self, *mpaths):
        """like get, returns None is value is zero (0) or not numeric.
        Is sometimes useful in mapping."""
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'getdecimal(%(mpath)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.getdecimal(*mpaths)

    def getcount(self):
        """count number of nodes in self.root. Number of nodes is number of records."""
        return self.root.getcount()

    def getcountoccurrences(self, *mpaths):
        """count number of nodes in self.root. Number of nodes is number of records."""
        return len(list(self.getloop(*mpaths)))

    def getcountsum(self, *mpaths):
        """return the sum for all values found in mpath.
        Eg total number of ordered quantities."""
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'get(%(mpath)s): "root" of incoming message is empty;'
                    " either split messages or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        return self.root.getcountsum(*mpaths)

    def getloop(self, *mpaths):
        """
        query tree with mpath; generates all the nodes.
        Is typically used as: for record in inn.get(mpath):
        """
        if self.root.record:
            # self.root is a real root
            # search recursive for rest of mpaths
            yield from self.root.getloop(*mpaths)
        else:
            # self.root is dummy root
            for childnode in self.root.children:
                # search recursive for rest of mpaths
                yield from childnode.getloop(*mpaths)

    def getloop_including_mpath(self, *mpaths):
        """
        as getloop, but returns a list: [mpath,mpath,etc,,node]
        ->node is same as returned by getloop()
        """
        if self.root.record:
            # self.root is a real root
            # search recursive for rest of mpaths
            yield from self.root.getloop_including_mpath(*mpaths)
        else:
            # self.root is dummy root
            for childnode in self.root.children:
                # search recursive for rest of mpaths
                yield from childnode.getloop_including_mpath(*mpaths)

    def put(self, *mpaths, **kwargs):
        if self.root.record is None and self.root.children:
            raise MappingRootError(
                _('put(%(mpath)s): "root" of outgoing message is empty; use out.putloop'),
                {"mpath": mpaths},
            )
        return self.root.put(*mpaths, **kwargs)

    def putraw(self, *mpaths, **kwargs):
        if self.root.record is None and self.root.children:
            raise MappingRootError(
                _('put(%(mpath)s): "root" of outgoing message is empty; use out.putloop'),
                {"mpath": mpaths},
            )
        return self.root.putraw(*mpaths, **kwargs)

    def putloop(self, *mpaths):
        if not self.root.record:
            # no input yet, and start with a putloop(): dummy root
            if len(mpaths) == 1:
                self.root.append(node.Node(record=mpaths[0]))
                return self.root.children[-1]
            raise MappingRootError(_("putloop(%(mpath)s): mpath too long???"), {"mpath": mpaths})
        return self.root.putloop(*mpaths)

    def sort(self, *mpaths):
        if self.root.record is None:
            raise MappingRootError(
                _(
                    'get(%(mpath)s): "root" of message is empty; either split messages'
                    " or use inn.getloop"
                ),
                {"mpath": mpaths},
            )
        self.root.sort(*mpaths)
