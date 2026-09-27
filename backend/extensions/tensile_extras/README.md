# tensile_extras

## `tensile.terminal_domain` v1

이 확장은 원본 `Frame`의 말단을 모델 입력용 prefix로 고르는 처리 단계다. v1 자동
정책은 진행축 마지막 10% 안의 후보만 보고, 후보 앞 최대 5점의 국소 하중 중앙값 `L`을
기준으로 한다. 후보는 최소 3점의 지지가 있고 `abs(y[i] - L) <= 0.10 * L`을
만족해야 하며, 다음 행의 20% 이상 급락 또는
첫 10% 급락 뒤 2~3행의 비증가 연결이 전체 20% 이상 손실에 이르는 경우만 인정한다.
가장 이른 후보를 유지하고 그 뒤를 제외한다. 수동 정책은 현재 입력 프레임의 0부터
세는 마지막 포함 행을 직접 받는다. 이 상수와 옵션은 `terminal_domain.py`의
`FIXED_OPTIONS`에 고정되어 저장 옵션 재현에도 그대로 사용한다.

연결의 마지막 저점이 `j`이고 후보 유지 행의 하중이 `y[i]`라면, `j` 또는 그 뒤의 값이
`y[i] * (1 - f) + y[j] * f` (`f = 0.50`)보다 **클 때** 후보를 폐기한다.
이는 검출한 손실의 절반을 회복하는 경계이며, 가중합 연산 순서도 보존한다.
정확히 같은 값은 허용되어
자를 수 있다. 이는 R13에서 고정한 엄격한 `greater than` 경계다.

## 보류와 범위

- 유효한 초 단위 `time`이 있으면 그것을, 아니면 엄격히 증가하는 변형률을, 그것도
  없으면 원래 행 순서를 진행축으로 쓴다. 시간 단위·값이 잘못되면 조용히 다른 단위로
  읽지 않고 대체 이유를 기록한다. 행 순서 fallback은 실제 간격을 증명하지 않는다.
- 후보 급락 연결에 큰 샘플링 간격이 있으면 `ambiguous_sampling_gap`으로 보류한다.
  큰 간격은 직전 최대 20개 양의 간격 중앙값의 **10배 초과**이면서 전체 진행 폭의
  **1% 초과**인 경우다. 실제 시간·변형률 간격을 모르는 행 순서 진행축에는 적용하지 않는다.
  후보 뒤에 남은 진행 폭이 **2% 초과**, suffix 하중 중앙값이 **`0.20 * L` 이상**,
  suffix 하중 범위가 **`0.10 * L` 이하**이면 안정된 저하 하중대로 보고
  `ambiguous_stable_low_suffix`로 보류한다.
  완만한 말단 하강은 자르지 않고 `gradual_tail_unresolved`로 남긴다.
- 이 단계는 지원되는 급격한 말단 하중 소실을 분리할 뿐이며, **파단(fracture) 검출기나
  물리적 파단 판정기가 아니다.** 완만한 하강, 의도된 하측 모델 구간, 파단 원인은
  별도 검토 대상이다. 이 변경 범위도 말단 급락 prefix 분리 기능으로 한정한다.

## 저장 recipe 예시

명시적으로 추가한 recipe에서 `engineering → terminal_domain → 기존 E/proof` 순서로
사용한다. 아래 치수와 탄성 구간은 예시이며 실제 시편 기록과 검토한 구간으로 정한다.
이 단계는 측정된 prefix만 고르고, 원본 프레임은 바꾸지 않는다. 뒤의 기존 E/proof
단계는 유지된 범위에서 자체 계산과 입력 검사를 수행한다.

```json
[
  {
    "plugin": "tensile.engineering",
    "options": {"gauge_length": 0.05, "area": 0.00001}
  },
  {
    "plugin": "tensile.terminal_domain",
    "options": {"policy": "terminal_loss_auto_v1"}
  },
  {
    "plugin": "tensile.elastic_modulus",
    "options": {
      "method": "linear_regression",
      "minimum_strain": 0.0005,
      "maximum_strain": 0.0025
    }
  },
  {
    "plugin": "tensile.proof_stress",
    "options": {"offset_strain": 0.002, "youngs_modulus": "@youngs_modulus"}
  }
]
```

수동 검토에서는 같은 위치에
`{"plugin": "tensile.terminal_domain", "options": {"policy": "manual_end_v1", "end_index": 120}}`
을 저장한다. `end_index`는 이 단계가 받은 현재 입력 프레임에서 0부터 세는 포함 끝 행이다.
등록만으로 기본 recipe에 들어가지는 않는다.

## 근거와 추적

규칙의 기준은 2026-09-21 재평가에서 동결한 R13 자료
`followup/13-automatic-model-domain/TERMINAL-IMPLEMENTATION.md`다. 그 자료의 엄격한
복구 경계(“`No value at j or later may recover to greater than y[i] minus half the
detected loss.`”)를 이 README와 코드에 자립적으로 적었다.

이 작업은 [fork #5](https://github.com/pikachu444/MatNexus/issues/5) 「항복 뒤 하강
처리 오류와 절단·평탄화·단조 보정 정책 검토」의 말단 급락 부분과
[검증 추적 #29](https://github.com/pikachu444/MatNexus/issues/29)에 연결된다. 기존 이슈를
닫는 변경이 아니며, 절단·평탄화·단조 보정과 전체 말단/파단 분류는 후속 범위다.

## 플랫폼 handoff

`tensile.terminal_domain` 등록과 `policy.help`가 추가되었으므로 플랫폼 담당자가
`python scripts/describe_extension_api.py`를 실행해 생성 문서
`docs/확장-계약.md`를 갱신해야 한다. 현재 pytest 설정은 `testpaths = ["tests"]`이므로
이 확장 폴더의 `test_terminal_domain.py`는 기본 CI에서 자동 수집되지 않는다.
플랫폼 담당자는 이 시험을 `backend/tests/unit/test_ext_tensile_terminal_domain.py`로
옮기고 확장 loader 설정을 연결해 기본 CI가 회귀 경계를 실행하도록 해야 한다.
확장 패키지의 `__init__.py`를 직접 import해 중복 등록하지 않도록
`matcore.extensions.load()` 경로로 등록해야 한다. 생성 문서와 플랫폼 시험 경로는
이 확장 소유 범위에서 고치지 않는다.
