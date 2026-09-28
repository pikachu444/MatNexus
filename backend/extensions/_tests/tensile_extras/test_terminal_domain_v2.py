"""Loader-path contracts for the v2 bounded tensile model-domain selector."""

from __future__ import annotations

import json

import numpy as np
import pytest

from matcore import processing, registry
from matcore.processing import Frame, ProcessingError, Step

processing.load_builtin()

AUTO_POLICY = "terminal_loss_auto_v2"
MANUAL_POLICY = "manual_end_strain_v1"
LEGACY_AUTO_POLICY = "terminal_loss_auto_v1"
LEGACY_MANUAL_POLICY = "manual_end_v1"


def _frame(
    stress: object,
    *,
    strain: object | None = None,
    time: object | None = None,
) -> Frame:
    values = np.asarray(stress, dtype=np.float64)
    count = len(values)
    columns: dict[str, np.ndarray] = {
        "displacement": np.arange(count, dtype=np.float64),
        "force": values / 2.0,
        "strain_engineering": (
            np.linspace(0.0, 1.0, count)
            if strain is None
            else np.asarray(strain, dtype=np.float64)
        ),
        "stress_engineering": values,
        "marker": np.arange(count, dtype=np.float64) + 0.25,
    }
    units = {
        "displacement": "m",
        "force": "N",
        "strain_engineering": "1",
        "stress_engineering": "Pa",
        "marker": "1",
    }
    if time is not None:
        columns["time"] = np.asarray(time, dtype=np.float64)
        units["time"] = "s"
    return Frame(columns, units)


def _run(frame: Frame, options: dict[str, object] | None = None) -> processing.PipelineResult:
    return processing.apply([Step("tensile.terminal_domain", options or {})], frame)


def _stage_values(result: processing.PipelineResult) -> dict[str, float]:
    return {item.key: item.value for item in result.stages[-1].scalars}


def test_v2_registration_is_loader_visible_and_between_nominal_and_sort() -> None:
    plugin = registry.get("tensile.terminal_domain")
    params = {item.name: item for item in plugin.params}
    assert plugin.kind == "processing"
    assert plugin.version == "2"
    assert plugin.order == 15
    assert registry.get("tensile.engineering").order < plugin.order
    assert plugin.order < registry.get("curve.sort_unique").order
    assert params["policy"].default == AUTO_POLICY
    assert params["policy"].choices == (
        AUTO_POLICY,
        MANUAL_POLICY,
        LEGACY_AUTO_POLICY,
        LEGACY_MANUAL_POLICY,
    )
    assert "이전 정책" in params["policy"].choice_labels[LEGACY_AUTO_POLICY]
    assert params["end_strain"].default == 0.50
    assert params["end_strain"].when == {"policy": (MANUAL_POLICY,)}
    assert params["end_index"].when == {"policy": (LEGACY_MANUAL_POLICY,)}


def test_default_auto_keeps_exact_bound_and_never_reenters_after_first_exceedance() -> None:
    strain = [0.0, 0.25, 0.50, 0.50, 0.60, 0.40, 0.70]
    frame = _frame([100.0] * len(strain), strain=strain)
    before = {key: values.copy() for key, values in frame.columns.items()}

    result = _run(frame)
    stage = result.stages[-1]
    values = _stage_values(result)

    assert stage.frame.length() == 4
    assert values["terminal_domain_end_index"] == 3.0
    assert values["terminal_domain_end_strain"] == 0.50
    assert values["terminal_domain_removed_points"] == 3.0
    assert values["terminal_domain_decision_code"] == 3.0
    assert values["terminal_domain_v2_end_reason_code"] == 2.0
    assert values["terminal_domain_v2_end_strain_bound"] == 0.50
    for key, original in before.items():
        np.testing.assert_array_equal(frame.columns[key], original)
        np.testing.assert_array_equal(stage.frame.columns[key], original[:4])
    assert "0번부터 3번 행까지 사용했습니다." in "\n".join(stage.notes)


def test_supported_early_drop_with_long_low_tail_precedes_the_strain_cap() -> None:
    stress = [100.0] * 30 + [0.0] * 70
    frame = _frame(stress)

    result = _run(frame)
    values = _stage_values(result)

    assert result.frame.length() == 30
    assert values["terminal_domain_end_index"] == 29.0
    assert values["terminal_domain_decision_code"] == 1.0
    assert values["terminal_domain_v2_end_reason_code"] == 1.0
    assert values["terminal_domain_v2_loss_candidate_index"] == 29.0
    assert "자동으로 하중 급락을 감지했습니다." in "\n".join(result.stages[-1].notes)


def test_recovery_after_strain_cap_vetoes_an_early_drop_using_full_source_suffix() -> None:
    stress = [100.0] * 30 + [0.0] * 10 + [100.0] * 60
    frame = _frame(stress)

    result = _run(frame)
    values = _stage_values(result)
    notes = "\n".join(result.stages[-1].notes)

    assert result.frame.length() == 50
    assert values["terminal_domain_end_index"] == 49.0
    assert values["terminal_domain_decision_code"] == 3.0
    assert values["terminal_domain_v2_loss_candidate_index"] == -1.0
    assert "전체 입력 데이터에서 확인했습니다." in notes


def test_loss_after_the_cap_does_not_replace_or_block_the_cap() -> None:
    stress = [100.0] * 60 + [0.0] * 40
    result = _run(_frame(stress))
    values = _stage_values(result)

    assert result.frame.length() == 50
    assert values["terminal_domain_end_index"] == 49.0
    assert values["terminal_domain_decision_code"] == 3.0
    assert values["terminal_domain_v2_loss_candidate_index"] == -1.0


def test_loss_started_before_cap_can_be_confirmed_by_chain_after_cap() -> None:
    strain = np.linspace(0.0, 0.6, 13)
    stress = [100.0] * 10 + [90.0, 40.0, 10.0]
    result = _run(_frame(stress, strain=strain))
    values = _stage_values(result)

    assert result.frame.length() == 10
    assert values["terminal_domain_end_index"] == 9.0
    assert values["terminal_domain_decision_code"] == 1.0


def test_flat_curve_that_ends_at_cap_does_not_probe_a_missing_next_row() -> None:
    strain = np.linspace(0.0, 0.5, 10)
    result = _run(_frame([100.0] * 10, strain=strain))

    assert result.frame.length() == 10
    assert _stage_values(result)["terminal_domain_decision_code"] == 0.0


def test_internal_dip_with_recovery_and_loaded_softening_remain_inside_cap() -> None:
    recovered = [100.0] * 15 + [0.0] * 5 + [100.0] * 80
    softening = [100.0] * 20 + [80.0, 65.0, 55.0, 48.0, 42.0] + [42.0] * 75

    for stress in (recovered, softening):
        result = _run(_frame(stress))
        values = _stage_values(result)
        assert result.frame.length() == 50
        assert values["terminal_domain_end_index"] == 49.0
        assert values["terminal_domain_decision_code"] == 3.0


def test_exact_twenty_percent_floor_plateau_is_preserved() -> None:
    stress = [100.0] * 30 + [20.0] * 70
    result = _run(_frame(stress))

    assert result.frame.length() == 50
    assert _stage_values(result)["terminal_domain_decision_code"] == 3.0


@pytest.mark.parametrize(
    "tail",
    (
        [80.0, 19.0],
        [80.0, 30.0, 19.0],
    ),
)
def test_two_or_three_nonincreasing_rows_can_reach_strictly_below_floor(
    tail: list[float],
) -> None:
    stress = [100.0] * 30 + tail + [19.0] * (70 - len(tail))
    result = _run(_frame(stress))

    assert result.frame.length() == 30
    assert _stage_values(result)["terminal_domain_v2_end_reason_code"] == 1.0


def test_ambiguous_gap_inside_candidate_support_is_rejected() -> None:
    time = [0.0, 1.0, 2.0, 3.0, 100.0, 101.0, 102.0, 103.0, 104.0, 1000.0, 1001.0]
    stress = [100.0] * 6 + [0.0] * 5
    frame = _frame(stress, time=time)

    with pytest.raises(
        ProcessingError,
        match="관측만으로 급락 위치를 확인할 수 없어 자동 제외를 보류합니다",
    ):
        _run(frame)


def test_gap_before_support_window_does_not_block_later_contiguous_support() -> None:
    time = [0.0, 1.0, 2.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    time.extend(float(value) for value in range(108, 208, 2))
    stress = [100.0] * 9 + [0.0] * (len(time) - 9)
    frame = _frame(stress, time=time)

    result = _run(frame)

    assert result.frame.length() == 9
    assert _stage_values(result)["terminal_domain_v2_end_reason_code"] == 1.0


def test_ordinal_progress_skips_early_detection_and_records_the_reason() -> None:
    strain = [0.0, 0.1, 0.2, 0.15, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70]
    stress = [100.0] * 4 + [0.0] * 6
    result = _run(_frame(stress, strain=strain))

    assert result.frame.length() == 8
    notes = "\n".join(result.stages[-1].notes)
    assert "시험 순서 확인 기준 코드" not in notes
    assert (
        "실제 시간이나 계속 증가하는 변형률을 사용할 수 없어 중간 급락은 판정하지 않았습니다"
        in notes
    )


def test_manual_strain_eight_tenths_includes_boundary_without_interpolation() -> None:
    strain = np.linspace(0.0, 1.0, 11)
    frame = _frame(np.arange(11, dtype=np.float64) + 100.0, strain=strain)
    before = {key: values.copy() for key, values in frame.columns.items()}

    result = _run(
        frame,
        {"policy": MANUAL_POLICY, "end_strain": 0.8},
    )
    stage = result.stages[-1]
    values = _stage_values(result)

    assert stage.frame.length() == 9
    assert values["terminal_domain_end_index"] == 8.0
    assert values["terminal_domain_end_strain"] == 0.8
    assert values["terminal_domain_decision_code"] == 2.0
    assert values["terminal_domain_v2_end_strain_bound"] == 0.8
    for key, original in before.items():
        np.testing.assert_array_equal(frame.columns[key], original)
        np.testing.assert_array_equal(stage.frame.columns[key], original[:9])


def test_manual_policy_without_a_value_uses_the_registered_half_strain_default() -> None:
    result = _run(_frame([100.0] * 5), {"policy": MANUAL_POLICY})
    values = _stage_values(result)

    assert result.frame.length() == 3
    assert values["terminal_domain_v2_end_strain_bound"] == 0.50


@pytest.mark.parametrize("bound", (True, False, 0.0, -0.1, float("nan"), float("inf"), "0.8"))
def test_manual_strain_rejects_nonpositive_nonfinite_or_nonreal_bound(bound: object) -> None:
    with pytest.raises(ProcessingError):
        _run(_frame([100.0] * 5), {"policy": MANUAL_POLICY, "end_strain": bound})


def test_fewer_than_two_point_manual_prefix_is_rejected() -> None:
    frame = _frame([100.0] * 5, strain=[0.0, 0.6, 0.7, 0.8, 0.9])
    with pytest.raises(ProcessingError, match="처리할 데이터가 2개 미만"):
        _run(frame, {"policy": MANUAL_POLICY, "end_strain": 0.5})


def test_inactive_policy_fields_are_ignored_but_unknown_options_are_rejected() -> None:
    frame = _frame([100.0] * 7)
    result = _run(
        frame,
        {"policy": AUTO_POLICY, "end_strain": "stale", "end_index": "stale"},
    )
    assert result.frame.length() == 4

    manual = _run(
        frame,
        {"policy": MANUAL_POLICY, "end_strain": 0.5, "end_index": "stale"},
    )
    assert manual.frame.length() == 4

    with pytest.raises(ProcessingError, match="지원하지 않는 말단 구간 옵션"):
        _run(frame, {"policy": AUTO_POLICY, "mystery": 1})


def test_new_json_recipe_round_trip_preserves_prefix_scalars_and_notes() -> None:
    frame = _frame([100.0] * 30 + [0.0] * 70)
    recipe = {"plugin": "tensile.terminal_domain", "options": {"policy": AUTO_POLICY}}
    replayed = json.loads(json.dumps(recipe))

    first = _run(frame, recipe["options"])
    second = _run(frame, replayed["options"])
    first_stage = first.stages[-1]
    second_stage = second.stages[-1]

    assert first_stage.notes == second_stage.notes
    assert _stage_values(first) == _stage_values(second)
    for key in frame.columns:
        np.testing.assert_array_equal(
            first_stage.frame.columns[key], second_stage.frame.columns[key]
        )
