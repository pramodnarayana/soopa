from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database.models import Base


class Ta(Base):
    """
    Transaction (ta) table for BOTS engine.
    Tracks the state and processing history of every EDI file.
    """

    __tablename__ = "ta"

    idta = Column(Integer, primary_key=True, autoincrement=True)
    statust = Column(Integer, default=0)
    status = Column(Integer, default=0)
    parent = Column(Integer, default=0, index=True)
    child = Column(Integer, default=0)
    script = Column(Integer, default=0)
    idroute = Column(String(35), default="")
    filename = Column(String(256), default="")
    frompartner = Column(String(35), default="")
    topartner = Column(String(35), default="")
    fromchannel = Column(String(35), default="")
    tochannel = Column(String(35), default="")
    editype = Column(String(35), default="")
    messagetype = Column(String(35), default="")
    alt = Column(String(35), default="")
    divtext = Column(String(128), default="")
    merge = Column(Boolean, default=False)
    nrmessages = Column(Integer, default=1)
    testindicator = Column(String(10), default="")
    reference = Column(String(256), default="", index=True)
    frommail = Column(String(256), default="")
    tomail = Column(String(256), default="")
    charset = Column(String(35), default="")
    retransmit = Column(Boolean, default=False)
    contenttype = Column(String(35), default="text/plain")
    errortext = Column(Text, default="")
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    confirmasked = Column(Boolean, default=False)
    confirmed = Column(Boolean, default=False)
    confirmtype = Column(String(35), default="")
    confirmidta = Column(Integer, default=0)
    envelope = Column(String(35), default="")
    botskey = Column(String(64), default="")
    cc = Column(String(512), default="")
    rsrv1 = Column(String(128), default="")
    rsrv2 = Column(Integer, default=0)
    rsrv3 = Column(String(35), default="")
    rsrv4 = Column(Integer, default=0)
    rsrv5 = Column(String(256), default="")
    filesize = Column(Integer, default=0)
    numberofresends = Column(Integer, default=0)


class Uniek(Base):
    """
    Unique counters table.
    Used by BOTS engine to generate sequential control numbers (ISA, UNB, etc).
    """

    __tablename__ = "uniek"

    domein = Column(String(35), primary_key=True)
    nummer = Column(Integer, default=1)


class Translate(Base):
    """
    Translation rules.
    Used to determine which mapping script should be applied for an incoming message type.
    """

    __tablename__ = "translate"

    id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Boolean, default=False)
    fromeditype = Column(String(35))
    frommessagetype = Column(String(35))
    alt = Column(String(35), default="")
    frompartner_id = Column(String(35), nullable=True)  # ForeignKey placeholder
    topartner_id = Column(String(35), nullable=True)  # ForeignKey placeholder
    tscript = Column(String(35))
    toeditype = Column(String(35))
    tomessagetype = Column(String(35))
    desc = Column(String(256), nullable=True)
    rsrv1 = Column(String(35), nullable=True)
    rsrv2 = Column(Integer, nullable=True)


class Partner(Base):
    __tablename__ = "partner"

    idpartner = Column(String(35), primary_key=True)
    active = Column(Boolean, default=False)
    isgroup = Column(Boolean, default=False)
    name = Column(String(256))


class Channel(Base):
    __tablename__ = "channel"

    idchannel = Column(String(35), primary_key=True)
    inorout = Column(String(3))
    type = Column(String(35))


class Routes(Base):
    __tablename__ = "routes"

    idroute = Column(String(35), primary_key=True)
    seq = Column(Integer, primary_key=True, default=1)
    active = Column(Boolean, default=False)


class FileReport(Base):
    __tablename__ = "filereport"

    idta = Column(Integer, primary_key=True)
    reportidta = Column(Integer)
    statust = Column(Integer)
    retransmit = Column(Integer)
    idroute = Column(String(35))
    fromchannel = Column(String(35))
    tochannel = Column(String(35))
    frompartner = Column(String(35))
    topartner = Column(String(35))
    frommail = Column(String(256))
    tomail = Column(String(256))
    ineditype = Column(String(35))
    inmessagetype = Column(String(35))
    outeditype = Column(String(35))
    outmessagetype = Column(String(35))
    incontenttype = Column(String(35))
    outcontenttype = Column(String(35))
    nrmessages = Column(Integer)
    ts = Column(DateTime(timezone=True))
    infilename = Column(String(256))
    inidta = Column(Integer, nullable=True)
    outfilename = Column(String(256))
    outidta = Column(Integer)
    divtext = Column(String(128))
    errortext = Column(Text)
    rsrv1 = Column(String(128), nullable=True)
    rsrv2 = Column(Integer, nullable=True)
    filesize = Column(Integer, nullable=True)


class Report(Base):
    __tablename__ = "report"

    idta = Column(Integer, primary_key=True)
    lastreceived = Column(Integer)
    lastdone = Column(Integer)
    lastopen = Column(Integer)
    lastok = Column(Integer)
    lasterror = Column(Integer)
    send = Column(Integer)
    processerrors = Column(Integer)
    ts = Column(DateTime(timezone=True))
    type = Column(String(35))
    status = Column(Boolean)
    rsrv1 = Column(String(256), nullable=True)
    rsrv2 = Column(Integer, nullable=True)
    filesize = Column(Integer, nullable=True)
    acceptance = Column(Integer, nullable=True)


class Mutex(Base):
    __tablename__ = "mutex"

    mutexk = Column(Integer, primary_key=True)
    mutexer = Column(Integer)
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
