"""Loader-path contracts for the opt-in v1 terminal-loss prefix selector."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from matcore import processing, registry
from matcore.processing import Frame, ProcessingError, Step

EXTENSIONS = Path(__file__).resolve().parents[1]
processing.load_builtin()
AUTO_POLICY = "terminal_loss_auto_v1"
MANUAL_POLICY = "manual_end_v1"


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
    return processing.apply(
        [Step("tensile.terminal_domain", options or {})],
        frame,
    )


def _stage_values(result: processing.PipelineResult) -> dict[str, float]:
    return {item.key: item.value for item in result.stages[-1].scalars}


def test_registration_is_available_through_the_extension_loader() -> None:
    loader_check = """
from matcore import extensions, processing, registry
import sys
from pathlib import Path

report = extensions.load(Path(sys.argv[1]))
assert not extensions.failures(report), report
processing.load_builtin()
plugin = registry.get("tensile.terminal_domain")
assert plugin.kind == "processing"
assert plugin.order == 20
assert plugin.version == "1"
assert plugin.params[0].choices == ("terminal_loss_auto_v1", "manual_end_v1")
"""
    completed = subprocess.run(
        [sys.executable, "-c", loader_check, str(EXTENSIONS)],
        cwd=EXTENSIONS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    plugin = registry.get("tensile.terminal_domain")
    params = {item.name: item for item in plugin.params}
    assert params["policy"].default == AUTO_POLICY
    assert "자동은 마지막 10%" in (params["policy"].help or "")
    assert params["end_index"].when == {"policy": (MANUAL_POLICY,)}


def test_abrupt_terminal_loss_selects_prefix_and_preserves_raw_frame() -> None:
    frame = _frame([100.0] * 10 + [0.0], time=np.arange(11, dtype=np.float64))
    before = {key: values.copy() for key, values in frame.columns.items()}

    result = _run(frame)
    stage = result.stages[-1]
    values = _stage_values(result)

    assert stage.plugin == "tensile.terminal_domain"
    assert stage.frame.length() == 10
    assert values["terminal_domain_end_index"] == 9.0
    assert values["terminal_domain_removed_points"] == 1.0
    assert values["terminal_domain_decision_code"] == 1.0
    assert values["terminal_domain_progress_basis_code"] == 2.0
    for key, original in before.items():
        np.testing.assert_array_equal(frame.columns[key], original)
        np.testing.assert_array_equal(stage.frame.columns[key], original[:10])


def test_json_recipe_round_trip_replays_prefix_scalars_and_notes() -> None:
    frame = _frame([100.0] * 10 + [0.0], time=np.arange(11, dtype=np.float64))
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


def test_inner_dip_with_recovery_is_not_cropped() -> None:
    frame = _frame([100.0] * 19 + [0.0, 100.0])

    result = _run(frame)
    values = _stage_values(result)

    assert result.frame is frame
    assert result.frame.length() == 21
    assert values["terminal_domain_decision_code"] == 0.0
    assert values["terminal_domain_removed_points"] == 0.0


def test_exact_half_loss_recovery_can_crop_but_above_it_keeps_horizon() -> None:
    prefix = [100.0] * 28

    exact_frame = _frame([*prefix, 90.0, 0.0, 50.0])
    exact_result = _run(exact_frame)
    exact_values = _stage_values(exact_result)

    # R13 freezes a strict greater-than recovery check: equality at half the
    # detected loss is still a valid terminal crop.
    assert exact_result.stages[-1].frame.length() == 28
    assert exact_values["terminal_domain_end_index"] == 27.0
    assert exact_values["terminal_domain_removed_points"] == 3.0

    above_frame = _frame([*prefix, 90.0, 0.0, 50.000001])
    above_result = _run(above_frame)
    above_values = _stage_values(above_result)

    assert above_result.frame is above_frame
    assert above_result.frame.length() == 31
    assert above_values["terminal_domain_decision_code"] == 0.0
    assert above_values["terminal_domain_removed_points"] == 0.0


def test_progressive_tail_is_reported_and_left_unchanged() -> None:
    stress = [100.0] * 20 + [95.0, 90.0, 85.0, 80.0, 75.0]
    frame = _frame(stress)

    result = _run(frame)

    assert result.frame is frame
    assert result.frame.length() == len(stress)
    assert _stage_values(result)["terminal_domain_decision_code"] == 0.0
    assert "gradual_tail_unresolved" in "\n".join(result.stages[-1].notes)


def test_late_stable_positive_suffix_is_ambiguous() -> None:
    frame = _frame([100.0] * 19 + [30.0, 30.0])

    with pytest.raises(ProcessingError, match="ambiguous_stable_low_suffix"):
        _run(frame)


def test_terminal_loss_across_large_sampling_gap_is_ambiguous() -> None:
    frame = _frame([100.0] * 100 + [0.0], time=[*range(100), 109.1])

    with pytest.raises(ProcessingError, match="ambiguous_sampling_gap"):
        _run(frame)


def test_manual_end_selects_the_inclusive_prefix() -> None:
    frame = _frame([100.0] * 8 + [0.0, 0.0])
    before = {key: values.copy() for key, values in frame.columns.items()}

    result = _run(
        frame,
        {"policy": MANUAL_POLICY, "end_index": 5},
    )
    stage = result.stages[-1]
    values = _stage_values(result)

    assert stage.frame.length() == 6
    assert values["terminal_domain_end_index"] == 5.0
    assert values["terminal_domain_decision_code"] == 2.0
    for key, original in before.items():
        np.testing.assert_array_equal(frame.columns[key], original)
        np.testing.assert_array_equal(stage.frame.columns[key], original[:6])


def test_invalid_or_unimplemented_policy_is_rejected() -> None:
    options_list: tuple[dict[str, object], ...] = (
        {"policy": MANUAL_POLICY},
        {"policy": MANUAL_POLICY, "end_index": 0},
        {"policy": "terminal_loss_auto_v2"},
    )
    for options in options_list:
        with pytest.raises(ProcessingError):
            _run(_frame([100.0] * 5), options)
