# Technical Debt Register

This document tracks identified technical debt, proposed refactoring, and estimated effort to resolve.

## 1. Modernization of Bots Core (Stateless AST Migration)

**Description:**
The open-source `bots_core` library heavily relies on a legacy, stateful `Node` class pattern to build, traverse, and count EDI segments (e.g., `SE01`, `GE01` counting via `node.getcount()`). Currently, we are bypassing this internal engine completely in our modern microservices architecture by injecting raw stateless Python JSON dictionaries (AST format) into the `bots_core.facade`.

Because `bots_core` doesn't natively parse our stateless AST for trailing counts, we temporarily built an `ASTUtils.count_segments()` workaround in the `transformer` domain layer.

**Proposed Resolution:**
To achieve the long-term vision of completely merging and modernizing `bots_core` as a first-class citizen of our modern Python stack:
1. Refactor the inner workings of `bots_core` (specifically `message.py`, `outmessage.py`, and `node.py`) to natively accept, traverse, and serialize stateless dictionary ASTs without forcing instantiation of legacy `Node` objects.
2. Move AST utility functions (like `count_segments`) natively into `bots_core/domain/ast_utils.py`.
3. Eliminate the legacy mapping engine scripts (`inn.get()`, `out.put()`) internally inside `bots_core` if they are fully deprecated by the API gateway.

**Estimated Effort:** Medium-High
**Estimated Time:** 1 to 2 Sprint Weeks (40 - 80 hours)
**Impact:** Will result in a completely modernized, lightning-fast, fully stateless fork of the `bots` EDI engine perfectly aligned with our cloud-native event-driven architecture.

## 2. Outbox Sweeper (CDC Fallback Relay)

**Description:**
The Outbox Sweeper has been implemented as a fallback to Debezium (CDC). It iterates over all shards to relay `PENDING` outbox events to SQS. However, the current implementation iterates over shards sequentially (`for shard in shards: await self._sweep_shard(...)`). As the number of shards grows in the multi-tenant architecture, this sequential sweep will take longer and potentially exceed the polling interval, causing lag.

**Proposed Resolution:**
Refactor the Outbox Sweeper to use Bounded Concurrency or Distributed Job Fan-out:
1. **Bounded Concurrency:** Run sweeps concurrently using `asyncio.gather` bounded by an `asyncio.Semaphore` so multiple shards are swept at once without exhausting resources.
2. **Distributed Job Fan-out:** Instead of a single job, spawn a `ScheduledJob` for each shard dynamically, allowing multiple orchestrator pods to load balance the shard sweeping.
3. **Garbage Collector (Pending):** A cleanup task that runs `DELETE FROM outbox WHERE status = 'COMPLETED'` for events older than 7 days to prevent unbounded database growth is still needed.

**Estimated Effort:** Low-Medium
**Estimated Time:** 1 to 2 days
**Impact:** Prevents the sweeper from falling behind as the number of database shards scales, ensuring enterprise-grade multi-tenant reliability.

## 3. AS2 Protocol

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


## 4. Domain Model Refactoring
- **Decoupled Validation**: Validation logic should be extracted from `Transformer` into a dedicated step before translation.

### 2. Audit for "Translate" terminology
- **"Translate/Translation"**: Audit remaining files for legacy terminology and ensure consistency with "Transform/Transformation".

### 3. Verify Inbound AS2 flow

## 5. Testing

### No Frontend Test Runner (Vitest)

**Priority:** Medium
`make test` skips frontend tests with a placeholder comment.
React component tests and TanStack Query mutation tests are not covered.


## 7. EDI Translation vs Validation

**Priority:** Medium
Currently, the bots engine does not support a lightweight validation mode (e.g., dry-run JSON -> EDI without full transformation). Validation is inherently tied to transformation. As a result, the API does very basic JSON structure validation, but strict EDI grammar validation happens asynchronously in the Worker. Future Action: Investigate if we can separate validation (e.g. strict JSON Schema or X12 rules parser) from transformation so the API can quickly reject invalid transactions without full engine processing.

### UnitOfWork Architecture (Control Plane vs Data Plane Naming)
Currently, the `UnitOfWork` (and its underlying SQL Alchemy repositories) leak infrastructure/deployment boundaries ("Control Plane" and "Data Plane") into domain business logic. We have giant God-objects like `SqlAlchemyControlPlaneRepository` inheriting from 10+ distinct repositories, causing namespace collisions and violating SOLID principles (Single Responsibility Principle).
**Future Action:** Refactor `UnitOfWork` to remove `control_plane` and `data_plane` concepts from class names and properties. Use Composition to expose distinct Bounded Contexts (e.g., `self.trading_partners`, `self.transactions`, `self.routes`) instead of lumping them into control/data plane buckets.

## 8. Hybrid SQS Tenancy (Dynamic Queue Resolution)

**Description:**
Currently, both inbound and outbound events are routed to a static, shared SQS queue (e.g., `TransformOrchestrationQueue`). In a multi-tenant environment, a massive batch of outbound events from one tenant can block critical inbound processing for all other tenants (the "noisy neighbor" problem).

**Proposed Resolution:**
Implement a Hybrid SQS routing model that dynamically resolves the target queue based on the tenant's tier and the event direction:
1. **Dynamic Queue Resolver:** The CDC Relay and Outbox Sweeper should read the `tenant_id` from the outbox event and lookup the tenant's tier (cached in memory).
2. **Standard Tenants:** Route inbound events to `standard-inbound-queue` and outbound events to `standard-outbound-queue`.
3. **Enterprise Tenants:** Route events to dedicated queues (e.g., `enterprise-{tenant_name}-inbound-queue`).
4. **Dedicated Workers:** Deploy separate worker pods for standard inbound, standard outbound, and dedicated enterprise queues to provide strict compute isolation.

**Estimated Effort:** Medium
**Estimated Time:** 3 to 5 days
**Impact:** Essential for enterprise-grade SaaS scaling. Guarantees compute isolation for enterprise customers and bulkheads heavy outbound processing from blocking high-priority inbound traffic.
