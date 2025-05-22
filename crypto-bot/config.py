# 전략 설정 모듈

SPIKE_CONFIG = {
    "interval": "1m",               # 사용할 분봉
    "limit": 150,                   # 데이터 몇 개 가져올지
    "vol_ma_window": 10,            # 거래량 평균 구간
    "spike_multiplier": 3,          # 스파이크 배수
    "disparity_ma": 90,             # 이격도 기준 MA
    "disparity_thresh": 2,          # 몇 % 이상 벗어나야 과이격
    "lookback": 5,                  # 최근 N봉 이내 스파이크 발생해야 인정
    "top_n": 20                     # 검사할 종목 수
}