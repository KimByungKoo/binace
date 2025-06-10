import pandas as pd
import numpy as np
from data_collector import fetch_ohlcv_data

def calculate_rsi(df, period=14):
    """
    RSI(Relative Strength Index) 계산
    """
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def calculate_macd(df, fast_period=12, slow_period=26, signal_period=9):
    """
    MACD(Moving Average Convergence Divergence) 계산
    """
    df['ema_fast'] = df['close'].ewm(span=fast_period, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_period, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['signal'] = df['macd'].ewm(span=signal_period, adjust=False).mean()
    df['histogram'] = df['macd'] - df['signal']
    return df

def calculate_bollinger_bands(df, period=20, num_std=2):
    """
    볼린저 밴드(Bollinger Bands) 계산
    """
    df['ma'] = df['close'].rolling(window=period).mean()
    df['std'] = df['close'].rolling(window=period).std()
    df['upper_band'] = df['ma'] + (df['std'] * num_std)
    df['lower_band'] = df['ma'] - (df['std'] * num_std)
    return df

def calculate_stochastic(df, k_period=14, d_period=3):
    """
    스토캐스틱(Stochastic) 계산
    """
    df['low_min'] = df['low'].rolling(window=k_period).min()
    df['high_max'] = df['high'].rolling(window=k_period).max()
    df['k'] = 100 * ((df['close'] - df['low_min']) / (df['high_max'] - df['low_min']))
    df['d'] = df['k'].rolling(window=d_period).mean()
    return df

def calculate_disparity(df, period=20):
    """
    이격도(Disparity) 계산
    """
    df['ma'] = df['close'].rolling(window=period).mean()
    df['disparity'] = (df['close'] - df['ma']) / df['ma'] * 100
    return df

# 예시: BTCUSDT 데이터에 기술 지표 적용
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MASKUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT", "FARTCOINUSDT", "ADAUSDT", "HUMAUSDT", "BNBUSDT", "VIRTUALUSDT", "LPTUSDT", "WIFUSDT", "RVNUSDT", "COMPUSDT", "WCTUSDT", "ENAUSDT", "ANIMEUSDT", "AAVEUSDT", "TRBUSDT", "LINKUSDT", "UMAUSDT", "AVAXUSDT", "NEIROUSDT", "HYPEUSDT", "MOODENGUSDT"]

for symbol in symbols:
    df = fetch_ohlcv_data(symbol)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger_bands(df)
    df = calculate_stochastic(df)
    df = calculate_disparity(df)
    print(f"{symbol} 기술 지표 계산 완료") 