import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# 거래 내역 로드
trades_df = pd.read_csv('volume_spike_trades.csv')
trades_df['time'] = pd.to_datetime(trades_df['time'])

# 스타일 설정
plt.style.use('default')
sns.set_theme()

# 1. 거래별 수익률 분포
plt.figure(figsize=(15, 10))

# 1-1. 수익률 히스토그램
plt.subplot(2, 2, 1)
sns.histplot(data=trades_df[trades_df['type'] == 'exit'], x='pnl', bins=50)
plt.title('거래별 수익률 분포')
plt.xlabel('수익률')
plt.ylabel('빈도')

# 1-2. 승/패 비율 파이 차트
plt.subplot(2, 2, 2)
win_loss = trades_df[trades_df['type'] == 'exit']['pnl'].apply(lambda x: '승' if x > 0 else '패').value_counts()
plt.pie(win_loss, labels=win_loss.index, autopct='%1.1f%%')
plt.title('승/패 비율')

# 2. 시간에 따른 수익률 변화
plt.subplot(2, 1, 2)
trades_df['cumulative_return'] = (1 + trades_df['pnl']).cumprod() - 1
plt.plot(trades_df[trades_df['type'] == 'exit']['time'], 
         trades_df[trades_df['type'] == 'exit']['cumulative_return'] * 100)
plt.title('누적 수익률 변화')
plt.xlabel('시간')
plt.ylabel('누적 수익률 (%)')
plt.grid(True)

# 그래프 저장
plt.tight_layout()
plt.savefig('trade_analysis.png')
print("그래프가 'trade_analysis.png'로 저장되었습니다.")

# 추가 통계 출력
print("\n=== 추가 통계 ===")
print(f"평균 수익 거래: {trades_df[trades_df['pnl'] > 0]['pnl'].mean()*100:.2f}%")
print(f"평균 손실 거래: {trades_df[trades_df['pnl'] < 0]['pnl'].mean()*100:.2f}%")
print(f"최대 연속 수익: {trades_df[trades_df['pnl'] > 0]['pnl'].max()*100:.2f}%")
print(f"최대 연속 손실: {trades_df[trades_df['pnl'] < 0]['pnl'].min()*100:.2f}%") 