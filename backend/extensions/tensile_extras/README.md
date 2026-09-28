# tensile_extras

## `tensile.terminal_domain` v2

이 확장은 원본 `Frame`의 연속 prefix를 모델 입력 범위로 고르는 처리 단계다. 등록
순서는 15이며, 공칭 응력·변형률 변환(order 10) 뒤, 정렬·중복 정리(order 20) 앞이다.
원래 행의 순서와 모든 열을 그대로 보존하고, 보간하거나 응력을 바꾸지 않는다.
시간 진행축은 선택하지 않아도 된다. 기본 `time` 열이 있고 초 단위로 유효하면 자동으로
사용하며, 없거나 유효하지 않으면 변형률 또는 행 순서로 대체하고 이유를 기록한다.

새 기본 정책 `terminal_loss_auto_v2`는 **공칭변형률 0.50 (50%) 상한**과 지원되는
급락 탐지를 함께 쓴다. 첫 공칭변형률이 0.50보다 큰 행 바로 전까지가 상한 prefix다.
경계와 같은 행은 포함한다. 곡선에 정확히 0.50인 점이 없으면 상한 안의 마지막 관측
행을 쓰며, 그 사이를 보간하지 않는다. 첫 초과 행 뒤에서 변형률이 되돌아와도 나중
행을 다시 포함하지 않는다.

자동 급락 탐지는 상한 prefix에서만 끝 후보를 고른다. 지원되는 급락 경계가 상한보다
앞이면 그 경계를 쓰고, 없거나 뒤에 있으면 상한을 쓴다. 늦은 후보는 v1의 마지막
진행축 10% 규칙(지지, 연결, 복구, 큰 간격, 안정된 하중 suffix)을 그대로 사용한다.
그보다 이른 후보는 시간 또는 엄격히 증가하는 변형률 진행축이 있을 때만 살핀다. 후보
직전 최대 5행의 중앙값 `L`은 양수여야 하고, 지원 행은 최소 3개이며 후보 응력은
`L`의 10% 안에 있어야 한다. 첫 하강은 최소 `0.10 * L`이고, 최대 3개의 비증가 연결
행 안에 응력이 `0.20 * L`보다 **작아야** 한다. 저하중 연결 끝부터 원자료 전체 끝까지
모든 응력이 `0.20 * L` 미만으로 남아야 하며, v1 손실 중점보다 큰 회복도 없어야 한다.
정확히 `0.20 * L`인 평탄부는 보존한다. 후보 지지 구간과 손실 연결의 큰 샘플링 간격은
자동 결정을 보류한다. 큰 간격은 직전 양의 진행 간격 중앙값의 10배 초과이면서 전체
진행 폭의 1% 초과일 때다.

이 자동 판정은 **모델 범위를 보수적으로 고르는 규칙**이며 물리적 파단이나 네킹을
판정하지 않는다. 정해진 회복·지속 하중 기준을 충족하면 해당 급락 후보를 선택하지
않는다. 공칭변형률 0.50 상한은 별도로 적용한다. 행 순서만 진행축으로 쓸 때 조기 탐지는 생략하고 그
이유를 기록한다. 회복 확인은 상한 뒤의 원자료까지 포함한다.

`manual_end_strain_v1`은 사용자가 양의 유한 끝 공칭변형률을 지정한다. 기본은 0.50이며
0.80처럼 더 큰 값을 줄 수 있다. 경계와 같은 행까지 원래 순서의 연속 prefix를 유지하고,
처음 경계를 넘은 행부터 뒤는 모두 제외한다. 이전 `manual_end_v1`의 0부터 세는 포함
행 옵션은 그대로 동작한다.

## 이전 정책과 저장 recipe

`terminal_loss_auto_v1`과 `manual_end_v1`은 이전 정책으로 선택 목록에 남아 있다. 이
정책을 명시한 저장 recipe는 같은 수치, notes, 거절 경계로 다시 실행된다. 이전 자동
정책은 진행축 마지막 10% 안에서만 후보를 찾고, 이전 수동 정책은 `end_index`를 받는다.
선택 목록의 이름에 “이전 정책”이 표시된다.

옵션에서 `policy`를 생략한 저장 recipe는 catalog 기본값을 사용한다. 따라서 과거에
정책을 생략했던 recipe는 이제 `terminal_loss_auto_v2`로 실행된다. 이전 결과를 재현해야
하면 recipe에 `terminal_loss_auto_v1`을 명시한다.

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "terminal_loss_auto_v2"}}
```

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "manual_end_strain_v1", "end_strain": 0.8}}
```

이전 index recipe도 재생할 수 있다.

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "manual_end_v1", "end_index": 120}}
```

일반 recipe에서는 공칭 변환 뒤, 기존 정렬·중복 정리와 E/proof 단계 앞에 선택형으로
추가한다. 등록은 기본 recipe에 단계를 자동 삽입하지 않는다. `ParamSpec` 선언이 기존
프론트 자동 폼을 구성한다. 프론트 표준 연동과 단계 활성화는 플랫폼 담당자의 별도
handoff 작업이다.

## v1 경계 보존

이전 자동 정책의 후보는 최소 3점 지지가 있고 후보 응력이 지지 구간 중앙값 `L`의
10% 안에 있어야 한다. 다음 행에서 20% 이상 급락하거나, 첫 10% 급락 뒤 2~3행의
비증가 연결이 전체 20% 이상 손실에 이르면 후보가 된다. 연결 끝 `j` 또는 그 뒤의 값이
`y[i] * (1 - f) + y[j] * f` (`f = 0.50`)보다 **클 때** 후보를 폐기한다. 정확히 같은
복구값은 허용된다. 이는 이전 recipe의 엄격한 `greater than` 경계다.

유효한 초 단위 `time`이 있으면 그것을, 아니면 엄격히 증가하는 변형률을, 그것도
아니면 원래 행 순서를 진행축으로 쓴다. 시간 단위나 값이 잘못되면 대체 이유를 기록한다.
이전 정책의 큰 간격 보류와 안정된 저하중 suffix 보류도 그대로 유지한다.

## 진단과 범위

기존 `terminal_domain_*` scalar는 계속 제공한다. v2는 선택 사유, 설정한 공칭변형률
경계, 지원된 급락 후보 행을 추가로 기록한다. 끝 행, 끝 변형률, 제외 행 수는 실제로
선택한 prefix를 나타낸다. 원본 `Frame`은 바뀌지 않는다.

절단·평탄화·단조 보정과 내부 급락 후 회복 곡선 연결은 이 변경 범위가 아니며 별도
후속 단계다. 이 처리는 전체 탄소성 계산이나 물성카드 검증 완료를 뜻하지 않는다.

## 근거와 추적

이전 정책의 기준은 2026-09-21 재평가에서 동결한 R13 자료
`followup/13-automatic-model-domain/TERMINAL-IMPLEMENTATION.md`다. 그 자료의 엄격한
복구 경계(“`No value at j or later may recover to greater than y[i] minus half the
detected loss.`”)를 코드에 자립적으로 적었다.

이 작업은 [fork #5](https://github.com/pikachu444/MatNexus/issues/5) 「항복 뒤 하강
처리 오류와 절단·평탄화·단조 보정 정책 검토」의 말단 급락 부분과
[검증 추적 #29](https://github.com/pikachu444/MatNexus/issues/29)에 연결된다. 기존 이슈를
닫는 변경이 아니다.

## 플랫폼 handoff

플랫폼 담당자는 `python scripts/describe_extension_api.py`를 실행해 생성 문서
`docs/확장-계약.md`를 갱신하고, v2 기본 정책과 파라미터를 표준 프론트에 연결해야 한다.
프론트 `processing/flow.ts`의 `blockers`와 `tests/unit/test_processing_flow.py::TestWalkable`은
`role="column"`에서 `required=False`를 무시한다. 원자료에 `time` 열이 없으면 backend의
변형률·행 순서 fallback 전에 UI와 flow 테스트가 막힌다. 플랫폼 단계에서 선택형 열을
허용하도록 두 flow 검사를 고쳐야 한다.
현재 pytest 설정의 `testpaths = ["tests"]`는 이 확장 폴더의 focused 시험을 기본 CI에서
수집하지 않으며, `_tests` 경로도 이 설정에 포함되지 않는다. focused 시험은 extension loader가 읽지 않도록
`backend/extensions/_tests/tensile_extras/` 아래에 둔다. 두 상위 디렉터리에는
`__init__.py`를 두지 않는다. backend에서 다음처럼 실행한다.

```powershell
python -m pytest -o addopts= -n 0 `
  extensions/_tests/tensile_extras/test_terminal_domain.py `
  extensions/_tests/tensile_extras/test_terminal_domain_v2.py
```

플랫폼 담당자는 두 시험 파일을 `backend/tests/unit/test_ext_tensile_terminal_domain.py`로
옮기거나 연결해 CI 회귀 범위에 넣는다. extension은 `matcore.extensions.load()` 경로로
로드한다.

## v2 실제 시험 5개

새 v2 상한 정책을 실제 인장 시험 5개에 적용한 결과는
[v2 보고서](reports/terminal_loss_v2/report.md)에서 확인할 수 있다.

## v1 역사적 시험 5개 비교

실제 인장 시험 5개의 보고서와 PDF는 이전 v1 자동 recipe 및 그 별도 후속 개발본을
비교한다. 이 자료는 v2의 공칭변형률 0.50 상한 결과가 아니다. PC1·PC5의 자동 근사와
BT3의 취득 순서 검증도 해당 비교 자료의 별도 후속 개발 결과다. 기존 보고서 파일은
이 변경에서 수정하지 않는다.

[한국어 보고서](reports/five_case_processing/report.md) ·
[4쪽 PDF](reports/five_case_processing/pdf/tensile-processing-five-cases.pdf)
