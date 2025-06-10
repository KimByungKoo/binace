from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time
import pandas as pd

# 크롬드라이버 옵션 설정 (브라우저 창 안 띄우기)
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# 크롬드라이버 경로 자동 감지 (환경에 따라 chromedriver 경로 지정 필요)
driver = webdriver.Chrome(options=chrome_options)

url = 'https://www.binance.com/ko/futures-activity/leaderboard'
driver.get(url)
time.sleep(5)  # 페이지 로딩 대기

# 스크롤을 내려서 더 많은 트레이더 로딩 (최대 10명만)
for _ in range(2):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

# 테이블 행 추출
rows = driver.find_elements(By.CSS_SELECTOR, 'div.leaderboard-table-row')

results = []
for row in rows[:10]:
    try:
        nickname = row.find_element(By.CSS_SELECTOR, 'div.nickname').text
        roi = row.find_element(By.CSS_SELECTOR, 'div.roi').text
        pnl = row.find_element(By.CSS_SELECTOR, 'div.pnl').text
        results.append({
            'nickname': nickname,
            'roi': roi,
            'pnl': pnl
        })
    except Exception as e:
        continue

driver.quit()

# 결과 저장 및 출력
results_df = pd.DataFrame(results)
results_df.to_csv('leaderboard_scraped.csv', index=False)
print(results_df) 