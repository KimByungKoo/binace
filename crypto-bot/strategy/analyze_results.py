import pandas as pd
from backtest import backtest_strategy
from data_collector import fetch_ohlcv_data
from technical_indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_stochastic, calculate_disparity

def analyze_trades(trades):
    """
    각 조건별 승률을 계산합니다.
    """
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_profit': 0,
            'max_profit': 0,
            'min_profit': 0
        }
    
    df = pd.DataFrame(trades)
    total_trades = len(df)
    winning_trades = len(df[df['profit'] > 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_profit': df['profit'].mean(),
        'max_profit': df['profit'].max(),
        'min_profit': df['profit'].min()
    }

# 예시: BTCUSDT 데이터에 백테스트 적용
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MASKUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT", "FARTCOINUSDT", "ADAUSDT", "HUMAUSDT", "BNBUSDT", "VIRTUALUSDT", "LPTUSDT", "WIFUSDT", "RVNUSDT", "COMPUSDT", "WCTUSDT", "ENAUSDT", "ANIMEUSDT", "AAVEUSDT", "TRBUSDT", "LINKUSDT", "UMAUSDT", "AVAXUSDT", "NEIROUSDT", "HYPEUSDT", "MOODENGUSDT"]

for symbol in symbols:
    df = fetch_ohlcv_data(symbol)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger_bands(df)
    df = calculate_stochastic(df)
    df = calculate_disparity(df)
    
    # 예시 조건: RSI < 30, MACD > 0, 이격도 < -2.0
    conditions = lambda df, i: (
        df['rsi'].iloc[i] < 30 and
        df['macd'].iloc[i] > 0 and
        df['disparity'].iloc[i] < -2.0
    )
    
    trades = backtest_strategy(df, conditions)
    results = analyze_trades(trades)
    print(f"{symbol} 백테스트 결과: {results}") 