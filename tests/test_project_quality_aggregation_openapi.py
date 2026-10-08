from __future__ import annotations

import json

from scripts.export_openapi import build_openapi_schema


def test_openapi_declares_the_closed_bounded_project_aggregate_contract() -> None:
    schema = build_openapi_schema()
    operation = schema["paths"]["/v1/quality-analysis/aggregate-projects"][
        "post"
    ]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    request_name = request_ref.rsplit("/", 1)[-1]
    request = schema["components"]["schemas"][request_name]

    project_ids = request["properties"]["project_ids"]
    assert project_ids["minItems"] == 1
    assert project_ids["maxItems"] == 25
    assert project_ids["items"]["pattern"] == "^[a-f0-9]{64}$"
    selection_mode = request["properties"]["selection_mode"]
    assert selection_mode["default"] == "all_analyzed_work"
    assert selection_mode["const"] == "all_analyzed_work"
    assert request["additionalProperties"] is False

    response_ref = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    response_name = response_ref.rsplit("/", 1)[-1]
    response = schema["components"]["schemas"][response_name]
    assert set(response["properties"]) == {
        "selection_mode",
        "estimand",
        "aggregation_method",
        "selected_project_count",
        "session_quality",
    }
    assert response["properties"]["selected_project_count"]["maximum"] == 25
    assert response["additionalProperties"] is False


def test_project_response_schemas_have_no_content_or_identity_fields() -> None:
    schemas = build_openapi_schema()["components"]["schemas"]
    aggregate_schema = {
        "ProjectQualityAggregate": schemas["ProjectQualityAggregate"],
        "ProjectSessionQualityAggregate": schemas[
            "ProjectSessionQualityAggregate"
        ],
        "ProjectQualityMetricAggregate": schemas[
            "ProjectQualityMetricAggregate"
        ],
        "ProjectQualityCompatibilityCohort": schemas[
            "ProjectQualityCompatibilityCohort"
        ],
    }
    serialized = json.dumps(aggregate_schema, sort_keys=True).casefold()
    assert '"compatibility_fingerprint"' in serialized

    for forbidden in (
        '"project_id"',
        '"project_ids"',
        '"session_id"',
        '"session_ids"',
        '"display_name"',
        '"evidence"',
        '"path"',
        '"excerpt"',
        '"prompt"',
        '"response"',
        '"tool_output"',
        '"provider_version"',
        '"adapter_version"',
        '"source_schema_version"',
        '"model_id"',
        '"tokenizer_id"',
        '"prompt_version"',
        '"rubric_version"',
    ):
        assert forbidden not in serialized
