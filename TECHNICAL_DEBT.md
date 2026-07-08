# Technical Debt

A living record of known gaps, shortcuts, and missing enterprise capabilities.

---

## AS2 Protocol

### Async MDN — Inbound Callback Not Implemented
**Priority:** High
**Affects:** Large enterprise partners (banks, healthcare networks) that require async MDN.

| Scenario | Status |
|---|---|
| Outbound, Sync MDN | ✅ Fully implemented |
| Outbound, Async MDN — `Receipt-Delivery-Option` header sent correctly | ✅ Implemented |
| Outbound, Async MDN — receiving the callback and reconciling it | ❌ Not implemented |
| Inbound — partner requests Async MDN via `Receipt-Delivery-Option` header | ❌ Not implemented |

**Required work:**
- `services/as2_server/core/receive_as2.py`: Detect when an inbound POST is an MDN callback
  (via `Content-Disposition: notification` or matching `Message-ID` header), route it to a
  dedicated `MDNReconciliationUseCase` instead of treating it as new EDI.
- `services/worker`: When `mdn_type == "ASYNC"`, after sending, write `PENDING_MDN` status and
  store the sent `Message-ID` and `MIC` so they can be matched when the callback arrives.
- Database: Add an `outbound_mdn_pending` table `(message_id, mic, trace_id, expires_at)`.

---

## Testing

### No Frontend Test Runner (Vitest)
**Priority:** Medium
`make test` skips frontend tests with a placeholder comment.
React component tests and TanStack Query mutation tests are not covered.
