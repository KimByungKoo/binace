import numpy as np
import pandas as pd

def calculate_rsi(prices, period=14):
    """
    RSI를 계산합니다. (바이낸스 방식)
    """
    # 가격 변화 계산
    delta = np.diff(prices)
    
    # 상승/하락 구분
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    
    # 첫 번째 평균 상승/하락 계산
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    
    # 나머지 기간에 대한 평균 계산 (Wilder's smoothing)
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    
    # RSI 계산
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def calculate_rsi_binance(prices, period=14):
    """
    바이낸스 방식의 RSI를 계산합니다.
    - 종가(Close)를 사용
    - 첫 번째 평균은 첫 번째 값으로 시작
    - 이후 EMA 방식 사용
    """
    # 가격 변화 계산 (종가 기준)
    delta = np.diff(prices)
    
    # 상승/하락 구분
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    
    # 첫 번째 평균 상승/하락 계산 (첫 번째 값으로 시작)
    avg_gain = gain[0]
    avg_loss = loss[0]
    
    # 나머지 기간에 대한 평균 계산 (EMA 방식)
    alpha = 1 / period
    for i in range(1, len(delta)):
        avg_gain = (1 - alpha) * avg_gain + alpha * gain[i]
        avg_loss = (1 - alpha) * avg_loss + alpha * loss[i]
    
    # RSI 계산
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def calculate_rsi_binance_alt(prices, period=14):
    """
    바이낸스의 대체 RSI 계산 방식
    - 종가(Close)를 사용
    - EMA 방식 적용
    """
    # 가격 변화 계산 (종가 기준)
    delta = np.diff(prices)
    
    # 상승/하락 구분
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    
    # 첫 번째 평균 상승/하락 계산 (단순 평균)
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    
    # 나머지 기간에 대한 평균 계산 (EMA 방식)
    alpha = 2 / (period + 1)
    for i in range(period, len(delta)):
        avg_gain = (1 - alpha) * avg_gain + alpha * gain[i]
        avg_loss = (1 - alpha) * avg_loss + alpha * loss[i]
    
    # RSI 계산
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi 