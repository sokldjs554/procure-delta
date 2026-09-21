from app.demo.control_room import build_scenario, list_scenarios

EXPECTED_ORDER = [
    "collect",
    "dedupe",
    "normalize",
    "documents",
    "ocr-route",
    "extract",
    "validate",
    "lifecycle",
    "delta",
    "eligibility",
    "ranking",
    "notification",
]


def test_scenario_catalog_is_fixed_and_reviewer_facing() -> None:
    rows = list_scenarios()
    assert [row.id for row in rows] == [
        "new-opportunity",
        "amendment-eligibility-change",
        "failure-recovery",
    ]


def test_amendment_scenario_exposes_stable_pipeline_order() -> None:
    scenario = build_scenario("amendment-eligibility-change")
    assert scenario.synthetic is True
    assert scenario.source_scope == "packaged_fixture"
    assert [stage.id for stage in scenario.stages] == EXPECTED_ORDER


def test_amendment_scenario_keeps_delta_eligibility_and_ranking_separate() -> None:
    scenario = build_scenario("amendment-eligibility-change")
    stages = {stage.id: stage for stage in scenario.stages}

    assert stages["delta"].output["changed_fields"]
    assert stages["delta"].decision["impact"] == "high"
    assert "region_restriction" in " ".join(stages["delta"].decision["reason_codes"])

    assert stages["eligibility"].output["before"]["allows_recommendation"] is True
    assert stages["eligibility"].output["after"]["allows_recommendation"] is False
    assert "region_not_served" in stages["eligibility"].output["after"]["hard_failure_codes"]

    assert stages["ranking"].output["after"]["recommended"] is False
    assert stages["ranking"].decision["eligibility_overrides_rank"] is True


def test_failure_scenario_exposes_verified_retry_classification_without_network_io() -> None:
    scenario = build_scenario("failure-recovery")
    failure = {stage.id: stage for stage in scenario.stages}["collect"]
    cases = failure.output["transport_cases"]

    assert [(row["name"], row["attempts"], row["succeeded"]) for row in cases] == [
        ("timeout-recovery", 3, True),
        ("rate-limit-recovery", 2, True),
        ("server-error-terminal", 3, False),
        ("forbidden-not-retried", 1, False),
    ]
    assert failure.notice == "합성 HTTP transport 주입 결과"


def test_control_room_scenarios_do_not_require_external_network(monkeypatch) -> None:
    from app.sources.http import ResilientHttpClient

    async def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(ResilientHttpClient, "request", forbidden)
    for row in list_scenarios():
        build_scenario(row.id)
