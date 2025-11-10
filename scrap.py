import time, os, json, logging, requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Date setup ---
date_range = datetime.now().strftime("%d%m%y-%d%m%y")

# --- Credentials ---
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")

# --- Telegram setup ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    """Send message to Telegram group."""
    if BOT_TOKEN and CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": text, "disable_notification": True}
            requests.post(url, data=payload, timeout=10)
            logging.info(f"Sent Telegram message: {text}")
        except Exception as e:
            logging.error(f"Failed to send Telegram message: {e}")
    else:
        logging.warning("Telegram credentials not set; skipping message.")

# --- Deduplication setup ---
SENT_FILE = "sent_messages.json"
EXPIRY_DAYS = 7

def load_sent():
    """Load sent messages and remove expired ones."""
    if not os.path.exists(SENT_FILE):
        return {}
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cutoff = datetime.utcnow() - timedelta(days=EXPIRY_DAYS)
        cleaned = {msg: ts for msg, ts in data.items()
                   if datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") > cutoff}
        expired = len(data) - len(cleaned)
        if expired > 0:
            logging.info(f"Cleaned {expired} expired entries.")
        return cleaned
    except Exception:
        return {}

def save_sent(sent_dict):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent_dict, f, ensure_ascii=False, indent=2)

sent = load_sent()

def mark_sent(msg):
    sent[msg] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# --- Chrome configuration ---
chrome_options = Options()
chrome_options.add_argument("--headless=new") 
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")
prefs = {
    "download.prompt_for_download": False,
    "directory_upgrade": True,
    "safebrowsing.enabled": False,
    "safebrowsing.disable_download_protection": True,
}
chrome_options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=chrome_options)

# --- Counters for summary ---
new_msgs = 0
skipped_msgs = 0
expired_msgs = 0

def process_table():
    """Process table rows on current page."""
    global new_msgs, skipped_msgs
    try:
        table = driver.find_element(By.XPATH, "//table")
        rows = table.find_elements(By.XPATH, ".//tbody//tr")

        for row in rows:
            try:
                col2 = row.find_element(By.XPATH, ".//td[2]").text.strip()
                col2 = row.find_element(By.XPATH, ".//td[3]").text.strip()
                col4 = row.find_element(By.XPATH, ".//td[4]").text.strip()
                cell = row.find_element(By.XPATH, ".//td[10]")

                try:
                    cell.find_element(By.XPATH, ".//i[contains(@class, 'fa-times')]")
                    msg = f"✔ Erro coluna 'Envio PDV' -> Filial: {col2} | Nome: {col3} | {col4}"
                    if msg not in sent:
                        logging.info(msg)
                        send_telegram_message(msg)
                        mark_sent(msg)
                        new_msgs += 1
                    else:
                        skipped_msgs += 1
                        logging.debug(f"Skipping duplicate: {msg}")
                except NoSuchElementException:
                    logging.debug(f"No checkmark for row {col2} | {col3} | {col4}")
            except Exception as row_err:
                logging.warning(f"Skipping a row due to error: {row_err}")
    except NoSuchElementException:
        logging.error("No table found on this page")

try:
    logging.info("Navigating to target URL and logging in")
    driver.get(os.getenv("WEBSITE"))

    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "/html/body/div[1]/div/div[2]/div/div[2]/div/form/div/div[1]/div/input"))).send_keys(username)
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "/html/body/div[1]/div/div[2]/div/div[2]/div/form/div/div[2]/div/input"))).send_keys(password)
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "/html/body/div[1]/div/div[2]/div/div[2]/div/form/div/div[3]/button"))).click()
    time.sleep(8)

    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "/html/body/div[1]/aside/div/div[4]/div/div/nav/ul/li[9]/a"))).click()
    time.sleep(8)

    data = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.ID, "orders_date_range")))
    data.clear()
    data.send_keys(date_range)
    data.send_keys(Keys.ENTER)
    time.sleep(8)

    # --- Process all pages ---
    while True:
        process_table()
        try:
            next_button = driver.find_element(By.XPATH, "//a[contains(., 'Próximo') or contains(., '›')]")
            driver.execute_script("arguments[0].scrollIntoView();", next_button)
            if "disabled" in next_button.get_attribute("class").lower():
                logging.info("Reached last page of the table.")
                break
            next_button.click()
            time.sleep(2)
        except NoSuchElementException:
            logging.info("No 'Next' button found; finished processing.")
            break

except Exception as e:
    logging.error(f"Error: {e}")
    # ts = time.strftime("%Y%m%d-%H%M%S")
    # driver.save_screenshot(f"screenshot_{ts}.png")
    # logging.info(f"Screenshot saved as screenshot_{ts}.png")

finally:
    # Save updated sent list
    before_cleanup = len(sent)
    save_sent(sent)
    after_cleanup = len(sent)
    expired_msgs = before_cleanup - after_cleanup

    # Summary
    summary = (
        f"Run summary:\n"
        f"• New messages sent: {new_msgs}\n"
        f"• Duplicates skipped: {skipped_msgs}\n"
        f"• Expired removed: {expired_msgs}"
    )
    logging.info(summary)
    # send_telegram_message(summary)

    driver.quit()
    logging.info("Browser closed and sent messages saved.")
