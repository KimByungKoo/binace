# 전략 설정 모듈

SPIKE_CONFIG = {
    "interval": "1m",               # 사용할 분봉
    "ma_window": 90,
    "disparity_threshold": 105.0,     # 105% 이
    "limit": 150,                   # 데이터 몇 개 가져올지
    "vol_ma_window": 10,            # 거래량 평균 구간
    "spike_multiplier": 2,          # 스파이크 배수
    "disparity_ma": 90,             # 이격도 기준 MA
    "disparity_thresh": 1.2,          # 몇 % 이상 벗어나야 과이격
    "lookback": 15,                  # 최근 N봉 이내 스파이크 발생해야 인정
    "top_n": 30    ,                 # 검사할 종목 
    
    "volatility_multiplier": 2.5,    # 과거 평균 변동률의 N배 이상이어야 spike로 인정
    


    # 가격 기울기
    "price_lookback": 5,
    "min_price_slope_pct": 0.5,
    
    
    # 알림 제어
    "notify_on_spike_fail": False,
    "notify_on_disparity_fail": False,
    "notify_on_price_slope_fail":False,
    "notify_on_error": False

}