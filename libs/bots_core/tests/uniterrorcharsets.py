#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
no plugin needed.
run in commandline.
should give no errors.
utf-16 etc are reported.
"""

import sys

from bots import botsinit, botsglobal, botslib
from bots.exceptions import BotsError

xrange = range
unichr = chr


def assertraise(expect, msg2, *args, **kwargs):
    """ ... """
    try:
        raise BotsError(msg2, *args, **kwargs)
    except Exception as msg:
        if not isinstance(msg, str):
            msg = str(msg)
            #~ print('not unicode', type(msg), expect)
            #~ print('Error xxx\n', msg)
        if expect:
            if str(expect) != msg.strip():
                print(expect, '(expected)')
                print(msg, '(received)')
        txt = botslib.txtexc()
        if not isinstance(txt, str):
            print('Error txt\n', txt)

# .decode(): bytes -> str
# .encode(): str -> bytes


def testrun():
    """ ... """
    print('\n')
    # normal, valid handling
    assertraise('','',{'test1':'test1','test2':'test2','test3':'test3'})
    assertraise('0test','0test',{'test1':'test1','test2':'test2','test3':'test3'})
    assertraise('0test test1 test2','0test %(test1)s %(test2)s %(test4)s',{'test1':'test1','test2':'test2','test3':'test3'})
    assertraise('1test test1 test2 test3','1test %(test1)s %(test2)s %(test3)s',{'test1':'test1','test2':'test2','test3':'test3'})
    assertraise('2test test1 test2 test3','2test %(test1)s %(test2)s %(test3)s',{'test1':'test1','test2':'test2','test3':'test3'})

    # different inputs in BotsError
    assertraise('3test','3test')
    assertraise('4test test1 test2','4test %(test1)s %(test2)s %(test3)s',{'test1':'test1','test2':'test2'})
    assertraise('5test test1 test2','5test %(test1)s %(test2)s %(test3)s',test1='test1',test2='test2')
    assertraise('6test','6test %(test1)s %(test2)s %(test3)s','test1')
    assertraise("7test ['test1', 'test2']",'7test %(test1)s %(test2)s %(test3)s',test1=['test1','test2'])
    assertraise("8test {'test1': 'test1', 'test2': 'test2'}",'8test %(test1)s %(test2)s %(test3)s',test1={'test1':'test1','test2':'test2'})
    # assertraise("9test [<module 'bots.botslib' from '/home/hje/Bots/botsdev/bots/botslib.pyc'>, <module 'bots.botslib' from '/home/hje/Bots/botsdev/bots/botslib.pyc'>]",
    #            '9test %(test1)s %(test2)s %(test3)s',test1=[botslib,botslib])

    # different charsets in BotsError
    assertraise('12test test1 test2 test3','12test %(test1)s %(test2)s %(test3)s',{'test1':'test1','test2':'test2','test3':'test3'})
    assertraise('13test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test2\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test3\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202',
                '13test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 %(test1)s %(test2)s %(test3)s',
                {'test1':'test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202','test2':'test2\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202','test3':'test3\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202'})
    assertraise('14test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202',
                '14test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 %(test1)s'.encode('utf_8'),
                {'test1':'test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202'.encode('utf_8')})
    assertraise('15test test1',
                '15test %(test1)s',
                {'test1':'test1'.encode('utf_16')})
    assertraise('16test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202',
                '16test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 %(test1)s',
                {'test1':'test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202'.encode('utf_16')})
    assertraise('17test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202',
                '17test\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202 %(test1)s',
                {'test1':'test1\u00E9\u00EB\u00FA\u00FB\u00FC\u0103\u0178\u01A1\u0202'.encode('utf_32')})
    assertraise('18test\u00E9\u00EB\u00FA\u00FB\u00FC test1\u00E9\u00EB\u00FA\u00FB\u00FC',
                '18test\u00E9\u00EB\u00FA\u00FB\u00FC %(test1)s',
                {'test1':'test1\u00E9\u00EB\u00FA\u00FB\u00FC'.encode('latin_1')})
    assertraise('19test test1',
                '19test %(test1)s',
                {'test1':'test1'.encode('cp500')})
    assertraise('20test test1',
                '20test %(test1)s',
                {'test1':'test1'.encode('euc_jp')})

    # make utf-8 str string,many chars
    l = []
    for i in xrange(0, pow(256, 2)):
        l.append(unichr(i))
    s = ''.join(l)
    print(type(s))
    assertraise('', s)
    s2 = s.encode('utf-8', 'surrogatepass')
    print(type(s2))
    assertraise('', s2)

    # iso-8859-1 bytes string, many chars
    s = b"""\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0\xb1\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xbb\xbc\xbd\xbe\xbf\xc0\xc1\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xcb\xcc\xcd\xce\xcf\xd0\xd1\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xdb\xdc\xdd\xde\xdf\xe0\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xeb\xec\xed\xee\xef\xf0\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xfb\xfc\xfd\xfe\xff"""
    print(type(s))
    assertraise('', s)
    s2 = s.decode('latin_1')
    print(type(s2))
    assertraise('', s2)
    print(s2)


if __name__ == '__main__':
    botsinit.generalinit('config')
    botsinit.initbotscharsets()
    botsglobal.logger = botsinit.initenginelogging('engine')
    botsglobal.ini.set('settings','debug','False')
    testrun()
    botsglobal.ini.set('settings','debug','True')
    testrun()
