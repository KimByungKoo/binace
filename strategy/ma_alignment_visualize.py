import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

# 데이터 불러오기
trades = pd.read_csv('ma_alignment_trades.csv')
df = pd.read_csv('/Users/bkkim/workspace/binace/binace/ohlcv_BTCUSDT_1m_180d.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
trades['time'] = pd.to_datetime(trades['time'])

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
        elif trade['type'] in ['stop_loss', 'exit_break_even', 'alignment_break', 'final_exit']:
            balance = trade['balance']
        trade_idx += 1
    
    equity_curve.append(balance)

df['equity'] = equity_curve

# 진입/청산 시점 표시용
entry_points = trades[trades['type'] == 'entry']
exit_points = trades[trades['type'].isin(['stop_loss', 'exit_break_even', 'alignment_break', 'final_exit'])]

# 1. 잔고 변화(Equity Curve) 시각화
plt.figure(figsize=(14,5))
plt.plot(df['timestamp'], df['equity'], label='Equity Curve')
plt.title('잔고 변화 (Equity Curve)')
plt.xlabel('시간')
plt.ylabel('잔고($)')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig('equity_curve.png')
plt.show()

# 2. 진입/청산 시점이 표시된 가격 차트
plt.figure(figsize=(14,6))
plt.plot(df['timestamp'], df['close'], label='BTCUSDT Close', color='gray', alpha=0.5)
plt.scatter(entry_points['time'], entry_points['price'], marker='^', color='green', label='Entry', zorder=5)
plt.scatter(exit_points['time'], exit_points['price'], marker='v', color='red', label='Exit', zorder=5)
plt.title('진입/청산 시점이 표시된 BTCUSDT 1분봉')
plt.xlabel('시간')
plt.ylabel('가격($)')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig('trade_points.png')
plt.show()

# 거래 통계 출력
print("\n=== 거래 통계 ===")
print(f"총 거래 횟수: {len(entry_points)}")
print(f"승리 거래: {len(exit_points[exit_points['balance'] > 10000])}")
print(f"손실 거래: {len(exit_points[exit_points['balance'] <= 10000])}")
print(f"최종 잔고: ${balance:,.2f}")
print(f"수익률: {(balance/10000 - 1)*100:.2f}%") 