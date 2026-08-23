from edi.core.bots.config.botsconfig import (
    BFORMAT,
    FORMAT,
    ID,
)
from edi.core.bots.domain.exceptions import GrammarError
from edi.core.bots.utils import botslib
from edi.core.bots.utils.botslib import gettext as _

ERROR_IN_GRAMMAR = "BOTS_error_1$%3@7#!%+_)_+[{]}"


class Grammar:
    def __init__(self, typeofgrammarfile, editype, grammarname):
        """import grammar; read syntax"""
        self.editype = editype
        self.module, self.grammarname = botslib.botsimport(typeofgrammarfile, editype, grammarname)
        # get syntax from grammar file
        self.original_syntaxfromgrammar = getattr(self.module, "syntax", {})
        if not isinstance(self.original_syntaxfromgrammar, dict):
            raise GrammarError(
                _('Grammar "%(grammar)s": syntax is not a dict{}.'), {"grammar": self.grammarname}
            )
        self.syntax = self.original_syntaxfromgrammar

    def class_specific_tests(self):
        """default function, subclasses have the actual checks."""

    def display(self, structure, level=0):
        """
        Draw grammar, with indentation for levels.
        For debugging.
        """
        for i in structure:
            print("Record: ", i.mpath, i)
            for field in i.fields:
                print("    Field: ", field)
            if i.level:
                self.display(i.level, level + 1)

    def _manipulatefieldformat(self, field, recordid):
        try:
            field[BFORMAT] = self.formatconvert[field[FORMAT]]
        except KeyError as exc:
            raise GrammarError(
                _(
                    'Grammar "%(grammar)s", record "%(record)s", field "%(field)s":'
                    ' format "%(format)s" has to be one of "%(keys)s".'
                ),
                {
                    "grammar": self.grammarname,
                    "record": recordid,
                    "field": field[ID],
                    "format": field[FORMAT],
                    "keys": self.formatconvert.keys(),
                },
            ) from exc
