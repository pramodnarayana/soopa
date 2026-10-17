import json

import pytest
from infra_seedwork.ecr import build_ecr_lifecycle_policy_doc


def test_build_ecr_lifecycle_policy_doc_defaults() -> None:
    doc_str = build_ecr_lifecycle_policy_doc()
    policy = json.loads(doc_str)

    assert "rules" in policy
    assert len(policy["rules"]) == 2

    rule1 = policy["rules"][0]
    assert rule1["rulePriority"] == 1
    assert rule1["selection"]["tagStatus"] == "untagged"
    assert rule1["selection"]["countNumber"] == 1
    assert rule1["action"]["type"] == "expire"

    rule2 = policy["rules"][1]
    assert rule2["rulePriority"] == 2
    assert rule2["selection"]["tagStatus"] == "any"
    assert rule2["selection"]["countType"] == "imageCountMoreThan"
    assert rule2["selection"]["countNumber"] == 10
    assert rule2["action"]["type"] == "expire"


def test_build_ecr_lifecycle_policy_doc_custom_params() -> None:
    doc_str = build_ecr_lifecycle_policy_doc(max_image_count=25, untagged_retention_days=3)
    policy = json.loads(doc_str)

    assert policy["rules"][0]["selection"]["countNumber"] == 3
    assert policy["rules"][1]["selection"]["countNumber"] == 25


def test_build_ecr_lifecycle_policy_doc_validation() -> None:
    with pytest.raises(ValueError, match="max_image_count must be at least 1"):
        build_ecr_lifecycle_policy_doc(max_image_count=0)

    with pytest.raises(ValueError, match="untagged_retention_days must be at least 1"):
        build_ecr_lifecycle_policy_doc(untagged_retention_days=0)
