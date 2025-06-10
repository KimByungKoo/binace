import pandas as pd
import numpy as np

def analyze_backtest_results():
    # 결과 파일 읽기
    df = pd.read_csv('btc_dominance_results.csv')
    
    # 전체 통계
    total_trades = df['trades'].sum()
    avg_win_rate = (df['win_rate'] * df['trades']).sum() / total_trades
    avg_return = (df['avg_return'] * df['trades']).sum() / total_trades
    
    # 심볼별 통계
    symbol_stats = df.groupby('symbol').agg({
        'trades': 'sum',
        'win_rate': lambda x: (x * df.loc[x.index, 'trades']).sum() / df.loc[x.index, 'trades'].sum(),
        'avg_return': lambda x: (x * df.loc[x.index, 'trades']).sum() / df.loc[x.index, 'trades'].sum()
    }).sort_values('trades', ascending=False)
    
    # 조건별 통계
    condition_stats = pd.DataFrame()
    for col in ['rsi_threshold', 'macd_threshold', 'disp_threshold', 'btc_dom_threshold', 'volume_ratio']:
        stats = df.groupby(col).agg({
            'trades': 'sum',
            'win_rate': lambda x: (x * df.loc[x.index, 'trades']).sum() / df.loc[x.index, 'trades'].sum(),
            'avg_return': lambda x: (x * df.loc[x.index, 'trades']).sum() / df.loc[x.index, 'trades'].sum()
        })
        condition_stats = pd.concat([condition_stats, stats])
    
    # 마크다운 형식으로 결과 출력
    print("# BTC 도미넌스 전략 백테스트 결과 분석")
    print("\n## 1. 전체 통계")
    print(f"- 총 거래 횟수: {total_trades:,}회")
    print(f"- 평균 승률: {avg_win_rate:.2f}%")
    print(f"- 평균 수익률: {avg_return:.2f}%")
    
    print("\n## 2. 심볼별 분석")
    print("\n### 거래 횟수 기준 상위 10개 심볼")
    print(symbol_stats.head(10).to_markdown())
    
    print("\n### 승률 기준 상위 10개 심볼")
    print(symbol_stats.sort_values('win_rate', ascending=False).head(10).to_markdown())
    
    print("\n### 평균 수익률 기준 상위 10개 심볼")
    print(symbol_stats.sort_values('avg_return', ascending=False).head(10).to_markdown())
    
    print("\n## 3. 조건별 분석")
    print("\n### RSI 조건별 성과")
    print(condition_stats.loc[condition_stats.index.get_level_values(0) == 'rsi_threshold'].to_markdown())
    
    print("\n### MACD 조건별 성과")
    print(condition_stats.loc[condition_stats.index.get_level_values(0) == 'macd_threshold'].to_markdown())
    
    print("\n### 이격도 조건별 성과")
    print(condition_stats.loc[condition_stats.index.get_level_values(0) == 'disp_threshold'].to_markdown())
    
    print("\n### BTC 도미넌스 조건별 성과")
    print(condition_stats.loc[condition_stats.index.get_level_values(0) == 'btc_dom_threshold'].to_markdown())
    
    print("\n### 거래량 비율 조건별 성과")
    print(condition_stats.loc[condition_stats.index.get_level_values(0) == 'volume_ratio'].to_markdown())
    
    print("\n## 4. 최적의 조건 조합")
    # 거래 횟수가 10회 이상이고 승률이 50% 이상인 조합만 필터링
    best_combinations = df[
        (df['trades'] >= 10) & 
        (df['win_rate'] >= 50)
    ].sort_values(['win_rate', 'avg_return'], ascending=[False, False])
    
    print("\n### 승률과 수익률이 높은 조합 (거래 10회 이상, 승률 50% 이상)")
    print(best_combinations.head(10).to_markdown())

if __name__ == "__main__":
    analyze_backtest_results() 