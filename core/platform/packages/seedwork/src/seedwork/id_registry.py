from enum import StrEnum


class SystemIdPrefix(StrEnum):
    """
    Generic system-wide ID prefixes for shared primitives.
    Domain-specific prefixes (like tenants, users, AS2 partners) should NOT be added here.
    They belong in their respective bounded context's DomainIdPrefix.
    """

    GENERIC = "sys_id"
    EVENT = "sys_evt"
    JOB = "sys_job"
    IDEMPOTENCY = "sys_idemp"
    OUTBOX = "sys_out"
    CLIENT = "sys_client"
    TRACE = "sys_trace"
    TX = "sys_tx"
    WORKFLOW_RUN = "wf_run"
    WORKFLOW_STEP = "wf_step"
    WORKFLOW_ATTEMPT = "wf_att"
    WORKFLOW_MATCH = "wf_mtch"
    WORKFLOW_CONDITION = "wf_cond"


class DomainIdPrefix(StrEnum):
    """
    Domain-specific prefixes for ID generation across bounded contexts.
    """

    # Identity
    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"  # noqa: S105
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_usr_rol"
    IDENTITY_OUTBOX = "iam_ob"

    # Notification
    NOTIFICATION_TEMPLATE = "notif_tmpl"
    NOTIFICATION_OUTBOX = "notif_ob"
    NOTIFICATION_ROUTE = "notif_rt"
    NOTIFICATION_RECORD = "notif_rec"
    NOTIFICATION_PREFERENCE = "notif_pref"

    # UCP
    UCP_APP = "ucp_app"
    UCP_SHARD = "ucp_shard"
    UCP_OUTBOX = "ucp_ob"
    UCP_WEBHOOK = "ucp_wh"

    # EDI
    EDI_CP_OUTBOX = "edi_cp_ob"
    EDI_DP_OUTBOX = "edi_dp_ob"
    EDI_AS2_SERVER = "edi_as2"
    EDI_AS2_PARTNER = "edi_as2_tp"
    EDI_AS2_PARTNERSHIP = "edi_as2_pship"
    EDI_SFTP_PARTNER = "edi_sftp"
    EDI_WEBHOOK = "edi_dp_wh"
    EDI_INBOUND_ROUTE = "edi_inb_rt"
    EDI_OUTBOUND_HEADER = "edi_outb_hdr"
    EDI_OUTBOUND_ROUTE = "edi_outb_rt"
    EDI_MESSAGE = "edi_msg"
    EDI_JSON = "edi_json"
    EDI_API_GATEWAY = "edi_api_gw"
    EDI_TRACE_EVENT = "edi_trace_evt"

    # Integration Platform (IP)
    IP_TRACE = "ip_trc"
    IP_TRACE_EVENT = "ip_trace_evt"
    IP_INBOUND_RECORD = "ip_inb"
    IP_CONNECTION = "ip_conn"
    IP_CATALOG = "ip_cat"
    IP_STREAM = "ip_strm"
    IP_REPLICA = "ip_rep"
    IP_REPLICA_REJECTION = "ip_rej"
    IP_NORMALIZED = "ip_nrm"
    IP_CANONICAL = "ip_canon"
    IP_OUTBOUND_RECORD = "ip_out"
    IP_OUTBOUND_DISPATCH = "ip_disp"
    IP_OUTBOX = "ip_obx"
    IP_GEM = "ip_gem"
    IP_STREAM_STATE = "ip_cst"
    IP_MDM_READING = "ip_mdmr"
    IP_MDM_SERVICE_POINT = "ip_mdms"
    IP_TMS_LOAD = "ip_tmsl"
    IP_TMS_CARRIER = "ip_tmsc"
    IP_SYNC_RUN = "ip_sync"
    IP_MAPPING_BINDING = "ip_bind"
    IP_NORMALIZATION_LEDGER = "ip_nlg"
    IP_NORMALIZATION_REJECTION = "ip_nrj"
    IP_SHADOW_DIFF = "ip_sdiff"
    IP_PENDING_REFERENCE = "ip_pref"
