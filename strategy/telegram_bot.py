import requests
import os
from dotenv import load_dotenv
import threading
import time

load_dotenv()

class TelegramBot:
    def __init__(self, rsi_monitor=None):
        self.token = os.getenv('TELEGRAM_TOKEN')  # 기존 설정 사용
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')  # 기존 설정 사용
        
        # 설정 확인
        if not self.token:
            print("Error: TELEGRAM_TOKEN is not set in .env file")
            return
        if not self.chat_id:
            print("Error: TELEGRAM_CHAT_ID is not set in .env file")
            return
            
        print(f"Telegram Bot initialized with token: {self.token[:5]}...")
        print(f"Chat ID: {self.chat_id}")
        
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.rsi_monitor = rsi_monitor
        self.last_update_id = 0
        self.running = True
        
        # 봇 연결 테스트
        self._test_connection()
        
        # 명령어 처리 스레드 시작
        self.command_thread = threading.Thread(target=self._handle_commands)
        self.command_thread.daemon = True
        self.command_thread.start()
    
    def _test_connection(self):
        """
        텔레그램 봇 연결을 테스트합니다.
        """
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url)
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get('ok'):
                    print(f"Successfully connected to bot: {bot_info['result']['username']}")
                    # 테스트 메시지 전송
                    self.send_message("🤖 RSI 모니터링 봇이 시작되었습니다.")
                else:
                    print("Error: Failed to get bot information")
            else:
                print(f"Error: Failed to connect to bot (Status code: {response.status_code})")
        except Exception as e:
            print(f"Error testing bot connection: {e}")
    
    def send_message(self, message):
        """
        텔레그램으로 메시지를 전송합니다.
        """
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data)
            if response.status_code != 200:
                print(f"Error sending message: {response.text}")
            return response.json()
        except Exception as e:
            print(f"Error sending telegram message: {e}")
            return None
    
    def _handle_commands(self):
        """
        텔레그램 명령어를 처리합니다.
        """
        print("텔레그램 명령어 처리 시작")
        while self.running:
            try:
                url = f"{self.base_url}/getUpdates"
                params = {
                    "offset": self.last_update_id + 1,
                    "timeout": 30
                }
                response = requests.get(url, params=params)
                if response.status_code != 200:
                    print(f"Error getting updates: {response.text}")
                    time.sleep(1)
                    continue
                    
                updates = response.json().get('result', [])
                if updates:
                    print(f"수신된 업데이트: {len(updates)}개")
                
                for update in updates:
                    self.last_update_id = update['update_id']
                    if 'message' in update and 'text' in update['message']:
                        text = update['message']['text']
                        print(f"수신된 명령어: {text}")
                        if text == '/rsi' and self.rsi_monitor:
                            print("RSI 명령어 처리 시작")
                            current_rsi = self.rsi_monitor.get_current_rsi()
                            if not current_rsi:
                                print("현재 RSI 데이터가 없습니다.")
                                self.send_message("⚠️ 아직 RSI 데이터가 수집되지 않았습니다. 잠시 후 다시 시도해주세요.")
                                continue
                                
                            message = "📊 <b>현재 RSI 상태</b>\n\n"
                            for symbol, rsi in current_rsi.items():
                                message += f"{symbol}: {rsi:.2f}\n"
                            print("RSI 상태 메시지 전송")
                            self.send_message(message)
                
            except Exception as e:
                print(f"Error handling commands: {e}")
                time.sleep(1)
    
    def stop(self):
        """
        봇을 중지합니다.
        """
        self.running = False
        self.command_thread.join() 