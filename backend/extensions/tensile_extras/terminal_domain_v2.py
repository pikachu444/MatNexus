"""Conservative v2 tensile model-domain selection with an engineering-strain bound."""

from __future__ import annotations

from numbers import Real
from typing import Any

import numpy as np

from matcore.processing import Frame, ProcessingError, Scalar, StepResult

from . import terminal_domain as legacy

AUTO_POLICY = "terminal_loss_auto_v2"
MANUAL_STRAIN_POLICY = "manual_end_strain_v1"
DEFAULT_END_STRAIN = 0.50
POLICIES = (AUTO_POLICY, MANUAL_STRAIN_POLICY)
POLICY_LABELS = {
    AUTO_POLICY: "자동 (변형률 제한·급락 감지)",
    MANUAL_STRAIN_POLICY: "수동 (변형률 제한)",
}
_KNOWN_OPTIONS = frozenset(
    {"policy", "strain", "stress", "time", "end_index", "end_strain", *legacy.FIXED_OPTIONS}
)


def terminal_domain(frame: Frame, options: dict[str, Any]) -> StepResult:
    """Dispatch v1 compatibility policies and v2 bounded policies."""
    unknown = sorted((key for key in options if key not in _KNOWN_OPTIONS), key=str)
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise ProcessingError(f"지원하지 않는 말단 구간 옵션입니다: {names}.")
    _validate_fixed_options(options)

    policy = options.get("policy", AUTO_POLICY)
    if not isinstance(policy, str):
        raise ProcessingError("'policy' 는 등록된 말단 구간 정책 이름이어야 합니다.")
    if policy in (legacy.AUTO_POLICY, legacy.MANUAL_POLICY):
        forwarded = dict(options)
        forwarded.pop("end_strain", None)
        if policy == legacy.AUTO_POLICY:
            forwarded.pop("end_index", None)
        return legacy.terminal_domain(frame, forwarded)
    if policy not in POLICIES:
        raise ProcessingError(f"지원하지 않는 말단 구간 정책입니다: {policy!r}.")

    return _terminal_domain_v2(frame, options, str(policy))


def _validate_fixed_options(options: dict[str, Any]) -> None:
    for key, expected in legacy.FIXED_OPTIONS.items():
        if key not in options:
            continue
        actual = options[key]
        if type(actual) is not type(expected) or actual != expected:
            raise ProcessingError(
                f"'{key}' 정책은 {expected!r} 로 고정되어 있습니다. "
                "다른 정책은 새 버전으로 정의해야 합니다."
            )


def _end_strain_value(options: dict[str, Any], policy: str) -> float:
    if policy == AUTO_POLICY:
        return DEFAULT_END_STRAIN
    raw = options.get("end_strain", DEFAULT_END_STRAIN)
    if isinstance(raw, (bool, np.bool_)) or not isinstance(raw, Real):
        raise ProcessingError("'end_strain' 은 bool 이 아닌 양의 유한 실수여야 합니다.")
    value = float(raw)
    if not np.isfinite(value) or value <= 0.0:
        raise ProcessingError("'end_strain' 은 bool 이 아닌 양의 유한 실수여야 합니다.")
    return value


def _cap_end(strain: np.ndarray, bound: float) -> int:
    above = np.flatnonzero(strain > bound)
    return int(above[0] - 1) if len(above) else len(strain) - 1


def _gap_in_rows_error(
    progress: np.ndarray,
    basis: str,
    start_row: int,
    end_row: int,
    candidate: int,
    context: str,
) -> ProcessingError | None:
    if basis == "ordinal":
        return None
    increments = np.diff(progress)
    for row in range(max(1, start_row + 1), end_row + 1):
        step_index = row - 1
        prior = increments[
            max(0, step_index - legacy.FIXED_OPTIONS["gap_preceding_steps"]) : step_index
        ]
        positive = prior[prior > 0.0]
        if not len(positive):
            continue
        local = legacy._median(positive)
        step = float(increments[step_index])
        if (
            step > legacy.FIXED_OPTIONS["gap_interval_ratio"] * local
            and step > legacy.FIXED_OPTIONS["gap_progress_fraction"]
        ):
            context_label = (
                "급락 후보 앞의 하중 확인 구간"
                if context == "지지 구간"
                else "급락 뒤의 연결 구간"
            )
            return ProcessingError(
                f"급락 후보 {candidate}번 행의 {context_label}에서 입력 행 {row - 1}→{row} "
                f"사이 간격 {step:.6g}이 직전 간격 중앙값 {local:.6g}의 10배를 넘고 "
                "전체 시험 구간의 1%보다 큽니다. 관측만으로 급락 위치를 확인할 수 없어 "
                "자동 제외를 보류합니다."
            )
    return None


def _early_chain_end(stress: np.ndarray, index: int, local: float) -> int | None:
    first = index + 1
    if first >= len(stress):
        return None
    if (
        stress[first]
        > stress[index] - legacy.FIXED_OPTIONS["chain_first_loss_fraction"] * local
    ):
        return None
    limit = min(len(stress) - 1, index + legacy.FIXED_OPTIONS["chain_max_rows"])
    for end in range(first, limit + 1):
        chain = stress[index + 1 : end + 1]
        if len(chain) > 1 and np.any(chain[1:] > chain[:-1]):
            return None
        if stress[end] < legacy.FIXED_OPTIONS["stable_suffix_load_fraction"] * local:
            return end
    return None


def _notes_for_loss(
    stress: np.ndarray, index: int, end: int, local: float, *, early: bool
) -> tuple[str, ...]:
    first_loss_fraction = float((stress[index] - stress[index + 1]) / local)
    total_loss_fraction = float((stress[index] - stress[end]) / local)
    return (
        f"자동으로 하중 급락을 감지했습니다. {index}번 행까지 사용하고, "
        f"{index + 1}번 행부터 제외했습니다.",
        f"급락 전 응력 {stress[index]:.6g} Pa, 첫 제외 행 응력 {stress[index + 1]:.6g} Pa, "
        f"급락 확인 구간의 마지막 응력 {stress[end]:.6g} Pa, "
        f"기준 응력 {local:.6g} Pa, 기준 응력 대비 첫 감소율={first_loss_fraction:.6g}, "
        f"기준 응력 대비 전체 감소율={total_loss_fraction:.6g}.",
    )


def _progress_notes_for_v2(
    basis: str, reason: str | None, strain_strict: bool
) -> tuple[str, ...]:
    if basis == "time":
        notes = ["초 단위 시간으로 시험의 순서를 확인했습니다."]
    elif basis == "strain":
        notes = ["시간을 사용할 수 없어 계속 증가하는 변형률로 시험의 순서를 확인했습니다."]
    else:
        notes = [
            "시간이나 계속 증가하는 변형률을 사용할 수 없어 "
            "원래 데이터 행 순서로 확인했습니다. "
            "행 순서는 실제 시간이나 변형률 간격을 나타내지 않습니다."
        ]
    if reason:
        readable_reason = reason.replace("시간 진행축", "시간 기준").replace(
            "0~1 진행축", "정규화된 순서 기준"
        )
        readable_reason = readable_reason.replace(
            "행 순서를 진행축으로 사용했습니다.", "행 순서만으로 순서를 확인했습니다."
        )
        notes.append(readable_reason)
    if not strain_strict:
        notes.append("변형률은 원래 행 순서에서 계속 증가하지 않습니다.")
    return tuple(notes)


def _v1_recovery_veto(stress: np.ndarray, index: int, end: int) -> bool:
    recovery_fraction = legacy.FIXED_OPTIONS["recovery_loss_fraction"]
    recovery_limit = (
        stress[index] * (1.0 - recovery_fraction) + stress[end] * recovery_fraction
    )
    return bool(np.any(stress[end:] > recovery_limit))


def _early_candidate(
    stress: np.ndarray,
    progress: np.ndarray,
    basis: str,
    index: int,
) -> tuple[int, float] | None:
    start = max(0, index - legacy.FIXED_OPTIONS["support_window_rows"])
    support = stress[start:index]
    if len(support) < legacy.FIXED_OPTIONS["minimum_support_rows"]:
        return None
    local = legacy._median(support)
    if local <= 0.0 or stress[index] <= 0.0:
        return None
    if abs(stress[index] - local) > legacy.FIXED_OPTIONS["support_tolerance_fraction"] * local:
        return None
    end = _early_chain_end(stress, index, local)
    if end is None:
        return None

    # The original loss midpoint remains a veto, and every later source row must
    # stay strictly below the low-load floor, including rows beyond the cap.
    if _v1_recovery_veto(stress, index, end):
        return None
    floor = legacy.FIXED_OPTIONS["stable_suffix_load_fraction"] * local
    if np.any(stress[end:] >= floor):
        return None

    support_gap = _gap_in_rows_error(progress, basis, start, index, index, "지지 구간")
    if support_gap is not None:
        raise support_gap
    chain_gap = legacy._gap_error(progress, basis, index, end)
    if chain_gap is not None:
        raise chain_gap
    return end, local


def _late_candidate(
    stress: np.ndarray,
    progress: np.ndarray,
    basis: str,
    index: int,
) -> tuple[int, float] | None:
    minimum = legacy.FIXED_OPTIONS["minimum_support_rows"] - 1
    if index < minimum or progress[index] < legacy.FIXED_OPTIONS["late_progress_fraction"]:
        return None
    start = max(0, index - legacy.FIXED_OPTIONS["support_window_rows"] + 1)
    local = legacy._median(stress[start : index + 1])
    if local <= 0.0 or stress[index] <= 0.0:
        return None
    if abs(stress[index] - local) > legacy.FIXED_OPTIONS["support_tolerance_fraction"] * local:
        return None
    chain = legacy._drop_chain(stress, index, local)
    if chain is None:
        return None
    end, _kind = chain
    if _v1_recovery_veto(stress, index, end):
        return None

    support_gap = _gap_in_rows_error(progress, basis, start, index, index, "지지 구간")
    if support_gap is not None:
        raise support_gap
    chain_gap = legacy._gap_error(progress, basis, index, end)
    if chain_gap is not None:
        raise chain_gap

    suffix = stress[index + 1 :]
    remaining = 1.0 - progress[index]
    stable_loaded = (
        remaining > legacy.FIXED_OPTIONS["stable_suffix_remaining_fraction"]
        and legacy._median(suffix)
        >= legacy.FIXED_OPTIONS["stable_suffix_load_fraction"] * local
        and np.min(suffix)
        >= np.max(suffix) - legacy.FIXED_OPTIONS["stable_suffix_range_fraction"] * local
    )
    if stable_loaded:
        raise ProcessingError(
            f"급락 후보 {index}번 행 뒤에도 전체 시험 구간의 {remaining:.6g}가량에 걸쳐 "
            "안정된 하중이 이어집니다. 계속 하중을 받는 구간일 수 있어 자동 제외를 보류합니다."
        )
    return end, local


def _automatic_loss_end(
    stress: np.ndarray,
    progress: np.ndarray,
    basis: str,
    cap_end: int,
) -> tuple[int | None, tuple[str, ...], bool]:
    early_notes: list[str] = []
    candidate_max = min(cap_end, len(stress) - 2)
    if basis in ("time", "strain"):
        for index in range(legacy.FIXED_OPTIONS["minimum_support_rows"], candidate_max + 1):
            if progress[index] >= legacy.FIXED_OPTIONS["late_progress_fraction"]:
                continue
            candidate = _early_candidate(stress, progress, basis, index)
            if candidate is None:
                continue
            end, local = candidate
            return index, _notes_for_loss(stress, index, end, local, early=True), False
    else:
        early_notes.append(
            "실제 시간이나 계속 증가하는 변형률을 사용할 수 없어 "
            "중간 급락은 판정하지 않았습니다. "
            "행 순서만으로는 실제 측정 간격을 알 수 없습니다."
        )

    for index in range(legacy.FIXED_OPTIONS["minimum_support_rows"] - 1, candidate_max + 1):
        if progress[index] < legacy.FIXED_OPTIONS["late_progress_fraction"]:
            continue
        candidate = _late_candidate(stress, progress, basis, index)
        if candidate is None:
            continue
        end, local = candidate
        return index, _notes_for_loss(stress, index, end, local, early=False), False
    return None, tuple(early_notes), legacy._gradual_unresolved(stress, progress)


def _terminal_domain_v2(frame: Frame, options: dict[str, Any], policy: str) -> StepResult:
    bound = _end_strain_value(options, policy)
    strain_name = str(options.get("strain", legacy.DEFAULT_STRAIN))
    stress_name = str(options.get("stress", legacy.DEFAULT_STRESS))
    time_name = str(options.get("time", legacy.DEFAULT_TIME))

    n, arrays = legacy._frame_arrays(frame)
    frame.require(strain_name, what="변형률")
    frame.require(stress_name, what="응력")
    legacy._require_unit(frame, strain_name, "1", what="변형률")
    legacy._require_unit(frame, stress_name, "Pa", what="응력")
    strain = legacy._real_values(arrays[strain_name], strain_name, what="변형률")
    stress = legacy._real_values(arrays[stress_name], stress_name, what="응력")
    strain_strict = legacy._strictly_increasing(strain)
    cap_end = _cap_end(strain, bound)
    if cap_end < 1:
        raise ProcessingError(
            f"공칭변형률 제한 {bound:.6g} 이하에서 처리할 데이터가 2개 미만입니다."
        )
    progress, basis, fallback_reason = legacy._progress(
        arrays, frame, strain, strain_name, time_name
    )
    progress_notes = _progress_notes_for_v2(basis, fallback_reason, strain_strict)

    loss_end: int | None = None
    automatic_notes: tuple[str, ...] = ()
    unresolved = False
    if policy == AUTO_POLICY:
        loss_end, automatic_notes, unresolved = _automatic_loss_end(
            stress, progress, basis, cap_end
        )
        end_index = min(cap_end, loss_end) if loss_end is not None else cap_end
        if loss_end is not None and loss_end <= cap_end:
            decision_code = 1.0
            reason_code = 1.0
            reason = "정해진 급락 기준을 충족해 급락 직전 행을 선택했습니다."
        elif cap_end < n - 1:
            decision_code = 3.0
            reason_code = 2.0
            reason = "자동 정책의 변형률 제한을 적용했습니다."
        else:
            decision_code = 0.0
            reason_code = 0.0
            reason = "급락 기준이나 변형률 제한에 따른 제외가 없습니다."
    else:
        end_index = cap_end
        decision_code = 2.0
        reason_code = 3.0
        reason = "지정한 변형률 제한을 적용했습니다."

    selected = frame if end_index == n - 1 else frame.select(np.arange(end_index + 1))
    removed = n - end_index - 1
    policy_label = POLICY_LABELS[policy]
    notes: list[str] = [f"처리 방식: {policy_label}.", *progress_notes]
    if policy == AUTO_POLICY:
        notes.append(
            f"자동 정책의 변형률 제한은 {bound:.6g} (50%)입니다. "
            "50%는 보편적인 파단 기준이 아닙니다."
        )
        if automatic_notes:
            notes.extend(automatic_notes)
        if loss_end is not None and loss_end > cap_end:
            notes.append(
                f"급락 후보 {loss_end}번 행의 확인 구간은 변형률 제한 뒤에 있어 "
                "끝 위치에 반영되지 않았습니다."
            )
        if reason_code == 2.0:
            notes.append(
                f"변형률 제한을 처음 넘은 {cap_end + 1}번 행부터 "
                f"뒤의 데이터 {removed}개를 제외했습니다."
            )
        elif reason_code == 0.0:
            notes.append(f"입력 데이터 {n}개를 모두 사용했습니다.")
        if unresolved:
            first_late = int(
                np.searchsorted(
                    progress, legacy.FIXED_OPTIONS["late_progress_fraction"], side="left"
                )
            )
            notes.append(
                "시험 순서의 마지막 10%에서 첫 응력 "
                f"{stress[first_late]:.6g} Pa 에서 마지막 응력 {stress[-1]:.6g} Pa 까지 "
                "전체 최대 응력의 10% 이상 낮아졌습니다. 완만한 감소는 급락 기준에 미치지 "
                "않았습니다. 변형률 제한은 별도로 적용합니다."
            )
    else:
        notes.append(
            f"수동 변형률 제한은 {bound:.6g}이며 자동 급락 감지는 적용하지 않았습니다."
        )
        if cap_end < n - 1:
            notes.append(
                f"변형률 제한을 처음 넘은 {cap_end + 1}번 행부터 "
                f"뒤의 데이터 {removed}개를 제외했습니다."
            )
        else:
            notes.append(f"입력 데이터 {n}개를 모두 사용했습니다.")
    notes.append(f"0번부터 {end_index}번 행까지 사용했습니다. {reason}")
    if policy == AUTO_POLICY:
        notes.append(
            "하중 회복 여부는 변형률 제한 뒤를 포함해 전체 입력 데이터에서 확인했습니다. "
            "이 처리는 사용할 데이터 범위를 정하며 네킹이나 파단을 판정하지 않습니다."
        )
    else:
        notes.append(
            "이 처리는 사용할 데이터 범위를 정하며 네킹이나 파단을 판정하지 않습니다."
        )

    scalar_values = (
        Scalar("terminal_domain_end_index", "절단 위치 (행 번호)", float(end_index), "1"),
        Scalar(
            "terminal_domain_end_strain",
            "종료점 변형률",
            float(strain[end_index]),
            "1",
            "strain",
        ),
        Scalar("terminal_domain_removed_points", "제외한 데이터 수", float(removed), "1"),
        Scalar("terminal_domain_input_points", "입력 데이터 수", float(n), "1"),
        Scalar(
            "terminal_domain_input_end_load", "처리 전 마지막 응력", float(stress[-1]), "Pa"
        ),
        Scalar("terminal_domain_decision_code", "끝단 처리 결과 코드", decision_code, "1"),
        Scalar(
            "terminal_domain_strain_strict",
            "변형률의 원래 순서 증가 여부",
            float(strain_strict),
            "1",
        ),
        Scalar(
            "terminal_domain_progress_basis_code",
            "시험 순서 확인 기준 코드",
            {"ordinal": 0.0, "strain": 1.0, "time": 2.0}[basis],
            "1",
        ),
        Scalar(
            "terminal_domain_v2_end_reason_code",
            "끝 위치를 정한 이유 코드",
            reason_code,
            "1",
        ),
        Scalar("terminal_domain_v2_end_strain_bound", "적용한 변형률 제한", float(bound), "1"),
        Scalar(
            "terminal_domain_v2_loss_candidate_index",
            "급락 직전 행 번호",
            float(loss_end) if loss_end is not None else -1.0,
            "1",
        ),
    )
    if not all(np.isfinite(scalar.value) for scalar in scalar_values):
        raise ProcessingError("끝단 처리 진단값을 만들 수 없습니다.")
    return StepResult(frame=selected, notes=tuple(notes), scalars=scalar_values)
