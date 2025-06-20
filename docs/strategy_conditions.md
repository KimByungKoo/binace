# 전략 실행 조건 및 결과

## 1. 기본 설정

- 백테스트 기간: 180일
- 시작일: 2024-12-09
- 종료일: 2025-06-07
- 시간프레임: 1분봉

## 2. 진입 조건

### RSI 조건

- RSI > 80
- RSI > 85
- RSI > 90

### 볼린저 밴드 조건

- 가격 > 볼린저 밴드 상단

### 거래량 조건

- 거래량 > 5봉 평균 거래량의 5배

## 3. 청산 조건

- RSI < 30
- 또는 손절: -1%
- 또는 익절: +1%

## 4. 최근 실행 결과 (2024-03-19)

### RSI 80 이상

- 평균 승률: 35.16%
- 최고 승률: 50.00% (BTC/USDT)
- 최저 승률: 20.00% (ETH/USDT)

### RSI 85 이상

- 평균 승률: 30.74%
- 최고 승률: 50.00% (BTC/USDT)
- 최저 승률: 20.00% (ETH/USDT)

### RSI 90 이상

- 평균 승률: 48.61%
- 최고 승률: 50.00% (BTC/USDT)
- 최저 승률: 40.00% (ETH/USDT)

## 5. 데이터 품질 이슈

- 일부 심볼 데이터 누락: MATIC, EOS
- 일부 심볼 데이터 중단: SOL/USDT (2025-05-11 이후)

## 6. 개선 필요 사항

1. 데이터 품질 개선

   - 선물 거래소 대신 현물 거래소 데이터 사용 검토
   - 데이터 연속성 보장

2. 전략 최적화
   - RSI 90 이상 조건에 집중
   - 거래량 조건 5배 → 3배로 조정 검토
   - 백테스트 기간 90일로 조정 검토

## 7. 참고 사항

- 이 문서는 전략의 실행 조건과 결과를 추적하기 위한 문서입니다.
- 전략 수정 시 이 문서도 함께 업데이트해주세요.
- 각 수정사항에 대한 결과도 이 문서에 기록해주세요.
