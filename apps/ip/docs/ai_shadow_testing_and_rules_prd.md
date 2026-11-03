# Product Requirements Document (PRD): AI Shadow Transformation & Natural Language Rule Synthesis

- **Document:** PRD-IP-013 — AI-Assisted Shadow Testing, Adversarial Edge-Case Synthesis & Natural Language Rules
- **Product:** Soopa Integration Platform (`apps/ip`)
- **Status:** Approved Specification (Gold Standard)
- **Bounded Context:** Normalization & Transformation (`L3 Normalization`)
- **Target Audience:** Integration Engineers, Utility Systems Architects, Billing Operations Leads
- **Related Specs:** [l3_normalization_design.md](l3_normalization_design.md), [ai_schema_mapping_prd.md](ai_schema_mapping_prd.md), [frontend_architecture_design.md](frontend_architecture_design.md)

---

## 1. Executive Summary & Problem Statement

### 1.1 The High Risk of Transformation Regressions in Production
In enterprise utilities, healthcare, and finance, modifying an active L3 Normalization transformer (e.g., updating how Itron OpenWay interval pulses are aggregated or how Landis+Gyr multiplier offsets are applied) is historically one of the highest-risk operations an IT team can undertake. 

A minor code tweak intended to fix an edge case for one customer or meter model frequently and silently corrupts downstream billing calculations for tens of thousands of other accounts:
1. **Manual test suites are never exhaustive:** Engineers write 10 to 20 unit tests covering the "happy path", missing critical real-world boundary conditions:
   - Solar net-metering back-feed generating negative pulse values.
   - Daylight Saving Time (DST) 2:00 AM fall-back (producing duplicate interval timestamps).
   - Leap seconds and leap years.
   - Register rollover (e.g., dial wrapping from `999999` to `000000`).
   - Null or missing phase voltage measurements during brownouts.
2. **Staging environments have stale, sanitized data:** Mappings that pass staging tests blow up in production when exposed to real-world network packet corruption and undocumented firmware quirks.
3. **Writing complex business rules is slow and error-prone:** Translating a utility tariff policy (e.g., *"If status is ESTIMATED and ambient temperature exceeds 95°F, apply heat-wave peak interpolation, else use 3-interval moving average"*) requires deep Python syntax mastery and hours of manual debugging.

### 1.2 The Product Solution: The "Confidence-First Transformation Workbench"
Soopa pairs our L3 Canonical Normalization pipeline with an **AI-Assisted Shadow Transformation & Adversarial Testing Suite**:
1. **Natural Language $\rightarrow$ AST Python Rule Synthesis:** Engineers type plain-English business rules directly inside the Monaco editor; an AI Co-Pilot compiles them into deterministic, type-safe Python Pydantic transformer methods.
2. **Adversarial Edge-Case Synthesis:** The AI analyzes the Canonical schema and automatically generates hundreds of synthetic, adversarial test cases designed specifically to stress-test boundary conditions before production deployment.
3. **Zero-Downtime Live Shadow Execution:** New transformer versions run in `SHADOW` mode against real, live production traffic in parallel with the active version.
4. **Side-by-Side Monaco Semantic Diff:** The UI renders an interactive, colorized diff comparing `Active Output` vs. `Shadow Output` on real production records, giving engineers 100% empirical proof of correctness before 1-click promotion.

---

## 2. Personas & Core User Workflows

### 2.1 Target Personas
1. **Utility Integration Engineer (Elena):** Maintains AMI-to-MDM data transformers. Needs 100% type safety, deterministic Python code, and zero production regressions.
2. **Billing Operations Specialist (Marcus):** Formulates complex rate calculations and VEE (Validation, Estimation, and Editing) rules. Prefers natural language prompts and visual verification over raw syntax debugging.
3. **Platform Administrator (Priya):** Manages release lifecycles and compliance audits. Requires audit trails for all deployed rules and automated circuit-breaking on faulty candidate transformers.

---

### 2.2 User Workflow: End-to-End Rule Synthesis & Shadow Promotion

```mermaid
sequenceDiagram
    autonumber
    actor Elena as "Integration Engineer (Elena)"
    participant Studio as "Monaco Shadow Studio UI"
    participant Synthesizer as "AI Rule Synthesizer"
    participant EdgeGen as "Adversarial Edge-Case Generator"
    participant ShadowRunner as "Shadow Execution Engine"
    participant DiffViewer as "Monaco Diff Viewer"

    Elena->>Studio: Selects Active L3 Transformer ("ItronOpenWayV4Transformer")
    Elena->>Studio: Clicks "Branch Shadow Candidate (v2.1-solar-net-metering)"
    Elena->>Studio: Enters Natural Language Prompt:
    Note over Elena,Studio: "If interval pulse is negative, set is_solar_export=true,\ncompute net_kwh = abs(pulse) * multiplier, and flag quality='DERIVED'."
    Studio->>Synthesizer: Synthesize AST Patch (Prompt + Active Transformer AST + Canonical Model)
    Synthesizer-->>Studio: Returns Python Code Patch + Method Replacements + Rationale
    Studio-->>Elena: Highlights proposed code in Monaco editor
    Elena->>Studio: Clicks "Run Adversarial Edge-Case Suite"
    Studio->>EdgeGen: Generate 200 domain stress-test cases
    EdgeGen-->>Studio: Injects DST shifts, rollovers, null phases, negative zeroes
    Studio->>Studio: Executes local unit test harness (198 passed, 2 expected anomalies flagged)
    Elena->>Studio: Clicks "Deploy Shadow Mode to Production"
    ShadowRunner->>ShadowRunner: Evaluates live production stream in parallel (0ms latency impact)
    ShadowRunner-->>DiffViewer: Streams real-time Semantic Diffs (Active vs. Shadow)
    DiffViewer-->>Elena: Displays side-by-side comparison on 50,000 real production records
    Elena->>Studio: Reviews diffs (Zero unexpected deltas) -> Clicks "Promote to Active"
    Studio->>Studio: Atomic cutover: v2.1 becomes Active; v2.0 archived
```

---

## 3. Detailed Functional Requirements

### 3.1 Natural Language Rule Synthesis

| ID | Requirement | Description | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **FR-RLS-01** | Natural Language to Python AST | Translates conversational business logic prompts into valid, PEP-8 compliant Python methods within the transformer class. | Generated code passes `mypy --strict`, has zero `Any`, zero `# type: ignore`, and conforms to Pydantic v2 domain schemas. |
| **FR-RLS-02** | Context-Aware AST Merging | The synthesizer MUST parse the existing transformer's Abstract Syntax Tree (AST) and cleanly replace or insert methods without altering unrelated helper functions or docstrings. | AST round-trip preserves all surrounding imports, comments, and unedited methods with 100% fidelity. |
| **FR-RLS-03** | Code Safety Sandbox & Security Invariants | The synthesizer MUST NEVER generate code containing unapproved imports (`os`, `sys`, `subprocess`, `socket`, `eval`, `exec`) or file system operations. | Security AST visitor statically rejects any unpermitted syntax before presenting to the user. |
| **FR-RLS-04** | Interactive Code Explanation & Rationale | The synthesizer MUST provide a concise, markdown-formatted explanation detailing which fields were mapped, what mathematical formulas were applied, and why. | Displayed in an expandable "AI Rationale" panel beside the Monaco editor. |

---

### 3.2 Adversarial Edge-Case Synthesis

| ID | Requirement | Description | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **FR-EDG-01** | Domain-Specific Fuzzing Categories | Analyzes Canonical Pydantic schemas and automatically synthesizes targeted test vectors covering five utility-specific edge categories: | Generates $\ge 200$ distinct test records within $< 4\text{ seconds}$. |
| | *1. Temporal Discontinuities* | Daylight Saving Time fall-back (duplicate 01:00–02:00 intervals), spring-forward (missing 02:00–03:00 intervals), leap year (Feb 29), leap seconds. | Accurately tests timestamp conversion and interval continuity. |
| | *2. Physical Invariants & Rollover* | Dial register wrapping (`999999` $\rightarrow$ `000005`), negative pulses (solar back-feed), consumption exceeding physical transformer capacity. | Proves that math does not overflow or produce negative interval calculations. |
| | *3. Multi-Phase Electrical Anomalies* | Voltage sag on Phase A with normal Phase B/C, inverted power factor (-1.0 to 1.0), zero-volt power outages. | Validates that power quality flags and status enums are correctly assigned. |
| | *4. Incomplete & Missing Data* | Missing interval records in a 96-interval day, null meter serial numbers, empty status arrays. | Verifies graceful fallback and appropriate estimation flags. |
| | *5. Structural & Unicode Fuzzing* | Meter serials containing emojis, non-ASCII characters, extreme-length strings (2048 chars), floating-point precision edge cases (`0.000000001`). | Proves parser resilience against crashes and memory bloat. |
| **FR-EDG-02** | Automated Pre-Flight Test Harness | Runs the candidate transformer against all synthesized edge cases in an isolated subprocess before allowing shadow deployment. | Generates a structured Test Report displaying pass rate, execution time per test, and exact stack traces for failed vectors. |

---

### 3.3 Zero-Impact Live Shadow Execution

| ID | Requirement | Description | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **FR-SHD-01** | Zero Fast-Path Latency Overhead | Shadow execution MUST run asynchronously (via fire-and-forget background tasks or dedicated shadow worker pools), completely isolated from the live L4 outbox pipeline. | Adding a shadow transformer introduces strictly $0.0\text{ ms}$ overhead to the active L1 $\rightarrow$ L4 delivery latency. |
| **FR-SHD-02** | Automated Circuit Breaking | If a candidate shadow transformer throws unhandled exceptions on $> 1\%$ of live production records, shadow execution is immediately paused. | Circuit breaker trips within 100 consecutive failures; emits an alert to the studio without affecting production traffic. |
| **FR-SHD-03** | Configurable Sampling Rate | Allows operators to configure shadow evaluation traffic sampling (e.g., 100% of traffic, 10% of traffic, or traffic for specific tenant/feeder IDs). | Evaluator respects sampling configuration with $< 1\%$ variance. |
| **FR-SHD-04** | Bounded Telemetry Storage & Retention | Shadow execution diffs are stored in a dedicated table (`ip_shadow_evaluations`) with a default TTL of 48 hours, automatically pruned in chunked batches. | Database retention jobs purge expired shadow rows without table locks or WAL bloat. |

---

### 3.4 Interactive Monaco Semantic Diff Viewer

| ID | Requirement | Description | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **FR-DIF-01** | Side-by-Side Visual Comparison | The UI provides a split Monaco diff editor rendering `Active Output JSON` on the left and `Shadow Output JSON` on the right. | Highlights added, deleted, and modified keys with standard git-style coloring. |
| **FR-DIF-02** | Numerical & Semantic Delta Highlighting | For floating-point and numerical fields (e.g., consumption kWh), the diff viewer computes and displays the absolute and percentage delta ($\Delta = +0.45\text{ kWh} \ (+2.3\%)$). | Renders inline delta badges beside modified numerical fields. |
| **FR-DIF-03** | Filter by Anomaly / Diff Only | Operators can toggle filters: *"Show Only Records with Diffs"*, *"Show Only Errors"*, or search by specific business ID (e.g., `MTR-700`). | Filters 100,000 evaluated records in $< 100\text{ ms}$ via indexed metadata columns. |
| **FR-DIF-04** | 1-Click Zero-Downtime Promotion | Clicking "Promote to Active" executes an atomic database pointer swap, immediately routing subsequent L2 events to the new transformer version across all worker pods. | Zero dropped records during transition; immediate cache invalidation across distributed worker fleet. |

---

## 4. Non-Functional & Enterprise Guardrails

1. **Security & Sandbox Isolation:** Code synthesis runs within strict compute and memory limits (256 MB RAM, 10-second timeout per batch). No dynamic `eval()` or unvetted third-party packages are permitted.
2. **Audit Logging & Governance:** Every rule change, promotion, and synthesized AST patch is logged to an immutable audit ledger (`ip_transformer_audit_log`), recording author ID, model version, prompt hash, and parent version commit hash.
3. **Air-Gap Compatibility:** All rule synthesis and edge-case generation interfaces use abstract ports, fully compatible with local self-hosted models (Ollama / vLLM Llama 3) for Tier 3B sovereign cloud deployments.

---

## 5. Success Metrics & KPIs

| Metric | Industry Baseline (Manual Testing) | Target with Soopa Shadow Studio |
| :--- | :--- | :--- |
| **Time to Develop Complex Utility Rule** | 1 to 2 business days | **$< 30\text{ minutes}$** |
| **Production Regressions on Deploy** | 5%–8% of transformer releases | **$0.0\%$ (Zero regressions)** |
| **Edge-Case Coverage** | ~15 manual unit test vectors | **$\ge 200$ automated synthetic vectors** |
| **Pre-Promotion Empirical Validation** | Zero (tested only on synthetic data) | **50,000+ real production records evaluated in shadow mode** |
