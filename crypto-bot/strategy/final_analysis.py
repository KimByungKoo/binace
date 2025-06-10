import pandas as pd
from data_collector import fetch_ohlcv_data
from technical_indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_stochastic, calculate_disparity
from backtest import backtest_strategy
from analyze_results import analyze_trades

def run_backtest_for_symbol(symbol):
    """
    각 심볼별로 백테스트를 수행하고 결과를 분석합니다.
    """
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
    return results

# 예시: 각 심볼별로 백테스트 수행
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MASKUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT", "FARTCOINUSDT", "ADAUSDT", "HUMAUSDT", "BNBUSDT", "VIRTUALUSDT", "LPTUSDT", "WIFUSDT", "RVNUSDT", "COMPUSDT", "WCTUSDT", "ENAUSDT", "ANIMEUSDT", "AAVEUSDT", "TRBUSDT", "LINKUSDT", "UMAUSDT", "AVAXUSDT", "NEIROUSDT", "HYPEUSDT", "MOODENGUSDT"]

results = {}
for symbol in symbols:
    results[symbol] = run_backtest_for_symbol(symbol)
    print(f"{symbol} 백테스트 결과: {results[symbol]}")

# 가장 높은 승률을 보이는 심볼 찾기
best_symbol = max(results.items(), key=lambda x: x[1]['win_rate'])
print(f"가장 높은 승률을 보이는 심볼: {best_symbol[0]}, 승률: {best_symbol[1]['win_rate']}%") 