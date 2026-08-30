from enum import StrEnum


class DomainIdPrefix(StrEnum):
    TEMPLATE = "notif_tmpl"
    OUTBOX = "notif_ob"
    ROUTE = "notif_rt"
    RECORD = "notif_rec"
    PREFERENCE = "notif_pref"
