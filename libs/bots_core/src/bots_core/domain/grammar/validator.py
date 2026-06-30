import contextlib

from bots_core.domain.exceptions import GrammarError
from bots_core.domain.models import (
    create_structure_node,
)
from bots_core.infrastructure.config.botsconfig import (
    BFORMAT,
    DECIMALS,
    FORMAT,
    ID,
    ISFIELD,
    LENGTH,
    LEVEL,
    MANDATORY,
    MAX,
    MAXREPEAT,
    MIN,
    MINLENGTH,
    MPATH,
    SUBFIELDS,
)
from bots_core.utils.botslib import gettext as _

ERROR_IN_GRAMMAR = "BOTS_error_1$%3@7#!%+_)_+[{]}"


def checkfield(grammar_obj, field, recordid):
    """'normalise' field: make list equal length"""
    # pylint: disable=too-many-branches, too-many-statements
    len_field = len(field)
    if len_field == 3:
        # that is: composite
        field += [None, False, None, None, "A", 1]
    elif len_field == 4:
        # that is: field (not a composite)
        field += [True, 0, 0, "A", 1]
    # each field is now equal length list
    # ~ elif len_field == 9:
    #       # this happens when there are errors in a table and table is read again
    #       # --> should not be possible
    # ~ raise GrammarError(_('Grammar "%(grammar)s": error in grammar; error is already reported in this run.'),
    # ~ {'grammar':grammar_obj.grammarname})
    else:
        safe_id = field[ID] if len_field > ID else "<unknown>"
        raise GrammarError(
            _(
                'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                ' field "%(field)s": list has invalid number of arguments.'
            ),
            {"grammar": grammar_obj.grammarname, "record": recordid, "field": safe_id},
        )
    if not isinstance(field[ID], str) or not field[ID]:
        raise GrammarError(
            _(
                'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                ' field "%(field)s": fieldID has to be a string.'
            ),
            {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
        )
    if isinstance(field[MANDATORY], str):
        if field[MANDATORY] not in ("M", "C"):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": mandatory/conditional must be "M" or "C".'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        field[MANDATORY] = 0 if field[MANDATORY] == "C" else 1
    elif isinstance(field[MANDATORY], tuple):
        if len(field[MANDATORY]) < 1:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": mandatory/conditional tuple is empty.'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        if not isinstance(field[MANDATORY][0], str):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": mandatory/conditional must be "M" or "C".'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        if field[MANDATORY][0] not in ("M", "C"):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": mandatory/conditional must be "M" or "C".'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        if len(field[MANDATORY]) < 2 or not isinstance(field[MANDATORY][1], int):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": number of repeats must be integer.'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        field[MAXREPEAT] = field[MANDATORY][1]
        field[MANDATORY] = 0 if field[MANDATORY][0] == "C" else 1
    else:
        raise GrammarError(
            _(
                'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                ' field "%(field)s": mandatory/conditional has to be a string'
                " (or tuple in case of repeating field)."
            ),
            {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
        )
    if field[ISFIELD]:
        # that is: field, and not a composite
        # get MINLENGTH (from tuple or if fixed
        if isinstance(field[LENGTH], (int, float)):
            pass
        elif isinstance(field[LENGTH], tuple):
            if not isinstance(field[LENGTH][0], (int, float)):
                raise GrammarError(
                    _(
                        'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                        ' field "%(field)s": min length "%(min)s" has to be a number.'
                    ),
                    {
                        "grammar": grammar_obj.grammarname,
                        "record": recordid,
                        "field": field[ID],
                        "min": field[LENGTH][0],
                    },
                )
            if not isinstance(field[LENGTH][1], (int, float)):
                raise GrammarError(
                    _(
                        'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                        ' field "%(field)s": max length "%(max)s" has to be a number.'
                    ),
                    {
                        "grammar": grammar_obj.grammarname,
                        "record": recordid,
                        "field": field[ID],
                        "max": field[LENGTH][1],
                    },
                )
            if field[LENGTH][0] > field[LENGTH][1]:
                raise GrammarError(
                    _(
                        'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                        ' field "%(field)s": min length "%(min)s" must be > max length "%(max)s".'
                    ),
                    {
                        "grammar": grammar_obj.grammarname,
                        "record": recordid,
                        "field": field[ID],
                        "min": field[LENGTH][0],
                        "max": field[LENGTH][1],
                    },
                )
            field[MINLENGTH] = field[LENGTH][0]
            field[LENGTH] = field[LENGTH][1]
        else:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": length "%(len)s" has to be number or (min,max).'
                ),
                {
                    "grammar": grammar_obj.grammarname,
                    "record": recordid,
                    "field": field[ID],
                    "len": field[LENGTH],
                },
            )
        if field[LENGTH] < 1:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": length "%(len)s" has to be at least 1.'
                ),
                {
                    "grammar": grammar_obj.grammarname,
                    "record": recordid,
                    "field": field[ID],
                    "len": field[LENGTH],
                },
            )
        if field[MINLENGTH] < 0:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": minlength "%(len)s" has to be at least 0.'
                ),
                {
                    "grammar": grammar_obj.grammarname,
                    "record": recordid,
                    "field": field[ID],
                    "len": field[LENGTH],
                },
            )
        # format
        if not isinstance(field[FORMAT], str):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": format "%(format)s" has to be a string.'
                ),
                {
                    "grammar": grammar_obj.grammarname,
                    "record": recordid,
                    "field": field[ID],
                    "format": field[FORMAT],
                },
            )
        grammar_obj._manipulatefieldformat(field, recordid)
        if field[BFORMAT] in "NIR":
            if isinstance(field[LENGTH], float):
                # Does not work for more than 9 decimal places.
                field[DECIMALS] = int((field[LENGTH] % 1) * 10.0001)
                field[LENGTH] = int(field[LENGTH])
                if field[DECIMALS] >= field[LENGTH]:
                    raise GrammarError(
                        _(
                            'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                            ' field "%(field)s": field length "%(len)s" has to be greater that nr of decimals "%(decimals)s".'
                        ),
                        {
                            "grammar": grammar_obj.grammarname,
                            "record": recordid,
                            "field": field[ID],
                            "len": field[LENGTH],
                            "decimals": field[DECIMALS],
                        },
                    )
            if isinstance(field[MINLENGTH], float):
                field[MINLENGTH] = int(field[MINLENGTH])
        else:  # if format 'R', A, D, T
            if isinstance(field[LENGTH], float):
                raise GrammarError(
                    _(
                        'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                        ' field "%(field)s": if format "%(format)s", no length "%(len)s".'
                    ),
                    {
                        "grammar": grammar_obj.grammarname,
                        "record": recordid,
                        "field": field[ID],
                        "format": field[FORMAT],
                        "len": field[LENGTH],
                    },
                )
            if isinstance(field[MINLENGTH], float):
                raise GrammarError(
                    _(
                        'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                        ' field "%(field)s": if format "%(format)s", no minlength "%(len)s".'
                    ),
                    {
                        "grammar": grammar_obj.grammarname,
                        "record": recordid,
                        "field": field[ID],
                        "format": field[FORMAT],
                        "len": field[MINLENGTH],
                    },
                )
    else:
        # check composite
        if not isinstance(field[SUBFIELDS], list):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s": is a composite field, has to have subfields.'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )
        if len(field[SUBFIELDS]) < 2:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in recorddefs, record "%(record)s",'
                    ' field "%(field)s" has < 2 sfields.'
                ),
                {"grammar": grammar_obj.grammarname, "record": recordid, "field": field[ID]},
            )


def checkstructure(grammar_obj, structure, mpath):
    """
    Recursive
    1.   Check structure.
    2.   Add keys: mpath, count
    """
    # pylint: disable=too-many-branches
    if not isinstance(structure, list):
        raise GrammarError(
            _('Grammar "%(grammar)s", in structure, at "%(mpath)s": not a list.'),
            {"grammar": grammar_obj.grammarname, "mpath": mpath},
        )
    for idx, i in enumerate(structure):
        if not isinstance(i, dict):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record should be a dict: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if ID not in i:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record without ID: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if not isinstance(i[ID], str):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' recordid of record is not a string: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if not i[ID]:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' recordid of record is empty: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if MIN not in i:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record without MIN: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if MAX not in i:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record without MAX: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if not isinstance(i[MIN], int):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record where MIN is not whole number: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if not isinstance(i[MAX], int):
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record where MAX is not whole number: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if not i[MAX]:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' MAX is zero: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": i},
            )
        if i[MIN] > i[MAX]:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure, at "%(mpath)s":'
                    ' record where MIN > MAX: "%(record)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": mpath, "record": str(i)[:100]},
            )
        i[MPATH] = mpath + [i[ID]]
        if LEVEL in i:
            checkstructure(grammar_obj, i[LEVEL], i[MPATH])
        structure[idx] = create_structure_node(i)


def checkbackcollision(grammar_obj, structure, collision=None):
    """
    Recursive.
    Check if grammar has back-collision problem.
    A message with collision problems is ambiguous.
    Case 1:  AAA BBB AAA
    Case 2:  AAA     BBB
             BBB CCC
    """
    if not collision:
        collision = []
    headerissave = False
    for i in structure:
        if i.id in collision:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure:'
                    ' back-collision detected at record "%(mpath)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": i.mpath},
            )
        if i.min_occ:
            headerissave = True
            if i.min_occ == i.max_occ:
                # so: fixed number of occurences;
                # can not lead to collision as is always clear where in structure record is
                # NOTE: this is mainly used for MIN=1, MAX=1
                collision = []
            else:
                # previous records do not cause collision.
                collision = [i.id]
        else:
            collision.append(i.id)
        if i.level:
            if i.min_occ == i.max_occ == 1:
                returncollision, returnheaderissave = checkbackcollision(grammar_obj, i.level)
            else:
                returncollision, returnheaderissave = checkbackcollision(
                    grammar_obj, i.level, [i.id]
                )
            collision.extend(returncollision)
            if returnheaderissave and i.id in collision:
                # one of segment(groups) is required,
                # there is always a segment after the header segment;
                # so remove header from nowcollision:
                collision.remove(i.id)
    # collision is used to update on higher level;
    # cleared indicates the header segment can not collide anymore
    return collision, headerissave


def checkbotscollision(grammar_obj, structure):
    """
    Recursive.
    Within one level: if twice the same tag: use BOTSIDNR.
    """
    collision = {}
    for i in structure:
        if i.id in collision:
            i.botsidnr = str(collision[i.id] + 1)
            collision[i.id] = collision[i.id] + 1
        else:
            i.botsidnr = "1"
            collision[i.id] = 1
        if i.level:
            checkbotscollision(grammar_obj, i.level)


def checknestedcollision(grammar_obj, structure, collision=None):
    """
    Recursive.
    Check if grammar has nested-collision problem.
    A message with collision problems is ambiguous.
    Case 1: AAA
            BBB CCC
                AAA
    """
    levelcollision = [] if not collision else collision[:]
    for i in reversed(structure):
        if i.level:
            if i.min_occ == i.max_occ == 1 or i.max_occ == 1:
                isa_safeheadersegment = checknestedcollision(grammar_obj, i.level, levelcollision)
            else:
                isa_safeheadersegment = checknestedcollision(
                    grammar_obj, i.level, levelcollision + [i.id]
                )
        else:
            isa_safeheadersegment = False
        if i.id in levelcollision and not isa_safeheadersegment:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", in structure:'
                    ' nesting collision detected at record "%(mpath)s".'
                ),
                {"grammar": grammar_obj.grammarname, "mpath": i.mpath},
            )
        if i.min_occ and not isa_safeheadersegment:
            # one of segment(groups) is required,
            # there is always a segment after the header segment;
            # so remove header from levelcollision:
            with contextlib.suppress(ValueError):
                levelcollision.remove(i.id)
        elif not i.min_occ:
            levelcollision.append(i.id)
    return not bool(levelcollision)
