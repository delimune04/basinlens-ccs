# NVIDIA integration plan

공식 자료 확인일: 2026-10-03. 아래 기술은 **연결 후보와 설계 근거**이며,
현재 BasinLens에 설치·학습·실행된 기능으로 표시하지 않는다.

## 1. Simulation Workflow Assistant: 실행을 둘러싼 자동화

NVIDIA의 2026-04-28 글과 공개 예제는 시뮬레이터 연동, 실행 관리,
결과 정리와 반복 실험을 다룬다. 글의 예제는 OPM Flow와 Brugge 모델을
사용한다. 이것만 연결해서 CCS 지질 모델이나 안전성 검증이 완성되지는 않는다.

- [공식 기술 글](https://developer.nvidia.com/blog/24-7-simulation-loops-how-agentic-ai-keeps-subsurface-engineering-moving/)
- [실제 공개 코드와 요구사항](https://github.com/NVIDIA/GenerativeAIExamples/tree/main/industries/energy/simulation-workflow-agent)

우리의 적용: 기준 시뮬레이션 실행 기록 → 제한된 parameter sweep →
실패 감지와 복구 → 근거에 연결된 결과 설명. 처음에는 결정론적 runner를
만들고, 자연어 planner는 검증된 도구만 호출하도록 붙인다. LLM은 물성·압력
제약·관측값을 임의로 수정하지 못한다. 재시도도 변경 전후를 별도 case로 남긴다.

확인한 README는 API 기반 quick try에는 GPU가 필요 없고, full RAG 구성에는
48GB 이상의 GPU 메모리를 요구한다고 명시한다. 8GB급 데스크톱에서 full stack
실행을 전제로 잡지 않는다. API 비용·비밀자료 전송·모델 이용 조건은 해당 기능을
실제로 도입할 때 정한다. 현재 이 프로젝트는 API를 호출하지 않는다.

## 2. PhysicsNeMo: 검증된 물리 계산의 surrogate

Shell–NVIDIA 사례는 CO₂ plume·포화도·압력을 학습하는 FNO 기반 방법과
업무에 맞는 오차 평가를 소개한다. 발표된 가속 배수는 해당 학습·시험 조건의
결과이며 우리의 성능 약속으로 사용하지 않는다.

- [Shell–NVIDIA 공식 사례](https://developer.nvidia.com/blog/spotlight-shell-accelerates-co2-storage-modeling-100000x-using-nvidia-physicsnemo/)
- [PhysicsNeMo 저장소](https://github.com/NVIDIA/physicsnemo)
- [확인한 CCUS 예제](https://github.com/NVIDIA/physicsnemo-sym/tree/0c5f18c31d03d46ec0cc3ef4ccbf761a956dd38c/examples/reservoir_simulation/CCUS)

조회한 소스 위치의 지문: `physicsnemo` main
`b45a5c810c741e6b41f8515be24c51121f8fc21f`, `physicsnemo-sym` main
`0c5f18c31d03d46ec0cc3ef4ccbf761a956dd38c`.
이는 소스 위치 확인이며 호환 환경 또는 실행 검증 결과가 아니다.
옛 글에 등장하는 `physicsnemo-launch` main tree는 이번 조회에서 404였으므로
그 경로를 바로 설치 가능한 자산으로 기재하지 않는다.

우리의 적용 순서:

1. CPU에서 CO₂ 기준 solver를 재현하고, 작은 synthetic case의 오류를 점검한다.
2. 지질 realization별로 분리한 학습·검증·독립 시험 자료를 만든다.
3. 작고 단순한 surrogate와 오차 기준을 먼저 설정한다.
4. 동일 조건에서 PhysicsNeMo 모델의 정확도·시간·GPU 메모리·총비용을 측정한다.
5. 학습 범위 밖 입력과 위험한 과소 압력 예측을 감지하고 기준 solver로 돌린다.

학습에 쓴 한 지질 realization의 인접 시점·격자가 시험 세트로 새지 않도록 한다.
정확도 기준에는 최대 압력과 주입정 주변 오차, CO₂ 질량수지, plume 위치가
포함된다. FNO/PINO를 사용했다는 사실만으로 보존법칙을 만족한다고 가정하지 않는다.

## 3. Omniverse와 시각화

3D 지층·압력·plume을 검토하는 장기 선택지로 둔다. 첫 버전은 기존
Streamlit/Plotly와 표준 grid/array 결과로 검증 가능한 시각화를 만든다.
과학적 비교가 완성된 뒤 사용자의 작업에 도움이 되는 3D 검토 화면을 추가한다.

## 4. OPM과의 관계·사용 조건

물리 엔진 후보는 [OPM Flow](https://opm-project.org/)의 CCS 모드다.
[공식 매뉴얼](https://opm-project.org/?page_id=955)과
[공식 CO2STORE 사례](https://opm-project.org/wp-content/uploads/2023/09/CLIMIT_22092023_CO2STORE_Cintia-TNO.pdf)를
기준으로 실제 지원 keyword, 유체 모델, 결과 변수와 버전을 확인한다.
일반 black-oil 예제가 CO₂–brine 검증 사례를 대신하지 않는다.

확인한 NVIDIA assistant 하위 경로의 LICENSE는 Apache-2.0이다. 그대로 사용할
경우 코드·자산별 원본 고지와 의존 항목의 별도 조건을 함께 기록한다. 모델
가중치·API·외부 시뮬레이터·자료는 프로젝트 코드의 라이선스를 자동으로 따르지 않는다.
이번 초안에는 NVIDIA 소스 복사, 모델 가중치, 원시 현장 자료를 포함하지 않았다.

## 도입 판단표

| 후보 | 도입을 시작하는 조건 | 중단·보류 조건 |
|---|---|---|
| Assistant 구조 | 결정론적 실행·검증·비용 상한이 이미 작동 | 근거 없는 물성 수정, 반복 실패, 비용 상한 부재 |
| PhysicsNeMo surrogate | 독립 시험 세트와 기준 solver 결과 확보 | 적용 범위 밖, 핵심 오차 기준 실패, 기준 solver보다 총비용 불리 |
| 3D digital twin | 좌표·단위가 검증된 시간별 grid 결과 확보 | 시각적 설득력이 데이터·물리 검증을 대신함 |

각 도입 결정은 비교 표와 실패 결과를 남긴다. 공개 코드가 있다는 이유만으로
모든 구성요소를 동시에 프로젝트 의존성에 넣지 않는다.
