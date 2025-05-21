from strategy.ma365 import monitor_top10_ma365
from strategy.ma90_disparity import ma90_watcher_loop
from telegram.commands import telegram_command_listener
import threading

if __name__ == "__main__":
    # MA365 감시 (1분봉, 기울기 포함)
    threading.Thread(target=monitor_top10_ma365, daemon=True).start()

    # 15분봉 MA90 이격도 감시 (자동 알림)
    threading.Thread(target=ma90_watcher_loop, daemon=True).start()

    # 텔레그램 명령 대기 (/ma90 등)
    telegram_command_listener()