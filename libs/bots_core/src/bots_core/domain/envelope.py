"""
Bots enveloppe lib
"""
# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, import-outside-toplevel, duplicate-code
# flake8: noqa:E501

import json as simplejson
import os
import shutil

# bots-modules
from bots_core.infrastructure.config import botsglobal
from bots_core.utils import botslib
from bots_core.domain import outmessage
from bots_core.infrastructure.config.botsconfig import ID, FIELDS, OK, DONE, ERROR
from bots_core.utils.botslib import gettext as _
from bots_core.domain.exceptions import BotsImportError, OutMessageError, txtexc


def mergemessages(startstatus, endstatus, idroute, rootidta=None, **kwargs):
    """
    Merges and/or envelopes one or more messages to one file (status TRANSLATED---->MERGED).
    Attribute 'merge' indicates message should be merged with similar messages (or not).
    If merge is False: 1 message per envelope - no merging 'merge' comes from db-ta;
    added in translation via from syntax of outgoing message (envelope, message, partner).
    Merge/not merge is implemented as separate loops:
        one for merge&envelope, another for enveloping only
    """
    # pylint: disable=broad-exception-caught
    if rootidta is None:
        rootidta = botsglobal.currentrun.get_minta4query()
    # **********for messages only to envelope (no merging)
    # editype,messagetype: needed to get right envelope
    # envelope: envelope to use
    # frompartner,topartner,testindicator,charset,nrmessages: needed for envelope (edifact, x12)
    # idta: ID of the db-ta
    # filename: file to envelope
    for row in botslib.query(
            """SELECT editype,
                      messagetype,
                      envelope,
                      frompartner,
                      topartner,
                      testindicator,
                      charset,
                      nrmessages,
                      idta,
                      filename,
                      rsrv3,
                      rsrv5
            FROM ta
            WHERE idta>%(rootidta)s
            AND status=%(status)s
            AND statust=%(statust)s
            AND merge=%(merge)s
            AND idroute=%(idroute)s
            ORDER BY idta
            """,
            {
                'rootidta': rootidta,
                'status': startstatus,
                'statust': OK,
                'merge': False,
                'idroute': idroute,
            }):
        try:
            ta_info = dict(row)
            ta_fromfile = botslib.OldTransaction(ta_info['idta'])
            # copy db_ta
            ta_tofile = ta_fromfile.copyta(status=endstatus)
            # create filename for enveloped message
            ta_info["filename"] = str(ta_tofile.idta)
            ta_info['idroute'] = idroute
            botsglobal.logger.debug(
                'Envelope 1 message editype: %(editype)s, messagetype: %(messagetype)s.', ta_info
            )
            envelope(ta_info, [row["filename"]], **kwargs)
            ta_info['filesize'] = os.path.getsize(botslib.abspathdata(ta_info['filename']))
        except Exception:
            txt = txtexc()
            ta_tofile.update(statust=ERROR, errortext=txt)
        else:
            # selection is used to update enveloped message;
            ta_tofile.update(statust=OK, **ta_info)
        finally:
            ta_fromfile.update(statust=DONE)

    # **********for messages to merge & envelope
    # editype,messagetype: needed to get right envelope
    # envelope: envelope to use
    # rsrv3 : user defined enveloping criterium
    # frompartner,topartner,testindicator,charset,nrmessages: needed for envelope (edifact, x12)
    for row in botslib.query(
            """SELECT editype,messagetype,envelope,rsrv3,frompartner,topartner,
                      testindicator,charset,rsrv5,sum(nrmessages) as nrmessages
               FROM ta
               WHERE idta>%(rootidta)s
               AND status=%(status)s
               AND statust=%(statust)s
               AND merge=%(merge)s
               AND idroute=%(idroute)s
               GROUP BY editype,messagetype,envelope,rsrv3,frompartner,topartner,testindicator,charset,rsrv5
               ORDER BY editype,messagetype,envelope,rsrv3,frompartner,topartner,testindicator,charset,rsrv5
            """,
            {
                'rootidta': rootidta,
                'status': startstatus,
                'statust': OK,
                'merge': True,
                'idroute': idroute,
            }):
        try:
            ta_info = dict(row)
            ta_info['idroute'] = idroute
            # do another query to gather individual idta and filenames
            filename_list = []
            for row2 in botslib.query(
                    """SELECT idta, filename
                       FROM ta
                       WHERE idta>%(rootidta)s
                       AND status=%(status)s
                       AND statust=%(statust)s
                       AND merge=%(merge)s
                       AND editype=%(editype)s
                       AND messagetype=%(messagetype)s
                       AND (frompartner=%(frompartner)s OR frompartner IS NULL)
                       AND (topartner=%(topartner)s OR topartner IS NULL)
                       AND testindicator=%(testindicator)s
                       AND envelope=%(envelope)s
                       AND rsrv3=%(rsrv3)s
                       AND charset=%(charset)s
                       ORDER BY idta
                    """,
                    {
                        'rootidta': rootidta,
                        'status': startstatus,
                        'statust': OK,
                        'merge': True,
                        'editype': ta_info['editype'],
                        'messagetype': ta_info['messagetype'],
                        'frompartner': ta_info['frompartner'],
                        'topartner': ta_info['topartner'],
                        'testindicator': ta_info['testindicator'],
                        'charset': ta_info['charset'],
                        'rsrv3': ta_info['rsrv3'],
                        'envelope': ta_info['envelope'],
                    }):
                ta_fromfile = botslib.OldTransaction(row2["idta"])
                # edi message to be merged/envelope
                if not filename_list:  # if first time in loop
                    # copy db_ta; parent=0 as enveloping works via child, not parent
                    ta2_tofile = ta_fromfile.copyta(status=endstatus, parent=0)
                    ta_info["filename"] = str(ta2_tofile.idta)
                ta_fromfile.update(
                    child=ta2_tofile.idta, statust=DONE
                )  # add child because of n->1 relation
                filename_list.append(row2["filename"])
            botsglobal.logger.debug(
                'Merge and envelope: editype: %(editype)s, messagetype:'
                ' %(messagetype)s, %(nrmessages)s messages',
                ta_info,
            )
            envelope(ta_info, filename_list, **kwargs)
            ta_info['filesize'] = os.path.getsize(botslib.abspathdata(ta_info['filename']))
        except Exception:
            txt = txtexc()
            ta2_tofile.update(statust=ERROR, errortext=txt)
        else:
            ta2_tofile.update(statust=OK, **ta_info)


def envelope(ta_info, ta_list, **kwargs):
    """
    dispatch function for class Envelope and subclasses.
    editype, edimessage and envelope essential for enveloping.

    How is enveloping determined:
    1.  no enveloping: ta_info['envelope'] is '' (or None)
        -   file(s) is/are just copied.
        -   no user scripting for envelope.
    2.  user scripted: there is a file in bots/envelopescripts/ta_info['editype']/ta_info['envelope'].py
            (and has to have a class ta_info['envelope'])
        -   user exits extends/replaces default enveloping.
            syntax:
                - grammar.editype.envelope (alt could be envelopescripts.editype.envelope;
                  but this is inline with incoming)
                - grammar.editype.messagetype
    3.  default envelope: if ta_info['editype'] is a class in this module, use it.
            script: - envelope.editype
            syntax: - grammar.editype.envelope
                    - grammar.editype.messagetype
    """
    userscript = scriptname = None
    if not ta_info.get('envelope'):
        # 1. no enveloping
        classtocall = noenvelope
    else:
        try:
            # check for user scripted enveloping
            userscript, scriptname = botslib.botsimport(
                'envelopescripts', ta_info['editype'], ta_info['envelope']
            )
            # 2. user scripted. If userscript does not have class ta_info['envelope']
            # no error is given - file can have other functions in it.
            classtocall = getattr(userscript, ta_info['envelope'], None)

        except BotsImportError:
            # 3. default envelope
            classtocall = None

        if classtocall is None:
            try:
                classtocall = globals()[ta_info['editype']]
            except KeyError as exc:
                raise OutMessageError(
                    _('Not found envelope "%(envelope)s" for editype "%(editype)s".'), ta_info) from exc

    info_from_mapping = simplejson.loads(ta_info['rsrv5']) if ta_info['rsrv5'] else {}
    env = classtocall(
        ta_info, ta_list, userscript, scriptname,
        info_from_mapping.get('envelope_content') or [{}, {}, {}, {}],
        info_from_mapping.get('syntax') or {},
        **kwargs
    )
    env.run()


class Envelope:
    """Base Class for enveloping; use subclasses."""
    # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-instance-attributes

    def __init__(
            self,
            ta_info, ta_list, userscript, scriptname,
            envelope_content, syntax, **kwargs):
        self.ta_info = ta_info
        self.ta_list = ta_list
        self.userscript = userscript
        self.scriptname = scriptname
        # dict with envelope data from mapping script
        self.envelope_content = envelope_content
        # dict with syntax data from mapping script
        self.syntax = syntax
        self.routedict = kwargs.get('routedict', {})

    def _openoutenvelope(self):
        """make an outmessage object; read the grammar."""
        # pylint: disable=attribute-defined-outside-init
        # self.ta_info contains information from ta:
        # editype, messagetype,testindicator,charset,envelope
        # make outmessage object.
        self.out = outmessage.outmessage_init(**self.ta_info)
        # read grammar for envelopesyntax. Remark: self.ta_info is not updated.
        self.out.messagegrammarread(typeofgrammarfile='envelope')

    def writefilelist(self, tofile):
        for filename in self.ta_list:
            with botslib.opendata(filename, "r", self.ta_info["charset"]) as fromfile:
                shutil.copyfileobj(fromfile, tofile, 1048576)

    def filelist2absolutepaths(self):
        """utility function; some classes need absolute filenames eg for xml-including"""
        return [botslib.abspathdata(filename) for filename in self.ta_list]

    def check_envelope_partners(self):
        """check if partners are known."""
        if not self.ta_info['frompartner']:
            raise OutMessageError(_('In enveloping "frompartner" unknown.'))
        if not self.ta_info['topartner']:
            raise OutMessageError(_('In enveloping "topartner" unknown.'))


class noenvelope(Envelope):
    """Only copies the input files to one output file."""

    def run(self):
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
        )
        if len(self.ta_list) > 1:
            with botslib.opendata(self.ta_info["filename"], "w", self.ta_info["charset"]) as tofile:
                self.writefilelist(tofile)
        else:
            self.ta_info['filename'] = self.ta_list[0]


class fixed(noenvelope):
    pass


class csv(noenvelope):
    def run(self):
        if self.ta_info['envelope'] == 'csvheader':
            # Adds first line to csv files with fieldnames; than write files.
            self._openoutenvelope()
            botslib.tryrunscript(
                self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
            )
            # Add headers
            self.out.put(dict(
                (field[ID], field[ID]) for field in self.out.defmessage.structure[0][FIELDS]
            ))
            self.out.tree2records(self.out.root)
            with botslib.opendata(self.ta_info["filename"], "w", self.ta_info["charset"]) as tofile:
                tofile.write(self.out.record2string(self.out.lex_records[0:1]))
                self.writefilelist(tofile)
        else:
            super().run()


class edifact(Envelope):
    """Generate UNB and UNZ segment; fill with data, write to interchange-file.
    partners:
      1. partner from database -> find syntax
      2. order of priority in suing partner data from differnt sources:
        1. envelope_content (from mapping)
        2. syntax
        3. via database (ta_info)
    """

    def run(self):
        self.check_envelope_partners()
        self._openoutenvelope()
        self.ta_info.update(self.out.ta_info)
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
        )

        # frompartner
        UNBsender = self.envelope_content[0].get('S002.0004') \
            or self.ta_info.get('S002.0004') \
            or self.ta_info['frompartner']
        UNBsender_qualifier = self.envelope_content[0].get('S002.0007') or self.ta_info['UNB.S002.0007']

        # topartner
        UNBreceiver = self.envelope_content[0].get('S003.0010') \
            or self.ta_info.get('S003.0010') \
            or self.ta_info['topartner']
        UNBreceiver_qualifier = self.envelope_content[0].get('S003.0007') or self.ta_info['UNB.S003.0007']

        # version dependent enveloping
        self.ta_info['version'] = self.envelope_content[0].get('S001.0002') or self.ta_info['version']
        if self.ta_info['version'] < '4':
            senddate = botslib.strftime('%y%m%d')
            reserve = ' '
        else:
            senddate = botslib.strftime('%Y%m%d')
            reserve = self.ta_info['reserve']

        # UNB reference: set from mapping or (counter per sender or receiver)
        # pylint: disable=consider-using-f-string
        self.ta_info['reference'] = self.envelope_content[0].get('0020') or botslib.unique(
            'unbcounter_%s%s' % (UNBsender, '_%s' % UNBreceiver if botsglobal.ini.getboolean(
                'settings', 'interchangecontrolperpartner', False) else ''))

        # testindicator:
        testindicator = ''
        # first check value from ta; do not use default
        # 1. set from mapping
        if self.envelope_content[0].get('0035') and self.envelope_content[0].get('0035') != '0':
            testindicator = '1'
        # 2. set from ta/database
        elif self.ta_info['testindicator'] and self.ta_info['testindicator'] != '0':
            testindicator = '1'
        # 3. set from syntax
        elif self.ta_info['UNB.0035'] != '0':
            testindicator = '1'

        # build the envelope tree/tree
        self.out.put({
            'BOTSID': 'UNB',
            'S001.0001': self.envelope_content[0].get('S001.0001') or self.ta_info['charset'],
            'S001.0002': self.envelope_content[0].get('S001.0002') or self.ta_info['version'],
            'S001.0080': self.envelope_content[0].get('S001.0080') or self.ta_info['UNB.S001.0080'],
            'S001.0133': self.envelope_content[0].get('S001.0133') or self.ta_info['UNB.S001.0133'],
            'S002.0004': UNBsender,
            'S002.0007': UNBsender_qualifier,
            'S002.0008': self.envelope_content[0].get('S002.0008') or self.ta_info['UNB.S002.0008'],
            'S002.0042': self.envelope_content[0].get('S002.0042') or self.ta_info['UNB.S002.0042'],
            'S003.0010': UNBreceiver,
            'S003.0007': UNBreceiver_qualifier,
            'S003.0014': self.envelope_content[0].get('S003.0014') or self.ta_info['UNB.S003.0014'],
            'S003.0046': self.envelope_content[0].get('S003.0046') or self.ta_info['UNB.S003.0046'],
            'S004.0017': self.envelope_content[0].get('S004.0017') or senddate,
            'S004.0019': self.envelope_content[0].get('S004.0019') or botslib.strftime('%H%M'),
            '0020':      self.ta_info['reference'],
            'S005.0022': self.envelope_content[0].get('S005.0022') or self.ta_info['UNB.S005.0022'],
            'S005.0025': self.envelope_content[0].get('S005.0025') or self.ta_info['UNB.S005.0025'],
            '0026':      self.envelope_content[0].get('0026') or self.ta_info['UNB.0026'],
            '0029':      self.envelope_content[0].get('0029') or self.ta_info['UNB.0029'],
            '0031':      self.envelope_content[0].get('0031') or self.ta_info['UNB.0031'],
            '0032':      self.envelope_content[0].get('0032') or self.ta_info['UNB.0032'],
            '0035':      testindicator,
        })
        self.out.put(
            {'BOTSID': 'UNB'},
            {
                'BOTSID': 'UNZ',
                '0036': self.ta_info['nrmessages'],
                '0020': self.ta_info['reference'],
            },
        )
        # user exit to change data in tree/segments
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'envelopecontent', ta_info=self.ta_info, out=self.out
        )
        # convert tree to segments
        self.out.checkmessage(self.out.root, self.out.defmessage)
        self.out.checkforerrorlist()
        self.out.tree2records(self.out.root)

        # write to file:
        with botslib.opendata(self.ta_info["filename"], "w", self.ta_info["charset"]) as tofile:
            if self.ta_info['forceUNA'] or self.ta_info['charset'] != 'UNOA':
                # write UNA, hardcoded.
                tofile.write(
                    'UNA'
                    + self.ta_info['sfield_sep']
                    + self.ta_info['field_sep']
                    + self.ta_info['decimaal']
                    + self.ta_info['escape']
                    + reserve
                    + self.ta_info['record_sep']
                    + self.ta_info['add_crlfafterrecord_sep']
                )
            # write UNB
            tofile.write(self.out.record2string(self.out.lex_records[0:1]))
            # write edifact messages
            self.writefilelist(tofile)
            # write UNZ
            tofile.write(self.out.record2string(self.out.lex_records[1:2]))


class tradacoms(Envelope):
    """Generate STX and END segment; fill with appropriate data, write to interchange file."""

    def run(self):
        """
        determine partnrIDs. either from mapping (via self.envelope_content)
        or database (via self.ta_info). Check: partnerIDs are required
        """
        self.check_envelope_partners()
        self._openoutenvelope()
        self.ta_info.update(self.out.ta_info)
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
        )
        # prepare data for envelope
        # frompartner
        sender = self.envelope_content[0].get('FROM.01') or self.ta_info.get('FROM.01') or self.ta_info['frompartner']

        # topartner
        receiver = self.envelope_content[0].get('UNTO.01') or self.ta_info.get('UNTO.01') or self.ta_info['topartner']

        # reference
        # pylint: disable=consider-using-f-string
        self.ta_info['reference'] = self.envelope_content[0].get('SNRF') or botslib.unique(
            'stxcounter_%s%s' % (sender, '_%s' % receiver if botsglobal.ini.getboolean(
                'settings', 'interchangecontrolperpartner', False) else ''))

        # build the envelope segments (that is, the tree from which the segments will be generated)
        self.out.put(
            {
                'BOTSID': 'STX',
                'STDS1': self.ta_info['STX.STDS1'],
                'STDS2': self.ta_info['STX.STDS2'],
                'FROM.01': sender,
                'UNTO.01': receiver,
                'TRDT.01': botslib.strftime('%y%m%d'),
                'TRDT.02': botslib.strftime('%H%M%S'),
                'SNRF': self.ta_info['reference'],
            }
        )
        if self.ta_info['STX.FROM.02']:
            self.out.put({'BOTSID': 'STX', 'FROM.02': self.ta_info['STX.FROM.02']})
        if self.ta_info['STX.UNTO.02']:
            self.out.put({'BOTSID': 'STX', 'UNTO.02': self.ta_info['STX.UNTO.02']})
        if self.ta_info['STX.APRF']:
            self.out.put({'BOTSID': 'STX', 'APRF': self.ta_info['STX.APRF']})
        if self.ta_info['STX.PRCD']:
            self.out.put({'BOTSID': 'STX', 'PRCD': self.ta_info['STX.PRCD']})
        # dummy segment; is not used
        self.out.put({'BOTSID': 'STX'}, {'BOTSID': 'END', 'NMST': self.ta_info['nrmessages']})
        # user exit
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'envelopecontent', ta_info=self.ta_info, out=self.out
        )
        # convert the tree into segments; here only the STX is written (first segment)
        self.out.checkmessage(self.out.root, self.out.defmessage)
        self.out.checkforerrorlist()
        self.out.tree2records(self.out.root)

        # start doing the actual writing:
        with botslib.opendata(self.ta_info["filename"], "w", self.ta_info["charset"]) as tofile:
            tofile.write(self.out.record2string(self.out.lex_records[0:1]))
            self.writefilelist(tofile)
            tofile.write(self.out.record2string(self.out.lex_records[1:2]))


class templatehtml(Envelope):
    """
    class for outputting edi as html (browser, email).
    Uses a genshi-template for the enveloping/merging.
    """

    def run(self):
        template_engine = self.ta_info.get('template_engine', 'genshi')
        if template_engine == 'django':
            from django.template.loader import get_template
        elif template_engine == 'genshi':
            try:
                from genshi.template import TemplateLoader
            except ModuleNotFoundError as exc:
                raise ImportError(
                    'Dependency failure: editype "templatehtml" requires python library "genshi".'
                ) from exc
        else:
            raise OutMessageError(f"template_engine unknown or unset: {template_engine}")
        self._openoutenvelope()
        self.ta_info.update(self.out.ta_info)
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
        )
        if not self.ta_info['envelope-template']:
            raise OutMessageError(
                _(
                    'While enveloping in "%(editype)s.%(messagetype)s":'
                    ' syntax option "envelope-template" not filled; is required.'
                ),
                self.ta_info,
            )
        templatefile = botslib.abspath(self.__class__.__name__, self.ta_info['envelope-template'])
        ta_list = self.filelist2absolutepaths()
        try:
            botsglobal.logger.debug('Start writing envelope to file "%(filename)s".', self.ta_info)
            if template_engine == 'django':
                tmpl = get_template(templatefile)
            elif template_engine == 'genshi':
                loader = TemplateLoader(auto_reload=False)
                tmpl = loader.load(templatefile)
        except Exception as exc:
            txt = txtexc()
            raise OutMessageError(
                _('While enveloping in "%(editype)s.%(messagetype)s", error:\n%(txt)s'),
                {
                    'editype': self.ta_info['editype'],
                    'messagetype': self.ta_info['messagetype'],
                    'txt': txt,
                },
            ) from exc
        try:
            context = {'data': ta_list, 'ta_info': self.ta_info}
            if template_engine == 'django':
                with botslib.opendata(self.ta_info['filename'], 'w', self.ta_info['charset']) as filehandler:
                    filehandler.write(tmpl.render(context))
            elif template_engine == 'genshi':
                stream = tmpl.generate(**context)
                with botslib.opendata_bin(self.ta_info['filename'], 'wb') as filehandler:
                    stream.render(method='xhtml', encoding=self.ta_info['charset'], out=filehandler)
        except Exception as exc:
            txt = txtexc()
            raise OutMessageError(
                _('While enveloping in "%(editype)s.%(messagetype)s", error:\n%(txt)s'),
                {
                    'editype': self.ta_info['editype'],
                    'messagetype': self.ta_info['messagetype'],
                    'txt': txt,
                },
            ) from exc
        finally:
            botsglobal.logger.debug(_('End html enveloping file "%(filename)s".'), self.ta_info)


class x12(Envelope):
    """Generate envelope segments; fill with appropriate data, write to interchange-file.
    partners:
      1. partner from database -> find syntax
      2. order of priority in suing partner data from differnt sources:
        1. envelope_content (from mapping)
        2. syntax
        3. via database (ta_info)
    """

    def run(self):
        # pylint: disable=too-many-locals
        self.check_envelope_partners()
        # read grammars, including partner syntax.
        # Partners from database (in ta_info) are used to find partner syntax
        self._openoutenvelope()
        self.ta_info.update(self.out.ta_info)

        # user exit to change ta_info
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'ta_infocontent', ta_info=self.ta_info
        )

        # test indicator can either be from configuration (self.ta_info['ISA15'])
        # or by mapping (self.ta_info['testindicator']); mapping overrules.
        if self.ta_info['testindicator'] and self.ta_info['testindicator'] != '0':
            # value from db/mapping; '0' is default value: if set in db and not default:
            testindicator = self.envelope_content[0].get('ISA15') or self.ta_info['testindicator']
        else:
            testindicator = self.envelope_content[0].get('ISA15') or self.ta_info['ISA15']

        # frompartner
        ISAsender_qualifier = self.envelope_content[0].get('ISA05') or self.ta_info['ISA05']
        ISAsender = self.envelope_content[0].get('ISA06') or self.ta_info.get('ISA06') or self.ta_info['frompartner']
        GS02sender = self.envelope_content[1].get('GS02') or self.ta_info.get('GS02') or self.ta_info['frompartner']

        # topartner
        ISAreceiver_qualifier = self.envelope_content[0].get('ISA07') or self.ta_info['ISA07']
        ISAreceiver = self.envelope_content[0].get('ISA08') or self.ta_info.get('ISA08') or self.ta_info['topartner']
        GS03receiver = self.envelope_content[1].get('GS03') or self.ta_info.get('GS03') or self.ta_info['topartner']

        # ISA/GS reference: set from mapping or (counter per sender or receiver)
        # pylint: disable=consider-using-f-string
        self.ta_info['reference'] = self.envelope_content[0].get('ISA13') or botslib.unique(
            'isacounter_%s%s' % (ISAsender, '_%s' % ISAreceiver if botsglobal.ini.getboolean(
                'settings', 'interchangecontrolperpartner', False) else ''))

        # date and time
        senddate, sendtime = botslib.strftime('%Y%m%d %H%M').split(' ')

        # version
        version = self.envelope_content[0].get('ISA12') or self.ta_info['version']

        # ISA14 - Ask Acknowledgment
        ask_confirm = self.envelope_content[0].get('ISA14') or '1' if botslib.checkconfirmrules(
            'ask-x12-997',
            idroute=self.ta_info.get('idroute'),
            idchannel=self.routedict.get('tochannel'),
            frompartner=self.ta_info.get('frompartner'),
            topartner=self.ta_info.get('topartner'),
            messagetype=self.ta_info.get('messagetype')
        ) else self.ta_info['ISA14']

        # build the envelope segments (generate tree from which the segments will be generated)
        self.out.put(
            {
                'BOTSID': 'ISA',
                'ISA01': self.envelope_content[0].get('ISA01') or self.ta_info['ISA01'],
                'ISA02': self.envelope_content[0].get('ISA02') or self.ta_info['ISA02'],
                'ISA03': self.envelope_content[0].get('ISA03') or self.ta_info['ISA03'],
                'ISA04': self.envelope_content[0].get('ISA04') or self.ta_info['ISA04'],
                'ISA05': ISAsender_qualifier,
                'ISA06': ISAsender.ljust(15),  # add spaces; is fixed length
                'ISA07': ISAreceiver_qualifier,
                'ISA08': ISAreceiver.ljust(15),  # add spaces; is fixed length
                'ISA09': self.envelope_content[0].get('ISA09') or senddate[2:],
                'ISA10': self.envelope_content[0].get('ISA10') or sendtime,
                # if ISA version > 00403, replaced by repertion separator (below, hardcoded)
                'ISA11': self.envelope_content[0].get('ISA11') or self.ta_info['ISA11'],
                'ISA12': version,
                'ISA13': self.ta_info['reference'],
                'ISA14': ask_confirm,
                'ISA15': testindicator,
            },
            # MIND: strip=False: ISA fields should not be stripped as it is fixed-length
            strip=False,
        )
        self.out.put(
            {'BOTSID': 'ISA'}, {'BOTSID': 'IEA', 'IEA01': '1', 'IEA02': self.ta_info['reference']}
        )

        gs06reference = self.envelope_content[1].get('GS06') or self.ta_info['reference']
        # GS08 is message version + extension. so: 850004010VICS -> 004010VICS
        gs08messagetype = self.envelope_content[1].get("GS08") or self.ta_info["messagetype"].split(".")[-1][3:]
        self.out.put(
            {'BOTSID': 'ISA'},
            {
                'BOTSID': 'GS',
                'GS01': self.envelope_content[1].get('GS01') or self.ta_info['functionalgroup'],
                'GS02': GS02sender,
                'GS03': GS03receiver,
                "GS04": (
                    self.envelope_content[1].get("GS04") or
                    senddate if gs08messagetype[:6] >= "004010" else senddate[2:]
                ),
                'GS05': self.envelope_content[1].get('GS05') or sendtime,
                'GS06': gs06reference,
                'GS07': self.envelope_content[1].get('GS07') or self.ta_info['GS07'],
                'GS08': gs08messagetype,
            },
        )
        self.out.put(
            {'BOTSID': 'ISA'},
            {'BOTSID': 'GS'},
            {'BOTSID': 'GE', 'GE01': self.ta_info['nrmessages'], 'GE02': gs06reference},
        )

        # user exit to change data in tree/segments
        botslib.tryrunscript(
            self.userscript, self.scriptname, 'envelopecontent', ta_info=self.ta_info, out=self.out
        )
        # convert the tree into segments; here only the UNB is written (first segment)
        self.out.checkmessage(self.out.root, self.out.defmessage)
        self.out.checkforerrorlist()
        self.out.tree2records(self.out.root)

        # ISA has the used separators at certain positions.
        isa_string = self.out.record2string(self.out.lex_records[0:1])
        # Bots would give errors for this (can not use sep as data) or compress these away.
        # So this is hardcoded.
        if self.ta_info['version'] < '00403':
            isa_string = (
                isa_string[:103]
                + self.ta_info['field_sep']
                + self.ta_info['sfield_sep']
                + isa_string[103:]
            )
        else:
            isa_string = (
                isa_string[:82]
                + self.ta_info['reserve']
                + isa_string[83:103]
                + self.ta_info['field_sep']
                + self.ta_info['sfield_sep']
                + isa_string[103:]
            )

        # start doing the actual writing:
        with botslib.opendata(self.ta_info["filename"], "w", self.ta_info["charset"]) as tofile:
            # write ISA
            tofile.write(isa_string)
            # write GS
            tofile.write(self.out.record2string(self.out.lex_records[1:2]))
            self.writefilelist(tofile)
            # write GE and IEA
            tofile.write(self.out.record2string(self.out.lex_records[2:]))


class json(noenvelope):
    def writefilelist(self, tofile):
        """Merge all json messages to a json list"""
        tofile.write("[")
        last = len(self.ta_list) - 1
        for i, filename in enumerate(self.ta_list):
            with botslib.opendata(filename, "r", self.ta_info["charset"]) as fromfile:
                tofile.write(fromfile.read().strip("[]"))
                if i < last:
                    tofile.write(",")
        tofile.write("]")


class jsonnocheck(json):
    pass


class xmlnocheck(noenvelope):
    pass


class xml(noenvelope):
    pass


class db(noenvelope):
    pass


class raw(noenvelope):
    pass
