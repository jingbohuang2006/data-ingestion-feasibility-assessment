from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.review_feature_report import build_validation_report, write_validation_report
from src.review_features import generate_review_features, load_feature_rules, read_normalized_reviews


ROOT = Path(__file__).parents[1]


def test_report_uses_actual_counts_and_preserves_lineage(tmp_path: Path) -> None:
    source = read_normalized_reviews(ROOT / "tests" / "fixtures" / "review_feature_cases.csv")
    features = generate_review_features(
        source, load_feature_rules(ROOT / "config" / "review_feature_rules_v1.yaml")
    )

    report = build_validation_report(features, input_row_count=len(source))
    summary = report["summary"]

    assert summary["input_row_count"] == 6
    assert summary["output_row_count"] == 6
    assert summary["row_count_preserved"]
    assert summary["unique_contextual_review_identity_count"] == 6
    assert summary["duplicate_contextual_identity_count"] == 0
    assert summary["lineage_fields_retained"]
    assert set(report["distributions"]["country"]) == {"us", "gb"}
    assert set(report["distributions"]["app_name"]) == {"App A", "App B"}

    paths = write_validation_report(report, tmp_path / "reports", "not-a-row-count")
    persisted = json.loads(paths[0].read_text(encoding="utf-8"))
    assert persisted["output_row_count"] == 6
    assert paths[1].exists() and paths[2].exists()


def test_report_rejects_missing_lineage() -> None:
    with pytest.raises(ValueError, match="missing lineage fields"):
        build_validation_report(pd.DataFrame({"review_id": ["r1"]}))
