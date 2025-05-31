from strategy.ma365 import monitor_top10_ma365
from strategy.ma90_disparity import ma90_watcher_loop
from telegram.commands import telegram_command_listener
from strategy.spike_disparity import spike_watcher_loop, monitor_ma365_breakout
from strategy.vtb_breakout_strategy import spike_watcher_loop1
from position_monitor import position_watcher_loop
import threading
from order_manager import monitor_trailing_stop, monitor_ma7_touch_exit, monitor_fixed_profit_loss_exit
from strategy.hyper_disparity import check_and_enter_hyper_disparity, report_top_5m_changers, get_top5_consecutive_green
from strategy.trade_executor import (
    wave_trade_watcher,
    check_system_health,
    update_market_analysis,
    generate_performance_report,
    save_trade_history,
    start_websocket_connections
)
from datetime import datetime
import time
a
def system_monitor_loop():
    """
    시스템 상태 모니터링 루프
    """
    while True:
        try:
            if not check_system_health():
                time.sleep(300)  # 5분 대기
            time.sleep(60)  # 1분마다 체크
        except Exception as e:
            print(f"시스템 모니터링 오류: {e}")
            time.sleep(60)

def market_analysis_loop():
    """
    시장 분석 업데이트 루프
    """
    while True:
        try:
            update_market_analysis()
            time.sleep(3600)  # 1시간마다 업데이트
        except Exception as e:
            print(f"시장 분석 오류: {e}")
            time.sleep(300)

def performance_report_loop():
    """
    성과 보고서 생성 루프
    """
    while True:
        try:
            now = datetime.utcnow()
            # 자정에 보고서 생성
            if now.hour == 0 and now.minute == 0:
                report = generate_performance_report()
                save_trade_history()
                time.sleep(60)  # 1분 대기
            time.sleep(30)  # 30초마다 체크
        except Exception as e:
            print(f"성과 보고서 생성 오류: {e}")
            time.sleep(300)

if __name__ == "__main__":
    print("🚀 트레이딩 봇 시작...")
    
    # 시스템 모니터링
    threading.Thread(target=system_monitor_loop, daemon=True).start()
     
    # 시장 분석
    threading.Thread(target=market_analysis_loop, daemon=True).start()

    # 성과 보고서
    threading.Thread(target=performance_report_loop, daemon=True).start()

    # 웹소켓 연결 시작
    start_websocket_connections()
 
    # 파동 기반 트레이딩
    threading.Thread(target=wave_trade_watcher, daemon=True).start()  # 진입 감시
    
    # 텔레그램 명령 대기
    telegram_command_listener()