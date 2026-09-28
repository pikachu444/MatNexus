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
            return ProcessingError(
                "ambiguous_sampling_gap: "
                f"후보 유지 행 {candidate} 의 {context}에서 입력 행 {row - 1}→{row} 진행 간격 "
                f"{step:.6g} 이 직전 간격 중앙값 {local:.6g} 의 10배 초과이며 "
                "전체 진행 폭의 1%보다 큽니다. 급락 위치를 관측만으로 정할 수 없어 "
                "자동 자르기를 보류합니다."
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
    label = "조기 급락" if early else "후반 급락"
    return (
        f"{label} 적용; 유지 행 {index}, 첫 제외 행 {index + 1}, 마지막 저하중 연결 행 {end}.",
        f"후보 행 응력 {stress[index]:.6g} Pa, 첫 제외 응력 {stress[index + 1]:.6g} Pa, "
        f"끝 연결 응력 {stress[end]:.6g} Pa, 국소 기준 L={local:.6g} Pa, "
        f"첫 손실/L={first_loss_fraction:.6g}, 총 손실/L={total_loss_fraction:.6g}.",
    )


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
            "ambiguous_stable_low_suffix: "
            f"후보 유지 행 {index} 뒤에 진행 폭 {remaining:.6g} 의 "
            "안정된 하중 구간이 남습니다. "
            "의도된 하측 모델 구간일 수 있어 자동 자르기를 보류합니다."
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
            "조기 급락 탐지는 실제 시간·변형률 진행축이 없어 건너뛰었습니다; "
            "행 순서는 간격을 증명하지 않습니다."
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
            f"공칭변형률 {bound:.6g} 이하에서 유지할 수 있는 연속 prefix가 2점 미만입니다."
        )
    progress, basis, fallback_reason = legacy._progress(
        arrays, frame, strain, strain_name, time_name
    )
    progress_notes = legacy._progress_notes(basis, fallback_reason, strain_strict)

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
            reason = "지원된 급락 경계가 선택되었습니다."
        elif cap_end < n - 1:
            decision_code = 3.0
            reason_code = 2.0
            reason = "고정 공칭변형률 상한이 선택되었습니다."
        else:
            decision_code = 0.0
            reason_code = 0.0
            reason = "급락과 공칭변형률 상한에 따른 제외가 없습니다."
    else:
        end_index = cap_end
        decision_code = 2.0
        reason_code = 3.0
        reason = "사용자가 지정한 끝 공칭변형률 경계가 선택되었습니다."

    selected = frame if end_index == n - 1 else frame.select(np.arange(end_index + 1))
    removed = n - end_index - 1
    notes: list[str] = [f"정책 {policy}.", *progress_notes]
    if policy == AUTO_POLICY:
        notes.append(f"고정 상한 공칭변형률 {bound:.6g} (50% 기본 상한).")
        if automatic_notes:
            notes.extend(automatic_notes)
        if loss_end is not None and loss_end > cap_end:
            notes.append(
                f"급락 후보 행 {loss_end} 는 상한 경계 {cap_end} 뒤여서 "
                "선택 결과에 영향을 주지 않았습니다."
            )
        if reason_code == 2.0:
            notes.append(
                f"상한 초과 첫 행 {cap_end + 1} 부터 끝까지 {removed}개 행을 제외했습니다."
            )
        elif reason_code == 0.0:
            notes.append(f"모든 {n}개 행을 유지했습니다.")
        if unresolved:
            first_late = int(
                np.searchsorted(
                    progress, legacy.FIXED_OPTIONS["late_progress_fraction"], side="left"
                )
            )
            notes.append(
                "gradual_tail_unresolved; 마지막 진행축 10% 구간 첫 응력 "
                f"{stress[first_late]:.6g} Pa 에서 끝 응력 {stress[-1]:.6g} Pa 까지 "
                "양의 원응력 최댓값의 10% 이상 감소했지만 "
                "자동 급락 기준을 만족하지 않았습니다."
            )
    else:
        notes.append(f"수동 끝 공칭변형률 {bound:.6g}.")
        if cap_end < n - 1:
            notes.append(
                f"상한 초과 첫 행 {cap_end + 1} 부터 끝까지 {removed}개 행을 제외했습니다."
            )
        else:
            notes.append(f"모든 {n}개 행을 유지했습니다.")
    notes.append(f"최종 선택 행 0~{end_index} 포함; {reason}")
    if policy == AUTO_POLICY:
        notes.append(
            "상한 뒤를 포함해 원자료 전체 suffix에서 회복 여부를 확인했습니다. "
            "말단 구간 선택은 모델용 범위이며 네킹이나 파단을 판정하지 않습니다."
        )
    else:
        notes.append("말단 구간 선택은 모델용 범위이며 네킹이나 파단을 판정하지 않습니다.")

    scalar_values = (
        Scalar(
            "terminal_domain_end_index", "모델 구간 끝 행 위치 (0부터)", float(end_index), "1"
        ),
        Scalar(
            "terminal_domain_end_strain",
            "모델 구간 끝 변형률",
            float(strain[end_index]),
            "1",
            "strain",
        ),
        Scalar("terminal_domain_removed_points", "제외한 말단 점 수", float(removed), "1"),
        Scalar("terminal_domain_input_points", "입력 점 수", float(n), "1"),
        Scalar("terminal_domain_input_end_load", "입력 끝 응력", float(stress[-1]), "Pa"),
        Scalar("terminal_domain_decision_code", "말단 결정 코드", decision_code, "1"),
        Scalar(
            "terminal_domain_strain_strict",
            "입력 변형률 엄격 증가 여부",
            float(strain_strict),
            "1",
        ),
        Scalar(
            "terminal_domain_progress_basis_code",
            "진행축 코드",
            {"ordinal": 0.0, "strain": 1.0, "time": 2.0}[basis],
            "1",
        ),
        Scalar(
            "terminal_domain_v2_end_reason_code",
            "모델 구간 끝 선택 사유 코드",
            reason_code,
            "1",
        ),
        Scalar(
            "terminal_domain_v2_end_strain_bound", "설정한 끝 공칭변형률", float(bound), "1"
        ),
        Scalar(
            "terminal_domain_v2_loss_candidate_index",
            "지원된 급락 후보 유지 행",
            float(loss_end) if loss_end is not None else -1.0,
            "1",
        ),
    )
    if not all(np.isfinite(scalar.value) for scalar in scalar_values):
        raise ProcessingError("말단 구간 진단값이 유한하지 않습니다.")
    return StepResult(frame=selected, notes=tuple(notes), scalars=scalar_values)
