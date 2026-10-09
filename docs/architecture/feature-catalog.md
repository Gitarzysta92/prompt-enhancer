# Feature and component catalog

Generated from `atlas.json`; audit 2026-10-08. Read [scope and colors](README.md) first.

122 components: 4 ready, 84 partial, 31 absent, 3 mock.

These are component counts, not a beta-completion percentage. All status claims are scoped below.

| ID | Component | Status | Scope | Gate |
| --- | --- | --- | --- | --- |
| [MA01](#ma01) | Consent, source onboarding and privacy tier boundary | PARTIAL | required | B01/B03/B07 V02/V12 |
| [MA02](#ma02) | Codex documented App Server reader and compatibility probe | PARTIAL | required | B07 V12/V17 |
| [MA03](#ma03) | Claude opt-in hooks and content-free telemetry ledger | PARTIAL | required | B07 V12/V17 |
| [MA04](#ma04) | Versioned Claude transcript compatibility reader | PARTIAL | required | B07 V12/V17 |
| [MA05](#ma05) | Minimization, pseudonymous ingest and ephemeral redaction preview | PARTIAL | required | B07/B11 V17 |
| [MA06](#ma06) | Explicit trusted metric dependency graph | READY (bounded) | required | B07 component contract |
| [MA07](#ma07) | Canonical twenty-metric schema and operability catalog | PARTIAL | required | B07 V12 |
| [MA08](#ma08) | Reviewed lifecycle, task profile and requirement evidence | PARTIAL | required | B05/B07 V08/V12 |
| [MA09](#ma09) | Claim census and observed-check link proposals | PARTIAL | required | B07 V12/V17 |
| [MA10](#ma10) | Experimental factor model adapters and bounded serial workers | PARTIAL | experimental | B04/B07 model interpretation gate |
| [MA11](#ma11) | Experimental probability pooling and calibration gates | PARTIAL | experimental | B07 model aggregation gate |
| [MA12](#ma12) | Sealed session analysis and publication | PARTIAL | required | B07 V12 |
| [MA13](#ma13) | Durable live watch, attempts, retry/backoff and last valid head | PARTIAL | required | B02/B07 V07/V13 |
| [MA14](#ma14) | Engineering V1 session/project ratio aggregation | READY (bounded) | required | B07 component aggregation / V12 |
| [MA15](#ma15) | Metric storage, coverage/provenance and read-only API | PARTIAL | required | B07 V12/V17 |
| [MA16](#ma16) | Live radar, metric workspace and session selection UI | PARTIAL | required | B07/B10 V12/V13 |
| [MA17](#ma17) | Calibration review, saved ratings and reports | PARTIAL | experimental | B07 V12 |
| [MA18](#ma18) | Prompt check, optional rewrite and Claude submit hook | PARTIAL | required | B03/B07 V12 |
| [MA19](#ma19) | Synthetic demonstration transport and provider fixtures | MOCK / DEMO | experimental | B01/B07 V17 |
| [MA20](#ma20) | Historical V1 publication compatibility preview | PARTIAL | experimental | B07 V12 |
| [MC01](#mc01) | prompt.task_definition_coverage | PARTIAL | required | B07 V12 |
| [MC02](#mc02) | prompt.problem_evidence_quality | PARTIAL | required | B07 V12 |
| [MC03](#mc03) | prompt.context_sufficiency | PARTIAL | required | B07 V12 |
| [MC04](#mc04) | prompt.constraint_precision | PARTIAL | required | B07 V12 |
| [MC05](#mc05) | prompt.acceptance_testability | PARTIAL | required | B07 V12 |
| [MC06](#mc06) | prompt.deliverable_contract | PARTIAL | required | B07 V12 |
| [MC07](#mc07) | collaboration.ambiguity_resolution | PARTIAL | required | B07 V12 |
| [MC08](#mc08) | collaboration.clarification_yield | PARTIAL | required | B07 V12 |
| [MC09](#mc09) | collaboration.exploration_conversion | PARTIAL | required | B07 V12 |
| [MC10](#mc10) | collaboration.scope_change_discipline | PARTIAL | required | B07 V12 |
| [MC11](#mc11) | collaboration.rework_candidate_rate | PARTIAL | required | B07 V12 |
| [MC12](#mc12) | logic.decomposition_coverage | PARTIAL | required | B07 V12 |
| [MC13](#mc13) | logic.hypothesis_test_linkage | MEASURED ADAPTER ABSENT | required | B07 V12 |
| [MC14](#mc14) | logic.decision_rationale_coverage | PARTIAL | required | B07 V12 |
| [MC15](#mc15) | logic.requirement_action_traceability | PARTIAL | required | B07 V12 |
| [MC16](#mc16) | logic.open_loop_closure | PARTIAL | required | B07 V12 |
| [MC17](#mc17) | outcome.agent_claim_grounding | MEASURED ADAPTER ABSENT | required | B07 V12 |
| [MC18](#mc18) | outcome.verification_strategy_adequacy | PARTIAL | required | B07 V12 |
| [MC19](#mc19) | outcome.first_pass_verification | PARTIAL | required | B07 V12 |
| [MC20](#mc20) | outcome.verified_requirement_coverage | PARTIAL | required | B07 V12 |
| [A01](#a01) | Agent wire contracts | READY (bounded) | required | B00; supports B03/B05 |
| [A02](#a02) | Persistent Agent projects and chat catalog | PARTIAL | required | B03/V02/V04/V07 |
| [A03](#a03) | Conversation retention and restart recovery | PARTIAL | required | B03/V07 |
| [A04](#a04) | Saved-message search, fork and export | PARTIAL | required | B03/V04/V17 |
| [A05](#a05) | Chat composer, drafts and runtime picker | PARTIAL | required | B03/B10/V02/V13 |
| [A06](#a06) | Conversation streaming, Stop and activity | PARTIAL | required | B03/B04/V05/V06/V07 |
| [A07](#a07) | Safe Markdown, code and workspace links | PARTIAL | required | B05/B10/V09/V17 |
| [A08](#a08) | Owned GGUF runtime and model switching | PARTIAL | required | B04/V05/V06/V07 |
| [A09](#a09) | Exact chat context evidence | PARTIAL | required | B04/V05/V06 |
| [A10](#a10) | Model catalog, download and placement advice | PARTIAL | required | B04; W00/W05 |
| [A11](#a11) | Native workspace folder selection | PARTIAL | required | B03/V03 |
| [A12](#a12) | Workspace discovery, reads and search | PARTIAL | required | B05/V08/V17 |
| [A13](#a13) | Native one-shot approval authority | PARTIAL | required | B05/V08/V17 |
| [A14](#a14) | Diffs, writes, change sets and lifecycle | PARTIAL | required | B05/V08/V09 |
| [A15](#a15) | Owned command execution | PARTIAL | required | B02/B05/V08/V17 |
| [A16](#a16) | Governed web fetch capability | PARTIAL | experimental | B01/B05/V17 |
| [A17](#a17) | Verified artifact cards and lineage | PARTIAL | required | B05/V09 |
| [A18](#a18) | Bounded document and PDF handling | PARTIAL | required | B05/B08/V09/V18 |
| [A19](#a19) | Image, WAV and document attachments | PARTIAL | experimental | B04/B05; supports W03 |
| [A20](#a20) | Optional prompt check beside composer | PARTIAL | required | B01/B03; W05/WP01-WP08 |
| [A21](#a21) | External Agent controller and CLI | PARTIAL | required | B03/B05/V17 |
| [A22](#a22) | Agent MCP server surface | PARTIAL | required | B06/V10/V17 |
| [A23](#a23) | MCP registry search and cache | PARTIAL | required | B06/V11 |
| [A24](#a24) | MCP reviewed setup and local package installation | PARTIAL | required | B06/V10/V17 |
| [A25](#a25) | MCP host and one-shot tool invocation | PARTIAL | required | B06/V10 |
| [A26](#a26) | MCP cleanup evidence and recovery | PARTIAL | required | B02/B06/B09/V10/V14 |
| [A27](#a27) | Synthetic preview transport | MOCK / DEMO | experimental | B01/V17 |
| [W00](#w00) | Approved workflow profiles and package feasibility | NOT IMPLEMENTED | required | W00/B00/B08 |
| [W01](#w01) | Typed workflow graph and plan preview | NOT IMPLEMENTED | required | W01 |
| [W02](#w02) | Durable workflow revisions and sequential engine | NOT IMPLEMENTED | required | W02 |
| [W03](#w03) | Qualified production multimodal workflow adapters | NOT IMPLEMENTED | required | W03 |
| [W04](#w04) | Resource leases and actual parallel inference | NOT IMPLEMENTED | required | W04 |
| [W05](#w05) | Visual workflow builder and device model advisor | NOT IMPLEMENTED | required | W05/B10 |
| [W06](#w06) | Installed headless workflow export and import | NOT IMPLEMENTED | required | W06/B08 |
| [W07](#w07) | Workflow matrix and real-model qualification | NOT IMPLEMENTED | required | W07 |
| [W08](#w08) | Workflow beta and prompt-enhancement integration | NOT IMPLEMENTED | required | W08; WP01-WP08; B08-B11 |
| [R01](#r01) | Native desktop shell and window ownership | PARTIAL | required | B02/V13 |
| [R02](#r02) | Hidden owned process trees and bounded I/O | PARTIAL | required | B02/V17 |
| [R03](#r03) | Runtime cleanup sequencing and restart admission | PARTIAL | required | B02/B09 |
| [R04](#r04) | App-local runtime bootstrap and WebView prerequisites | PARTIAL | required | B02/B08/V01 |
| [R05](#r05) | Loopback local authentication, origin and CSRF boundary | PARTIAL | required | B02/V17 |
| [R06](#r06) | Native approval authority | PARTIAL | required | B05/V08 |
| [R07](#r07) | Application data path and retention inventory | PARTIAL | required | B08/B09/V16 |
| [R08](#r08) | Filesystem reparse and private staging checks | PARTIAL | required | B08/B09/V17 |
| [R09](#r09) | SQLite migrations and schema compatibility | PARTIAL | required | B03/B09/V15 |
| [R10](#r10) | Consistent backup and restore verification | PARTIAL | required | B09/V15 |
| [R11](#r11) | Signed update discovery and manifest verification | PARTIAL | required | B09/V14 |
| [R12](#r12) | Download, staging and package verification | PARTIAL | required | B09/V14 |
| [R13](#r13) | Update status and explicit check/stage/retry UI actions | PARTIAL | required | B09/V14 |
| [R14](#r14) | Host quiescence and update admission | PARTIAL | required | B09/V15 |
| [R15](#r15) | Durable update operation journal | PARTIAL | required | B09/V15 |
| [R16](#r16) | Native MSIX deployment transaction primitive | PARTIAL | required | B09/V14/V15 |
| [R17](#r17) | Product update Apply endpoint and relaunch | NOT IMPLEMENTED | required | B09/V14 |
| [R18](#r18) | Update rollback and package/data recovery executor | NOT IMPLEMENTED | required | B09/V15 |
| [R19](#r19) | Windows release assembly and pinned dependency inputs | PARTIAL | required | B00/B08/V18 |
| [R20](#r20) | Dependency provenance and third-party notices | PARTIAL | required | B08/V18 |
| [R21](#r21) | Compiled source-deterrent MSIX artifact | PARTIAL | required | B08/W00/V18 |
| [R22](#r22) | Signing identity and binary-only release channel | NOT IMPLEMENTED | required | B09/B11 |
| [R23](#r23) | Clean-machine install, uninstall and update acceptance | NOT IMPLEMENTED | required | B09/B11 |
| [R24](#r24) | Coherent private source custody and main baseline | PARTIAL | required | B00 |
| [R25](#r25) | Owner-review feature-branch collaboration policy | READY (bounded) | required | B00 |
| [R26](#r26) | Backend/frontend/privacy quality CI | PARTIAL | required | B00/B11 |
| [R27](#r27) | Agent deferred-loading and bundle gate | PARTIAL | required | B10/B11 |
| [R28](#r28) | Release evidence consistency evaluator | PARTIAL | required | B11 |
| [R29](#r29) | Development update verifier fake | MOCK / DEMO | experimental | B09 |
| [R30](#r30) | Deferred accounts, payments, teams and social foundations | PARTIAL | deferred | B01/deferred |
| [WF01](#wf01) | Workflow text LLM | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF02](#wf02) | Workflow vision-language model | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF03](#wf03) | Workflow text classifier | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF04](#wf04) | Workflow text embedding | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF05](#wf05) | Workflow image classifier | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF06](#wf06) | Workflow object detector | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF07](#wf07) | Workflow speech recognition | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WF08](#wf08) | Workflow audio classifier | NOT IMPLEMENTED | required | W00/W03/W07 |
| [WP01](#wp01) | Typed draft input/output | NOT IMPLEMENTED | required | WP01 |
| [WP02](#wp02) | Review, apply and undo UI | NOT IMPLEMENTED | required | WP02 |
| [WP03](#wp03) | Exact draft/run binding | NOT IMPLEMENTED | required | WP03 |
| [WP04](#wp04) | Idempotent enhancement and send | NOT IMPLEMENTED | required | WP04 |
| [WP05](#wp05) | Enhancement failure recovery | NOT IMPLEMENTED | required | WP05 |
| [WP06](#wp06) | Shared runtime resource budget | NOT IMPLEMENTED | required | WP06 |
| [WP07](#wp07) | Private retention and export | NOT IMPLEMENTED | required | WP07 |
| [WP08](#wp08) | Builder/composer/headless parity | NOT IMPLEMENTED | required | WP08 |

## MA01

**Consent, source onboarding and privacy tier boundary** — PARTIAL; required; gates `B01/B03/B07 V02/V12`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/application/onboarding.py`](../../src/prompt_enhancer/application/onboarding.py) — different<br>[`src/prompt_enhancer/ingestion.py`](../../src/prompt_enhancer/ingestion.py) — identical-lf-normalized<br>[`frontend/src/features/onboarding/FirstRunPanel.tsx`](../../frontend/src/features/onboarding/FirstRunPanel.tsx) — different

**Tests:** [`tests/test_onboarding.py`](../../tests/test_onboarding.py) — identical-lf-normalized<br>[`tests/test_consent_adapter_access.py`](../../tests/test_consent_adapter_access.py) — identical-lf-normalized<br>[`tests/test_ingestion_and_database.py`](../../tests/test_ingestion_and_database.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Ledger October 7: 52 backend onboarding/schema/privacy and six synthetic App browser cases passed on a separate five-file clean cohort.

**Gap:** Native first-run/provider ingestion and clean installation remain open. Onboarding source differs from origin/main.

**Next:** Admit the reviewed setup cohort; run an isolated installed first-run journey.

## MA02

**Codex documented App Server reader and compatibility probe** — PARTIAL; required; gates `B07 V12/V17`.

Dependencies: MA01

**Source:** [`src/prompt_enhancer/infrastructure/providers/codex_app_server/adapter.py`](../../src/prompt_enhancer/infrastructure/providers/codex_app_server/adapter.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/codex_app_server/schema_preflight.py`](../../src/prompt_enhancer/infrastructure/providers/codex_app_server/schema_preflight.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/codex_app_server/content_source.py`](../../src/prompt_enhancer/infrastructure/providers/codex_app_server/content_source.py) — different

**Tests:** [`tests/test_codex_ingestion_privacy.py`](../../tests/test_codex_ingestion_privacy.py) — identical-lf-normalized<br>[`tests/test_provider_compatibility_service.py`](../../tests/test_provider_compatibility_service.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Adapter unchanged against origin/main; read-only construction and consent-tier declarations inspected.

**Gap:** Supported installed-provider versions and complete source coverage require explicit acceptance; raw provider data was not accessed.

**Next:** Qualify a documented version using synthetic schema/transport fixtures, then separately authorized real-provider acceptance.

## MA03

**Claude opt-in hooks and content-free telemetry ledger** — PARTIAL; required; gates `B07 V12/V17`.

Dependencies: MA01

**Source:** [`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/receiver.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/receiver.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/adapter.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/adapter.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/telemetry.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/telemetry.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/http/otlp_ingest_routes.py`](../../src/prompt_enhancer/interfaces/http/otlp_ingest_routes.py) — identical-lf-normalized

**Tests:** [`tests/test_claude_code_hooks_adapter.py`](../../tests/test_claude_code_hooks_adapter.py) — identical-lf-normalized<br>[`tests/test_claude_code_hooks_receiver.py`](../../tests/test_claude_code_hooks_receiver.py) — identical-lf-normalized<br>[`tests/test_claude_code_telemetry.py`](../../tests/test_claude_code_telemetry.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Adapter and OTLP route unchanged against origin/main; synthetic end-to-end ingestion test exists.

**Gap:** Hooks do not enumerate requirement/hypothesis/verification opportunity sets and cannot make those metric denominators complete.

**Next:** Test installation opt-in, revocation, version changes and duplicate delivery against the declared synthetic source matrix.

## MA04

**Versioned Claude transcript compatibility reader** — PARTIAL; required; gates `B07 V12/V17`.

Dependencies: MA01

**Source:** [`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/transcript_adapter.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/transcript_adapter.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/transcript_reader.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/transcript_reader.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/providers/claude_code_hooks/text_source.py`](../../src/prompt_enhancer/infrastructure/providers/claude_code_hooks/text_source.py) — identical-lf-normalized

**Tests:** [`tests/test_session_provider_resolution.py`](../../tests/test_session_provider_resolution.py) — identical-lf-normalized<br>[`tests/test_session_model_ensemble.py`](../../tests/test_session_model_ensemble.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Transcript adapter unchanged against origin/main.

**Gap:** Compatibility adapter is implemented; complete-history assumptions, truncation/rotation and actual provider acceptance remain separately gated.

**Next:** Preserve explicit completeness/version evidence and qualify supported source versions.

## MA05

**Minimization, pseudonymous ingest and ephemeral redaction preview** — PARTIAL; required; gates `B07/B11 V17`.

Dependencies: MA02, MA03, MA04

**Source:** [`src/prompt_enhancer/privacy.py`](../../src/prompt_enhancer/privacy.py) — identical-lf-normalized<br>[`src/prompt_enhancer/ingestion.py`](../../src/prompt_enhancer/ingestion.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/redaction_preview.py`](../../src/prompt_enhancer/application/analysis/redaction_preview.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/text_contracts.py`](../../src/prompt_enhancer/application/analysis/text_contracts.py) — different

**Tests:** [`tests/test_ingestion_and_database.py::test_raw_source_identifiers_never_cross_sqlite_boundary`](../../tests/test_ingestion_and_database.py) — identical-lf-normalized<br>[`tests/test_redaction_preview.py`](../../tests/test_redaction_preview.py) — identical-lf-normalized<br>[`tests/test_local_redaction.py`](../../tests/test_local_redaction.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Ingestion/privacy unchanged against origin/main. Bounded preview store has explicit TTL, exact approval and no persistence port.

**Gap:** Current full pipeline/privacy and native review acceptance still needed; pseudonymous derived metrics remain sensitive.

**Next:** Carry canaries through ingress, persistence, API and UI/export in one current-build test.

## MA06

**Explicit trusted metric dependency graph** — READY (bounded); required; gates `B07 component contract`.

Dependencies: MA05

**Source:** [`src/prompt_enhancer/application/analysis/registry.py`](../../src/prompt_enhancer/application/analysis/registry.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/contracts.py`](../../src/prompt_enhancer/application/analysis/contracts.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/deterministic.py`](../../src/prompt_enhancer/application/analysis/deterministic.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_engine_composition.py::test_registry_rejects_feature_dependency_cycles`](../../tests/test_metric_engine_composition.py) — identical-lf-normalized<br>[`tests/test_metric_engine_composition.py::test_unknown_values_survive_composed_calculation`](../../tests/test_metric_engine_composition.py) — identical-lf-normalized<br>[`tests/test_metric_engine_contracts.py`](../../tests/test_metric_engine_contracts.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Bounded readiness is the pure trusted-registry/component contract only: unchanged against origin/main; historical metric synthetic selections passed (ledger 306 metric-named tests). Fresh October 8 synthetic selection: 122 tests passed across metric contracts/composition, session/project aggregation and Agent contract/parameter modules; owned cleanup confirmed. This count covers the whole selection, not each node.

**Gap:** This green node does not qualify inference, provider coverage or release behavior.

**Next:** Retain duplicate/missing/cycle/tier/unknown contract tests and run them on the selected documentation commit if needed.

## MA07

**Canonical twenty-metric schema and operability catalog** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_evidence_readiness_v2.py`](../../src/prompt_enhancer/application/analysis/metric_evidence_readiness_v2.py) — identical-lf-normalized<br>[`docs/metric-operability.md`](../../docs/metric-operability.md) — different

**Tests:** [`tests/test_metric_contract_v2.py`](../../tests/test_metric_contract_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Source confirms 20 contracts, 18 evidence-conditional paths, two adapter gaps, eight experimental estimate paths and zero model-authoritative measured metrics.

**Gap:** Contract file unchanged but operability differs from origin/main. Catalog existence is not twenty numeric metrics per session.

**Next:** Keep per-contract readiness and unavailable reasons visible; close the two provider adapter gaps without substituting estimates.

## MA08

**Reviewed lifecycle, task profile and requirement evidence** — PARTIAL; required; gates `B05/B07 V08/V12`.

Dependencies: MA05, MA07

**Source:** [`src/prompt_enhancer/application/analysis/metric_lifecycle_evidence.py`](../../src/prompt_enhancer/application/analysis/metric_lifecycle_evidence.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/declared_task_profiles.py`](../../src/prompt_enhancer/application/analysis/declared_task_profiles.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/requirement_plan_evidence.py`](../../src/prompt_enhancer/application/analysis/requirement_plan_evidence.py) — different<br>[`src/prompt_enhancer/application/analysis/requirement_action_evidence.py`](../../src/prompt_enhancer/application/analysis/requirement_action_evidence.py) — different<br>[`src/prompt_enhancer/application/analysis/requirement_verification_evidence.py`](../../src/prompt_enhancer/application/analysis/requirement_verification_evidence.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_projection_v5.py`](../../tests/test_metric_projection_v5.py) — identical-lf-normalized<br>[`tests/test_metric_projection_v6.py`](../../tests/test_metric_projection_v6.py) — identical-lf-normalized<br>[`tests/test_metric_projection_v7.py`](../../tests/test_metric_projection_v7.py) — identical-lf-normalized<br>[`tests/test_metric_projection_v8.py`](../../tests/test_metric_projection_v8.py) — identical-lf-normalized<br>[`tests/test_requirement_verification_live_e2e.py`](../../tests/test_requirement_verification_live_e2e.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Historical source/integration evidence exists; plan/action files differ from origin/main; verification file unchanged.

**Gap:** Source/browser/API mocks cannot establish actual native review authority or complete provider enumeration.

**Next:** Use one synthetic project to exercise actual native review, stale rejection, current sealed publication and rendered values.

## MA09

**Claim census and observed-check link proposals** — PARTIAL; required; gates `B07 V12/V17`.

Dependencies: MA08

**Source:** `src/prompt_enhancer/application/analysis/claim_grounding_census.py` — absent-on-main<br>`src/prompt_enhancer/application/analysis/claim_grounding_links.py` — absent-on-main<br>`src/prompt_enhancer/application/analysis/claim_grounding_link_review.py` — absent-on-main<br>`frontend/src/features/model-ensemble/ClaimGroundingLinkReviewPanel.tsx` — absent-on-main

**Tests:** [`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different<br>`frontend/src/features/model-ensemble/ClaimGroundingLinkReviewPanel.adversarial.test.tsx` — absent-on-main

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. claim_grounding_links.py absent from origin/main. Contracts explicitly set proposal_only true, measured false and metric_authority_established false.

**Gap:** UI/review proposal work exists but does not close the claim-grounding measured adapter.

**Next:** Complete exact outcome-authority design and tests before changing metric operability; preserve proposal labeling.

## MA10

**Experimental factor model adapters and bounded serial workers** — PARTIAL; experimental; gates `B04/B07 model interpretation gate`.

Dependencies: MA05, MA07

**Source:** [`src/prompt_enhancer/infrastructure/text_models/model_ensemble.py`](../../src/prompt_enhancer/infrastructure/text_models/model_ensemble.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/model_ensemble.py`](../../src/prompt_enhancer/application/analysis/model_ensemble.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/probabilistic_metrics.py`](../../src/prompt_enhancer/application/analysis/probabilistic_metrics.py) — different

**Tests:** [`tests/test_local_model_ensemble_expert_contract.py`](../../tests/test_local_model_ensemble_expert_contract.py) — different<br>[`tests/test_chunked_model_ensemble.py`](../../tests/test_chunked_model_ensemble.py) — different<br>[`tests/test_probabilistic_metric_contracts_v2.py`](../../tests/test_probabilistic_metric_contracts_v2.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Actual development-model pilots in the ledger failed semantic/structural comparison gates; adapters are real implementations, not mocks. Runtime file unchanged; probabilistic contracts differ from origin/main.

**Gap:** NLI/rubric interpretation remains unqualified. Exact quote and valid JSON do not establish semantic correctness. Single expert cannot meet minimum-two contributor pooling.

**Next:** Freeze references; qualify each approved contributor on development then holdout; retain rejected/incomplete cases and actual resource cleanup evidence.

## MA11

**Experimental probability pooling and calibration gates** — PARTIAL; experimental; gates `B07 model aggregation gate`.

Dependencies: MA10

**Source:** [`src/prompt_enhancer/application/analysis/probabilistic_metrics.py`](../../src/prompt_enhancer/application/analysis/probabilistic_metrics.py) — different<br>[`src/prompt_enhancer/infrastructure/text_models/probabilistic_metrics.py`](../../src/prompt_enhancer/infrastructure/text_models/probabilistic_metrics.py) — different

**Tests:** [`tests/test_probabilistic_metric_contracts_v2.py`](../../tests/test_probabilistic_metric_contracts_v2.py) — identical-lf-normalized<br>[`tests/test_probabilistic_metric_persistence.py`](../../tests/test_probabilistic_metric_persistence.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Source pins not-calibrated-v1, minimum two experts and explicit unresolved-mass/retained-sample gates.

**Gap:** Calibration/domain validity and actual multi-expert pooling remain open; estimates must stay separate from measurements.

**Next:** Validate actual contributor outputs through pooling, then domain calibration and unknown/OOD withholding.

## MA12

**Sealed session analysis and publication** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08, MA11

**Source:** [`src/prompt_enhancer/application/analysis/session_model_ensemble.py`](../../src/prompt_enhancer/application/analysis/session_model_ensemble.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v8.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v8.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_publication_v2.py`](../../src/prompt_enhancer/application/analysis/metric_publication_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/sqlite/model_ensemble.py`](../../src/prompt_enhancer/infrastructure/sqlite/model_ensemble.py) — different

**Tests:** [`tests/test_session_model_ensemble.py`](../../tests/test_session_model_ensemble.py) — identical-lf-normalized<br>[`tests/test_model_ensemble_r8_persistence.py`](../../tests/test_model_ensemble_r8_persistence.py) — identical-lf-normalized<br>[`tests/test_model_ensemble_r8_api.py`](../../tests/test_model_ensemble_r8_api.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Session service and SQLite ensemble file differ from origin/main; current projection_v8 unchanged.

**Gap:** One current source-to-model-to-store-to-API-to-radar acceptance is open. Large service and repository mix many evidence versions and authorities.

**Next:** Qualify current end-to-end publication; only then extract cohesive orchestration/review/persistence pieces behind unchanged contracts.

## MA13

**Durable live watch, attempts, retry/backoff and last valid head** — PARTIAL; required; gates `B02/B07 V07/V13`.

Dependencies: MA12

**Source:** [`src/prompt_enhancer/application/analysis/model_ensemble_watch.py`](../../src/prompt_enhancer/application/analysis/model_ensemble_watch.py) — different<br>[`src/prompt_enhancer/infrastructure/sqlite/model_ensemble_watch.py`](../../src/prompt_enhancer/infrastructure/sqlite/model_ensemble_watch.py) — different<br>[`src/prompt_enhancer/interfaces/http/model_ensemble_watch_routes.py`](../../src/prompt_enhancer/interfaces/http/model_ensemble_watch_routes.py) — identical-lf-normalized

**Tests:** [`tests/test_session_model_ensemble.py`](../../tests/test_session_model_ensemble.py) — identical-lf-normalized<br>[`tests/test_model_ensemble_persistence.py`](../../tests/test_model_ensemble_persistence.py) — different<br>`tests/test_analysis_job_cancel_publication_races.py` — absent-on-main

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. State/lease/attempt contracts and bounded failure policy inspected; watch source differs from origin/main.

**Gap:** Real runtime failure/recovery, cancellation and restart plus last-valid-head display need exact current native/model acceptance.

**Next:** Exercise one successful refresh, provider/runtime failure, explicit retry, cancel and process cleanup without touching personal sessions.

## MA14

**Engineering V1 session/project ratio aggregation** — READY (bounded); required; gates `B07 component aggregation / V12`.

Dependencies: MA06

**Source:** [`src/prompt_enhancer/application/analysis/session_quality_aggregation.py`](../../src/prompt_enhancer/application/analysis/session_quality_aggregation.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/project_quality_aggregation.py`](../../src/prompt_enhancer/application/analysis/project_quality_aggregation.py) — identical-lf-normalized

**Tests:** [`tests/test_session_quality_aggregation.py::test_known_metrics_use_ratio_of_sums_and_summed_coverage`](../../tests/test_session_quality_aggregation.py) — identical-lf-normalized<br>[`tests/test_session_quality_aggregation.py::test_every_compatibility_dimension_blocks_mixed_provenance_without_a_winner`](../../tests/test_session_quality_aggregation.py) — identical-lf-normalized<br>[`tests/test_project_quality_aggregation.py`](../../tests/test_project_quality_aggregation.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Green is bounded pure read-only aggregation readiness only: both files unchanged against origin/main; historical ledger covers synthetic storage/API aggregation and one packaged dashboard path. Input is SessionAnalysisRunRepository / STANDARD_ENGINEERING_V1, not canonical model-ensemble sealed receipts. Green does not certify all-twenty ensemble pooling. Fresh October 8 synthetic selection: 122 tests passed across metric contracts/composition, session/project aggregation and Agent contract/parameter modules; owned cleanup confirmed. This count covers the whole selection, not each node.

**Gap:** No claim of universal cross-provider/model comparability or all-state rendered acceptance.

**Next:** Keep ratio-of-sums within exact provenance cohorts; add current measured/Pending UI cases to narrow packaged coverage.

## MA15

**Metric storage, coverage/provenance and read-only API** — PARTIAL; required; gates `B07 V12/V17`.

Dependencies: MA12, MA14

**Source:** [`src/prompt_enhancer/infrastructure/sqlite/metric_coverage.py`](../../src/prompt_enhancer/infrastructure/sqlite/metric_coverage.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/sqlite/session_analysis_runs.py`](../../src/prompt_enhancer/infrastructure/sqlite/session_analysis_runs.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/http/metric_coverage_routes.py`](../../src/prompt_enhancer/interfaces/http/metric_coverage_routes.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/mcp/server.py`](../../src/prompt_enhancer/interfaces/mcp/server.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_coverage_sqlite.py`](../../tests/test_metric_coverage_sqlite.py) — identical-lf-normalized<br>[`tests/test_metric_coverage_api.py`](../../tests/test_metric_coverage_api.py) — identical-lf-normalized<br>[`tests/test_session_metric_pack_provenance.py`](../../tests/test_session_metric_pack_provenance.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Ledger packaged synthetic analytics pass b0e075 carried one fictional source through API/browser: Unknown tokens, observed 0/eligible 1/coverage 0, verification count 0 without completion-prose success.

**Gap:** One synthetic source is not all metrics/states, native or live-provider acceptance.

**Next:** Extend exact hand-computed fixtures across state and provenance matrix; retain read-only allowlisted exports.

## MA16

**Live radar, metric workspace and session selection UI** — PARTIAL; required; gates `B07/B10 V12/V13`.

Dependencies: MA13, MA15

**Source:** [`frontend/src/features/model-ensemble/ModelEnsembleOverlay.tsx`](../../frontend/src/features/model-ensemble/ModelEnsembleOverlay.tsx) — different<br>[`frontend/src/features/model-ensemble/ModelEnsembleRadar.tsx`](../../frontend/src/features/model-ensemble/ModelEnsembleRadar.tsx) — different<br>[`frontend/src/features/model-ensemble/MetricWorkspace.tsx`](../../frontend/src/features/model-ensemble/MetricWorkspace.tsx) — different<br>[`frontend/src/features/session-radar/SessionRadarCard.tsx`](../../frontend/src/features/session-radar/SessionRadarCard.tsx) — different<br>[`frontend/src/features/live-window/LiveMiniWindow.tsx`](../../frontend/src/features/live-window/LiveMiniWindow.tsx) — identical-lf-normalized

**Tests:** [`frontend/src/features/model-ensemble/ModelEnsembleOverlay.test.tsx`](../../frontend/src/features/model-ensemble/ModelEnsembleOverlay.test.tsx) — different<br>[`frontend/src/features/model-ensemble/ModelEnsembleRadar.test.ts`](../../frontend/src/features/model-ensemble/ModelEnsembleRadar.test.ts) — different<br>`frontend/src/features/session-radar/SessionRadarCard.test.tsx` — absent-on-main<br>[`frontend/src/features/live-window/LiveMiniWindow.test.tsx`](../../frontend/src/features/live-window/LiveMiniWindow.test.tsx) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Radar/overlay/SessionRadar sources differ from origin/main; synthetic UI regressions and historical packaged slice exist.

**Gap:** Two different live surfaces (legacy timeline mini-window and canonical ensemble overlay) need clear navigation/naming. Complete runtime-to-radar and native viewport acceptance open.

**Next:** Test selection/change, stale head, missing axes, retry, scroll/viewport and reconnect with the actual canonical service.

## MA17

**Calibration review, saved ratings and reports** — PARTIAL; experimental; gates `B07 V12`.

Dependencies: MA15

**Source:** [`src/prompt_enhancer/application/analysis/calibration_cases.py`](../../src/prompt_enhancer/application/analysis/calibration_cases.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/calibration_ratings.py`](../../src/prompt_enhancer/application/analysis/calibration_ratings.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/estimators/calibration_reporting.py`](../../src/prompt_enhancer/application/estimators/calibration_reporting.py) — identical-lf-normalized<br>[`frontend/src/features/calibration/CalibrationPage.tsx`](../../frontend/src/features/calibration/CalibrationPage.tsx) — identical-lf-normalized

**Tests:** [`tests/test_calibration_cases.py`](../../tests/test_calibration_cases.py) — different<br>[`tests/test_calibration_ratings.py`](../../tests/test_calibration_ratings.py) — identical-lf-normalized<br>[`tests/test_calibration_report_persistence.py`](../../tests/test_calibration_report_persistence.py) — different<br>`tests/test_packaged_calibration_receipt.py` — absent-on-main

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Historical packaged synthetic passes d9ff5a/73227d saved three ratings including cannot-judge across reload/export. Ratings source unchanged against origin/main. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Saved ratings/UI do not establish model calibration; full module batch, expiry and real-model quality acceptance open.

**Next:** Add current review expiry/restart cases and a separately governed calibration dataset/quality gate. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## MA18

**Prompt check, optional rewrite and Claude submit hook** — PARTIAL; required; gates `B03/B07 V12`.

Dependencies: MA06

**Source:** [`src/prompt_enhancer/application/prompt_check.py`](../../src/prompt_enhancer/application/prompt_check.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/hooks/prompt_check_hook.py`](../../src/prompt_enhancer/interfaces/hooks/prompt_check_hook.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/http/prompt_check_routes.py`](../../src/prompt_enhancer/interfaces/http/prompt_check_routes.py) — identical-lf-normalized<br>[`frontend/src/features/prompt-check/PromptCheckPage.tsx`](../../frontend/src/features/prompt-check/PromptCheckPage.tsx) — identical-lf-normalized

**Tests:** [`tests/test_prompt_check.py`](../../tests/test_prompt_check.py) — identical-lf-normalized<br>[`frontend/src/features/prompt-check/PromptCheckPage.test.tsx`](../../frontend/src/features/prompt-check/PromptCheckPage.test.tsx) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Core/hook unchanged against origin/main. Six deterministic cue metrics plus optional labeled local-model commentary; source comments/tests prohibit prompt/commentary persistence. Deterministic preflight works without a loaded model; optional commentary/rewrite uses the active A08 runtime. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Current full model/hook installed experience and workflow-backed enhancement integration remain unqualified; deterministic cues are limited language/task heuristics.

**Next:** Validate user draft retention, explicit apply, local-model unavailable fallback and opt-in hook failure behavior; route future workflow enhancement through same reviewed boundary. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## MA19

**Synthetic demonstration transport and provider fixtures** — MOCK / DEMO; experimental; gates `B01/B07 V17`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/adapters/synthetic.py`](../../src/prompt_enhancer/adapters/synthetic.py) — identical-lf-normalized<br>[`frontend/src/shared/api/syntheticTransport.ts`](../../frontend/src/shared/api/syntheticTransport.ts) — different<br>[`frontend/src/shared/platform/runtimeMode.ts`](../../frontend/src/shared/platform/runtimeMode.ts) — identical-lf-normalized

**Tests:** [`frontend/src/shared/api/syntheticTransport.test.ts`](../../frontend/src/shared/api/syntheticTransport.test.ts) — different<br>[`frontend/src/shared/platform/runtimeMode.test.ts`](../../frontend/src/shared/platform/runtimeMode.test.ts) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Explicit synthetic_demo/local_real discriminated transport composition inspected.

**Gap:** Demo numbers and fake transports cannot certify live metrics; this grey node is intentional test/demo infrastructure.

**Next:** Keep preview badge and reject transport/runtime mismatch; never silently fallback from real service to synthetic data.

## MA20

**Historical V1 publication compatibility preview** — PARTIAL; experimental; gates `B07 V12`.

Dependencies: MA07, MA15

**Source:** [`src/prompt_enhancer/application/analysis/session_metric_publication_service.py`](../../src/prompt_enhancer/application/analysis/session_metric_publication_service.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_publication_api.py`](../../tests/test_metric_publication_api.py) — different<br>[`tests/test_metric_publication_v2.py`](../../tests/test_metric_publication_v2.py) — identical-lf-normalized

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Service explicitly documents read-only preview, not canonical live head, with withholding tags.

**Gap:** Architecture/UI must not treat this preview as current all-twenty publication or a fallback success.

**Next:** Retain compatibility identity and visible limits; keep it out of the canonical watch head path.

## MC01

**prompt.task_definition_coverage** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v2.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v2.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v2.py`](../../tests/test_metric_projection_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Focus-owned fixed-factor rubric.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC02

**prompt.problem_evidence_quality** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v2.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v2.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v2.py`](../../tests/test_metric_projection_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Focus-owned diagnostic-task rubric.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC03

**prompt.context_sufficiency** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v2.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v2.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v2.py`](../../tests/test_metric_projection_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Focus-owned fixed-factor context rubric.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC04

**prompt.constraint_precision** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v5.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v5.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v5.py`](../../tests/test_metric_projection_v5.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Reviewed declared task-profile slots.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC05

**prompt.acceptance_testability** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v5.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v5.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v5.py`](../../tests/test_metric_projection_v5.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Reviewed outcomes and distinct checkable active clauses.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC06

**prompt.deliverable_contract** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v5.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v5.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v5.py`](../../tests/test_metric_projection_v5.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Reviewed deliverable slots.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC07

**collaboration.ambiguity_resolution** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v4.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v4.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Confirmed complete lifecycle enumeration.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC08

**collaboration.clarification_yield** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v4.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v4.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Confirmed complete lifecycle enumeration.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC09

**collaboration.exploration_conversion** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v4.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v4.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Confirmed complete lifecycle enumeration.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC10

**collaboration.scope_change_discipline** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v4.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v4.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Confirmed complete lifecycle enumeration.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC11

**collaboration.rework_candidate_rate** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v4.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v4.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v4.py`](../../tests/test_metric_projection_v4.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Confirmed rework lifecycle, lower-is-better numerator.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC12

**logic.decomposition_coverage** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v6.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v6.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v6.py`](../../tests/test_metric_projection_v6.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Native-reviewed clause classification and plan links.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC13

**logic.hypothesis_test_linkage** — MEASURED ADAPTER ABSENT; required; gates `B07 V12`.

Dependencies: MA07

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/provider_evidence.py`](../../src/prompt_enhancer/application/analysis/provider_evidence.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Missing typed hypothesis opportunity/link/outcome adapter.

**Gap:** Metric contract and withholding exist; the required measured adapter is absent. Proposals/model output are not outcome authority.

**Next:** Implement a versioned authoritative opportunity/link/outcome adapter with negative and provenance tests before enabling numeric publication.

## MC14

**logic.decision_rationale_coverage** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/semantic_units.py`](../../src/prompt_enhancer/application/analysis/semantic_units.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v2.py`](../../tests/test_metric_projection_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Documented decision semantic units.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC15

**logic.requirement_action_traceability** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v7.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v7.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v7.py`](../../tests/test_metric_projection_v7.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Native-reviewed requirement-to-action graph.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC16

**logic.open_loop_closure** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v3.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v3.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v3.py`](../../tests/test_metric_projection_v3.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Explicit plan-to-superseding-action link.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC17

**outcome.agent_claim_grounding** — MEASURED ADAPTER ABSENT; required; gates `B07 V12`.

Dependencies: MA07, MA09

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/provider_evidence.py`](../../src/prompt_enhancer/application/analysis/provider_evidence.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Missing measured claim opportunity/link/outcome adapter.

**Gap:** Metric contract and withholding exist; the required measured adapter is absent. Proposals/model output are not outcome authority.

**Next:** Implement a versioned authoritative opportunity/link/outcome adapter with negative and provenance tests before enabling numeric publication.

## MC18

**outcome.verification_strategy_adequacy** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA06

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/semantic_units.py`](../../src/prompt_enhancer/application/analysis/semantic_units.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v2.py`](../../tests/test_metric_projection_v2.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Documented verification-strategy semantic units.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC19

**outcome.first_pass_verification** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/objective_metric_projection.py`](../../src/prompt_enhancer/application/analysis/objective_metric_projection.py) — identical-lf-normalized

**Tests:** [`tests/test_objective_metric_projection.py`](../../tests/test_objective_metric_projection.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Reviewed task and task-scoped verification receipt.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## MC20

**outcome.verified_requirement_coverage** — PARTIAL; required; gates `B07 V12`.

Dependencies: MA07, MA08

**Source:** [`src/prompt_enhancer/application/analysis/metric_contract_v2.py`](../../src/prompt_enhancer/application/analysis/metric_contract_v2.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/analysis/metric_operability.py`](../../src/prompt_enhancer/application/analysis/metric_operability.py) — different<br>[`src/prompt_enhancer/application/analysis/metric_projection_v8.py`](../../src/prompt_enhancer/application/analysis/metric_projection_v8.py) — identical-lf-normalized

**Tests:** [`tests/test_metric_projection_v8.py`](../../tests/test_metric_projection_v8.py) — identical-lf-normalized<br>[`tests/test_metric_operability.py`](../../tests/test_metric_operability.py) — different

**Evidence:** Read-only source/test inspection 2026-10-08. No tests or native/provider/model execution rerun by this audit. Historical ledger evidence must be rebound to a current commit/package. Canonical operability-v6 contract: Reviewed compatible Codex source, plan, observed check and fresh seal.

**Gap:** Measured implementation exists conditionally. Exact reviewed evidence, complete denominator and current storage/API/rendered/native acceptance remain required; missing evidence is not zero.

**Next:** Exercise hand-computable known/zero/unknown/pending/not-applicable cases end to end, including required review and provenance.

## A01

**Agent wire contracts** — READY (bounded); required; gates `B00; supports B03/B05`.

Dependencies: Entry/boundary component; see system map.

**Source:** `src/prompt_enhancer/application/local_agent_contracts.py` — absent-on-main<br>[`src/prompt_enhancer/application/local_agent_limits.py`](../../src/prompt_enhancer/application/local_agent_limits.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/local_agent_receipts.py`](../../src/prompt_enhancer/application/local_agent_receipts.py) — identical-lf-normalized

**Tests:** `tests/test_local_agent_contracts.py` — absent-on-main<br>`tests/test_agent_parameters_contract.py` — absent-on-main

**Evidence:** Bounded source contract extraction: ledger September 27 records 398 distinct passing cases, identical 43 AST definitions and 17 public schemas. Inspected October 8; this is historical source evidence, not installed-app acceptance. Fresh October 8 synthetic selection: 122 tests passed across metric contracts/composition, session/project aggregation and Agent contract/parameter modules; owned cleanup confirmed. This count covers the whole selection, not each node.

**Gap:** Extracted contract module is absent from origin/main; retain identity and import-side-effect guarantees during integration.

**Next:** Admit this reviewed dependency-complete extraction through owner-reviewed PR and run its focused regression selection at the candidate commit.

## A02

**Persistent Agent projects and chat catalog** — PARTIAL; required; gates `B03/V02/V04/V07`.

Dependencies: A01

**Source:** [`src/prompt_enhancer/application/agent_catalog.py`](../../src/prompt_enhancer/application/agent_catalog.py) — different<br>[`src/prompt_enhancer/infrastructure/sqlite/agent_catalog.py`](../../src/prompt_enhancer/infrastructure/sqlite/agent_catalog.py) — different<br>[`frontend/src/features/agent/AgentCatalogRail.tsx`](../../frontend/src/features/agent/AgentCatalogRail.tsx) — identical-lf-normalized

**Tests:** [`tests/test_agent_catalog.py`](../../tests/test_agent_catalog.py) — different<br>[`frontend/src/features/agent/AgentCatalogRail.test.tsx`](../../frontend/src/features/agent/AgentCatalogRail.test.tsx) — identical-lf-normalized

**Evidence:** Inspected source October 8: project/chat creation, revision checks, search, pin/archive/restore/delete and repository Protocol exist; tests present. Historical B03 synthetic results remain bounded.

**Gap:** Actual installed restart and whole lifecycle acceptance are open. Catalog metadata persistence does not imply opted-in message retention.

**Next:** Exercise all catalog actions and workspace-preserving deletion after native restart on the frozen candidate.

## A03

**Conversation retention and restart recovery** — PARTIAL; required; gates `B03/V07`.

Dependencies: A02

**Source:** [`src/prompt_enhancer/application/agent_catalog.py`](../../src/prompt_enhancer/application/agent_catalog.py) — different<br>[`src/prompt_enhancer/application/local_agent.py`](../../src/prompt_enhancer/application/local_agent.py) — different<br>[`src/prompt_enhancer/infrastructure/sqlite/agent_catalog.py`](../../src/prompt_enhancer/infrastructure/sqlite/agent_catalog.py) — different

**Tests:** [`tests/test_agent_history.py`](../../tests/test_agent_history.py) — identical-lf-normalized<br>`frontend/src/features/agent/AgentPage.resumeOwnership.test.tsx` — absent-on-main

**Evidence:** Append-only event journal and deterministic projection inspected October 8. Historical packaged synthetic probe retained complete and stopped replies across forced server restart.

**Gap:** History is explicit local-history opt-in; recovered authority is off. Graceful native restart and real inference interruption remain unqualified.

**Next:** Prove graceful close/reopen, interrupted truth, storage failure and read-only recovery without copying approval authority.

## A04

**Saved-message search, fork and export** — PARTIAL; required; gates `B03/V04/V17`.

Dependencies: A02, A03

**Source:** [`src/prompt_enhancer/application/agent_catalog.py`](../../src/prompt_enhancer/application/agent_catalog.py) — different<br>[`frontend/src/features/agent/AgentMessageSearchDialog.tsx`](../../frontend/src/features/agent/AgentMessageSearchDialog.tsx) — different<br>[`frontend/src/features/agent/AgentCatalogRail.tsx`](../../frontend/src/features/agent/AgentCatalogRail.tsx) — identical-lf-normalized

**Tests:** [`tests/test_agent_message_search.py`](../../tests/test_agent_message_search.py) — identical-lf-normalized<br>[`tests/test_agent_message_search_storage.py`](../../tests/test_agent_message_search_storage.py) — identical-lf-normalized<br>[`tests/test_agent_session_forking.py`](../../tests/test_agent_session_forking.py) — identical-lf-normalized

**Evidence:** Source exposes snapshot-bound paging, settled-history fork, explicit export. Tests cover atomic cross-repository fork and unsupported metadata-only source.

**Gap:** Feature-complete native journey and export review remain open; external controller manifest intentionally excludes saved-message search.

**Next:** Validate selected-data export, fork lineage, duplicate request handling and search across restart.

## A05

**Chat composer, drafts and runtime picker** — PARTIAL; required; gates `B03/B10/V02/V13`.

Dependencies: A02, A08, A09

**Source:** [`frontend/src/features/agent/AgentPage.tsx`](../../frontend/src/features/agent/AgentPage.tsx) — different<br>[`frontend/src/features/agent/AgentRuntimeControl.tsx`](../../frontend/src/features/agent/AgentRuntimeControl.tsx) — different<br>`frontend/src/features/agent/AgentGenerationSettings.tsx` — absent-on-main

**Tests:** [`frontend/src/features/agent/AgentPage.test.tsx`](../../frontend/src/features/agent/AgentPage.test.tsx) — different<br>`frontend/src/features/agent/AgentPage.closeDraft.test.tsx` — absent-on-main<br>[`frontend/src/features/agent/AgentRuntimeControl.test.tsx`](../../frontend/src/features/agent/AgentRuntimeControl.test.tsx) — different

**Evidence:** Source allows model-free chat/drafting, separates runtime selection, capability states and draft retention; inspected October 8. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** AgentPage remains a large stateful orchestration component; supported native scaling and all keyboard/focus/viewport paths not accepted. Dirty tree differs substantially from main.

**Next:** Finish bounded native composer/picker acceptance; extract controllers only when changing a demonstrated defect. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A06

**Conversation streaming, Stop and activity** — PARTIAL; required; gates `B03/B04/V05/V06/V07`.

Dependencies: A01, A03, A08

**Source:** [`src/prompt_enhancer/application/local_agent.py`](../../src/prompt_enhancer/application/local_agent.py) — different<br>[`frontend/src/features/agent/AgentConversationTimeline.tsx`](../../frontend/src/features/agent/AgentConversationTimeline.tsx) — different<br>[`frontend/src/features/agent/AgentTurnDetails.tsx`](../../frontend/src/features/agent/AgentTurnDetails.tsx) — different

**Tests:** [`tests/test_local_agent_completion.py`](../../tests/test_local_agent_completion.py) — identical-lf-normalized<br>[`tests/test_local_agent_turn_details.py`](../../tests/test_local_agent_turn_details.py) — identical-lf-normalized<br>[`tests/test_local_agent_usage_transport.py`](../../tests/test_local_agent_usage_transport.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentConversationTimeline.test.tsx`](../../frontend/src/features/agent/AgentConversationTimeline.test.tsx) — identical-lf-normalized

**Evidence:** Monotonic event sequence, stream phase and terminal receipts exist. Historical packaged fixture proves streaming/Stop/recovery without real inference. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Exact qualified model streaming, crash and cancellation cleanup remain unaccepted; model-provided reasoning is conditional and cannot be manufactured.

**Next:** Run response/Stop/crash/restart with the approved CPU and NVIDIA profiles, retaining truthful finish reasons. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A07

**Safe Markdown, code and workspace links** — PARTIAL; required; gates `B05/B10/V09/V17`.

Dependencies: A06

**Source:** [`frontend/src/features/agent/AgentMessageContent.tsx`](../../frontend/src/features/agent/AgentMessageContent.tsx) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentCopyButton.tsx`](../../frontend/src/features/agent/AgentCopyButton.tsx) — identical-lf-normalized

**Tests:** [`frontend/src/features/agent/AgentMessageContent.test.tsx`](../../frontend/src/features/agent/AgentMessageContent.test.tsx) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentCopyButton.test.tsx`](../../frontend/src/features/agent/AgentCopyButton.test.tsx) — identical-lf-normalized

**Evidence:** October 8 inspection confirms react-markdown/GFM, protocol allowlist, remote image suppression and bounded relative workspace-link validation.

**Gap:** This audit did not execute renderer tests; complete browser/native content accessibility remains open.

**Next:** Include hostile HTML/link/media and copy/focus fixtures in the frozen UI acceptance run.

## A08

**Owned GGUF runtime and model switching** — PARTIAL; required; gates `B04/V05/V06/V07`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/application/local_models.py`](../../src/prompt_enhancer/application/local_models.py) — different<br>[`src/prompt_enhancer/interfaces/http/local_model_routes.py`](../../src/prompt_enhancer/interfaces/http/local_model_routes.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/owned_process.py`](../../src/prompt_enhancer/application/owned_process.py) — identical-lf-normalized

**Tests:** [`tests/test_local_models.py`](../../tests/test_local_models.py) — identical-lf-normalized

**Evidence:** One-runtime coordinator, CPU/GPU/split modes, revision-bound switch, health/capability probing and blocked unknown cleanup are implemented. Synthetic and subprocess-boundary tests exist. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Real CPU/NVIDIA model profiles, measured VRAM release and installed-runtime acceptance remain open. Generic compatibility must not imply any HF model works.

**Next:** Freeze exact profiles and qualify inference, switch during generation, crash and owned unload on supported hardware. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A09

**Exact chat context evidence** — PARTIAL; required; gates `B04/V05/V06`.

Dependencies: A08

**Source:** [`src/prompt_enhancer/application/agent_session_context.py`](../../src/prompt_enhancer/application/agent_session_context.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/local_models.py`](../../src/prompt_enhancer/application/local_models.py) — different<br>[`frontend/src/features/agent/AgentRuntimeControl.tsx`](../../frontend/src/features/agent/AgentRuntimeControl.tsx) — different

**Tests:** [`tests/test_local_models.py::test_exact_chat_context_preflight_refuses_before_inference`](../../tests/test_local_models.py) — identical-lf-normalized<br>[`tests/test_local_models.py::test_missing_or_malformed_exact_counter_remains_unknown`](../../tests/test_local_models.py) — identical-lf-normalized<br>[`frontend/src/shared/api/agentSessionContextContract.test.ts`](../../frontend/src/shared/api/agentSessionContextContract.test.ts) — identical-lf-normalized

**Evidence:** Context binds exact turn/model/request preflight. Recovered chats and unsupported counters explicitly remain unmeasured; inspected October 8. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Actual runtime template/token count behavior on the qualified profiles is not established by contracts alone.

**Next:** Verify context number and capacity against exact served runtime, then change model and restart to confirm invalidation. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A10

**Model catalog, download and placement advice** — PARTIAL; required; gates `B04; W00/W05`.

Dependencies: A08

**Source:** [`src/prompt_enhancer/application/local_models.py`](../../src/prompt_enhancer/application/local_models.py) — different<br>[`src/prompt_enhancer/interfaces/http/local_model_routes.py`](../../src/prompt_enhancer/interfaces/http/local_model_routes.py) — identical-lf-normalized

**Tests:** [`tests/test_local_models.py::test_download_verifies_the_pinned_artifact_and_records_its_provenance`](../../tests/test_local_models.py) — identical-lf-normalized<br>[`tests/test_local_models.py::test_placement_admission_fails_closed_without_accelerator_evidence`](../../tests/test_local_models.py) — identical-lf-normalized<br>[`tests/test_local_models.py::test_read_only_model_discovery_never_spawns_a_runtime`](../../tests/test_local_models.py) — identical-lf-normalized

**Evidence:** Verified provenance, size/hash download, hardware observation, compatibility and placement contracts exist. Public-only acquisition explicitly avoids cached HF credentials.

**Gap:** Automatic task-specific qualified-model recommendations across eight families are absent; existing hardware fit is not benchmarked best-model evidence.

**Next:** Qualify the bounded catalog and show estimated versus measured memory and evidence-backed task suitability.

## A11

**Native workspace folder selection** — PARTIAL; required; gates `B03/V03`.

Dependencies: A02

**Source:** [`src/prompt_enhancer/application/workspace_folder_picker.py`](../../src/prompt_enhancer/application/workspace_folder_picker.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentPage.tsx`](../../frontend/src/features/agent/AgentPage.tsx) — different<br>[`src/prompt_enhancer/interfaces/http/local_agent_routes.py`](../../src/prompt_enhancer/interfaces/http/local_agent_routes.py) — different

**Tests:** [`tests/test_workspace_folder_picker.py`](../../tests/test_workspace_folder_picker.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentPage.test.tsx`](../../frontend/src/features/agent/AgentPage.test.tsx) — different

**Evidence:** Capability/select/cancel/busy/unavailable states and model-independent creation flow exist.

**Gap:** Supported native select/cancel acceptance remains open; browser-only composition cannot imply native chooser availability.

**Next:** Verify chooser select/cancel before any model loads in the installed app.

## A12

**Workspace discovery, reads and search** — PARTIAL; required; gates `B05/V08/V17`.

Dependencies: A11

**Source:** [`src/prompt_enhancer/application/local_agent_workspace.py`](../../src/prompt_enhancer/application/local_agent_workspace.py) — different<br>[`src/prompt_enhancer/application/local_agent_discovery.py`](../../src/prompt_enhancer/application/local_agent_discovery.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentWorkspaceDiscoveryPanel.tsx`](../../frontend/src/features/agent/AgentWorkspaceDiscoveryPanel.tsx) — different

**Tests:** [`tests/test_workspace_read_boundaries.py`](../../tests/test_workspace_read_boundaries.py) — identical-lf-normalized<br>[`tests/test_workspace_discovery.py`](../../tests/test_workspace_discovery.py) — identical-lf-normalized<br>`tests/test_workspace_stat_semantics.py` — absent-on-main

**Evidence:** Workspace tools isolated from session orchestration; bounded list/read/search/discovery and path checks have source tests.

**Gap:** Broader adversarial and installed native acceptance remains open; maps are bounded, not proof every workspace file was understood.

**Next:** Validate traversal/reparse/race refusal and supported large/missing-file fallback with synthetic workspaces.

## A13

**Native one-shot approval authority** — PARTIAL; required; gates `B05/V08/V17`.

Dependencies: A01, A11

**Source:** [`src/prompt_enhancer/interfaces/http/user_presence.py`](../../src/prompt_enhancer/interfaces/http/user_presence.py) — different<br>[`src/prompt_enhancer/application/local_agent.py`](../../src/prompt_enhancer/application/local_agent.py) — different<br>[`frontend/src/features/agent/AgentReviewDrawer.tsx`](../../frontend/src/features/agent/AgentReviewDrawer.tsx) — identical-lf-normalized

**Tests:** [`tests/test_user_presence.py`](../../tests/test_user_presence.py) — different<br>[`tests/test_agent_write_proposals.py`](../../tests/test_agent_write_proposals.py) — identical-lf-normalized

**Evidence:** Keyed exact-request fingerprint, monotonic expiry and separate native capability exist; browser same-origin is only CSRF. Tests exercise refusal paths. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Actual native confirmation authorizing exactly the reviewed effect remains a release acceptance requirement.

**Next:** Prove approve/reject/cancel/stale review/project-switch paths through the actual installed native host. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A14

**Diffs, writes, change sets and lifecycle** — PARTIAL; required; gates `B05/V08/V09`.

Dependencies: A12, A13

**Source:** [`src/prompt_enhancer/application/local_agent_transactions.py`](../../src/prompt_enhancer/application/local_agent_transactions.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/local_agent_file_lifecycle.py`](../../src/prompt_enhancer/application/local_agent_file_lifecycle.py) — different<br>[`src/prompt_enhancer/application/local_agent_changes.py`](../../src/prompt_enhancer/application/local_agent_changes.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentChangeSetPanel.tsx`](../../frontend/src/features/agent/AgentChangeSetPanel.tsx) — identical-lf-normalized

**Tests:** [`tests/test_workspace_write_boundaries.py`](../../tests/test_workspace_write_boundaries.py) — identical-lf-normalized<br>[`tests/test_workspace_transactions.py`](../../tests/test_workspace_transactions.py) — identical-lf-normalized<br>[`tests/test_workspace_lifecycle.py`](../../tests/test_workspace_lifecycle.py) — identical-lf-normalized<br>[`tests/test_agent_change_set.py`](../../tests/test_agent_change_set.py) — identical-lf-normalized

**Evidence:** Create/edit/move/trash, previews and revision-bound transactions exist; historical packaged fixture proved refusal, discard and stale review with unchanged files.

**Gap:** Successful native-approved end-to-end write and recovery are still unaccepted; file lifecycle must not inherit chat deletion authority.

**Next:** Validate exact approve/reject writes, stale snapshots, multi-file partial failure and artifact reconciliation.

## A15

**Owned command execution** — PARTIAL; required; gates `B02/B05/V08/V17`.

Dependencies: A13

**Source:** [`src/prompt_enhancer/application/local_command_process.py`](../../src/prompt_enhancer/application/local_command_process.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/local_agent_workspace.py`](../../src/prompt_enhancer/application/local_agent_workspace.py) — different<br>[`src/prompt_enhancer/application/owned_process.py`](../../src/prompt_enhancer/application/owned_process.py) — identical-lf-normalized

**Tests:** [`tests/test_agent_command_control.py`](../../tests/test_agent_command_control.py) — identical-lf-normalized<br>[`tests/test_agent_command_process.py`](../../tests/test_agent_command_process.py) — identical-lf-normalized<br>[`tests/test_agent_command_windows.py`](../../tests/test_agent_command_windows.py) — identical-lf-normalized<br>[`tests/test_agent_command_api.py`](../../tests/test_agent_command_api.py) — identical-lf-normalized

**Evidence:** Bounded owned process, command control and Windows policy tests exist; native authority and cleanup truth integrate with Agent state. Later proposal (2026-10-09): ADR 0022 adds reviewed inference-provider selection on main 6fa1100; see the journal for synthetic evidence. This does not rebind the frozen October 8 source observation or qualify an external model.

**Gap:** Signed native acceptance, repeated lifecycle cycles and all cleanup failure UX not qualified.

**Next:** Verify approved synthetic commands, timeout/cancel, descendant cleanup and unresolved cleanup blocking further work. Review ADR 0022 and its gateway validation before accepting the inference boundary extension.

## A16

**Governed web fetch capability** — PARTIAL; experimental; gates `B01/B05/V17`.

Dependencies: A13

**Source:** `src/prompt_enhancer/application/governed_web_fetch.py` — absent-on-main<br>[`src/prompt_enhancer/application/local_agent_workspace.py`](../../src/prompt_enhancer/application/local_agent_workspace.py) — different<br>[`frontend/src/features/agent/AgentPage.tsx`](../../frontend/src/features/agent/AgentPage.tsx) — different

**Tests:** `tests/test_governed_web_fetch.py` — absent-on-main<br>`tests/test_governed_web_fetch_policy.py` — absent-on-main

**Evidence:** Governed-fetch boundary and explicit capability states exist. UI reports unavailable when no governed fetcher is installed.

**Gap:** Capability depends on composition; absence must not become an enabled placeholder. No native release fetch qualification claimed.

**Next:** Keep unavailable compositions disabled and qualify only the explicitly supported protected fetch profile.

## A17

**Verified artifact cards and lineage** — PARTIAL; required; gates `B05/V09`.

Dependencies: A14

**Source:** [`src/prompt_enhancer/application/agent_artifacts.py`](../../src/prompt_enhancer/application/agent_artifacts.py) — different<br>[`src/prompt_enhancer/infrastructure/sqlite/agent_artifacts.py`](../../src/prompt_enhancer/infrastructure/sqlite/agent_artifacts.py) — different<br>[`frontend/src/features/agent/AgentArtifactsPanel.tsx`](../../frontend/src/features/agent/AgentArtifactsPanel.tsx) — different<br>[`frontend/src/features/agent/AgentArtifactCaptureDialog.tsx`](../../frontend/src/features/agent/AgentArtifactCaptureDialog.tsx) — identical-lf-normalized

**Tests:** [`tests/test_agent_artifacts.py`](../../tests/test_agent_artifacts.py) — different<br>`tests/test_agent_directory_move_artifacts.py` — absent-on-main<br>[`frontend/src/features/agent/AgentArtifactCaptureDialog.test.tsx`](../../frontend/src/features/agent/AgentArtifactCaptureDialog.test.tsx) — identical-lf-normalized

**Evidence:** Artifacts synchronize verified writes or explicit capture of validated existing files, with versions, export lineage and directory-move reconciliation.

**Gap:** Native successful write-to-artifact journey and final package preview acceptance remain open; assistant prose alone is not artifact evidence.

**Next:** Verify real approved write/capture, renamed/missing/corrupt files and no false card after unsuccessful proposal.

## A18

**Bounded document and PDF handling** — PARTIAL; required; gates `B05/B08/V09/V18`.

Dependencies: A17

**Source:** [`src/prompt_enhancer/application/agent_document_previews.py`](../../src/prompt_enhancer/application/agent_document_previews.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentDocumentPreview.tsx`](../../frontend/src/features/agent/AgentDocumentPreview.tsx) — identical-lf-normalized<br>`frontend/src/features/agent/AgentPdfPreviewUnavailable.tsx` — absent-on-main<br>`frontend/src/build/betaPdfPolicy.ts` — absent-on-main

**Tests:** [`tests/test_agent_document_previews.py`](../../tests/test_agent_document_previews.py) — identical-lf-normalized<br>`frontend/src/features/agent/AgentPdfPreviewUnavailable.test.tsx` — absent-on-main

**Evidence:** Bounded DOCX/PPTX/XLSX/ODT text projections and archive/XML constraints exist. Beta PDF substitution reports unavailable; parser/worker exclusion is deliberate.

**Gap:** Inline PDF viewer is intentionally omitted from beta until dependency provenance closes. External/download fallback is not inline rendering. Fallback module is absent on main.

**Next:** Verify beta archive excludes the PDF worker and safe user-initiated file fallback works.

## A19

**Image, WAV and document attachments** — PARTIAL; experimental; gates `B04/B05; supports W03`.

Dependencies: A08, A03

**Source:** [`src/prompt_enhancer/application/agent_attachments.py`](../../src/prompt_enhancer/application/agent_attachments.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/agent_attachment_documents.py`](../../src/prompt_enhancer/application/agent_attachment_documents.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentComposerAttachments.tsx`](../../frontend/src/features/agent/AgentComposerAttachments.tsx) — identical-lf-normalized<br>[`frontend/src/features/agent/pcmWavRecorder.ts`](../../frontend/src/features/agent/pcmWavRecorder.ts) — identical-lf-normalized

**Tests:** [`tests/test_agent_attachments.py`](../../tests/test_agent_attachments.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentComposerAttachments.test.tsx`](../../frontend/src/features/agent/AgentComposerAttachments.test.tsx) — identical-lf-normalized<br>[`frontend/src/features/agent/pcmWavRecorder.test.ts`](../../frontend/src/features/agent/pcmWavRecorder.test.ts) — identical-lf-normalized

**Evidence:** Structural PNG/JPEG/WAV validation, model capability probes, bounded document projection, staged lifecycle and fork remapping exist.

**Gap:** Model input and recording remain separately capability-gated; no universal multimodal support or qualified audio/vision profile follows from an enabled file picker.

**Next:** Keep unsupported modes hidden; qualify exact approved vision/audio model inputs and measure resource cleanup.

## A20

**Optional prompt check beside composer** — PARTIAL; required; gates `B01/B03; W05/WP01-WP08`.

Dependencies: A05

**Source:** [`src/prompt_enhancer/application/prompt_check.py`](../../src/prompt_enhancer/application/prompt_check.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentPromptCheck.tsx`](../../frontend/src/features/agent/AgentPromptCheck.tsx) — identical-lf-normalized

**Tests:** [`tests/test_prompt_check.py`](../../tests/test_prompt_check.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentPromptCheck.test.tsx`](../../frontend/src/features/agent/AgentPromptCheck.test.tsx) — identical-lf-normalized

**Evidence:** Bounded text-only prior conversation, deterministic cues, visibly model-derived commentary and explicit Use suggested prompt action exist. Deterministic preflight works without a loaded model; optional commentary/rewrite uses the active A08 runtime.

**Gap:** This is a fixed preflight, not the approved reusable multimodel workflow hook. Application-to-infrastructure construction is a documented layering exception.

**Next:** Qualify current optional rewrite flow, then reuse W engine for WP01-WP08 without silent replace/send.

## A21

**External Agent controller and CLI** — PARTIAL; required; gates `B03/B05/V17`.

Dependencies: A01, A06, A13

**Source:** [`src/prompt_enhancer/application/agent_orchestration.py`](../../src/prompt_enhancer/application/agent_orchestration.py) — different<br>[`src/prompt_enhancer/application/agent_controller_client.py`](../../src/prompt_enhancer/application/agent_controller_client.py) — identical-lf-normalized<br>[`src/prompt_enhancer/interfaces/agent_controller_cli.py`](../../src/prompt_enhancer/interfaces/agent_controller_cli.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/agent_controller_http.py`](../../src/prompt_enhancer/infrastructure/agent_controller_http.py) — identical-lf-normalized

**Tests:** [`tests/test_agent_orchestration.py`](../../tests/test_agent_orchestration.py) — different<br>[`tests/test_agent_controller_cli.py`](../../tests/test_agent_controller_cli.py) — different<br>[`tests/test_agent_controller_http.py`](../../tests/test_agent_controller_http.py) — identical-lf-normalized<br>[`tests/test_agent_controller_ownership.py`](../../tests/test_agent_controller_ownership.py) — identical-lf-normalized

**Evidence:** Provider-neutral loopback manifest, monotonic cursor, explicit request admission and controller ownership exist; message submission is explicitly not idempotent.

**Gap:** CLI is Agent control, not workflow headless runner. Remote clients may not approve native effects; ambiguous message submission must never be blindly retried.

**Next:** Validate exact installed controller endpoint and cursor recovery, retaining consent and non-idempotent submission semantics.

## A22

**Agent MCP server surface** — PARTIAL; required; gates `B06/V10/V17`.

Dependencies: A21

**Source:** [`src/prompt_enhancer/interfaces/agent_mcp.py`](../../src/prompt_enhancer/interfaces/agent_mcp.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/agent_mcp_surface.py`](../../src/prompt_enhancer/application/agent_mcp_surface.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/agent_mcp_connections.py`](../../src/prompt_enhancer/application/agent_mcp_connections.py) — identical-lf-normalized

**Tests:** [`tests/test_agent_mcp.py`](../../tests/test_agent_mcp.py) — different<br>[`tests/test_agent_mcp_integration.py`](../../tests/test_agent_mcp_integration.py) — different<br>[`tests/test_agent_mcp_http.py`](../../tests/test_agent_mcp_http.py) — identical-lf-normalized<br>[`tests/test_agent_mcp_connections.py`](../../tests/test_agent_mcp_connections.py) — identical-lf-normalized

**Evidence:** Agent-specific MCP surface and connection contracts exist; historical owned loopback integration covers authentication, revocation and synthetic transactions.

**Gap:** This export/control surface must remain distinct from registry discovery and hosting third-party MCP servers. Native and signed-package acceptance still open.

**Next:** Qualify supported clients and immediate revocation without exposing raw transcripts or native approval authority.

## A23

**MCP registry search and cache** — PARTIAL; required; gates `B06/V11`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/application/mcp_registry_catalog.py`](../../src/prompt_enhancer/application/mcp_registry_catalog.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/mcp_registry.py`](../../src/prompt_enhancer/infrastructure/mcp_registry.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentMcpStorePanel.tsx`](../../frontend/src/features/agent/AgentMcpStorePanel.tsx) — different

**Tests:** [`tests/test_mcp_registry_catalog.py`](../../tests/test_mcp_registry_catalog.py) — identical-lf-normalized<br>`tests/test_packaged_mcp_store_receipt.py` — absent-on-main<br>[`frontend/src/features/agent/AgentMcpStorePanel.test.tsx`](../../frontend/src/features/agent/AgentMcpStorePanel.test.tsx) — different

**Evidence:** Version/provenance/icon and exact-cache search/review contracts exist. Current ledger B06 records a packaged restart/outage development journey passing; older canceled run remains historical.

**Gap:** Needs exact signed RC replay; discovery is not trust or universal compatibility. Live exact review can legitimately fail during outage.

**Next:** Repeat cached/uncached query and live-review outage behavior on frozen package.

## A24

**MCP reviewed setup and local package installation** — PARTIAL; required; gates `B06/V10/V17`.

Dependencies: A13, A23

**Source:** [`src/prompt_enhancer/application/mcp_server_management.py`](../../src/prompt_enhancer/application/mcp_server_management.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/mcp_local_packages.py`](../../src/prompt_enhancer/application/mcp_local_packages.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/mcp_package_installer.py`](../../src/prompt_enhancer/infrastructure/mcp_package_installer.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/sqlite/mcp_server_management.py`](../../src/prompt_enhancer/infrastructure/sqlite/mcp_server_management.py) — identical-lf-normalized

**Tests:** [`tests/test_mcp_server_management.py`](../../tests/test_mcp_server_management.py) — identical-lf-normalized<br>[`tests/test_mcp_package_installer.py`](../../tests/test_mcp_package_installer.py) — identical-lf-normalized<br>`tests/test_mcp_package_installer_runtime_dependency.py` — absent-on-main

**Evidence:** Review/configuration persistence, local package provenance and runtime dependency checks exist with synthetic tests.

**Gap:** Checksum-pinned supported package actual native install/connect/remove and clean-machine prerequisites remain unaccepted.

**Next:** Qualify one local package and one loopback remote profile with owner-reviewed bindings.

## A25

**MCP host and one-shot tool invocation** — PARTIAL; required; gates `B06/V10`.

Dependencies: A13, A24

**Source:** [`src/prompt_enhancer/application/mcp_managed_runtime.py`](../../src/prompt_enhancer/application/mcp_managed_runtime.py) — different<br>[`src/prompt_enhancer/application/mcp_managed_host.py`](../../src/prompt_enhancer/application/mcp_managed_host.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/mcp_managed_host_supervisor.py`](../../src/prompt_enhancer/infrastructure/mcp_managed_host_supervisor.py) — different<br>[`src/prompt_enhancer/infrastructure/mcp_guarded_host.py`](../../src/prompt_enhancer/infrastructure/mcp_guarded_host.py) — identical-lf-normalized<br>[`frontend/src/features/agent/AgentMcpManagedRuntimePanel.tsx`](../../frontend/src/features/agent/AgentMcpManagedRuntimePanel.tsx) — identical-lf-normalized

**Tests:** [`tests/test_mcp_managed_runtime.py`](../../tests/test_mcp_managed_runtime.py) — different<br>[`tests/test_mcp_managed_host_contracts.py`](../../tests/test_mcp_managed_host_contracts.py) — identical-lf-normalized<br>[`tests/test_mcp_guarded_host.py`](../../tests/test_mcp_guarded_host.py) — identical-lf-normalized

**Evidence:** App-run host ownership, project tool snapshot, prepare/native approve/revision recheck, bounded result and content-free durable receipt exist.

**Gap:** Curated native host lifecycle/restart/removal acceptance is open; durable configuration cannot silently restore authority.

**Next:** Run setup/use/revoke/remove, failed setup retry and restart with no orphan hosts or remembered approval.

## A26

**MCP cleanup evidence and recovery** — PARTIAL; required; gates `B02/B06/B09/V10/V14`.

Dependencies: A25

**Source:** `src/prompt_enhancer/infrastructure/mcp_managed_cleanup_proof.py` — absent-on-main<br>[`src/prompt_enhancer/application/mcp_managed_runtime.py`](../../src/prompt_enhancer/application/mcp_managed_runtime.py) — different<br>`src/prompt_enhancer/application/updates/mcp_readiness.py` — absent-on-main

**Tests:** `tests/test_mcp_managed_cleanup_proof.py` — absent-on-main<br>`tests/test_mcp_managed_host_cleanup.py` — absent-on-main<br>`tests/test_update_mcp_readiness.py` — absent-on-main

**Evidence:** October 8 inspection: retained exact-host binding and owned-task/context/process settlement observation. It explicitly cannot clear quarantine or shutdown uncertainty. Module absent on main.

**Gap:** Read-only cleanup observation is not durable recovery authority. Actual supported recovery and update prerequisite acceptance remain open.

**Next:** Finish verified cleanup recovery without equating process absence or terminal receipt to ownership-complete cleanup.

## A27

**Synthetic preview transport** — MOCK / DEMO; experimental; gates `B01/V17`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`frontend/src/shared/api/syntheticTransport.ts`](../../frontend/src/shared/api/syntheticTransport.ts) — different<br>[`frontend/src/shared/api/syntheticFixtures.ts`](../../frontend/src/shared/api/syntheticFixtures.ts) — identical-lf-normalized<br>[`frontend/src/shared/api/syntheticModelLabFixture.ts`](../../frontend/src/shared/api/syntheticModelLabFixture.ts) — identical-lf-normalized<br>[`frontend/src/shared/api/syntheticResearchFixture.ts`](../../frontend/src/shared/api/syntheticResearchFixture.ts) — identical-lf-normalized

**Tests:** [`frontend/src/shared/api/syntheticTransport.test.ts`](../../frontend/src/shared/api/syntheticTransport.test.ts) — different

**Evidence:** Explicit runtimeKind synthetic_fixture; predefined fictional results, status and research/model lab fixtures. Onboarding intentionally unavailable in synthetic mode.

**Gap:** Demo visuals prove neither local inference nor real provider metrics, tool authority or runtime lifecycle.

**Next:** Keep demo visibly identified and prevent placeholder actions from presenting themselves as real service capabilities.

## W00

**Approved workflow profiles and package feasibility** — NOT IMPLEMENTED; required; gates `W00/B00/B08`.

Dependencies: A08, A10

**Source:** [`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different<br>[`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Ledger W00-W08 explicitly required/not started. October 8 source inventory found no production workflow modules; current model/research adapters are prerequisites only.

**Gap:** Eight family profiles plus second LLM, approved revisions/hashes/licenses/preprocessing, hardware and compiled text/image/audio worker proof missing.

**Next:** Close baseline custody, freeze approved profiles and prove representative compiled workers before editor construction.

## W01

**Typed workflow graph and plan preview** — NOT IMPLEMENTED; required; gates `W01`.

Dependencies: W00

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** No workflow contracts/API/type graph source found; research workflow taxonomy is unrelated.

**Gap:** Versioned ports, explicit converters, cycle/limit validation and exhaustive supported/rejected edge matrix absent.

**Next:** Implement finite typed contracts and validation for one run, 32 nodes, 16 model nodes and acyclic edges.

## W02

**Durable workflow revisions and sequential engine** — NOT IMPLEMENTED; required; gates `W02`.

Dependencies: W01

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** No production workflow store, run journal or scheduler found. Agent history and analysis jobs are different bounded contexts.

**Gap:** Immutable revisions, input snapshots, node attempts, stable-port joins, duplicate Run admission and interrupted recovery missing.

**Next:** Add dedicated private workflow persistence and deterministic sequential chain/branch/join execution.

## W03

**Qualified production multimodal workflow adapters** — NOT IMPLEMENTED; required; gates `W03`.

Dependencies: W00, W01, W02, A19

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`src/prompt_enhancer/infrastructure/text_models/transformers_backends.py`](../../src/prompt_enhancer/infrastructure/text_models/transformers_backends.py) — different<br>[`src/prompt_enhancer/application/local_models.py`](../../src/prompt_enhancer/application/local_models.py) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Existing GGUF chat and research text model backends are present; no qualified production workflow adapter family set exists.

**Gap:** Text/vision-language/classifiers/embeddings/detection/ASR/audio adapters with typed validated outputs and real-profile qualification missing.

**Next:** Implement approved profiles in reviewed family slices with explicit preprocessing and genuine inference evidence.

## W04

**Resource leases and actual parallel inference** — NOT IMPLEMENTED; required; gates `W04`.

Dependencies: W02, W03

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`src/prompt_enhancer/application/local_models.py`](../../src/prompt_enhancer/application/local_models.py) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Chat coordinator intentionally owns at most one runtime; it is not a workflow two-worker coordinator.

**Gap:** CPU/RAM/VRAM admission, loading peaks, max-two overlap, sequential/automatic/require-parallel policy and stable joins absent.

**Next:** Create separate owned workflow handles/leases preserving personal chat/research runtimes; prove actual inference overlap and cleanup.

## W05

**Visual workflow builder and device model advisor** — NOT IMPLEMENTED; required; gates `W05/B10`.

Dependencies: W01, W02, W03, W04, A10

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`frontend/package.json`](../../frontend/package.json) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** No Blueprint/React Flow editor route or production builder source found; model hardware catalog is only a prerequisite.

**Gap:** Typed canvas, accessible list alternative, Build/Run/Results views, saved templates and task-specific profile recommendations absent.

**Next:** Lazy-load editor outside Agent bundle, render backend validation and qualified compatibility/memory evidence.

## W06

**Installed headless workflow export and import** — NOT IMPLEMENTED; required; gates `W06/B08`.

Dependencies: W02, W03, W04

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Existing Agent controller CLI does not implement workflow validate/run/import/export.

**Gap:** Portable definition/model lock/input template/launcher, GUI-headless engine parity and review-bound exports missing.

**Next:** Reuse the workflow engine from installed runner, exclude weights/secrets/paths/content by default and require explicit input binding.

## W07

**Workflow matrix and real-model qualification** — NOT IMPLEMENTED; required; gates `W07`.

Dependencies: W01, W02, W03, W04, W05, W06

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Acceptance requirements are documented; executable multimodal topology/placement qualification does not yet exist.

**Gap:** Series/parallel/mixed positive and rejection matrix, real CPU/NVIDIA overlap, restart/cancel/failure and ten-cycle cleanup evidence missing.

**Next:** Generate contract cases, deterministic engine cases and exact-profile real inference cases, recording package/model/runtime hashes.

## W08

**Workflow beta and prompt-enhancement integration** — NOT IMPLEMENTED; required; gates `W08; WP01-WP08; B08-B11`.

Dependencies: W05, W06, W07, A20

**Source:** [`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different<br>[`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`frontend/src/features/agent/AgentPromptCheck.tsx`](../../frontend/src/features/agent/AgentPromptCheck.tsx) — identical-lf-normalized

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved amendment includes saved workflow selection beside draft and optional pre-send execution. Present Prompt Check is a separate fixed preflight.

**Gap:** WP01-WP08 saved-workflow composer hook plus signed install/update/retention integration missing; no silent draft replacement/send is allowed.

**Next:** Connect selected compatible saved workflow to composer with explicit preview/acceptance, then qualify exact signed RC workflows with B00-B11 gates.

## R01

**Native desktop shell and window ownership** — PARTIAL; required; gates `B02/V13`.

Dependencies: R02, R03, R04

**Source:** [`src/prompt_enhancer/desktop_overlay.py`](../../src/prompt_enhancer/desktop_overlay.py) — different

**Tests:** [`tests/test_desktop_lifecycle.py`](../../tests/test_desktop_lifecycle.py) — identical-lf-normalized<br>[`tests/test_desktop_overlay.py`](../../tests/test_desktop_overlay.py) — different<br>[`tests/support/desktop_native_probe.py`](../../tests/support/desktop_native_probe.py) — different

**Evidence:** Static review 2026-10-08; ledger records ten synthetic native Agent launch/close cycles on 2026-09-26, not installed-candidate acceptance.

**Gap:** Main/child-window interaction, current compiled package and installed lifecycle are not qualified together.

**Next:** Run the declared native lifecycle matrix on one frozen candidate, including child/main close and forced termination.

## R02

**Hidden owned process trees and bounded I/O** — PARTIAL; required; gates `B02/V17`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/application/owned_process.py`](../../src/prompt_enhancer/application/owned_process.py) — identical-lf-normalized

**Tests:** [`tests/test_owned_process.py`](../../tests/test_owned_process.py) — identical-lf-normalized<br>[`tests/test_runtime_cancellation_unit.py`](../../tests/test_runtime_cancellation_unit.py) — different

**Evidence:** Static review 2026-10-08; Windows Job Object admission, no-shell spawning and output/time bounds exist. Existing tests cover descendants, overflow and visible windows.

**Gap:** Primitive implementation is present; every advertised packaged caller still needs its own cleanup evidence.

**Next:** Reuse this boundary for every release worker and retain exit, reader, handle and resource cleanup results.

## R03

**Runtime cleanup sequencing and restart admission** — PARTIAL; required; gates `B02/B09`.

Dependencies: R02

**Source:** [`src/prompt_enhancer/application/runtime_lifecycle.py`](../../src/prompt_enhancer/application/runtime_lifecycle.py) — different<br>[`src/prompt_enhancer/api.py`](../../src/prompt_enhancer/api.py) — different

**Tests:** [`tests/test_runtime_liveness.py`](../../tests/test_runtime_liveness.py) — different<br>[`tests/test_desktop_lifecycle.py`](../../tests/test_desktop_lifecycle.py) — identical-lf-normalized<br>`tests/test_update_cross_service_continuation.py` — absent-on-main

**Evidence:** Static review 2026-10-08; one-owner cleanup, reentrant/pending/interrupted states and bounded waits are implemented.

**Gap:** Unconfirmed cleanup cannot be treated as a stopped service; full current native lifecycle remains open.

**Next:** Exercise overlapping cleanup/update/exit on the frozen native composition and keep unconfirmed state visible.

## R04

**App-local runtime bootstrap and WebView prerequisites** — PARTIAL; required; gates `B02/B08/V01`.

Dependencies: R02, R21

**Source:** `src/prompt_enhancer/infrastructure/windows_runtime_bootstrap.py` — absent-on-main<br>`src/prompt_enhancer/infrastructure/windows_desktop_prerequisites.py` — absent-on-main<br>[`src/prompt_enhancer/desktop_overlay.py`](../../src/prompt_enhancer/desktop_overlay.py) — different

**Tests:** `tests/test_windows_runtime_bootstrap.py` — absent-on-main<br>`tests/test_windows_runtime_bootstrap_desktop_entrypoints.py` — absent-on-main<br>`tests/test_windows_desktop_prerequisites.py` — absent-on-main

**Evidence:** Static review 2026-10-08; fixed pywin32 import/DLL paths avoid arbitrary .pth execution. New bootstrap/prerequisite files are absent from origin/main.

**Gap:** Dependency-complete source custody and installed no-development-tools validation are outstanding.

**Next:** Admit the reviewed bootstrap cohort, compile it, and validate missing-prerequisite recovery in a clean Windows environment.

## R05

**Loopback local authentication, origin and CSRF boundary** — PARTIAL; required; gates `B02/V17`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/config.py`](../../src/prompt_enhancer/config.py) — identical-lf-normalized<br>[`src/prompt_enhancer/api.py`](../../src/prompt_enhancer/api.py) — different<br>[`src/prompt_enhancer/interfaces/http/browser_session.py`](../../src/prompt_enhancer/interfaces/http/browser_session.py) — identical-lf-normalized

**Tests:** [`tests/test_browser_session.py`](../../tests/test_browser_session.py) — identical-lf-normalized<br>[`tests/test_security_hardening.py`](../../tests/test_security_hardening.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; configuration rejects non-loopback hosts, API compares exact loopback origin and validates browser CSRF for mutations.

**Gap:** Current signed artifact has no completed native security acceptance.

**Next:** Run adversarial browser/API boundary tests against the frozen packaged host.

## R06

**Native approval authority** — PARTIAL; required; gates `B05/V08`.

Dependencies: R01, R05

**Source:** [`src/prompt_enhancer/interfaces/http/user_presence.py`](../../src/prompt_enhancer/interfaces/http/user_presence.py) — different<br>[`src/prompt_enhancer/desktop_overlay.py`](../../src/prompt_enhancer/desktop_overlay.py) — different

**Tests:** [`tests/test_user_presence.py`](../../tests/test_user_presence.py) — different<br>[`tests/test_agent_write_proposals.py`](../../tests/test_agent_write_proposals.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; native authority is distinct from same-origin browser authorization, with exact update-binding support.

**Gap:** Actual approved/rejected/stale workspace action on the current installed app remains unproven.

**Next:** Execute one native approval matrix with synthetic files; preserve exact reviewed operation and state binding.

## R07

**Application data path and retention inventory** — PARTIAL; required; gates `B08/B09/V16`.

Dependencies: R08

**Source:** [`src/prompt_enhancer/config.py`](../../src/prompt_enhancer/config.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/maintenance/inventory.py`](../../src/prompt_enhancer/application/maintenance/inventory.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/paths/policy.py`](../../src/prompt_enhancer/application/paths/policy.py) — identical-lf-normalized

**Tests:** [`tests/test_windows_distribution_hardening.py`](../../tests/test_windows_distribution_hardening.py) — different

**Evidence:** Static review 2026-10-08; data root and path classifications exist outside the package layout.

**Gap:** Installer/uninstaller retention, installed model-cache placement and migration behavior are not accepted.

**Next:** Verify package replacement/uninstall/reinstall retains synthetic chats, settings and model references according to policy.

## R08

**Filesystem reparse and private staging checks** — PARTIAL; required; gates `B08/B09/V17`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/infrastructure/paths/local.py`](../../src/prompt_enhancer/infrastructure/paths/local.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/paths/windows_private_directory.py`](../../src/prompt_enhancer/infrastructure/paths/windows_private_directory.py) — identical-lf-normalized

**Tests:** [`tests/test_windows_distribution_hardening.py`](../../tests/test_windows_distribution_hardening.py) — different<br>[`tests/test_windows_private_update_staging.py`](../../tests/test_windows_private_update_staging.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; explicit symlink/reparse rejection and a narrow Windows DACL adapter for update staging exist.

**Gap:** DACL protection is deliberately narrow, not proof that all application paths are hardened.

**Next:** Qualify actual installed staging permissions and keep unsupported paths explicitly unverified.

## R09

**SQLite migrations and schema compatibility** — PARTIAL; required; gates `B03/B09/V15`.

Dependencies: R07, R10

**Source:** [`src/prompt_enhancer/database.py`](../../src/prompt_enhancer/database.py) — different<br>[`src/prompt_enhancer/infrastructure/sqlite/migrations.py`](../../src/prompt_enhancer/infrastructure/sqlite/migrations.py) — different

**Tests:** [`tests/test_database_unknowns.py`](../../tests/test_database_unknowns.py) — different<br>[`tests/test_auxiliary_sqlite_migrations.py`](../../tests/test_auxiliary_sqlite_migrations.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; migration implementation is substantial and versioned; targeted historical tests do not prove update rollback.

**Gap:** Older-binary/newer-schema refusal and package/data recovery need installed transition evidence.

**Next:** Freeze supported schema transitions and test forward migration, interruption and safe refusal under signed N-to-N+1 acceptance.

## R10

**Consistent backup and restore verification** — PARTIAL; required; gates `B09/V15`.

Dependencies: R07, R09

**Source:** [`src/prompt_enhancer/application/maintenance/backup.py`](../../src/prompt_enhancer/application/maintenance/backup.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/sqlite/online_backup.py`](../../src/prompt_enhancer/infrastructure/sqlite/online_backup.py) — identical-lf-normalized

**Tests:** [`tests/test_windows_distribution_hardening.py`](../../tests/test_windows_distribution_hardening.py) — different

**Evidence:** Static review 2026-10-08; SQLite Connection.backup plus integrity_check and all-before-mutation restore validation exist.

**Gap:** Restore execution, authenticated recovery linkage and update-integrated backup are not delivered by these pure contracts.

**Next:** Compose bounded migration backup and explicit recovery without overwriting failed/newer data.

## R11

**Signed update discovery and manifest verification** — PARTIAL; required; gates `B09/V14`.

Dependencies: R22

**Source:** [`src/prompt_enhancer/infrastructure/updates/configuration.py`](../../src/prompt_enhancer/infrastructure/updates/configuration.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/updates/https_manifest_source.py`](../../src/prompt_enhancer/infrastructure/updates/https_manifest_source.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/updates/ed25519_verifier.py`](../../src/prompt_enhancer/infrastructure/updates/ed25519_verifier.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/updates/verification.py`](../../src/prompt_enhancer/application/updates/verification.py) — identical-lf-normalized

**Tests:** [`tests/test_application_update_configuration.py`](../../tests/test_application_update_configuration.py) — identical-lf-normalized<br>[`tests/test_https_update_manifest_source.py`](../../tests/test_https_update_manifest_source.py) — identical-lf-normalized<br>[`tests/test_application_update_replay.py`](../../tests/test_application_update_replay.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; package-owned public trust configuration, HTTPS acquisition, Ed25519 and replay checks exist.

**Gap:** Real owner-controlled release endpoint, public trust key and signed metadata are not frozen.

**Next:** Supply public release identities and verify a real signed manifest while preserving explicit check consent.

## R12

**Download, staging and package verification** — PARTIAL; required; gates `B09/V14`.

Dependencies: R08, R11, R21

**Source:** [`src/prompt_enhancer/application/updates/status.py`](../../src/prompt_enhancer/application/updates/status.py) — different<br>[`src/prompt_enhancer/infrastructure/updates/staging.py`](../../src/prompt_enhancer/infrastructure/updates/staging.py) — identical-lf-normalized<br>[`src/prompt_enhancer/infrastructure/updates/msix_preflight.py`](../../src/prompt_enhancer/infrastructure/updates/msix_preflight.py) — different<br>[`src/prompt_enhancer/infrastructure/updates/windows_msix_signer.py`](../../src/prompt_enhancer/infrastructure/updates/windows_msix_signer.py) — identical-lf-normalized

**Tests:** [`tests/test_application_update_staging_failures.py`](../../tests/test_application_update_staging_failures.py) — identical-lf-normalized<br>[`tests/test_staged_package_review.py`](../../tests/test_staged_package_review.py) — different<br>`tests/test_windows_staged_package_lease.py` — absent-on-main

**Evidence:** Static review 2026-10-08; bounded staging, archive/identity checks and WinVerifyTrust-backed signer inspection are implemented.

**Gap:** Real signed packages and install/update acceptance are unavailable; source validators alone are insufficient.

**Next:** Qualify staged N+1 tamper, wrong signer, expiry, replay and downgrade cases on the selected release artifact.

## R13

**Update status and explicit check/stage/retry UI actions** — PARTIAL; required; gates `B09/V14`.

Dependencies: R05, R11, R12, R17

**Source:** [`src/prompt_enhancer/interfaces/http/application_update_routes.py`](../../src/prompt_enhancer/interfaces/http/application_update_routes.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/updates/status.py`](../../src/prompt_enhancer/application/updates/status.py) — different

**Tests:** [`tests/test_application_update_api.py`](../../tests/test_application_update_api.py) — identical-lf-normalized<br>[`tests/test_application_update_coordinator.py`](../../tests/test_application_update_coordinator.py) — identical-lf-normalized

**Evidence:** Static review 2026-10-08; routes expose status/check/stage/cancel/retry/verify with instance/revision binding.

**Gap:** A push to main cannot currently activate a usable install-and-relaunch action; Apply route does not exist.

**Next:** Keep status truthful and wire apply only after the native transaction prerequisites and release inputs close.

## R14

**Host quiescence and update admission** — PARTIAL; required; gates `B09/V15`.

Dependencies: R03, R06

**Source:** `src/prompt_enhancer/application/updates/host_preparation.py` — absent-on-main<br>`src/prompt_enhancer/application/updates/worker_readiness.py` — absent-on-main<br>`src/prompt_enhancer/interfaces/http/update_admission.py` — absent-on-main

**Tests:** `tests/test_update_host_preparation.py` — absent-on-main<br>`tests/test_update_cross_service_continuation.py` — absent-on-main<br>`tests/test_update_agent_mcp_composition.py` — absent-on-main

**Evidence:** Static review 2026-10-08; exact reviewed services close admission jointly and expose cleanup uncertainty. Key files are absent from origin/main.

**Gap:** All owned activity and native unsaved-state coverage must agree before installer handoff.

**Next:** Complete remaining exact-owner cleanup/recovery bindings and prove no admitted work races installation.

## R15

**Durable update operation journal** — PARTIAL; required; gates `B09/V15`.

Dependencies: R08

**Source:** `src/prompt_enhancer/application/updates/apply_journal.py` — absent-on-main<br>`src/prompt_enhancer/infrastructure/updates/apply_journal.py` — absent-on-main

**Tests:** `tests/test_update_apply_journal.py` — absent-on-main

**Evidence:** Static review 2026-10-08; atomic CAS journal records exact operation/release state. Files are absent from origin/main.

**Gap:** Journal exists as an uncomposed primitive; real restart reconciliation is missing.

**Next:** Bind journal to the native apply route and validate crash points with retained operation state.

## R16

**Native MSIX deployment transaction primitive** — PARTIAL; required; gates `B09/V14/V15`.

Dependencies: R06, R12, R14, R15

**Source:** `src/prompt_enhancer/application/updates/apply_execution.py` — absent-on-main<br>`src/prompt_enhancer/infrastructure/updates/windows_msix_executor.py` — absent-on-main<br>`src/prompt_enhancer/infrastructure/updates/windows_staged_package_lease.py` — absent-on-main

**Tests:** `tests/test_update_apply_execution.py` — absent-on-main<br>`tests/test_windows_msix_executor.py` — absent-on-main<br>`tests/test_windows_staged_package_lease.py` — absent-on-main

**Evidence:** Static review 2026-10-08; explicitly uncomposed controller orders native approval, journal, held package verification and fixed Add-AppxPackage execution.

**Gap:** Installer return is explicitly not relaunch success; no product endpoint invokes this controller.

**Next:** Compose only after exact native approval, quiescence, verified package and durable recovery prerequisites are accepted.

## R17

**Product update Apply endpoint and relaunch** — NOT IMPLEMENTED; required; gates `B09/V14`.

Dependencies: R16, R18

**Source:** [`src/prompt_enhancer/interfaces/http/application_update_routes.py`](../../src/prompt_enhancer/interfaces/http/application_update_routes.py) — identical-lf-normalized<br>`src/prompt_enhancer/application/updates/apply_execution.py` — absent-on-main

**Tests:** `tests/test_update_apply_execution.py` — absent-on-main

**Evidence:** Static review 2026-10-08 confirms no /apply handler; transaction docstring explicitly says it is not connected to HTTP/status.

**Gap:** A real end-to-end update button that installs, relaunches and reports success is missing.

**Next:** Implement reviewed-state-only Apply operation, status progress and verified first-launch completion after prerequisite qualification.

## R18

**Update rollback and package/data recovery executor** — NOT IMPLEMENTED; required; gates `B09/V15`.

Dependencies: R09, R10, R15

**Source:** `src/prompt_enhancer/application/updates/recovery_plan.py` — absent-on-main

**Tests:** `tests/test_update_recovery_plan.py` — absent-on-main

**Evidence:** Static review 2026-10-08; existing module explicitly performs offline evidence reconciliation and never installs, rolls back or relaunches.

**Gap:** Recovery planning is implemented; executable restoration of compatible package/data pairs is not.

**Next:** Implement bounded recovery authority, preserve failed/newer data, and prove interruption recovery without schema misuse.

## R19

**Windows release assembly and pinned dependency inputs** — PARTIAL; required; gates `B00/B08/V18`.

Dependencies: R24, R20

**Source:** `src/prompt_enhancer/infrastructure/build_staging.py` — absent-on-main<br>`scripts/stage_windows_release.py` — absent-on-main<br>`scripts/prepare_windows_python_runtime.py` — absent-on-main<br>`scripts/prepare_windows_launchers.py` — absent-on-main<br>`scripts/prepare_msix_candidate.py` — absent-on-main

**Tests:** `tests/test_windows_release_staging.py` — absent-on-main<br>`tests/test_windows_launchers.py` — absent-on-main<br>`tests/test_msix_candidate.py` — absent-on-main

**Evidence:** Static review 2026-10-08; explicit file manifests, hashes and no-clobber staging exist; several preparation scripts are absent from origin/main.

**Gap:** A clean private source candidate with complete current dependency custody has not been assembled and qualified.

**Next:** Review coherent source groups and build only from the resulting frozen commit.

## R20

**Dependency provenance and third-party notices** — PARTIAL; required; gates `B08/V18`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/infrastructure/frontend_notice_inventory.py`](../../src/prompt_enhancer/infrastructure/frontend_notice_inventory.py) — different<br>`src/prompt_enhancer/infrastructure/frontend_notice_renderer.py` — absent-on-main<br>`scripts/prepare_compiled_dependency_inventory.py` — absent-on-main

**Tests:** [`tests/test_frontend_notice_inventory.py`](../../tests/test_frontend_notice_inventory.py) — different<br>`tests/test_frontend_notice_renderer.py` — absent-on-main<br>`tests/test_compiled_dependency_inventory.py` — absent-on-main

**Evidence:** Static review 2026-10-08; inventory records opaque assets/workers and compiler-reported modules. Compiler-to-binary binding and license obligations remain explicit gaps.

**Gap:** Release-bound notices and opaque PDF worker provenance are not closed; inventory success is not license clearance.

**Next:** Bind notices to exact compiled payload; resolve PDF obligations or exclude its worker from the beta artifact.

## R21

**Compiled source-deterrent MSIX artifact** — PARTIAL; required; gates `B08/W00/V18`.

Dependencies: R04, R19, R20

**Source:** `scripts/prepare_compiled_dependency_inventory.py` — absent-on-main<br>`scripts/pack_msix_candidate.py` — absent-on-main<br>[`scripts/verify_msix_package.py`](../../scripts/verify_msix_package.py) — different<br>`scripts/verify_msix_sdk_unpack.py` — absent-on-main

**Tests:** `tests/test_compiled_dependency_inventory.py` — absent-on-main<br>`tests/test_pack_msix_candidate.py` — absent-on-main<br>`tests/test_msix_sdk_unpack.py` — absent-on-main

**Evidence:** Ledger records historical compiled base-app feasibility and unsigned repeatability. Static review 2026-10-08 does not establish a current compiled text/image/audio candidate.

**Gap:** First-party source exclusion, qualified workers, deterministic inputs and exact current payload acceptance remain open.

**Next:** Compile representative workers early, then inspect and run the complete payload with no developer tools.

## R22

**Signing identity and binary-only release channel** — NOT IMPLEMENTED; required; gates `B09/B11`.

Dependencies: R21

**Source:** [`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different<br>[`src/prompt_enhancer/infrastructure/updates/configuration.py`](../../src/prompt_enhancer/infrastructure/updates/configuration.py) — identical-lf-normalized

**Tests:** No executable test/implementation at this level.

**Evidence:** Latest ledger input checklist still lacks verified package identity/publisher, public signer fingerprint, update key and owner-controlled release destination. Gate references (not executable tests): V01, V14, V18.

**Gap:** No qualified owner-signed distribution channel or clean-machine release candidate.

**Next:** Record public identity/trust metadata and binary release destination; keep secrets under owner control.

## R23

**Clean-machine install, uninstall and update acceptance** — NOT IMPLEMENTED; required; gates `B09/B11`.

Dependencies: R17, R18, R21, R22

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different<br>[`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Ledger explicitly leaves signed clean-machine installation/update/recovery/uninstall unproven. Gate references (not executable tests): V01, V14, V15, V16.

**Gap:** Required user journey evidence is absent even though several implementation primitives exist.

**Next:** Execute declared standard-user Windows and physical NVIDIA acceptance on the exact signed candidate.

## R24

**Coherent private source custody and main baseline** — PARTIAL; required; gates `B00`.

Dependencies: Entry/boundary component; see system map.

**Source:** `docs/beta-progress-journal.md` — absent-on-main<br>[`docs/product-readiness-matrix-2026-09-12.md`](../../docs/product-readiness-matrix-2026-09-12.md) — different<br>`scripts/inspect_beta_worktree.py` — absent-on-main

**Tests:** `tests/test_inspect_beta_worktree.py` — absent-on-main

**Evidence:** Static review 2026-10-08: current checkout acdf0e5 differs from origin/main bfb67b6; substantial modified/untracked implementation remains unpublished. Gate references (not executable tests): B00-CUSTODY, B00-INVENTORY.

**Gap:** Classification is not content approval; full source baseline and portable inventory ancestor-race issue remain open.

**Next:** Review dependency-complete cohorts, preserve all work, and stage only explicit reviewed groups.

## R25

**Owner-review feature-branch collaboration policy** — READY (bounded); required; gates `B00`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`AGENTS.md`](../../AGENTS.md) — different<br>[`CONTRIBUTING.md`](../../CONTRIBUTING.md) — different<br>[`docs/collaboration-workflow.md`](../../docs/collaboration-workflow.md) — identical-lf-normalized<br>[`.github/workflows/collaboration-policy.yml`](../../.github/workflows/collaboration-policy.yml) — identical-lf-normalized<br>[`scripts/check_collaboration_policy.py`](../../scripts/check_collaboration_policy.py) — identical-lf-normalized

**Tests:** [`tests/test_collaboration_policy.py`](../../tests/test_collaboration_policy.py) — identical-lf-normalized

**Evidence:** Bounded policy/metadata-validator readiness: origin/main contains collaboration guide, task/PR templates and base-commit metadata validator; the documentation branch states owner final review/merge in AGENTS. Fresh October 8 collaboration/privacy selection passed 144 tests with owned cleanup confirmed. This is not platform permission enforcement.

**Gap:** Written policy and metadata CI do not enforce owner-only merge; remote protection must be checked separately. Current campaign checkout lacks several main-branch additions.

**Next:** Use task-specific feature branches and PRs with owner acceptance; do not claim platform protection without read-back evidence.

## R26

**Backend/frontend/privacy quality CI** — PARTIAL; required; gates `B00/B11`.

Dependencies: R24

**Source:** [`.github/workflows/quality-gate.yml`](../../.github/workflows/quality-gate.yml) — different<br>[`frontend/package.json`](../../frontend/package.json) — different<br>[`docs/ci-quality-gate.md`](../../docs/ci-quality-gate.md) — identical-lf-normalized

**Tests:** No executable test/implementation at this level.

**Evidence:** Static review 2026-10-08; pinned CI actions, Linux/Windows backend and frontend jobs exist. Latest clean-cohort full frontend timed out at 600.11s without final failure census. Gate references (not executable tests): Q-PYTEST, Q-NPM-TEST, Q-E2E, Q-PRIVACY-SCAN, Q-CHECK-API.

**Gap:** No complete current clean-candidate quality gate; platform checks and repository plan/billing state are separate evidence.

**Next:** Preserve incremental test outcomes, localize bounded failures and run full release gates once on the frozen candidate.

## R27

**Agent deferred-loading and bundle gate** — PARTIAL; required; gates `B10/B11`.

Dependencies: R24, R26

**Source:** `frontend/scripts/check-agent-bundle-budget.mjs` — absent-on-main<br>`frontend/agent-bundle-budget.json` — absent-on-main<br>[`frontend/src/features/agent/AgentPage.tsx`](../../frontend/src/features/agent/AgentPage.tsx) — different

**Tests:** `frontend/scripts/check-agent-bundle-budget.test.mjs` — absent-on-main

**Evidence:** Latest Oct7 clean-main build fails E_BOUNDARY for eight deferred chunk identities; budget tools are absent from origin/main. Older dirty-tree pass is historical. Gate references (not executable tests): Q-BUNDLE-BUDGET.

**Gap:** Clean-source lazy graph is not aligned with the reviewed budget; absence of chunks is not absence of eight product features.

**Next:** Admit dependency-complete lazy-boundary/tooling changes and verify the same unchanged budgets.

## R28

**Release evidence consistency evaluator** — PARTIAL; required; gates `B11`.

Dependencies: R23, R26, R27

**Source:** `src/prompt_enhancer/application/build_evidence/beta_release.py` — absent-on-main<br>`scripts/check_beta_release.py` — absent-on-main<br>[`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** `tests/test_beta_release_evidence.py` — absent-on-main<br>`tests/test_check_beta_release_cli.py` — absent-on-main

**Evidence:** Static review 2026-10-08; fixed B/V/W/WP contracts reject missing or inconsistent records. Historical synthetic test passes only validate evaluator behavior.

**Gap:** No accepted exact signed candidate, authentic complete evidence set or owner release review exists.

**Next:** Collect actual evidence for required dimensions; evaluator must remain a consistency check rather than release authority.

## R29

**Development update verifier fake** — MOCK / DEMO; experimental; gates `B09`.

Dependencies: Entry/boundary component; see system map.

**Source:** [`src/prompt_enhancer/infrastructure/updates/development_verifier.py`](../../src/prompt_enhancer/infrastructure/updates/development_verifier.py) — identical-lf-normalized

**Tests:** [`tests/test_application_update_configuration.py`](../../tests/test_application_update_configuration.py) — identical-lf-normalized

**Evidence:** Static source inventory; development verification adapter is separate from production Ed25519 composition.

**Gap:** Mock verification cannot demonstrate an authentic release or signing trust.

**Next:** Keep fake restricted to synthetic tests and use the production verifier for release evidence.

## R30

**Deferred accounts, payments, teams and social foundations** — PARTIAL; deferred; gates `B01/deferred`.

Dependencies: R05

**Source:** [`src/prompt_enhancer/config.py`](../../src/prompt_enhancer/config.py) — identical-lf-normalized<br>[`src/prompt_enhancer/application/paid_product/services.py`](../../src/prompt_enhancer/application/paid_product/services.py) — different<br>`src/prompt_enhancer/infrastructure/paid_product/stripe_testmode.py` — absent-on-main<br>`src/prompt_enhancer/infrastructure/paid_product/stripe_checkout_testmode.py` — absent-on-main

**Tests:** `tests/test_paid_product_stripe_testmode.py` — absent-on-main<br>`tests/test_paid_product_checkout.py` — absent-on-main

**Evidence:** Static review 2026-10-08; development flags default off, team control plane is in-memory/synthetic, payment adapters explicitly target test mode. This aggregate includes more developed local social metadata but no production paid service. Real bounded development foundations exist; production identity/billing/hosting is not qualified. Do not label this entire area a mock.

**Gap:** No production account/billing/hosted-team readiness; these features are outside the current beta gate.

**Next:** Preserve code/data, hide unavailable controls, and require a separate product/security decision before production activation.

## WF01

**Workflow text LLM** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Text -> Text or validated JSON. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF02

**Workflow vision-language model** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Image and prompt -> Text or validated JSON. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF03

**Workflow text classifier** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Text -> Labels and model scores. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF04

**Workflow text embedding** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Text -> Vector with encoder identity and dimensions. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF05

**Workflow image classifier** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: PNG/JPEG -> Labels and model scores. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF06

**Workflow object detector** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: PNG/JPEG -> Boxes, labels and model scores. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF07

**Workflow speech recognition** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Bounded PCM WAV -> Transcript and supported timestamps. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WF08

**Workflow audio classifier** — NOT IMPLEMENTED; required; gates `W00/W03/W07`.

Dependencies: W00, W01, W02

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved requirement; no qualified production workflow adapter. Existing chat/research adapters do not establish workflow support.

**Gap:** Contract: Bounded PCM WAV -> Labels and model scores. Approved immutable model/runtime/license/preprocessing/resource profile and genuine inference are missing.

**Next:** Freeze an approved profile in W00, implement the W03 adapter, test every declared placement/input/output and cleanup. Text LLM also needs a second profile for switching.

## WP01

**Typed draft input/output** — NOT IMPLEMENTED; required; gates `WP01`.

Dependencies: W01, W03

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Reject missing or incompatible inputs before loading.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP02

**Review, apply and undo UI** — NOT IMPLEMENTED; required; gates `WP02`.

Dependencies: W05

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Compare original/suggestion and preserve ordinary Send.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP03

**Exact draft/run binding** — NOT IMPLEMENTED; required; gates `WP03`.

Dependencies: W02, W05

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Reject late results after draft/chat/workflow changes.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP04

**Idempotent enhancement and send** — NOT IMPLEMENTED; required; gates `WP04`.

Dependencies: W02, W05

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** One run and at most one explicitly authorized send; no recursion.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP05

**Enhancement failure recovery** — NOT IMPLEMENTED; required; gates `WP05`.

Dependencies: W02, W05

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Preserve original draft on cancel, crash, timeout or restart.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP06

**Shared runtime resource budget** — NOT IMPLEMENTED; required; gates `WP06`.

Dependencies: W04, W05

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Wait or request explicit stop-and-run without replacing personal runtime.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP07

**Private retention and export** — NOT IMPLEMENTED; required; gates `WP07`.

Dependencies: W02, W06, W08

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Keep contents out of analytics/default export and do not restore hook authority.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.

## WP08

**Builder/composer/headless parity** — NOT IMPLEMENTED; required; gates `WP08`.

Dependencies: W05, W06, W07, W08

**Source:** [`docs/beta-acceptance-gates.md`](../../docs/beta-acceptance-gates.md) — different

**Tests:** No executable test/implementation at this level.

**Evidence:** Approved WP requirement; existing prompt check is not this saved-workflow feature.

**Gap:** Use one qualified engine and prove retention through update.

**Next:** Implement after required W contracts/engine/adapters and test the named WP gate.
