import numpy as np
import pandas as pd

def calculate_rsi(prices, period=14):
    """
    RSI를 계산합니다.
    """
    # 가격 변화 계산
    delta = np.diff(prices)
    
    # 상승/하락 구분
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    
    # 평균 상승/하락 계산
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    
    # 나머지 기간에 대한 평균 계산
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    
    # RSI 계산
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi 