import pandas as pd
from data_collector import fetch_ohlcv_data
from technical_indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_stochastic, calculate_disparity

def backtest_strategy(df, conditions):
    """
    각 기술 지표 조합에 대해 백테스트를 수행합니다.
    """
    trades = []
    position = None
    
    for i in range(1, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1]
        
        # 진입 조건 확인
        if position is None:
            if conditions(df, i):
                position = {
                    'entry_price': current['close'],
                    'entry_time': current.name,
                    'stop_loss': current['close'] * 0.98,  # 손절매 -2.0%
                    'take_profit_1': current['close'] * 1.04,  # 익절 4%
                    'take_profit_2': current['close'] * 1.08,  # 익절 8%
                    'take_profit_3': current['close'] * 1.12,  # 익절 12%
                    'remaining_position': 1.0
                }
        
        # 청산 조건 확인
        if position is not None:
            if current['low'] <= position['stop_loss']:
                profit = (position['stop_loss'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['stop_loss'],
                    'profit': profit,
                    'exit_type': 'stop_loss'
                })
                position = None
                continue
            
            if current['high'] >= position['take_profit_3'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.4
                profit = (position['take_profit_3'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_3'],
                    'profit': profit,
                    'exit_type': 'take_profit_3',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
            
            if current['high'] >= position['take_profit_2'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.3
                profit = (position['take_profit_2'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_2'],
                    'profit': profit,
                    'exit_type': 'take_profit_2',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
            
            if current['high'] >= position['take_profit_1'] and position['remaining_position'] > 0:
                exit_amount = position['remaining_position'] * 0.3
                profit = (position['take_profit_1'] - position['entry_price']) / position['entry_price'] * 100
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry_price': position['entry_price'],
                    'exit_price': position['take_profit_1'],
                    'profit': profit,
                    'exit_type': 'take_profit_1',
                    'position_size': exit_amount
                })
                position['remaining_position'] -= exit_amount
    
    return trades

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
    print(f"{symbol} 백테스트 완료: {len(trades)} 거래") 