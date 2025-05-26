# 전략 설정 모듈

SPIKE_CONFIG = {
    "interval": "1m",               # 사용할 분봉
    "ma_window": 90,
    "disparity_threshold": 105.0,     # 105% 이
    "limit": 150,                   # 데이터 몇 개 가져올지
    "vol_ma_window": 10,            # 거래량 평균 구간
    "spike_multiplier": 2,          # 스파이크 배수
    "disparity_ma": 90,             # 이격도 기준 MA
    "disparity_thresh": 1.1,          # 몇 % 이상 벗어나야 과이격
    "lookback": 15,                  # 최근 N봉 이내 스파이크 발생해야 인정
    "top_n": 50    ,                 # 검사할 종목 
    
    "volatility_multiplier": 2.0,    # 과거 평균 변동률의 N배 이상이어야 spike로 인정
    
    
    "volume_spike_multiplier": 1.8,
    "min_disparity_pct": 0.1,
    "ma_periods": [7, 20, 30, 60],
    "require_alignment": True,  # 정배열/역배열 필터링 유무
    "reverse_trade": True,      # 반대방향 진입 여부


    # 가격 기울기
    "price_lookback": 5,
    "min_price_slope_pct": 0.5,
    
    "checks": [
    "five_green_ma5",
        "disparity",        # 이격도
        "ma_order",         # MA 정배열/역배열
        "slope",            # 시작점 기준 기울기
       # "spike_strength",   # 과열 강도 (최저시가 → 최고종가)
        "volatility"        # 최근 변동성 대비 파동폭
        ],
    
    # 알림 제어
    "notify_on_spike_fail": True,
    "notify_on_disparity_fail": True,
    "notify_on_price_slope_fail":True,
    "notify_on_error": False,   

    "auto_execute": True

}