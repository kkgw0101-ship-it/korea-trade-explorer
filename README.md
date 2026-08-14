# KCC글라스 Trade Intelligence Platform

관세청의 **품목별 국가별 수출입실적 Open API**를 이용해 HS Code 기준의 월별 수출입 흐름을 분석하는 Streamlit 대시보드입니다.

## 주요 기능

- 인증키 없이 확인할 수 있는 재현 가능한 샘플 모드
- HS 2·4·6·10단위 품목과 상대국·기간 조회
- 수출·수입·무역수지 KPI와 최근 12개월 비교
- KCC글라스 공식 국문 풀컬러 CI와 브랜드 컬러 적용
- 금액(USD)과 중량(kg)을 분리한 월별 수출입 추이
- 금액·중량 전년동월 증감률, 무역수지, kg당 신고단가 시각화
- 월별 집계와 API 원자료 분리 조회 및 CSV 다운로드
- 데이터 출처, 단위, 갱신 주기, 지표 정의를 화면에 명시
- API 필드 누락과 세부 품목 중복 월을 안전하게 처리

## 로컬 실행

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

처음 열면 샘플 데이터가 자동으로 표시됩니다. 실제 통계는 왼쪽의 `관세청 API 조회`를 선택한 뒤 공공데이터포털의 일반 인증키(Decoding)를 입력해 조회합니다.

## 배포 환경의 인증키 설정

공개 서비스에서 사용자가 인증키를 매번 입력하지 않게 하려면 Streamlit Secrets에 아래 값을 등록합니다.

```toml
DATA_GO_KR_SERVICE_KEY = "발급받은 일반 인증키(Decoding)"
```

인증키는 코드나 저장소에 커밋하지 않습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 데이터 해석

- 금액 단위는 USD, 중량은 kg입니다.
- 수출은 FOB, 수입은 CIF 기준입니다.
- 무역수지는 `수출액 - 수입액`으로 재계산합니다.
- HS 상위 단위 조회는 여러 세부 품목 행을 같은 월로 합산합니다.
- 최근 월 수치는 신고 정정과 반영 시차로 바뀔 수 있습니다.
- kg당 신고단가는 품질·규격·품목 구성·운임·환율 변화의 영향을 함께 받습니다.

## 구조

```text
app.py               Streamlit 화면과 상호작용
trade_data.py        API 조회, 응답 정규화, 월별 집계, KPI 계산
theme.py             디자인 토큰과 UI 컴포넌트
assets/              KCC글라스 공식 브랜드 자산
sample_data.py       데모용 재현 가능한 샘플 시계열
hs_presets.py        자주 쓰는 HS Code
country_codes.py     상대국 코드
tests/               데이터 계층 회귀 테스트
```

데이터 출처: [공공데이터포털](https://www.data.go.kr/) · [관세청 무역통계](https://tradedata.go.kr/)
