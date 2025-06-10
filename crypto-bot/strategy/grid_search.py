import pandas as pd
from itertools import product
from data_collector import fetch_ohlcv_data
from technical_indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_stochastic, calculate_disparity
from backtest import backtest_strategy
from analyze_results import analyze_trades

# 탐색할 조건 범위
RSI_THRESHOLDS = [20, 25, 30, 35, 40]
MACD_THRESHOLDS = [0, 0.5, 1.0]
DISPARITY_THRESHOLDS = [-3.0, -2.0, -1.0]

symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MASKUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "TRUMPUSDT", "LAUSDT", "FARTCOINUSDT", "ADAUSDT", "HUMAUSDT", "BNBUSDT", "VIRTUALUSDT", "LPTUSDT", "WIFUSDT", "RVNUSDT", "COMPUSDT", "WCTUSDT", "ENAUSDT", "ANIMEUSDT", "AAVEUSDT", "TRBUSDT", "LINKUSDT", "UMAUSDT", "AVAXUSDT", "NEIROUSDT", "HYPEUSDT", "MOODENGUSDT"]

results = []

for symbol in symbols:
    df = fetch_ohlcv_data(symbol)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger_bands(df)
    df = calculate_stochastic(df)
    df = calculate_disparity(df)
    
    for rsi_th, macd_th, disp_th in product(RSI_THRESHOLDS, MACD_THRESHOLDS, DISPARITY_THRESHOLDS):
        conditions = lambda df, i: (
            df['rsi'].iloc[i] < rsi_th and
            df['macd'].iloc[i] > macd_th and
            df['disparity'].iloc[i] < disp_th
        )
        trades = backtest_strategy(df, conditions)
        stats = analyze_trades(trades)
        results.append({
            'symbol': symbol,
            'rsi_th': rsi_th,
            'macd_th': macd_th,
            'disp_th': disp_th,
            'total_trades': stats['total_trades'],
            'win_rate': stats['win_rate'],
            'avg_profit': stats['avg_profit']
        })
        print(f"{symbol} | RSI<{rsi_th}, MACD>{macd_th}, DISP<{disp_th} => 승률: {stats['win_rate']}%, 거래수: {stats['total_trades']}, 평균수익률: {stats['avg_profit']}")

# 결과를 데이터프레임으로 저장
results_df = pd.DataFrame(results)
results_df.to_csv('grid_search_results.csv', index=False)
print("그리드 서치 결과가 grid_search_results.csv 파일로 저장되었습니다.") 