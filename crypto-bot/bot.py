from strategy.ma365 import monitor_top10_ma365
from strategy.ma90_disparity import ma90_watcher_loop
from telegram.commands import telegram_command_listener
from strategy.spike_disparity import spike_watcher_loop
from position_monitor import position_watcher_loop
#from strategy.disparity_monitor import run_disparity_monitor
import threading
from order_manager import monitor_trailing_stop,monitor_ma7_touch_exit,monitor_fixed_profit_loss_exit

from strategy.hyper_disparity import check_and_enter_hyper_disparity

if __name__ == "__main__":
    #!/bin/bash
    print("🔧 실행 중...") 
    
     
    # MA365 감시 (1분봉, 기울기 포함)
    # threading.Thread(target=monitor_top10_ma365, daemon=True).start()

    # 15분봉 MA90 이격도 감시 (자동 알림)
    # threading.Thread(target=ma90_watcher_loop, daemon=True).start()

 
    #threading.Thread(target=spike_watcher_loop, daemon=True).start()

    
    threading.Thread(target=check_and_enter_hyper_disparity, daemon=True).start()
    

    # threading.Thread(target=monitor_trailing_stop, daemon=True).start()
    # threading.Thread(target=monitor_ma7_touch_exit, daemon=True).start()
    threading.Thread(target=monitor_fixed_profit_loss_exit, daemon=True).start()
    

    
    # 텔레그램 명령 대기 (/ma90 등)
    telegram_command_listener()