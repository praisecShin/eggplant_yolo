# `_when`의 Python 버전별 계약 확인

- 저장소 `AGENTS.md`는 Python 3.10 이상을 지원 범위로 명시합니다.
- 실제 시험 인터프리터는 Python 3.14.4입니다. 이 버전에서 초 없음·소수 초·Z 형식을 국소 실행했고 결과는 `b31_extra_compat.log`에 있습니다.
- [Python 3.10 datetime.fromisoformat 공식 문서](https://docs.python.org/3.10/library/datetime.html#datetime.datetime.fromisoformat)는 isoformat 출력 역변환 범위와 숫자 오프셋 문법을 명시하며 Z 접미사는 그 범위에 없습니다.
- [Python 3.11 datetime.fromisoformat 공식 문서](https://docs.python.org/3.11/library/datetime.html#datetime.datetime.fromisoformat)는 Z 예제와 3.11에서 파싱 범위를 넓힌 변경 사항을 명시합니다.
- Python 3.10 실행 파일은 현재 환경에 없어 직접 실행하지 않았습니다. 버전별 API 계약과 `_when`의 ValueError → 0.0 흐름을 근거로 호환성 결함을 판단했습니다.
