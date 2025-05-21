from utils.telegram import send_telegram_message
from utils.binance import get_top_symbols, check_ma365_proximity_with_slope
import time

def monitor_top10_ma365():
    active = {}
    send_telegram_message("👑 시총 TOP20 종목 MA365 근접 감시 시작됨 (기울기 분석 포함)")
    
    while True:
        try:
            top20 = get_top_symbols(20)
            for symbol in top20:
                result = check_ma365_proximity_with_slope(symbol)
                if not result:
                    continue

                is_close = result['diff_pct'] <= 0.2

                if is_close and not active.get(symbol):
                    msg = f"📌 *{symbol}* MA365 근접!\n"
                    msg += f"   ├ 현재가: `{round(result['price'], 4)}`\n"
                    msg += f"   ├ MA365: `{round(result['ma'], 4)}`\n"
                    msg += f"   ├ 이격도: `{round(result['diff_pct'], 3)}%`\n"
                    msg += f"   ├ 기울기: `{round(result['slope_pct'], 3)}%`\n"
                    if result['entry_signal']:
                        msg += f"✅ *진입각 포착됨* (MA 근접 + 기울기 완만)"
                    else:
                        msg += f"⚠️ 기울기 급함 → 진입각 아님"
                    send_telegram_message(msg)
                    active[symbol] = True

                elif not is_close:
                    active[symbol] = False

        except Exception as e:
            print("[MA365 감시 오류]", e)

        time.sleep(60)