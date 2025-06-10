import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import json
import os
from typing import Dict, List
import threading
from queue import Queue
import time

from strategy.trade_executor import backtest_ma200_strategy
from utils.binance import get_top_symbols

def run_backtest_for_symbol(symbol: str, result_queue: Queue) -> None:
    """
    단일 심볼에 대한 백테스트를 실행하고 결과를 큐에 저장합니다.
    
    Args:
        symbol: 거래 심볼
        result_queue: 결과를 저장할 큐
    """
    try:
        print(f"[{symbol}] 백테스트 시작...")
        result = backtest_ma200_strategy(symbol)
        result_queue.put((symbol, result))
        print(f"[{symbol}] 백테스트 완료")
    except Exception as e:
        print(f"[{symbol}] 백테스트 실행 중 오류 발생: {str(e)}")
        result_queue.put((symbol, {"error": str(e)}))

def run_backtest() -> None:
    """
    모든 심볼에 대해 백테스트를 실행하고 결과를 저장합니다.
    """
    try:
        # 결과 저장 디렉토리 생성
        results_dir = "backtest_results"
        os.makedirs(results_dir, exist_ok=True)
        
        # 현재 시간 기준으로 결과 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = os.path.join(results_dir, f"ma200_backtest_{timestamp}.json")
        
        # 모든 심볼 가져오기 (상위 30개)
        symbols = get_top_symbols(30)
        print(f"총 {len(symbols)}개 심볼에 대한 백테스트를 시작합니다...")
        
        # 결과를 저장할 큐 생성
        result_queue = Queue()
        
        # 스레드 생성 및 시작
        threads = []
        for symbol in symbols:
            thread = threading.Thread(
                target=run_backtest_for_symbol,
                args=(symbol, result_queue)
            )
            threads.append(thread)
            thread.start()
            
            # API 요청 제한을 고려하여 딜레이 추가
            time.sleep(1)
            
            # 스레드가 너무 많이 생성되지 않도록 제한
            if len(threads) >= 3:  # 최대 3개의 스레드만 동시 실행
                for t in threads:
                    t.join()
                threads = []
        
        # 남은 스레드 완료 대기
        for thread in threads:
            thread.join()
        
        # 결과 수집
        results = {}
        while not result_queue.empty():
            symbol, result = result_queue.get()
            results[symbol] = result
        
        # 결과 저장
        with open(result_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n백테스트 결과가 {result_file}에 저장되었습니다.")
        
        # 결과 분석
        analyze_results(results)
        
    except Exception as e:
        print(f"백테스트 실행 중 오류 발생: {str(e)}")

def analyze_results(results: Dict) -> None:
    """
    백테스트 결과를 분석하고 요약합니다.
    
    Args:
        results: 백테스트 결과 딕셔너리
    """
    # 에러가 없는 결과만 필터링
    valid_results = {k: v for k, v in results.items() if "error" not in v}
    
    if not valid_results:
        print("유효한 백테스트 결과가 없습니다.")
        return
    
    # 전체 거래 수
    total_trades = sum(r["total_trades"] for r in valid_results.values())
    
    # 평균 승률
    avg_win_rate = np.mean([r["win_rate"] for r in valid_results.values()])
    
    # 평균 수익률
    avg_profit = np.mean([r["total_profit"] for r in valid_results.values()])
    
    # 평균 최대 손실폭
    avg_drawdown = np.mean([r["max_drawdown"] for r in valid_results.values()])
    
    # 평균 수익팩터
    avg_profit_factor = np.mean([r["profit_factor"] for r in valid_results.values()])
    
    print("\n## 백테스트 결과 요약")
    print(f"- 분석된 심볼 수: {len(valid_results)}")
    print(f"- 총 거래 수: {total_trades}")
    print(f"- 평균 승률: {avg_win_rate:.2f}%")
    print(f"- 평균 수익률: {avg_profit:.2f}%")
    print(f"- 평균 최대 손실폭: {avg_drawdown:.2f}%")
    print(f"- 평균 수익팩터: {avg_profit_factor:.2f}")
    
    # 상위 5개 심볼 출력
    print("\n## 상위 5개 심볼")
    sorted_symbols = sorted(
        valid_results.items(),
        key=lambda x: x[1]["total_profit"],
        reverse=True
    )[:5]
    
    for symbol, result in sorted_symbols:
        print(f"\n### {symbol}")
        print(f"- 총 거래 수: {result['total_trades']}")
        print(f"- 승률: {result['win_rate']:.2f}%")
        print(f"- 총 수익률: {result['total_profit']:.2f}%")
        print(f"- 최대 손실폭: {result['max_drawdown']:.2f}%")
        print(f"- 수익팩터: {result['profit_factor']:.2f}")

if __name__ == "__main__":
    run_backtest() 