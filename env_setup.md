# 환경 변수 설정 가이드

## .env 파일 생성

프로젝트 루트에 `.env` 파일을 생성하고 다음 내용을 추가하세요:

```env
# 텔레그램 설정
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# 바이낸스 API 설정
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET_KEY=your_binance_secret_key_here

# 테스트넷 사용 여부 (true/false)
BINANCE_TESTNET=false
```

## 바이낸스 API 키 설정

### 1. 바이낸스 계정에서 API 키 생성

1. 바이낸스 로그인
2. API 관리 페이지로 이동
3. 새 API 키 생성
4. **스팟 거래** 권한 활성화
5. **IP 제한** 설정 (권장)

### 2. 테스트넷 사용 (권장)

- `BINANCE_TESTNET=true`로 설정
- 테스트넷 API 키 사용
- 실제 자금 없이 테스트 가능

### 3. 실제 거래 사용

- `BINANCE_TESTNET=false`로 설정
- 실제 API 키 사용
- **주의**: 실제 자금이 사용됩니다!

## 보안 주의사항

1. **API 키 보안**

   - API 키를 절대 공개하지 마세요
   - IP 제한 설정 권장
   - 정기적으로 API 키 갱신

2. **거래 위험**

   - 실제 거래는 자금 손실 위험이 있습니다
   - 충분한 테스트 후 사용하세요
   - 투자 금액을 제한하세요

3. **모니터링**
   - 봇 실행 중 정기적으로 상태 확인
   - 텔레그램 알림 모니터링
   - 예상치 못한 동작 시 즉시 중단

## 실행 모드

### 시뮬레이션 모드

- API 키가 설정되지 않은 경우
- 실제 주문 없이 시뮬레이션만 실행
- 안전한 테스트 가능

### 테스트넷 모드

- `BINANCE_TESTNET=true`
- 실제 거래소 환경에서 테스트
- 테스트용 자금 사용

### 실제 거래 모드

- `BINANCE_TESTNET=false`
- 실제 자금으로 거래
- **매우 위험하므로 주의**
