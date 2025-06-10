import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

def calculate_rsi(df, period=14):
    """RSI 계산"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def analyze_entry_rsi():
    # 데이터 로드
    df = pd.read_csv('/Users/bkkim/workspace/binace/binace/ohlcv_BTCUSDT_1m_180d.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # RSI 계산
    df = calculate_rsi(df, period=14)
    
    # 거래 내역 로드
    trades_df = pd.read_csv('rsi_short_trades.csv')
    trades_df['time'] = pd.to_datetime(trades_df['time'])
    
    # 진입/청산 시점의 RSI 값 추출
    entry_rsi = []
    exit_rsi = []
    exit_types = []  # 'profit' or 'loss'
    
    for i in range(0, len(trades_df), 2):
        if i + 1 >= len(trades_df):
            break
            
        entry_time = trades_df.iloc[i]['time']
        exit_time = trades_df.iloc[i+1]['time']
        pnl = trades_df.iloc[i+1]['pnl']
        
        # 진입/청산 시점의 RSI 값 찾기
        entry_idx = df[df['timestamp'] == entry_time].index
        exit_idx = df[df['timestamp'] == exit_time].index
        
        if len(entry_idx) > 0 and len(exit_idx) > 0:
            entry_rsi.append(df.iloc[entry_idx[0]]['RSI'])
            exit_rsi.append(df.iloc[exit_idx[0]]['RSI'])
            exit_types.append('profit' if pnl > 0 else 'loss')
    
    # 결과를 DataFrame으로 변환
    result_df = pd.DataFrame({
        'entry_rsi': entry_rsi,
        'exit_rsi': exit_rsi,
        'exit_type': exit_types
    })
    
    # 시각화
    plt.figure(figsize=(15, 10))
    
    # 1. 진입 시점 RSI 분포
    plt.subplot(2, 2, 1)
    sns.histplot(data=result_df, x='entry_rsi', hue='exit_type', bins=30)
    plt.title('진입 시점 RSI 분포 (수익/손실)')
    plt.xlabel('RSI')
    plt.ylabel('빈도')
    
    # 2. 수익/손실 비율
    plt.subplot(2, 2, 2)
    result_df['exit_type'].value_counts().plot(kind='pie', autopct='%1.1f%%')
    plt.title('수익/손실 비율')
    
    # 3. 진입 RSI 구간별 승률
    plt.subplot(2, 1, 2)
    bins = [0, 90, 95, 98, 100]
    labels = ['90-95', '95-98', '98-100', '100']
    result_df['rsi_range'] = pd.cut(result_df['entry_rsi'], bins=bins, labels=labels)
    win_rates = result_df.groupby('rsi_range')['exit_type'].apply(lambda x: (x == 'profit').mean() * 100)
    win_rates.plot(kind='bar')
    plt.title('진입 RSI 구간별 승률')
    plt.xlabel('RSI 구간')
    plt.ylabel('승률 (%)')
    
    plt.tight_layout()
    plt.savefig('rsi_entry_analysis.png')
    
    # 통계 출력
    print("\n=== RSI 진입 분석 결과 ===")
    print("\n수익 거래:")
    profit_df = result_df[result_df['exit_type'] == 'profit']
    print(f"평균 진입 RSI: {profit_df['entry_rsi'].mean():.2f}")
    print(f"최소 진입 RSI: {profit_df['entry_rsi'].min():.2f}")
    print(f"최대 진입 RSI: {profit_df['entry_rsi'].max():.2f}")
    
    print("\n손실 거래:")
    loss_df = result_df[result_df['exit_type'] == 'loss']
    print(f"평균 진입 RSI: {loss_df['entry_rsi'].mean():.2f}")
    print(f"최소 진입 RSI: {loss_df['entry_rsi'].min():.2f}")
    print(f"최대 진입 RSI: {loss_df['entry_rsi'].max():.2f}")
    
    print("\nRSI 구간별 승률:")
    for rsi_range, win_rate in win_rates.items():
        print(f"{rsi_range}: {win_rate:.2f}%")

if __name__ == "__main__":
    analyze_entry_rsi() 