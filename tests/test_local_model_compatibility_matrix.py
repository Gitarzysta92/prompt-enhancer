from pathlib import Path

from scripts.export_local_model_compatibility import build_matrix, export_matrix


def test_public_compatibility_matrix_is_generated_from_synthetic_contract_cases(
    tmp_path: Path,
) -> None:
    matrix = build_matrix()
    assert "`supported`" in matrix
    assert "`unknown`" in matrix
    assert "`unsupported`" in matrix
    assert "live_text_probe_verified" in matrix
    assert "/v1/chat/completions/input_tokens" in matrix
    assert "synthetic" in matrix.lower()
    output = tmp_path / "matrix.md"
    export_matrix(output)
    assert output.read_text(encoding="utf-8") == matrix


def test_checked_in_compatibility_matrix_is_current() -> None:
    checked_in = Path("docs/local-model-compatibility-matrix.md")
    assert checked_in.read_text(encoding="utf-8") == build_matrix()
