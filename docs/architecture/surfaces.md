# Route, feature and source inventory

This census covers the inspected source tree, not every runtime state or every button.

1161 Python/TypeScript/TSX/CSS source files; 23 route families; 32 frontend feature directories; 53 HTTP route modules.

## Route families

| Route family | Title | Beta classification |
| --- | --- | --- |
| `discovery` | Discovery | required |
| `local_sources` | Data sources | required |
| `analysis_jobs` | Analysis jobs | required |
| `research` | Methods & models | experimental |
| `team` | Team analytics | deferred |
| `social` | Social hub | deferred |
| `task_flow` | Task flow | required |
| `projects` | Projects | required |
| `sessions` | Sessions | required |
| `calibration` | Calibration | required |
| `models` | Models | required |
| `settings` | Settings | required |
| `prompt_checks` | Prompt check | required |
| `overview` | Overview | required |
| `agent` | Agent | required |
| `project_overview` | Project workspace | required |
| `live` | Live | required |
| `project_sessions` | Project workspace | required |
| `project_automation` | Project automation | required |
| `project_metrics` | Project workspace | required |
| `session_metrics` | Project workspace | required |
| `task` | Task analysis | required |
| `not_found` | Page not found | required |

Route source: `frontend/src/app/appRouteManifest.ts` (development observation).

`project_automation` is the existing scheduling surface, not the absent multimodel builder.
Imported Projects/Sessions are analytics catalogs; authored Agent projects/chats use a different store.

## Frontend feature slices

| Directory | Architectural lane |
| --- | --- |
| `frontend/src/features/agent/` | Agent |
| `frontend/src/features/analysis-job-centre/` | Analytics / application UI |
| `frontend/src/features/calibration/` | Analytics / application UI |
| `frontend/src/features/coaching-loop/` | Analytics / application UI |
| `frontend/src/features/discovery-inbox/` | Analytics / application UI |
| `frontend/src/features/live-window/` | Analytics / application UI |
| `frontend/src/features/local-models/` | Runtime |
| `frontend/src/features/local-sources/` | Analytics / application UI |
| `frontend/src/features/metric-coverage/` | Analytics / application UI |
| `frontend/src/features/model-ensemble/` | Analytics / application UI |
| `frontend/src/features/model-judge/` | Analytics / application UI |
| `frontend/src/features/model-link-experiment/` | Analytics / application UI |
| `frontend/src/features/onboarding/` | Analytics / application UI |
| `frontend/src/features/overview/` | Analytics / application UI |
| `frontend/src/features/project-automation/` | Analytics / application UI |
| `frontend/src/features/project-catalog/` | Analytics / application UI |
| `frontend/src/features/project-timeline/` | Analytics / application UI |
| `frontend/src/features/project-workspace/` | Analytics / application UI |
| `frontend/src/features/prompt-check/` | Analytics / application UI |
| `frontend/src/features/provider-compatibility/` | Analytics / application UI |
| `frontend/src/features/quality-profile/` | Analytics / application UI |
| `frontend/src/features/research-lab/` | Analytics / application UI |
| `frontend/src/features/session-catalog/` | Analytics / application UI |
| `frontend/src/features/session-radar/` | Analytics / application UI |
| `frontend/src/features/session-reader/` | Analytics / application UI |
| `frontend/src/features/session-timeline/` | Analytics / application UI |
| `frontend/src/features/settings/` | Analytics / application UI |
| `frontend/src/features/social/` | Deferred product |
| `frontend/src/features/task-detail/` | Analytics / application UI |
| `frontend/src/features/task-flow/` | Analytics / application UI |
| `frontend/src/features/task-review/` | Analytics / application UI |
| `frontend/src/features/team-analytics/` | Deferred product |

## Largest source files

Physical lines, including comments and blanks. Generated clients and append-only migrations need different treatment from hand-written coordinators.

| File | Lines |
| --- | --- |
| `frontend/src/shared/api/generated/openapi.ts` | 35800 |
| `src/prompt_enhancer/infrastructure/sqlite/migrations.py` | 17806 |
| `frontend/src/shared/api/httpTransport.ts` | 8576 |
| `frontend/src/features/agent/AgentPage.test.tsx` | 7901 |
| `src/prompt_enhancer/application/local_agent.py` | 6535 |
| `frontend/src/styles.css` | 5950 |
| `frontend/src/shared/api/httpTransport.test.ts` | 5649 |
| `src/prompt_enhancer/infrastructure/sqlite/mcp_server_management.py` | 5528 |
| `src/prompt_enhancer/application/local_models.py` | 5213 |
| `src/prompt_enhancer/infrastructure/sqlite/agent_catalog.py` | 5208 |
| `src/prompt_enhancer/application/mcp_server_management.py` | 5087 |
| `frontend/src/features/agent/AgentPage.tsx` | 4901 |
| `src/prompt_enhancer/application/analysis/session_model_ensemble.py` | 4231 |
| `src/prompt_enhancer/database.py` | 4060 |
| `src/prompt_enhancer/application/local_agent_workspace.py` | 3923 |
| `src/prompt_enhancer/infrastructure/sqlite/estimators.py` | 3894 |
| `frontend/src/shared/api/contracts.ts` | 3807 |
| `src/prompt_enhancer/infrastructure/sqlite/model_ensemble.py` | 3667 |
| `src/prompt_enhancer/application/history/contracts.py` | 3526 |
| `src/prompt_enhancer/application/analysis/requirement_action_evidence.py` | 3476 |

## Static dependency pressure

Python AST parse errors: 0. Absolute application imports pointing at infrastructure/interfaces: 0.

This is a narrow syntactic indicator. Relative/dynamic imports, calls and runtime wiring are not comprehensively analyzed. Each listed edge needs review before deciding it violates an intended boundary.

| Caller | Line | Imported module |
| --- | --- | --- |

## HTTP route modules

- `src/prompt_enhancer/interfaces/http/agent_hardening_routes.py`
- `src/prompt_enhancer/interfaces/http/agent_mcp_routes.py`
- `src/prompt_enhancer/interfaces/http/agent_metric_evidence_routes.py`
- `src/prompt_enhancer/interfaces/http/analysis_job_routes.py`
- `src/prompt_enhancer/interfaces/http/analysis_routes.py`
- `src/prompt_enhancer/interfaces/http/annotation_routes.py`
- `src/prompt_enhancer/interfaces/http/application_update_routes.py`
- `src/prompt_enhancer/interfaces/http/automation_grant_routes.py`
- `src/prompt_enhancer/interfaces/http/calibration_routes.py`
- `src/prompt_enhancer/interfaces/http/claim_grounding_census_routes.py`
- `src/prompt_enhancer/interfaces/http/claim_grounding_link_review_routes.py`
- `src/prompt_enhancer/interfaces/http/claim_grounding_review_routes.py`
- `src/prompt_enhancer/interfaces/http/claude_local_source_routes.py`
- `src/prompt_enhancer/interfaces/http/control_plane_routes.py`
- `src/prompt_enhancer/interfaces/http/declared_task_profile_routes.py`
- `src/prompt_enhancer/interfaces/http/display_label_routes.py`
- `src/prompt_enhancer/interfaces/http/estimator_routes.py`
- `src/prompt_enhancer/interfaces/http/local_agent_routes.py`
- `src/prompt_enhancer/interfaces/http/local_model_routes.py`
- `src/prompt_enhancer/interfaces/http/local_source_routes.py`
- `src/prompt_enhancer/interfaces/http/mcp_registry_routes.py`
- `src/prompt_enhancer/interfaces/http/mcp_server_management_routes.py`
- `src/prompt_enhancer/interfaces/http/metric_coverage_routes.py`
- `src/prompt_enhancer/interfaces/http/metric_lifecycle_evidence_routes.py`
- `src/prompt_enhancer/interfaces/http/metric_readiness_routes.py`
- `src/prompt_enhancer/interfaces/http/model_ensemble_routes.py`
- `src/prompt_enhancer/interfaces/http/model_ensemble_watch_routes.py`
- `src/prompt_enhancer/interfaces/http/model_judge_routes.py`
- `src/prompt_enhancer/interfaces/http/model_link_experiment_routes.py`
- `src/prompt_enhancer/interfaces/http/onboarding_routes.py`
- `src/prompt_enhancer/interfaces/http/otlp_ingest_routes.py`
- `src/prompt_enhancer/interfaces/http/paid_checkout_routes.py`
- `src/prompt_enhancer/interfaces/http/paid_product_routes.py`
- `src/prompt_enhancer/interfaces/http/project_quality_aggregation_routes.py`
- `src/prompt_enhancer/interfaces/http/project_timeline_routes.py`
- `src/prompt_enhancer/interfaces/http/prompt_check_routes.py`
- `src/prompt_enhancer/interfaces/http/provider_compatibility_routes.py`
- `src/prompt_enhancer/interfaces/http/requirement_action_evidence_routes.py`
- `src/prompt_enhancer/interfaces/http/requirement_plan_evidence_routes.py`
- `src/prompt_enhancer/interfaces/http/requirement_verification_evidence_routes.py`
- `src/prompt_enhancer/interfaces/http/research_routes.py`
- `src/prompt_enhancer/interfaces/http/review_routes.py`
- `src/prompt_enhancer/interfaces/http/session_analysis_command_routes.py`
- `src/prompt_enhancer/interfaces/http/session_analysis_routes.py`
- `src/prompt_enhancer/interfaces/http/session_quality_aggregation_routes.py`
- `src/prompt_enhancer/interfaces/http/session_reader_routes.py`
- `src/prompt_enhancer/interfaces/http/session_timeline_routes.py`
- `src/prompt_enhancer/interfaces/http/shared_folder_routes.py`
- `src/prompt_enhancer/interfaces/http/social_routes.py`
- `src/prompt_enhancer/interfaces/http/spa_routes.py`
- `src/prompt_enhancer/interfaces/http/task_lifecycle_routes.py`
- `src/prompt_enhancer/interfaces/http/task_routes.py`
- `src/prompt_enhancer/interfaces/http/workspace_folder_picker_routes.py`
