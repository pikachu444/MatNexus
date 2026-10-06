# tensile_extras

## `tensile.terminal_domain` v2

처리 순서는 `F-d`와 `L0/A0` 입력 → 공칭 응력·변형률 계산(order 10) → 끝단 처리(order 15)
→ 정렬·중복 정리(order 20) → 인장강도 등 후속 계산이다. 이 단계는 원본 데이터의 첫 행부터
끊기지 않고 이어지는 행만 골라 다음 계산에 전달한다.
원래 행 순서와 모든 열을 그대로 보존하며, 값을 보간하거나 응력을 바꾸지 않는다.
시간 열은 선택 사항이다. 기본 `time` 열이 있고 초 단위로 유효하면 사용한다. 사용할 수
없으면 계속 증가하는 변형률을 확인하고, 그것도 쓸 수 없으면 원래 행 순서를 사용하며
이유를 기록한다.

새 기본 정책 `terminal_loss_auto_v2`는 **공칭변형률 제한 0.50 (50%)**과 급락 감지를
함께 적용한다. 공칭변형률은 변형 전 시편 치수를 기준으로 계산한 변형률이다. 자동 정책의
50%는 고정 제한이며 보편적인 파단 기준은 아니다. 변형률이 0.50을 처음 넘는 행부터 뒤를
제외하고, 경계와 같은 행은 포함한다. 데이터에 정확히 0.50인 점이 없으면 제한 안의 마지막
관측 행을 사용하며, 그 사이를 보간하지 않는다. 이후 변형률이 낮아져도 제외한 행을 다시
포함하지 않는다.

자동 급락 감지는 변형률 제한 안에서 끝으로 쓸 위치를 찾는다. 정해진 기준을 충족한 급락이
제한보다 먼저 나오면 급락 직전 행을 끝으로 선택하고, 급락이 없거나 제한 뒤에 있으면 제한을 적용한다.
시험 진행의 마지막 10%에 있는 급락은 이전 자동 정책과 같은 하중 지지·연결·회복 기준으로
확인한다. 그보다 앞선 급락은 실제 시간 또는 엄격히 증가하는 변형률을 사용할 수 있을 때만
확인한다. 급락 직전 최대 5개 행의 하중 중앙값 `L`은 양수여야 하고, 확인에 필요한 행은 최소
3개이며, 급락 후보 행의 응력은 `L`의 10% 안에 있어야 한다. 첫 하강은 최소 `0.10 * L`이고,
최대 3개의 연속 비증가 행 안에 응력이 `0.20 * L`보다 **작아야** 한다. 급락 뒤 원본 데이터
끝까지 응력이 `0.20 * L` 미만으로 유지되어야 하며, 이전 정책의 절반 손실 회복 기준을 넘는
회복이 없어야 한다. 정확히 `0.20 * L`인 평탄부는 보존한다. 급락 전후를 확인하는 구간에 큰
샘플링 간격이 있으면 자동 판단을 보류한다. 큰 간격은 직전 양의 시간·변형률 간격 중앙값의
10배를 넘고 전체 시험 구간의 1%보다 클 때다.

이 규칙은 **계산에 사용할 데이터 범위를 보수적으로 정하는 방법**이며 물리적 파단이나 네킹을
판정하지 않는다. 정해진 회복 기준을 충족하면 해당 급락 위치를 종료점으로 선택하지 않는다.
변형률 제한은 별도로 적용한다. 하중을 유지하며 완만히 연화하는 구간도 급락 종료점으로
선택하지 않는다. 행 순서만 사용할 때는 실제 시간·변형률 간격을 알 수 없어 중간 급락
감지를 생략하고 이유를 기록한다. 회복 여부는 제한 뒤를 포함한 원본 데이터 전체에서 확인한다.

`manual_end_strain_v1`은 사용자가 양의 유한 공칭변형률 제한을 지정한다. 기본값은 0.50이며
0.50은 50%, 0.80은 80%다. 0.80은 예시이며 기본값이 아니다. 제한과 같은 행까지 포함하고,
처음 제한을 넘은 행부터 뒤는 모두 제외한다. 수동 방식에는 자동 급락 감지를 적용하지 않는다.

## 이전 정책과 저장 recipe

화면에는 `terminal_loss_auto_v2`와 `manual_end_strain_v1` 두 방식만 표시한다.
`terminal_loss_auto_v1`과 `manual_end_v1`은 화면 선택지에서 제거했지만, backend dispatcher는
명시된 이전 저장 recipe를 같은 수치와 제외 경계로 다시 실행하도록 유지한다. 이전 자동 방식은
시험 진행 마지막 10% 안에서만 급락을 찾고, 이전 수동 방식은 `end_index`를 받는다.

옵션에서 `policy`를 생략한 저장 recipe는 catalog 기본값을 사용한다. 따라서 과거에
정책을 생략했던 recipe는 이제 `terminal_loss_auto_v2`로 실행된다. 이전 결과를 재현해야
하면 recipe에 `terminal_loss_auto_v1`을 명시한다.

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "terminal_loss_auto_v2"}}
```

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "manual_end_strain_v1", "end_strain": 0.8}}
```

0.80은 가능한 수동 입력의 예시이며 기본값은 0.50이다. 이전 자동 recipe도 재생할 수 있다.

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "terminal_loss_auto_v1"}}
```

이전 행 번호 recipe도 재생할 수 있다.

```json
{"plugin": "tensile.terminal_domain", "options": {"policy": "manual_end_v1", "end_index": 120}}
```

일반 recipe에서는 F-d와 L0/A0 입력 뒤, 공칭 응력·변형률 계산 다음, 정렬·중복 정리와
인장강도 등 후속 계산 앞에 선택형으로
추가한다. 등록만으로 기본 recipe에 자동 삽입되지는 않는다. 기존 `ParamSpec` 선언이
프론트 입력 폼을 구성한다. 표준 프론트 연결과 단계 활성화는 플랫폼 담당자의 별도 작업이다.

## v1 경계 보존

이전 자동 정책의 후보는 최소 3점 지지가 있고 후보 응력이 지지 구간 중앙값 `L`의
10% 안에 있어야 한다. 다음 행에서 20% 이상 급락하거나, 첫 10% 급락 뒤 2~3행의
비증가 연결이 전체 20% 이상 손실에 이르면 후보가 된다. 연결 끝 `j` 또는 그 뒤의 값이
`y[i] * (1 - f) + y[j] * f` (`f = 0.50`)보다 **클 때** 후보를 폐기한다. 정확히 같은
복구값은 허용된다. 이는 이전 recipe의 엄격한 `greater than` 경계다.

유효한 초 단위 `time`이 있으면 그것을, 아니면 엄격히 증가하는 변형률을, 그것도
아니면 원래 행 순서를 시험 순서 확인에 사용한다. 시간 단위나 값이 잘못되면 대체 이유를
기록한다. 이전 정책의 큰 간격 보류와 안정된 저하중 구간 보류도 그대로 유지한다.

## 진단과 범위

기존 `terminal_domain_*` 진단값은 계속 제공한다. 새 정책은 선택 이유, 적용한 공칭변형률
제한, 급락 직전 행 번호를 추가로 기록한다. 절단 위치, 종료점 변형률, 제외 데이터 수는
실제로 선택한 행을 나타낸다. 원본 `Frame`은 바뀌지 않는다.

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
`role="column"`에서 `required=False`를 무시한다. 입력 안내와 단계 계약 검사는 선택 시간 열을
필수로 간주하지만, 현재 미리보기 실행 자체를 차단하지는 않으며 서버 요청은 backend에 전달된다.
시간 열이 없거나 사용할 수 없으면 backend가 변형률 또는 행 순서를 사용해 실행한다.
플랫폼 단계에서 이 안내와 계약 검사가 선택형 열을 반영하도록 고쳐야 한다.
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

새 자동 50% 제한을 실제 인장 시험 5개에 적용한 결과는
[v2 보고서](reports/terminal_loss_v2/report.md)에서 확인할 수 있다.

## v1 역사적 시험 5개 비교

실제 인장 시험 5개의 보고서와 PDF는 이전 v1 자동 recipe 및 그 별도 후속 개발본을
비교한다. 이 자료는 새 공칭변형률 0.50 제한 결과가 아니다. PC1·PC5의 자동 근사와
BT3의 취득 순서 검증도 해당 비교 자료의 별도 후속 개발 결과다. 기존 보고서 파일은
이 변경에서 수정하지 않는다.

[한국어 보고서](reports/five_case_processing/report.md) ·
[4쪽 PDF](reports/five_case_processing/pdf/tensile-processing-five-cases.pdf)
