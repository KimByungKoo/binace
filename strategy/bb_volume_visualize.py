import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

# 데이터 불러오기
trades = pd.read_csv('bb_volume_trades.csv')
df = pd.read_csv('/Users/bkkim/workspace/binace/binace/ohlcv_BTCUSDT_1m_180d.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
trades['time'] = pd.to_datetime(trades['time'])

# 볼린저 밴드 계산
window = 20
num_std = 2
df['MA'] = df['close'].rolling(window=window).mean()
df['STD'] = df['close'].rolling(window=window).std()
df['Upper'] = df['MA'] + (df['STD'] * num_std)
df['Lower'] = df['MA'] - (df['STD'] * num_std)

# 거래량 스파이크 계산
df['Volume_MA'] = df['volume'].rolling(window=window).mean()
df['Volume_Std'] = df['volume'].rolling(window=window).std()
df['Volume_Upper'] = df['Volume_MA'] + (df['Volume_Std'] * 2)

# 잔고 계산
balance = 10000  # 초기 잔고
equity_curve = []
trade_idx = 0

for i, row in df.iterrows():
    current_time = row['timestamp']
    current_price = row['close']
    
    # 현재 시점의 거래가 있는지 확인
    while trade_idx < len(trades) and trades['time'].iloc[trade_idx] == current_time:
        trade = trades.iloc[trade_idx]
        if trade['type'] == 'entry':
            balance = trade['balance']
        elif trade['type'] == 'exit':
            balance = trade['balance']
        trade_idx += 1
    
    equity_curve.append(balance)

df['equity'] = equity_curve

# 진입/청산 시점 표시용
entry_points = trades[trades['type'] == 'entry']
exit_points = trades[trades['type'] == 'exit']

# 1. 잔고 변화(Equity Curve) 시각화
plt.figure(figsize=(14,5))
plt.plot(df['timestamp'], df['equity'], label='Equity Curve')
plt.title('잔고 변화 (Equity Curve)')
plt.xlabel('시간')
plt.ylabel('잔고($)')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig('bb_volume_equity_curve.png')
plt.show()

# 2. 볼린저 밴드와 거래 시점
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14,10), gridspec_kw={'height_ratios': [3, 1]})

# 가격 차트와 볼린저 밴드
ax1.plot(df['timestamp'], df['close'], label='BTCUSDT Close', color='gray', alpha=0.5)
ax1.plot(df['timestamp'], df['Upper'], label='Upper Band', color='red', alpha=0.3)
ax1.plot(df['timestamp'], df['MA'], label='MA', color='blue', alpha=0.3)
ax1.plot(df['timestamp'], df['Lower'], label='Lower Band', color='green', alpha=0.3)
ax1.scatter(entry_points['time'], entry_points['price'], marker='^', color='green', label='Entry', zorder=5)
ax1.scatter(exit_points['time'], exit_points['price'], marker='v', color='red', label='Exit', zorder=5)
ax1.set_title('볼린저 밴드와 거래 시점')
ax1.set_ylabel('가격($)')
ax1.legend()
ax1.grid(True)

# 거래량 차트
ax2.bar(df['timestamp'], df['volume'], label='Volume', color='gray', alpha=0.5)
ax2.plot(df['timestamp'], df['Volume_Upper'], label='Volume Upper', color='red', alpha=0.3)
ax2.set_xlabel('시간')
ax2.set_ylabel('거래량')
ax2.legend()
ax2.grid(True)

plt.tight_layout()
plt.savefig('bb_volume_trade_points.png')
plt.show()

# 거래 통계 출력
print("\n=== 거래 통계 ===")
print(f"총 거래 횟수: {len(entry_points)}")
print(f"승리 거래: {len(exit_points[exit_points['balance'] > 10000])}")
print(f"손실 거래: {len(exit_points[exit_points['balance'] <= 10000])}")
print(f"최종 잔고: ${balance:,.2f}")
print(f"수익률: {(balance/10000 - 1)*100:.2f}%") 