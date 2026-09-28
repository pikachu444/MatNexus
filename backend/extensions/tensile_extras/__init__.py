"""인장 덧붙이기 — **처리 단계와 묶음을 확장 폴더에서 등록하는지 재는 자리.**

`ghosh_hardening` 이 적합식(①)을, `johnson_cook_static` 이 카드 블록을 확장 폴더에서
붙였다. 남은 창구가 둘이었다 — **처리 단계**(시험 하나: 곡선 → 스칼라)와 **묶음**(여러
시험 → 하나). 창구는 같은 `registry.register` 인데 확장에서 써 본 적이 없었다
(2026-09-13, [계획] 계산 확장 1단계). 이 폴더가 둘을 실제로 붙인다.

- `yield_ratio` — 항복비(항복강도 ÷ 인장강도). 앞 단계가 낸 값을 `@` 로 받는 단계.
- `temperature_family` — 온도별 인장 곡선을 묶어 **온도별 소성 표**와 온도 연화
  요약(기울기·Johnson-Cook m)을 낸다. 속도 가족과 같은 모양. 구성원은 파이썬
  수집기 없이 **선언**(`meta["members"]`)으로 모으고, 카드는 `card=` 로 선언한
  함수가 블록을 만든다(`/fitting/cards/from-group`). 블록과 Abaqus 덱은 `card.py`.

중심 코드는 한 줄도 안 고쳤다. 계산은 옆 파일에 있다.
"""

from __future__ import annotations

from matcore.registry import ParamSpec, Produced, register

from . import (  # noqa: F401  (card 는 import 만으로 블록·렌더러를 등록한다)
    card,
    ratio,
    temperature,
    terminal_domain,
    terminal_domain_v2,
)

register(
    id="tensile.yield_ratio",
    kind="processing",
    label="항복비",
    applies_to=("tensile",),
    # 키만으로 거르지 않는다 — 변위·하중을 재는 시험이면 강도가 나오고 항복비가 선다.
    requires_channels=(("displacement",), ("force",)),
    params=(
        ParamSpec(
            name="proof_stress",
            label="항복강도",
            type="float",
            unit="Pa",
            default="@proof_stress",
            required=True,
            help="항복강도 단계가 낸 값. 손으로 적으면 항복 정의를 바꿔도 여기는 옛 값이 "
            "남는다.",
        ),
        ParamSpec(
            name="tensile_strength",
            label="인장강도",
            type="float",
            unit="Pa",
            default="@tensile_strength",
            required=True,
            help="인장강도 단계가 낸 값.",
        ),
    ),
    makes_values=(
        Produced(
            key="yield_ratio",
            label="항복비",
            si_unit="1",
            help="항복강도 ÷ 인장강도. 강구조 규격이 상한(예: 0.85)을 둔다.",
        ),
    ),
    # 강도(70)·항복강도(60) 뒤, 소성 곡선(90) 앞 — 재샘플(95)이 맨 끝인 것은 규칙이다.
    order=85,
    version="1",
)(ratio.yield_ratio)

register(
    id="tensile.terminal_domain",
    kind="processing",
    label="끝단 처리",
    applies_to=("tensile",),
    requires_channels=(("displacement",), ("force",)),
    params=(
        ParamSpec(
            name="policy",
            label="처리 방식",
            type="choice",
            choices=(
                terminal_domain_v2.AUTO_POLICY,
                terminal_domain_v2.MANUAL_STRAIN_POLICY,
                terminal_domain.AUTO_POLICY,
                terminal_domain.MANUAL_POLICY,
            ),
            default=terminal_domain_v2.AUTO_POLICY,
            choice_labels={
                terminal_domain_v2.AUTO_POLICY: "자동 (급락 감지·변형률 제한)",
                terminal_domain_v2.MANUAL_STRAIN_POLICY: "수동 (변형률 상한 지정)",
                terminal_domain.AUTO_POLICY: "자동 (기존 급락 기준, 이전 정책)",
                terminal_domain.MANUAL_POLICY: "수동 (끝 행 번호 지정, 이전 정책)",
            },
            choice_help={
                terminal_domain_v2.AUTO_POLICY: (
                    "공칭변형률 0.50 (50%)를 고정 상한으로 둡니다. "
                    "급락 뒤 하중이 낮게 이어지고 "
                    "이전 손실의 절반을 넘게 회복하지 않아야 급락 직전 행을 끝으로 씁니다. "
                    "회복 기준을 넘으면 그 급락 지점은 선택하지 않습니다. "
                    "50%는 보편적인 파단 기준이 아닙니다."
                ),
                terminal_domain_v2.MANUAL_STRAIN_POLICY: (
                    "실험 치수로 계산한 공칭변형률의 상한을 지정합니다. 0.50은 50%, "
                    "0.80은 80%입니다. 상한과 같은 행은 포함하고 처음 상한을 넘은 행부터 "
                    "뒤는 제외하며, 보간하지 않습니다."
                ),
                terminal_domain.AUTO_POLICY: (
                    "저장된 이전 자동 recipe 재실행용입니다. 시험 순서의 마지막 10%에서 "
                    "기존 급락 기준을 적용합니다."
                ),
                terminal_domain.MANUAL_POLICY: (
                    "저장된 이전 수동 recipe 재실행용입니다. 현재 입력 데이터에서 0부터 세는 "
                    "끝 행 번호를 지정합니다."
                ),
            },
            help=(
                "자동은 공칭변형률 0.50 (50%)를 고정 상한으로 두고 "
                "급락 뒤 하중이 낮게 이어지는지, "
                "이전 손실의 절반을 넘게 회복하는지 확인합니다. "
                "수동은 입력한 공칭변형률 상한을 "
                "사용합니다. 50%는 보편적인 파단 기준이 아닙니다. 이전 정책은 저장 recipe "
                "재실행용입니다."
            ),
        ),
        ParamSpec(
            name="end_index",
            label="끝 행 번호",
            type="int",
            required=True,
            when={"policy": (terminal_domain.MANUAL_POLICY,)},
            help=(
                "이전 수동 정책에서만 사용합니다. 현재 입력 데이터에서 "
                "0부터 세는 행 번호입니다. "
                "해당 행까지 포함하고 그 뒤는 모두 제외합니다."
            ),
        ),
        ParamSpec(
            name="end_strain",
            label="변형률 상한",
            type="float",
            unit="1",
            dimension="strain",
            default=terminal_domain_v2.DEFAULT_END_STRAIN,
            required=True,
            when={"policy": (terminal_domain_v2.MANUAL_STRAIN_POLICY,)},
            help=(
                "실험 치수로 계산한 공칭변형률의 상한입니다. 0.50은 50%, 0.80은 80%입니다. "
                "상한과 같은 행은 포함하고, 처음 상한을 넘은 행부터 뒤는 모두 제외합니다. "
                "사이의 값은 보간하지 않습니다."
            ),
        ),
        ParamSpec(
            name="strain",
            label="변형률 열",
            type="str",
            role="column",
            default=terminal_domain.DEFAULT_STRAIN,
            unit="1",
            dimension="strain",
        ),
        ParamSpec(
            name="stress",
            label="응력 열",
            type="str",
            role="column",
            default=terminal_domain.DEFAULT_STRESS,
            unit="Pa",
        ),
        ParamSpec(
            name="time",
            label="시간 열",
            type="str",
            role="column",
            default=terminal_domain.DEFAULT_TIME,
            required=False,
            unit="s",
            help=(
                "기본 'time' 열이 있으면 초 단위인지 확인해 사용합니다. 선택한 열이 없거나 "
                "값 또는 단위가 유효하지 않으면 변형률 또는 행 순서로 대체하고 "
                "이유를 기록합니다."
            ),
        ),
    ),
    makes_values=(
        Produced(
            key="terminal_domain_end_index",
            label="절단 위치 (행 번호)",
            si_unit="1",
            help=(
                "결과에 포함한 마지막 행 번호입니다. 해당 행도 포함하며, "
                "행 번호는 0부터 시작합니다."
            ),
        ),
        Produced(
            key="terminal_domain_end_strain",
            label="종료점 변형률",
            si_unit="1",
            help="결과에 포함한 마지막 행의 공칭변형률입니다.",
        ),
        Produced(
            key="terminal_domain_removed_points",
            label="제외한 데이터 수",
            si_unit="1",
            help="현재 입력 데이터에서 제외한 행 수입니다.",
        ),
        Produced(key="terminal_domain_input_points", label="입력 데이터 수", si_unit="1"),
        Produced(
            key="terminal_domain_input_end_load",
            label="처리 전 마지막 응력",
            si_unit="Pa",
        ),
        Produced(
            key="terminal_domain_decision_code",
            label="끝단 처리 결과 코드",
            si_unit="1",
            help=(
                "0은 제외 없음, 1은 자동 급락 제외, 2는 수동 끝 지정, "
                "3은 자동 변형률 상한입니다."
            ),
        ),
        Produced(
            key="terminal_domain_strain_strict",
            label="변형률의 원래 순서 증가 여부",
            si_unit="1",
        ),
        Produced(
            key="terminal_domain_progress_basis_code",
            label="시험 순서 확인 기준 코드",
            si_unit="1",
            help=(
                "0은 데이터 행 순서, 1은 변형률, 2는 초 단위 시간입니다. "
                "시간 열이나 변형률을 사용할 수 "
                "없었던 이유는 단계 설명에 기록됩니다."
            ),
        ),
        Produced(
            key="terminal_domain_v2_end_reason_code",
            label="끝 위치를 정한 이유 코드",
            si_unit="1",
            help="0은 제외 없음, 1은 급락 기준 적용, 2는 자동 상한, 3은 수동 상한입니다.",
        ),
        Produced(
            key="terminal_domain_v2_end_strain_bound",
            label="적용한 변형률 상한",
            si_unit="1",
            help="자동은 고정 0.50, 수동은 입력한 상한입니다.",
        ),
        Produced(
            key="terminal_domain_v2_loss_candidate_index",
            label="급락 직전 행 번호",
            si_unit="1",
            help=(
                "급락 기준을 적용했을 때 제외 시작 행 바로 전의 0부터 세는 행 번호입니다. "
                "급락을 적용하지 않으면 -1입니다."
            ),
        ),
    ),
    order=15,
    version="2",
)(terminal_domain_v2.terminal_domain)
register(
    id="tensile.temperature_family",
    kind="grouping",
    label="온도별 소성 곡선",
    applies_to=("tensile",),
    requires_channels=(("displacement",), ("force",)),
    params=(
        ParamSpec(
            name="bin_kelvin",
            label="같은 온도로 볼 폭",
            type="float",
            unit="K",
            default=5.0,
            help=(
                "온도가 이 폭 안에서 다르면 같은 온도로 묶음. 5 면 296 과 299 는 한 묶음. "
                "장비가 목표 온도를 정확히 재현하지 못하므로 0 이면 시편마다 따로 섬."
            ),
        ),
        ParamSpec(
            name="levels",
            label="응력비를 읽을 변형률",
            type="str",
            default=temperature.DEFAULT_LEVELS,
            dimension="strain",
            help=(
                "이 진소성변형률들에서 기준 온도 대비 응력비를 읽음. 쉼표로 구분. "
                "첫 값에서 연화 기울기(dσ/dT)도 냄."
            ),
        ),
        ParamSpec(
            name="model",
            label="온도 연화 식",
            type="choice",
            choices=temperature.MODELS,
            default="none",
            choice_labels={"none": "식 없이 표만", "johnson_cook": "Johnson-Cook (m 만)"},
            choice_help={
                "none": "온도별 표만 산출. 솔버가 표를 그대로 받으면 충분.",
                "johnson_cook": (
                    "σ/σ₀ = 1 - T*^m, T* = (T-T₀)/(T_melt-T₀). 기준 온도 T₀ 는 가장 낮은 "
                    "묶음, 녹는점은 아래 칸. 응력이 안 내린 온도는 못 넣음."
                ),
            },
            help="온도별 표에 더해 응력비를 식으로 요약할지 여부.",
        ),
        ParamSpec(
            name="melt_temperature",
            label="녹는점",
            type="float",
            unit="K",
            default=0.0,
            help=(
                "Johnson-Cook 을 고를 때만. 기준 온도보다 커야 함"
                "(강 ≈ 1,800 K, 알루미늄 ≈ 930 K)."
            ),
        ),
    ),
    makes_values=(
        Produced(key="temperature_count", label="온도 묶음 수", si_unit="1"),
        Produced(key="reference_temperature", label="기준 온도", si_unit="K"),
        Produced(key="temperature_min", label="가장 낮은 온도", si_unit="K"),
        Produced(key="temperature_max", label="가장 높은 온도", si_unit="K"),
        Produced(
            key="softening_slope",
            label="온도 연화 기울기",
            si_unit="Pa/K",
            help="첫 변형률에서 읽은 응력의 온도에 대한 기울기(최소제곱). 음수면 연화.",
        ),
        Produced(key="softening_r_squared", label="기울기의 R²", si_unit="1"),
        Produced(key="jc_m", label="Johnson-Cook m", si_unit="1"),
        Produced(key="model_r_squared", label="식의 R²", si_unit="1"),
    ),
    # **구성원을 모으는 법을 선언한다.** 채택된 결과의 두 열과 시험 조건의 온도.
    # 파이썬 수집기가 없어도 grouping 이 이 선언을 읽는다(`app/modules/grouping`).
    # `register` 의 남는 키워드는 `Plugin.meta` 로 간다.
    members={
        "from": "adopted_result",
        "columns": [temperature.PLASTIC_STRAIN, temperature.TRUE_STRESS],
        "conditions": [temperature.TEMPERATURE],
    },
    # **카드를 만드는 법도 선언한다.** 묶음 결과(값·상세·경고)를 블록으로 바꾸는
    # 함수 — 재료·탄성·계보는 중심의 공용 길(`/fitting/cards/from-group`)이 맡는다.
    card=temperature.card_blocks,
    order=25,
    version="2",
)(temperature.temperature_family)
