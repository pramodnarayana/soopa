"""
Bots router lib
"""
# pylint: disable=invalid-name

# bots-modules
from bots_core.infrastructure.config import botsglobal
from bots_core.utils import botslib
from bots_core.domain import envelope
from bots_core.application.use_cases import preprocess
from bots_core.application.use_cases import transform
from bots_core.infrastructure.config.botsconfig import (
    OK,
    DONE,
    ERROR,
    FILEIN,
    FILEOUT,
    PROCESS,
    EXTERNIN,
    EXTERNOUT,
    MERGED,
    TRANSLATED,
    RESEND,
)
from bots_core.utils.botslib import gettext as _
from bots_core.infrastructure.config.botsinit import LOG_LEVELS
from bots_core.domain.exceptions import BotsImportError, ScriptError


@botslib.log_session
def rundispatcher(command, routestorun):
    """one run for each command"""
    # get the route class from this module
    classtocall = globals()[command]
    botsglobal.currentrun = classtocall(command, routestorun)
    if botsglobal.currentrun.run():
        # return result of evaluation of run: nr of errors, 0 (no error)
        return botsglobal.currentrun.evaluate()
    botsglobal.logger.info(_('Nothing to do in run.'))
    # return 0 (no error)
    return 0


class new:
    """New route run"""
    def __init__(self, command, routestorun):
        self.routestorun = routestorun
        self.command = command
        # the idta of rundispatcher is rootidta of run
        self.minta4query = botslib._Transaction.processlist[-1]
        self.minta4query_crash = None
        self.keep_track_if_outchannel_deferred = {}
        self.userscript = None
        self.scriptname = None

    def run(self):
        """
        call self.router(route) for each route in self.routestorun.
        """
        for route in self.routestorun:
            botslib.setrouteid(route)
            self.router(route)
            botslib.setrouteid('')
        return True

    @botslib.log_session
    def router(self, route):
        """
        for each route (as in self.routestorun).
        a route can have multiple parts (seq)
        """
        # is there a user routescript?
        try:
            self.userscript, self.scriptname = botslib.botsimport('routescripts', route)
        except BotsImportError:
            # routescript is not there; other errors like syntax errors are not catched
            self.userscript = self.scriptname = None

        foundroute = False
        for row in botslib.query(
                """SELECT idroute,
                          fromchannel_id as fromchannel,
                          tochannel_id as tochannel,
                          fromeditype,
                          frommessagetype,
                          alt,
                          frompartner_id as frompartner,
                          topartner_id as topartner,
                          toeditype,
                          tomessagetype,
                          seq,
                          frompartner_tochannel_id,
                          topartner_tochannel_id,
                          testindicator,
                          translateind,
                          defer,
                          zip_incoming,
                          zip_outgoing
                FROM routes
                WHERE idroute=%(idroute)s
                AND active=%(active)s
                ORDER BY seq""",
                {'idroute': route, 'active': True}):
            # convert to real dictionary (as self.command is added to routedict)
            routedict = dict(row)
            # this way command is passed to ohter functions.
            routedict['command'] = self.command
            foundroute = True
            botsglobal.logger.log(
                LOG_LEVELS['START'], _('Running route: %(idroute)s %(seq)s'), routedict)
            self.routepart(routedict)
            # handle deferred-logic: mark if channel is deffered, umark if run
            self.keep_track_if_outchannel_deferred[routedict['tochannel']] = routedict['defer']
            botsglobal.logger.log(
                LOG_LEVELS['DONE'], _('Finished route: %(idroute)s %(seq)s'), routedict)
        if not foundroute:
            message = _('There is no (active) route "%(route)s".')
            botsglobal.logger.critical(message, {'route': route})
            botslib.sendbotserrorreport(message, {'route': route})

    @botslib.log_session
    def routepart(self, routedict):
        """
        communication.run one route part. variants:
         - a route can be a routescript
         - a route can do only incoming
         - a route can do only outgoing
         - a route can do both incoming and outgoing
         - at several points functions from a routescript are called - if function is in routescript
        """
        # pylint: disable=too-many-branches, too-many-statements
        # if routescript has function 'main': communication.run 'main' (and do nothing else)
        if botslib.tryrunscript(self.userscript, self.scriptname, 'main', routedict=routedict):
            # so: if function ' main' : communication.run only the routescript, nothing else.
            return
        if not (
                self.userscript
                or routedict['fromchannel']
                or routedict['tochannel']
                or routedict['translateind']):

            raise ScriptError(
                _('Route "%(idroute)s" is empty: no routescript, not enough parameters.'), routedict
            )

        botslib.tryrunscript(self.userscript, self.scriptname, 'start', routedict=routedict)

        # incoming part of route:
        # - incommunication
        # - assign attributes from route to incoming files
        # - preprocessing
        #
        # tricky is what should be picked up in each step.
        # edi-files can be:
        # - via inchannel
        # - re-received
        # - injected - out via web API, web API gives reponse that is in itself an inbound file (eg ordrsp)
        rootidta = self.get_minta4query()
        if routedict['fromchannel']:
            # only done for edi files from this route-part, this inchannel
            botslib.tryrunscript(
                self.userscript, self.scriptname, 'preincommunication', routedict=routedict
            )
            # communication.run is stripped in the native implementation
            # add attributes from route to the received files;
            where = {
                'statust': OK,
                'status': FILEIN,
                'fromchannel': routedict['fromchannel'],
                'idroute': routedict['idroute'],
                'rootidta': rootidta,
            }
            change = {
                'editype': routedict['fromeditype'],
                'messagetype': routedict['frommessagetype'],
                'frompartner': routedict['frompartner'],
                'topartner': routedict['topartner'],
                'alt': routedict['alt'],
            }
            nr_of_incoming_files_for_channel = botslib.updateinfo(change=change, where=where)
            botslib.tryrunscript(
                self.userscript, self.scriptname, 'postincommunication', routedict=routedict
            )
            if nr_of_incoming_files_for_channel:
                # unzip incoming files (if indicated)
                if routedict['zip_incoming'] == 1:
                    # unzip incoming (non-zipped gives error).
                    preprocess.preprocess(
                        routedict=routedict,
                        function=preprocess.botsunzip,
                        rootidta=rootidta,
                        pass_non_zip=False,
                    )
                elif routedict['zip_incoming'] == 2:
                    # unzip incoming if zipped.
                    preprocess.preprocess(
                        routedict=routedict,
                        function=preprocess.botsunzip,
                        rootidta=rootidta,
                        pass_non_zip=True,
                    )
                # run mailbag-module.
                if botsglobal.ini.getboolean('settings', 'compatibility_mailbag', False):
                    editypes_via_mailbag = ['mailbag']
                else:
                    editypes_via_mailbag = ['mailbag', 'edifact', 'x12', 'tradacoms']
                if routedict['fromeditype'] in editypes_via_mailbag:
                    # mailbag for the route.
                    preprocess.preprocess(
                        routedict=routedict,
                        function=preprocess.mailbag,
                        rootidta=rootidta,
                        frommessagetype=routedict['frommessagetype'],
                    )

        # translate, merge, pass through: INFILE->MERGED
        if routedict['translateind'] in [1, 3]:
            # translate: for files in route
            botslib.tryrunscript(
                self.userscript, self.scriptname, 'pretranslation', routedict=routedict
            )
            transform.translate(
                startstatus=FILEIN, endstatus=TRANSLATED, routedict=routedict, rootidta=rootidta
            )
            botslib.tryrunscript(
                self.userscript, self.scriptname, 'posttranslation', routedict=routedict
            )
            # **merge: for files in this route-part (the translated files)
            botslib.tryrunscript(self.userscript, self.scriptname, 'premerge', routedict=routedict)
            envelope.mergemessages(
                startstatus=TRANSLATED,
                endstatus=MERGED,
                idroute=routedict['idroute'],
                rootidta=rootidta,
                routedict=routedict,
            )
            botslib.tryrunscript(self.userscript, self.scriptname, 'postmerge', routedict=routedict)
        elif routedict['translateind'] == 2:
            # pass-through: pickup the incoming files
            # and mark these as MERGED (==translation is finished)
            botslib.addinfo(
                change={'status': MERGED, 'statust': OK},
                where={
                    'status': FILEIN,
                    'statust': OK,
                    'idroute': routedict['idroute'],
                    'rootidta': rootidta,
                },
            )
        # NOTE: routedict['translateind'] == 0
        # than nothing will happen with the files in this route.

        # ommunication outgoing channel: MERGED->RAWOUT
        if routedict['tochannel']:
            # **build query to add outchannel as attribute to outgoing files***
            # filter files in route for outchannel
            towhere = {
                'status': MERGED,
                'statust': OK,
                'idroute': routedict['idroute'],
                'editype': routedict['toeditype'],
                'messagetype': routedict['tomessagetype'],
                'testindicator': routedict['testindicator'],
            }
            # remove nul-values from dict
            towhere = dict((key, value) for key, value in towhere.items() if value)
            wherestring = ' AND '.join(key + '=%(' + key + ')s ' for key in towhere)
            if routedict['frompartner_tochannel_id']:
                # use frompartner_tochannel
                # in where-clause of query (partner/group dependent outchannel)
                towhere['frompartner_tochannel_id'] = routedict['frompartner_tochannel_id']
                wherestring += """\
                    AND (frompartner=%(frompartner_tochannel_id)s
                    OR frompartner in (SELECT from_partner_id
                    FROM partnergroup
                    WHERE to_partner_id=%(frompartner_tochannel_id)s )) """
            if routedict['topartner_tochannel_id']:
                # use topartner_tochannel
                # in where-clause of query (partner/group dependent outchannel
                towhere['topartner_tochannel_id'] = routedict['topartner_tochannel_id']
                wherestring += """\
                    AND (topartner=%(topartner_tochannel_id)s
                    OR topartner in (SELECT from_partner_id
                    FROM partnergroup
                    WHERE to_partner_id=%(topartner_tochannel_id)s )) """
            toset = {'status': FILEOUT, 'statust': OK, 'tochannel': routedict['tochannel']}
            towhere['rootidta'] = rootidta
            nr_of_outgoing_files_for_channel = botslib.addinfocore(
                change=toset, where=towhere, wherestring=wherestring)

            if nr_of_outgoing_files_for_channel:
                # **set asked confirmation/acknowledgements
                botslib.set_asked_confirmrules(routedict, rootidta=rootidta)
                # **zip outgoing
                # for files in this route-part for this out-channel
                if routedict['zip_outgoing'] == 1:
                    preprocess.postprocess(
                        routedict=routedict,
                        function=preprocess.botszip,
                        rootidta=rootidta,
                    )

            # actual communication: run outgoing channel (if not deferred)
            # for all files in run that are for this channel
            # (including the deferred ones from other routes)
            if not routedict["defer"] or botsglobal.ini.getboolean("acceptance", "runacceptancetest", False):
                if botslib.countoutfiles(idchannel=routedict['tochannel'], rootidta=rootidta):
                    botslib.tryrunscript(
                        self.userscript, self.scriptname, 'preoutcommunication', routedict=routedict
                    )
                    # communication.run is stripped in the native implementation
                    # in communication several things can go wrong.
                    # all outgoing files should have same status;
                    # that way all recomnnunication can be handled the same:
                    # - status EXTERNOUT statust DONE (if communication goes OK)
                    # - status EXTERNOUT status ERROR (if file is not communicatied)
                    # to have the same status for all outgoing files some manipulation is needed,
                    # eg in case no connection could be made.
                    botslib.addinfo(
                        change={'status': EXTERNOUT, 'statust': ERROR},
                        where={
                            'status': FILEOUT,
                            'statust': OK,
                            'tochannel': routedict['tochannel'],
                            'rootidta': rootidta,
                        },
                    )
                    botslib.tryrunscript(
                        self.userscript,
                        self.scriptname,
                        'postoutcommunication',
                        routedict=routedict,
                    )

        botslib.tryrunscript(self.userscript, self.scriptname, 'end', routedict=routedict)

    def evaluate(self):
        """evaluate self.command"""
        # pylint: disable=broad-exception-caught
        try:
            return True
        except Exception:
            botsglobal.logger.exception(_('Error in automatic maintenance.'))
            return 1

    def get_minta4query(self):
        """get the first idta for queries etc in whole run."""
        return self.minta4query


class crashrecovery(new):
    """a crashed run is rerun."""

    def run(self):
        # get rootidta of crashed run
        for row in botslib.query(
                """SELECT MAX(idta) as crashed_idta
                FROM ta
                WHERE idta < %(rootidta_of_current_run)s
                AND script = 0 """,
                {'rootidta_of_current_run': self.minta4query}):
            self.minta4query_crash = row["crashed_idta"]
        if not self.minta4query_crash:
            # no run
            return False

        rootofcrashedrun = botslib.OldTransaction(self.minta4query_crash)
        rootofcrashedrun.update(statust=DONE)
        # clean up things from crash **********************************
        # delete run report
        botslib.changeq(
            """DELETE FROM report WHERE idta = %(rootofcrashedrun)s""",
            {'rootofcrashedrun': rootofcrashedrun.idta},
        )
        # delete file reports
        botslib.changeq(
            """DELETE FROM filereport WHERE idta>%(rootofcrashedrun)s""",
            {'rootofcrashedrun': rootofcrashedrun.idta},
        )
        # delete ta's for children of crashed merges (using child-relation)
        mergedidtatodelete = set()
        for row in botslib.query(
                """SELECT child FROM ta
                WHERE idta > %(rootofcrashedrun)s
                AND statust = %(statust)s
                AND status != %(status)s
                AND child != 0""",
                {'rootofcrashedrun': rootofcrashedrun.idta, 'status': PROCESS, 'statust': OK}):
            mergedidtatodelete.add(row["child"])
        for idta in mergedidtatodelete:
            ta_object = botslib.OldTransaction(idta)
            ta_object.delete()
        # delete ta's after ERROR and OK for other (using parent-relation)
        for row in botslib.query(
                """SELECT idta FROM ta
                WHERE idta > %(rootofcrashedrun)s
                AND ( statust = %(statust1)s OR statust = %(statust2)s )
                AND status != %(status)s
                AND child = 0""", {
                    'rootofcrashedrun': rootofcrashedrun.idta,
                    'status': PROCESS,
                    'statust1': OK,
                    'statust2': ERROR,
                }):
            ta_object = botslib.OldTransaction(row["idta"])
            ta_object.deletechildren()

        return super().run()

    def get_minta4query(self):
        """get the first idta for queries etc in whole run."""
        return self.minta4query_crash


class automaticretrycommunication(new):
    """
    Bots automatic retry communication class
    """
    def run(self) -> bool:
        """reinjects files with failed communication."""
        # bots keeps track of last time automaticretrycommunication was done; reason: performance
        idta_lastretry = botslib.unique(
            'bots__automaticretrycommunication', updatewith=self.minta4query
        )
        if idta_lastretry == 1:
            # this is the first time automaticretrycommunication is run.
            # do not do anything this run, in order to avoid sending older files.
            # no run
            return False
        for row in botslib.query(
                """SELECT MIN(idta) AS min_idta
                FROM filereport
                WHERE idta > %(idta_lastretry)s
                AND statust = %(statust)s """,
                {'statust': ERROR, 'idta_lastretry': idta_lastretry}):
            startidta = row["min_idta"]
        if not startidta:
            # no run
            return False
        do_retransmit = False
        for row in botslib.query(
                """SELECT idta,parent,numberofresends
                FROM ta
                WHERE idta > %(startidta)s
                AND status = %(status)s
                AND statust = %(statust)s """,
                {'statust': ERROR, 'status': EXTERNOUT, 'startidta': startidta}):
            do_retransmit = True
            ta_outgoing = botslib.OldTransaction(row["idta"])
            # set retransmit back to False
            ta_outgoing.update(retransmit=False, statust=RESEND)
            # parent ta with status RAWOUT; this is where the outgoing file is kept
            ta_resend = botslib.OldTransaction(
                row["parent"]
            )
            # inject; status is DONE so this ta is not used further
            ta_externin = ta_resend.copyta(
                status=EXTERNIN, statust=DONE
            )
            # reinjected file is ready as new input
            ta_externin.copyta(
                status=FILEOUT, statust=OK, numberofresends=row["numberofresends"]
            )

        if do_retransmit:
            return super().run()
        # no run
        return False


class resend(new):
    """
    Bots resend class
    """
    def run(self) -> bool:
        """
        prepare the files indicated by user to be resend.
        Resend does not have a good performance.
        The start query can take some time as whole ta tabel is scanned.
        AFAIK this can be improved by maintaining separate list of files to resend.

        :return: indication if files should be resend.
        """
        do_retransmit = False
        for row in botslib.query(
                """SELECT idta,parent,numberofresends
                FROM ta
                WHERE retransmit = %(retransmit)s
                AND status = %(status)s""",
                {'retransmit': True, 'status': EXTERNOUT}):
            do_retransmit = True
            # resend transaction
            # how does this work?
            # a send edi-file has status EXTERNOUT (but filename is extreenal fiel name, not a stored file)
            # so need to go back to status FILEOUT...but there might be more ta with status FILEOUT.
            # eg file->mimefile is from FILEOUT to FILEOUT.
            # but if other postprocessing are used these also are from FILEOUT to FILEOUT...
            # solution: when mimefying set rsrv2 to 1 (is a num field)
            # than:
            #     if first ta.FILEOUT is not mime: use first ta.FILEOUT
            #     else use 2nd FILEOUT/parent
            # so in a resend: run routes/routeparts as usual - but no real incommunication.
            # when a re-injected ta.FILEOUT is there pick up and send. if needed, mimified - but not post-processed.

            # set ta.EXTERNOUT back to retransmit=False. change statust=RESEND to indicate that file is resend.
            ta_outgoing = botslib.OldTransaction(row["idta"])
            # set retransmit back to False
            ta_outgoing.update(retransmit=False, statust=RESEND)
            # get parent of ta.EXTERNOUT
            ta_resend = botslib.OldTransaction(row["parent"])
            ta_resend.synall()
            # pylint: disable=no-member
            if ta_resend.rsrv2 == 1:
                # mimefile...use parent
                ta_resend2 = botslib.OldTransaction(ta_resend.parent)
                # inject; status is DONE so this ta is not used further
                ta_externin = ta_resend2.copyta(status=EXTERNIN, statust=DONE)
            else:
                # inject; status is DONE so this ta is not used further
                ta_externin = ta_resend.copyta(status=EXTERNIN, statust=DONE)

            # reinjected file is ready as new input
            ta_externin.copyta(
                status=FILEOUT, statust=OK, numberofresends=row["numberofresends"]
            )

        # return: indication if files have been send.
        if do_retransmit:
            return super().run()
        # no run
        return False


class rereceive(new):
    """
    Bots rereceive class
    """
    def run(self) -> bool:
        """
        prepare the files indicated by user to be rereceived.

        :return: indication if files should be rereceived.
        """
        do_retransmit = False
        for row in botslib.query(
                """SELECT idta
                FROM filereport
                WHERE retransmit = %(retransmit)s """,
                {'retransmit': 1}):
            # True is at least one file needs to be received
            do_retransmit = True
            # reset the 'rereceive' indication in db.filereport
            botslib.changeq(
                """UPDATE filereport
                SET retransmit = %(retransmit)s
                WHERE idta = %(idta)s""",
                {"idta": row["idta"], "retransmit": 0},
            )
            # reinject transaction
            # how does this work?
            # an edi-file comes in bots with status EXTERNIN
            # (with org filename but no stored file) -> FILEIN (with stored file)
            # note that filereport has same idta as the EXTERNIN.
            # copy ta.EXTERNIN
            # copy ta.FILEIN, parent is copied ta.EXTERNIN
            # so in a rereceive: run routes/routeparts as usual - but no real incommunication.
            # and as ta.EXTERNIN and ta.FILEIN are already there (re-injected), these are picked up and processed.
            ta_org_EXTERNIN = botslib.OldTransaction(row["idta"])
            ta_new_EXTERNIN = ta_org_EXTERNIN.copyta(status=EXTERNIN, statust=DONE, parent=0)
            for row2 in botslib.query(
                    """SELECT idta FROM ta WHERE parent = %(parent)s """,
                    {"parent": row["idta"]}):
                ta_org_FILEIN = botslib.OldTransaction(row2['idta'])
                # ta_new_FILEIN
                ta_org_FILEIN.copyta(status=FILEIN, statust=OK, parent=ta_new_EXTERNIN.idta)
                break

        # return: indication if files have been rereceived.
        if do_retransmit:
            return super().run()
        # no run
        return False
