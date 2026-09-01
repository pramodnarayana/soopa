from enum import StrEnum


class NotificationIdPrefix(StrEnum):
    TEMPLATE = "notif_tmpl"
    OUTBOX = "notif_ob"
    ROUTE = "notif_rt"
    RECORD = "notif_rec"
    PREFERENCE = "notif_pref"
