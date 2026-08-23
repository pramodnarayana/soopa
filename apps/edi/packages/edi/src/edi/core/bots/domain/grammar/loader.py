from edi.core.bots.config.botsconfig import (
    ID,
    ISFIELD,
    SUBFIELDS,
)
from edi.core.bots.domain.exceptions import BotsImportError, GrammarError, GrammarPartMissing
from edi.core.bots.domain.models import (
    FieldDefinition,
    StructureNode,
    create_field_definition,
)
from edi.core.bots.utils.botslib import gettext as _

ERROR_IN_GRAMMAR = "BOTS_error_1$%3@7#!%+_)_+[{]}"

from . import validator


def grammarread(editype, grammarname, typeofgrammarfile) -> "Grammar":  # noqa: F821
    """
    reads/imports a grammar (dispatch function for class Grammar and subclasses).
    typeofgrammarfile indicates some differences in reading/syntax handling:
     - envelope: read whole grammar, get right syntax
     - grammar: read whole grammar, get right syntax.
     - partners: only syntax is read
    grammars are imported from usersys/<'typeofgrammarfile'>/<editype>/<grammarname>.
    """
    # pylint: disable=protected-access
    from edi.core.bots.domain.grammar import formats

    try:
        classtocall = getattr(formats, editype)
    except AttributeError as exc:
        raise GrammarError(
            _(
                'Read grammar for editype "%(editype)s" messagetype "%(messagetype)s",'
                " but editype is unknown."
            ),
            {"editype": editype, "messagetype": grammarname},
        ) from exc

    if typeofgrammarfile == "grammars":
        # read grammar for a certain editype/messagetype
        messagegrammar = classtocall(
            typeofgrammarfile="grammars", editype=editype, grammarname=grammarname
        )
        # Get right syntax: 1. start with classtocall.defaultsyntax
        messagegrammar.syntax = classtocall.defaultsyntax.copy()
        # Find out what envelope is used:
        envelope = (
            messagegrammar.original_syntaxfromgrammar.get("envelope")
            or messagegrammar.syntax["envelope"]
        )
        if envelope and envelope != grammarname:
            # when reading messagetype 'edifact' envelope will also be edifact->so do not read it.
            try:
                # read envelope grammar
                envelopegrammar = classtocall(
                    typeofgrammarfile="grammars", editype=editype, grammarname=envelope
                )
                # Get right syntax: 2. update with syntax from envelope
                messagegrammar.syntax.update(envelopegrammar.original_syntaxfromgrammar)
            except BotsImportError:
                # not all envelopes have grammar files; eg csvheader, user defined envelope.
                pass
        # Get right syntax: 3. update with syntax of messagetype
        messagegrammar.syntax.update(messagegrammar.original_syntaxfromgrammar)
        init_restofgrammar(messagegrammar)
        return messagegrammar

    if typeofgrammarfile == "envelope":
        # Read grammar for enveloping (outgoing). For 'noenvelope' no grammar is read.
        # Read grammar for messagetype first -> to find out envelope.
        messagegrammar = classtocall(
            typeofgrammarfile="grammars", editype=editype, grammarname=grammarname
        )
        # Get right syntax: 1. start with default syntax
        syntax = classtocall.defaultsyntax.copy()
        envelope = messagegrammar.original_syntaxfromgrammar.get("envelope") or syntax["envelope"]
        try:
            envelopegrammar = classtocall(
                typeofgrammarfile="grammars", editype=editype, grammarname=envelope
            )
            # Get right syntax: 2. update with envelope syntax
            syntax.update(envelopegrammar.original_syntaxfromgrammar)
        except BotsImportError:
            envelopegrammar = messagegrammar
        # Get right syntax: 3. update with message syntax
        syntax.update(messagegrammar.original_syntaxfromgrammar)
        envelopegrammar.syntax = syntax
        init_restofgrammar(envelopegrammar)
        return envelopegrammar

    if typeofgrammarfile == "partners":
        messagegrammar = classtocall(
            typeofgrammarfile="partners", editype=editype, grammarname=grammarname
        )
        messagegrammar.syntax = messagegrammar.original_syntaxfromgrammar.copy()
        return messagegrammar

    raise BotsImportError(
        _('Unknown typeofgrammarfile: "%(typeofgrammarfile)s".'),
        {"typeofgrammarfile": typeofgrammarfile},
    )


def init_restofgrammar(grammar_obj):
    grammar_obj.nextmessage = getattr(grammar_obj.module, "nextmessage", None)
    grammar_obj.nextmessage2 = getattr(grammar_obj.module, "nextmessage2", None)
    grammar_obj.nextmessageblock = getattr(grammar_obj.module, "nextmessageblock", None)
    # checks on nextmessage, nextmessage2, nextmessageblock
    if grammar_obj.nextmessage is None:
        if grammar_obj.nextmessage2 is not None:
            raise GrammarError(
                _('Grammar "%(grammar)s": if nextmessage2: nextmessage has to be used.'),
                {"grammar": grammar_obj.grammarname},
            )
    else:
        if grammar_obj.nextmessageblock is not None:
            raise GrammarError(
                _('Grammar "%(grammar)s": nextmessageblock and nextmessage not both allowed.'),
                {"grammar": grammar_obj.grammarname},
            )

    # most grammars have a structure; but eg templatehtml not (only syntax)
    if grammar_obj.syntax["has_structure"]:
        # read recorddefs.
        # recorddefs are checked and changed,
        # so need to indicate if recordsdef has already been checked and changed.
        # done by setting entry 'BOTS_1$@#%_error' in recorddefs;
        # if this entry is True: read, errors; False: read OK.
        try:
            do_recorddefs(grammar_obj)
        except GrammarPartMissing:  # noqa: TRY203
            # basic checks on recordsdef - it is not there, or not a dict, etc.
            raise
        except Exception:  # noqa: TRY203
            raise
        # read structure
        # structure is checked and changed, so need to indicate if structure
        # has already been checked and changed.
        # done by setting entry 'BOTS_1$@#%_error' in structure[0];
        # if this entry is True: read, errors; False: read OK.
        try:
            do_structure(grammar_obj)
        except GrammarPartMissing:  # noqa: TRY203
            # basic checks on strucure - it is not there, or not a list, etc.
            raise
        except Exception:  # noqa: TRY203
            raise
        # link recordsdefs to structure
        # as structure can be re-used/imported from other grammars,
        # do this always when reading grammar.
        linkrecorddefs2structure(grammar_obj, grammar_obj.structure)
    grammar_obj.class_specific_tests()


def do_recorddefs(grammar_obj):  # noqa: C901
    """
    1. check the recorddefinitions for validity.
    2. adapt in field-records: normalise length lists, set bool ISFIELD, etc
    """
    # pylint: disable=too-many-branches
    try:
        grammar_obj.recorddefs = grammar_obj.module.recorddefs
    except AttributeError as exc:
        if (
            getattr(grammar_obj, "editype", None) == "x12"
            and grammar_obj.grammarname != "envelope"
            and len(grammar_obj.grammarname) > 4
        ):
            version = grammar_obj.grammarname[-4:]
            recorddefs_module_path = f"edi.core.grammar.x12.{version}.records00{version}"
            try:
                import importlib

                records_module = importlib.import_module(recorddefs_module_path)
                grammar_obj.recorddefs = records_module.recorddefs
            except ImportError:
                pass

        if (
            not hasattr(grammar_obj, "recorddefs")
            and getattr(grammar_obj, "editype", None) == "edifact"
            and grammar_obj.grammarname != "envelope"
            and "D" in grammar_obj.grammarname
            and "UN" in grammar_obj.grammarname
        ):
            version = grammar_obj.grammarname.split("D", 1)[1].split("UN")[0]
            recorddefs_module_path = f"edi.core.grammar.edifact.D{version}.recordsD{version}UN"
            try:
                import importlib

                records_module = importlib.import_module(recorddefs_module_path)
                grammar_obj.recorddefs = records_module.recorddefs
            except ImportError:
                pass

        if not hasattr(grammar_obj, "recorddefs"):
            _exception = GrammarPartMissing(
                _('Grammar "%(grammar)s": no recorddefs, is required.'),
                {"grammar": grammar_obj.grammarname},
            )
            _exception.__cause__ = None
            raise _exception from exc
    if not isinstance(grammar_obj.recorddefs, dict):
        raise GrammarPartMissing(
            _('Grammar "%(grammar)s": recorddefs is not a dict.'),
            {"grammar": grammar_obj.grammarname},
        )

    if ERROR_IN_GRAMMAR in grammar_obj.recorddefs:
        raise GrammarError(
            _('Grammar "%(grammar)s": already reported as erroneous.'),
            {"grammar": grammar_obj.grammarname},
        )

    # If already parsed
    if grammar_obj.recorddefs and all(
        isinstance(v, list) and v and all(isinstance(f, FieldDefinition) for f in v)
        for v in grammar_obj.recorddefs.values()
    ):
        return
    # not checked (in this run): so check the recorddefs
    for recordid, fields in grammar_obj.recorddefs.items():
        if not isinstance(recordid, str):
            raise GrammarError(
                _('Grammar "%(grammar)s", in recorddefs, record "%(record)s": is not a string.'),
                {"grammar": grammar_obj.grammarname, "record": recordid},
            )
        if not recordid:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s":'
                    " recordid with empty string."
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid},
            )
        if not isinstance(fields, list):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s":'
                    " no correct fields found."
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid},
            )
        if False:
            if len(fields) < 1:
                raise GrammarError(
                    _('Grammar "%(grammar)s", in recorddefs, record "%(record)s": too few fields.'),
                    {"grammar": grammar_obj.grammarname, "record": recordid},
                )
        else:
            if len(fields) < 2:
                raise GrammarError(
                    _('Grammar "%(grammar)s", in recorddefs, record "%(record)s": too few fields.'),
                    {"grammar": grammar_obj.grammarname, "record": recordid},
                )

        # to check if BOTSID is present
        has_botsid = False
        # to check for double fieldnames
        fieldnamelist = []
        for i, field in enumerate(fields):
            validator.checkfield(grammar_obj, field, recordid)
            if not field[ISFIELD]:
                # composite
                for j, sfield in enumerate(field[SUBFIELDS]):
                    validator.checkfield(grammar_obj, sfield, recordid)
                    if sfield[ID] in fieldnamelist:
                        raise GrammarError(
                            _(
                                'Grammar "%(grammar)s", in recorddefs, record "%(record)s":'
                                ' field "%(field)s" appears twice.'
                                " Field names should be unique within a record."
                            ),
                            {
                                "grammar": grammar_obj.grammarname,
                                "record": recordid,
                                "field": sfield[ID],
                            },
                        )
                    fieldnamelist.append(sfield[ID])
                    field[SUBFIELDS][j] = create_field_definition(sfield)
            else:
                if field[ID] == "BOTSID":
                    has_botsid = True
                if field[ID] in fieldnamelist:
                    raise GrammarError(
                        _(
                            'Grammar "%(grammar)s", in recorddefs, record "%(record)s":'
                            ' field "%(field)s" appears twice.'
                            " Field names should be unique within a record."
                        ),
                        {
                            "grammar": grammar_obj.grammarname,
                            "record": recordid,
                            "field": field[ID],
                        },
                    )
                fieldnamelist.append(field[ID])

            fields[i] = create_field_definition(field)

        if not has_botsid:
            # there is no field 'BOTSID' in record
            raise GrammarError(
                _('Grammar "%(grammar)s", in recorddefs, record "%(record)s": no field BOTSID.'),
                {"grammar": grammar_obj.grammarname, "record": recordid},
            )


def do_structure(grammar_obj):
    """
    1. check the structure for validity.
    2. adapt in structure: Add keys: mpath, count
    3. remember that structure is checked and adapted
       (so when grammar is read again, no checking/adapt needed)
    """
    try:
        grammar_obj.structure = grammar_obj.module.structure
    except AttributeError as exc:
        _exception = GrammarPartMissing(
            _('Grammar "%(grammar)s": no structure, is required.'),
            {"grammar": grammar_obj.grammarname},
        )
        _exception.__cause__ = None
        raise _exception from exc
    if not isinstance(grammar_obj.structure, list):
        raise GrammarPartMissing(
            _('Grammar "%(grammar)s": structure is not a list.'),
            {"grammar": grammar_obj.grammarname},
        )
    if len(grammar_obj.structure) != 1:
        print("DEBUG STRUCTURE FAILED LENGTH:", grammar_obj.structure)
        raise GrammarPartMissing(
            _('Grammar "%(grammar)s", in structure: structure must have exactlty one root record.'),
            {"grammar": grammar_obj.grammarname},
        )
    if not isinstance(grammar_obj.structure[0], (dict, StructureNode)):
        raise GrammarPartMissing(
            _(
                'Grammar "%(grammar)s": in structure:'
                " expect a dict or StructureNode for root record, but did not find that."
            ),
            {"grammar": grammar_obj.grammarname},
        )

    if not isinstance(grammar_obj.structure[0], StructureNode):
        # not checked (in this run): so check the structure and convert
        validator.checkstructure(grammar_obj, grammar_obj.structure, [])

    if grammar_obj.syntax["checkcollision"]:
        validator.checkbackcollision(grammar_obj, grammar_obj.structure)
        validator.checknestedcollision(grammar_obj, grammar_obj.structure)
    validator.checkbotscollision(grammar_obj, grammar_obj.structure)


def linkrecorddefs2structure(grammar_obj, structure):
    """
    recursive
    for each record in structure:
        add the pointer to the right recorddefinition.
    """
    for i in structure:
        try:
            # lookup the recordID in recorddefs (a dict);
            # set pointer in structure to recorddefs/fields
            i.fields = grammar_obj.recorddefs[i.id]
        except KeyError as exc:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure:'
                    ' no record definition for record "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "record": i.id},
            ) from exc
        if i.level:
            linkrecorddefs2structure(grammar_obj, i.level)
