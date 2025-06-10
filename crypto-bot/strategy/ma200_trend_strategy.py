import pandas as pd
import numpy as np
from datetime import datetime
import math
import sys
import os

# 상위 디렉토리를 파이썬 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.telegram import send_telegram_message
from utils.binance import get_1m_klines, get_top_symbols

# === CONFIG ===
CONFIG = {
    "adx_thresh": 25,
    "rsi_min": 60,
    "rsi_max": 70,
    "vol_multiplier": 2.0,
    "bollinger_length": 20,
    "bollinger_stddev": 2,
    "max_positions": 3,
    "risk_reward_ratio": 2.2,
    "leverage": 10,
    "capital_per_trade": 100
}

def calculate_ma200_slope(symbol):
    try:
        # 15분봉 데이터 가져오기
        # 200개 MA 계산을 위해 최소 200+5=205개 데이터 필요. 충분한 여유분 확보
        df = get_1m_klines(symbol, interval='15m', limit=600)  
        if df.empty:
            print(f"❌ {symbol}: 데이터 없음")
            return None, None, None, None

        # 종가를 float로 변환
        df['close'] = df['close'].astype(float)
        
        # 200개 이동평균선 계산
        df['ma200'] = df['close'].rolling(window=200).mean()
        # 추가 스무딩(노이즈 제거)
        df['ma200_smooth'] = df['ma200'].rolling(window=5).mean()
        
        # MA200 스무스 유효 데이터
        ma = df['ma200_smooth'].dropna()
        if len(ma) < 2:
            print(f"❌ {symbol}: MA200 데이터 부족")
            return None, None, None, None
        
        # 최근 N봉 (예: 50봉) 데이터 사용
        recent_ma = ma.tail(50)
        if len(recent_ma) < 2:
             print(f"❌ {symbol}: 최근 MA200 데이터 부족")
             return None, None, None, None

        values = recent_ma.values
        last_pos = len(values) - 1
        end_price = values[-1]
        
        # 최근 N봉 내에서 가장 마지막에 나타난 최고점 찾기
        max_val = -float('inf')
        start_pos = 0
        # 마지막 봉은 제외하고 최고점 찾기
        for i in range(len(values) - 1):
             if values[i] > max_val:
                 max_val = values[i]
                 start_pos = i

        start_price = values[start_pos]
        delta_bars = last_pos - start_pos
        
        # 각도 및 퍼센트 변화 계산
        if start_price == 0 or delta_bars <= 0:
            percent_change = 0
            angle = 0
        else:
             percent_change = (end_price - start_price) / start_price * 100
             pct_per_bar = (end_price - start_price) / start_price / delta_bars
             K = 10000  # 필요시 조정
             angle = pct_per_bar * K

        # 이격도: 현재가와 MA200 스무스의 마지막 값 기준
        last_ma = values[-1] # 최근 50봉의 마지막 값
        last_close = df['close'].iloc[-1]
        if last_ma == 0:
            disparity = 0
        else:
            disparity = (last_close - last_ma) / last_ma * 100
        
        # 현재 이격도와 부호가 반대인 과거 이격도 평균 (최근 100봉 기준 유지)
        # 주의: closes_recent, ma_recent도 전체 ma 기준으로 변경 필요하면 추후 수정
        closes_recent = df['close'].iloc[-100:].values
        ma_recent = df['ma200_smooth'].dropna().tail(100).values # 최근 100봉만
        disparities_recent = [(c - m) / m * 100 if m != 0 else 0 for c, m in zip(closes_recent, ma_recent)]

        if disparity >= 0:
            opp_disparities_avg = [d for d in disparities_recent[:-1] if d < 0]
        else:
            opp_disparities_avg = [d for d in disparities_recent[:-1] if d > 0]

        if opp_disparities_avg:
            avg_disparity = sum(opp_disparities_avg) / len(opp_disparities_avg)
        else:
            avg_disparity = None
        
        return percent_change, angle, disparity, avg_disparity
        
    except Exception as e:
        print(f"❌ {symbol} 계산 중 오류: {str(e)}")
        return None, None, None, None

def scan_ma200_trends():
    try:
        symbols = get_top_symbols(150)  # 상위 50개 심볼 스캔
        trend_list = []
        
        print(f"🔍 {len(symbols)}개 심볼 스캔 중...")
        
        for symbol in symbols:
            slope, angle, disparity, opp_disparity_avg = calculate_ma200_slope(symbol)
            
            if slope is not None and angle is not None and disparity is not None:
                # 새로운 부호 조건 적용
                if angle * disparity < 0: # 기존 부호 조건 (각도와 이격도 부호 다름)
                    if opp_disparity_avg is not None and abs(disparity) > abs(opp_disparity_avg): # 이격도 절대값 > 반대부호평균 절대값
                        sign_check = '😀' # 새로운 부호
                    else:
                        sign_check = 'O' # 기존 부호 유지
                else:
                    sign_check = 'X' # 기존 부호 유지

                trend_list.append({
                    'symbol': symbol,
                    'slope': slope,
                    'angle': angle,
                    'disparity': disparity,
                    'opp_disparity_avg': opp_disparity_avg,
                    'sign_check': sign_check
                })
        
        # 각도 기준으로 정렬
        trend_list.sort(key=lambda x: x['angle'], reverse=True)
        
        # 결과 출력
        if trend_list:
            print("\n📈 200개 이동평균선 기울기, 각도, 이격도 리스트\n")
            print(f"{'심볼':<10} {'퍼센트변화':<15} {'각도':<10} {'이격도':<10} {'반대부호평균':<10} {'부호':<3}")
            print("-" * 55)
            
            for item in trend_list:
                opp_disp = f"{item['opp_disparity_avg']:>8.2f}%" if item['opp_disparity_avg'] is not None else "   N/A   "
                print(f"{item['symbol']:<10} {item['slope']:>10.4f}% {item['angle']:>10.2f}° {item['disparity']:>8.2f}%   {opp_disp}   {item['sign_check']}")
        else:
            print("❌ 데이터를 가져올 수 없습니다.")
            
    except Exception as e:
        print(f"⚠️ MA200 트렌드 스캔 실패: {str(e)}")

# 테스트 실행
if __name__ == "__main__":
    scan_ma200_trends() 