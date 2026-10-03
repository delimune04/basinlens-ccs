# Development plan

설계 기준일: 2026-10-03. 수능 및 남은 시험 종료 후 실제 작업 가능한 날부터
단계를 계산한다. 아래 작업량은 집중 개발 기준의 추정이며 완료일 약속이 아니다.
한 번에 한 대표 과제를 진행하고, 단계 통과 근거가 없으면 다음 기능을 늘리지 않는다.

## 지금 완료한 준비

- [x] 기존 v0.1 저장소와 scientific scope 확인
- [x] 연구·실무 목표, 구조, NVIDIA 적용과 검증 계획 작성
- [x] v0.2 실행 묶음·보고서·해시·환경 기록 및 검증 명령 구현
- [x] 기존 계산값 회귀 확인과 17개 테스트
- [x] Claude Code/Codex가 읽을 지침과 인계 문서 작성
- [ ] 실물 자료 기반 scientific validation
- [ ] 현업 사용성 검토 또는 industry pilot

## 단계별 완성 상태

| 단계 | 완료 결과 | 통과 기준 |
|---|---|---|
| 1. 데이터·재현성 | 단위·출처가 있는 case contract | 결측·NaN·잘못된 단위 차단; 재현 가능한 bundle |
| 2. 실제 참조 사례 | Sleipner asset register와 작은 QC 결과 | 자료의 권한·좌표·정의·파일 해시 확인 |
| 3. 물리 기준 엔진 | CO₂–brine baseline과 작은 ensemble | 질량·압력·수치 수렴성, 독립 benchmark 비교 |
| 4. 관측 비교 | 지진 QC·관측 경계·모델 비교 보고서 | 지질학적 설명과 비유일성·측정 불확실성 |
| 5. 가속과 자동화 | surrogate 비교, bounded job runner | 적용 범위·핵심 오차·총비용, 실패복구 |
| 6. 사용성·전달 | 기술보고서·demo·현업 pilot | 타인이 설치·재현하고 한 업무를 끝냄 |

## 다음 작업 단위

하나의 작업은 하나의 PR로 끝낸다. 의존 단계가 아직 미구현이면 인터페이스만
실행된 기능처럼 꾸미지 않고, 검증된 작은 vertical slice를 제출한다.

| 순서 | 작업 | 예상 집중 작업량 | 인수 기준 |
|---|---|---|---|
| [T1](https://github.com/delimune04/basinlens-ccs/issues/1) | 입력 식별자·범위·오류 전달 보강 | 1일 | NaN/공백 ID 차단, 문자열 ID 보존, 직접 생성 물성 범위, regression |
| [T2](https://github.com/delimune04/basinlens-ccs/issues/2) | 단위·출처를 포함한 case/evidence schema | 1–2일 | 버전 계약, synthetic 예시, 관측/가정/미확인 구분, legacy adapter |
| [T3](https://github.com/delimune04/basinlens-ccs/issues/3) | Sleipner asset register와 작은 QC | 1–2일 | 허용된 작은 asset, SHA·CRS·datum·라이선스·자료 부족 목록 |
| [T4](https://github.com/delimune04/basinlens-ccs/issues/4) | OPM adapter의 첫 CO₂ 사례 실행 | 1–2일 + 환경 준비 | 고정 버전, 명령·입력·로그, 실제 압력/질량 변수, 실패 보존 |
| [T5](https://github.com/delimune04/basinlens-ccs/issues/5) | CO₂ 사례의 독립 검증과 수렴 비교 | 1–2일 | no-injection·보존량·시간/격자 refinement 표 |
| [T6](https://github.com/delimune04/basinlens-ccs/issues/6) | 4D seismic subset QC·관측 비교 | 1–2일 + 자료 접근 | 시간/좌표/진폭 QC와 threshold 민감도; 포화도 변환 미검증 표시 |
| [T7](https://github.com/delimune04/basinlens-ccs/issues/7) | PhysicsNeMo feasibility와 독립 시험 설계 | 1–2일 + GPU 자원 | 요구 메모리 실측, 기준 정확도·비용 표, 학습 자료 누출 점검 |
| [T8](https://github.com/delimune04/basinlens-ccs/issues/8) | 제한된 sweep runner와 작업 기록 | 1–2일 | job/time 상한, 실패 상태, 재시도 변경 기록; 이후 planner 연결 |

T4 이후 일정은 물리·자료 문제가 확인되면 다시 추정한다. 대형 grid,
history matching, 다중 사용자 서비스, full RAG stack은 첫 iteration의 목표가 아니다.

## Claude Code ↔ Codex ↔ 프로젝트 소유자

프로젝트 소유자가 지질 가정·검증 질문·실험 해석을 선택하고 설명한다.
한 AI 도구가 작은 구현 PR을 작성하면 다른 도구가 식·단위·경계 조건·실패
처리와 테스트를 검토한다. 리뷰에서도 AI의 정답을 전제하지 않고 알려진
계산·benchmark·교수 자문으로 확인한다.

동시에 같은 브랜치를 편집하지 않는다. `AGENTS.md`와 `CLAUDE.md`를 읽고
원격 최신 상태를 가져온 뒤 한 issue를 선택한다. 세션 끝에는 변경, 테스트,
남은 오류와 다음 명령을 `HANDOFF.md`에 남긴다. 실제로 수행한 기여와
AI 지원 범위는 CV·보고서에 맞게 구분한다.
