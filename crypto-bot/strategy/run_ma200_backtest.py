import sys
import os
import pandas as pd
from datetime import datetime, timedelta
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.trade_executor import backtest_ma200_strategy, print_backtest_results, get_top_symbols

def format_time(timestamp):
    """타임스탬프를 보기 좋은 형식으로 변환"""
    if isinstance(timestamp, (int, float)):
        # 밀리초 타임스탬프를 datetime으로 변환
        return datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(timestamp, str):
        return timestamp
    elif isinstance(timestamp, datetime):
        return timestamp.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(timestamp, pd.Timestamp):
        return timestamp.strftime('%Y-%m-%d %H:%M:%S')
    return str(timestamp)

def print_backtest_summary(results_list):
    """전체 백테스트 결과 요약을 출력"""
    print("\n=== 전체 백테스트 결과 요약 ===")
    print(f"테스트 기간: {results_list[0]['start_time']} ~ {results_list[0]['end_time']}")
    print(f"테스트 종목 수: {len(results_list)}")
    
    # 전체 통계
    total_trades = sum(r['total_trades'] for r in results_list)
    total_profit = sum(r['total_profit'] for r in results_list)
    avg_win_rate = sum(r['win_rate'] for r in results_list) / len(results_list)
    
    print(f"\n전체 거래 횟수: {total_trades}")
    print(f"전체 수익률: {total_profit:.2f}%")
    print(f"평균 승률: {avg_win_rate:.2f}%")
    
    # 수익률 기준 상위 10종목
    print("\n=== 수익률 상위 10종목 ===")
    sorted_results = sorted(results_list, key=lambda x: x['total_profit'], reverse=True)
    for i, result in enumerate(sorted_results[:10], 1):
        print(f"{i}. {result['symbol']}: {result['total_profit']:.2f}% (거래횟수: {result['total_trades']})")
    
    # 마크다운 표 생성
    md_content = f"""# MA200 전략 백테스트 결과

## 테스트 정보
- 테스트 기간: {results_list[0]['start_time']} ~ {results_list[0]['end_time']}
- 테스트 종목 수: {len(results_list)}
- 전체 거래 횟수: {total_trades}
- 전체 수익률: {total_profit:.2f}%
- 평균 승률: {avg_win_rate:.2f}%

## 상위 10종목 결과
| 순위 | 심볼 | 수익률 | 거래횟수 | 승률 | 최대손실폭 | 수익팩터 |
|------|------|--------|----------|------|------------|----------|
"""
    
    for i, result in enumerate(sorted_results[:10], 1):
        md_content += f"| {i} | {result['symbol']} | {result['total_profit']:.2f}% | {result['total_trades']} | {result['win_rate']:.2f}% | {result['max_drawdown']:.2f}% | {result['profit_factor']:.2f} |\n"
    
    md_content += "\n## 전체 종목 결과\n"
    md_content += "| 심볼 | 수익률 | 거래횟수 | 승률 | 최대손실폭 | 수익팩터 |\n"
    md_content += "|------|--------|----------|------|------------|----------|\n"
    
    for result in sorted_results:
        md_content += f"| {result['symbol']} | {result['total_profit']:.2f}% | {result['total_trades']} | {result['win_rate']:.2f}% | {result['max_drawdown']:.2f}% | {result['profit_factor']:.2f} |\n"
    
    # 마크다운 파일 저장
    md_filename = f"ma200_backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"\n마크다운 결과가 {md_filename} 파일로 저장되었습니다.")

def main():
    # 상위 50종목 가져오기
    symbols = get_top_symbols(20)
    print(f"\n상위 50종목 백테스트 시작...")
    
    results_list = []
    total_symbols = len(symbols)
    
    for idx, symbol in enumerate(symbols, 1):
        print(f"\n[{idx}/{total_symbols}] {symbol} 백테스트 중... ({(idx/total_symbols*100):.1f}%)")
        results = backtest_ma200_strategy(symbol)
        
        if "error" not in results:
            # 시작/종료 시간 추가
            if results['trades']:
                results['start_time'] = format_time(results['trades'][0]['entry_time'])
                results['end_time'] = format_time(results['trades'][-1]['exit_time'])
            results_list.append(results)
            
            # 개별 종목 결과 출력
            print(f"\n=== {symbol} 백테스트 결과 ===")
            print(f"총 거래 횟수: {results['total_trades']}")
            print(f"승률: {results['win_rate']:.2f}%")
            print(f"총 수익: {results['total_profit']:.2f}%")
            
            # 거래 내역 출력
            if results['trades']:
                print("\n거래 내역:")
                for i, trade in enumerate(results['trades'], 1):
                    print(f"\n거래 #{i}")
                    print(f"진입: {format_time(trade['entry_time'])} @ {trade['entry_price']:.8f}")
                    print(f"청산: {format_time(trade['exit_time'])} @ {trade['exit_price']:.8f}")
                    print(f"수익률: {trade['profit']:.2f}%")
                    print(f"청산 사유: {trade['exit_reason']}")
    
    # 전체 결과 요약 출력
    if results_list:
        print_backtest_summary(results_list)
    
    # 결과를 CSV 파일로 저장
    if results_list:
        df = pd.DataFrame([{
            'symbol': r['symbol'],
            'total_trades': r['total_trades'],
            'win_rate': r['win_rate'],
            'total_profit': r['total_profit'],
            'max_drawdown': r['max_drawdown'],
            'profit_factor': r['profit_factor'],
            'start_time': r['start_time'],
            'end_time': r['end_time']
        } for r in results_list])
        
        filename = f"ma200_backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False)
        print(f"\nCSV 결과가 {filename} 파일로 저장되었습니다.")

if __name__ == "__main__":
    main() 