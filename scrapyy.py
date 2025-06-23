import time
import csv
import os
import zipfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CHROMEDRIVER_PATH = "/usr/local/bin/chromedriver"
CHROME_BINARY_PATH = "/opt/google/chrome-linux64/chrome"

BASE_URL = "https://www.pricecharting.com"
CATEGORY_URL = "https://www.pricecharting.com/category/pokemon-cards"
PROCESSED_CARDS_FILE = "scraped_cards.txt"
CSV_FILENAME = "allcorectpricees.csv"


def init_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920x1080")
    options.binary_location = CHROME_BINARY_PATH

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def fetch_console_urls(driver):
    driver.get(CATEGORY_URL)
    wait = WebDriverWait(driver, 10)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.sets")))
    except TimeoutException:
        print("Timeout waiting for console sets container.")
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href^='/console/']")
    # Filter out Japanese and Chinese sets
    return list({
        a.get_attribute("href") for a in anchors 
        if a.get_attribute("href").startswith(BASE_URL + "/console/pokemon")
        and "japanese" not in a.get_attribute("href").lower()
        and "chinese" not in a.get_attribute("href").lower()
    })


def get_card_links_from_console(driver, console_url):
    driver.get(console_url)
    time.sleep(2)
    card_links = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        cards = driver.find_elements(By.CSS_SELECTOR, "a[href^='/game/']")
        card_links.update(card.get_attribute('href') for card in cards)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    return list(card_links)


def clean_price(price_elem):
    if price_elem:
        text = price_elem.text.strip()
        return text if text != "-" else "N/A"
    return "N/A"


def should_skip_card(prices):
    """Check if any price is below $6.00"""
    for price in prices[:6]:  # Check all price fields (raw through PSA 10)
        if price != "N/A":
            try:
                price_value = float(price.replace('$', '').replace(',', ''))
                if price_value < 6.00:
                    return True
            except ValueError:
                continue
    return False


def fetch_card_data(driver, card_url):
    driver.get(card_url)
    wait = WebDriverWait(driver, 10)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1#product_name")))
    except TimeoutException:
        print(f"Timeout loading card page: {card_url}")
        return None
        
    # Skip Chinese cards by checking title
    name = driver.find_element(By.CSS_SELECTOR, "h1#product_name").text.strip()
    if any(word.lower() in name.lower() for word in ["Chinese", "China", "Asia"]):
        print(f"Skipping Chinese card: {name}")
        return None

    # Get price elements first to check if we should skip
    price_elements = driver.find_elements(By.CSS_SELECTOR, "span.price.js-price")
    prices = [clean_price(pe) for pe in price_elements[:6]]  # Get first 6 price fields
    
    # Skip if any price is below $6.00
    if should_skip_card(prices):
        print(f"Skipping card (price < $6.00): {card_url}")
        return None

    try:
        rarity = driver.find_element(By.CSS_SELECTOR, "td.details[itemprop='description']").text.strip()
    except NoSuchElementException:
        rarity = "none"
    try:
        model_number = driver.find_element(By.CSS_SELECTOR, "td.details[itemprop='model-number']").text.strip()
    except NoSuchElementException:
        model_number = "N/A"
    image_url = next((img.get_attribute("src") for img in driver.find_elements(By.CSS_SELECTOR, "img") if img.get_attribute("src") and "1600.jpg" in img.get_attribute("src")), "N/A")
    
    return {
        "Name": name,
        "Raw Price": prices[0] if len(prices) > 0 else "N/A",
        "Grade 7 Price": prices[1] if len(prices) > 1 else "N/A",
        "Grade 8 Price": prices[2] if len(prices) > 2 else "N/A",
        "Grade 9 Price": prices[3] if len(prices) > 3 else "N/A",
        "Grade 9.5 Price": prices[4] if len(prices) > 4 else "N/A",
        "PSA 10 Price": prices[5] if len(prices) > 5 else "N/A",
        "Rarity": rarity,
        "Model Number": model_number,
        "Image URL": image_url,
        "Card URL": card_url
    }


def save_to_csv(data, filename=CSV_FILENAME, write_header=False, mode='a'):
    if not data:
        print("No data to save.")
        return
    with open(filename, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(data)
    print(f"Saved to {filename}")


def zip_csv_file(csv_filename=CSV_FILENAME, zip_filename="allcorectpricees.zip"):
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(csv_filename, arcname=os.path.basename(csv_filename))
    print(f"Zipped to {zip_filename}")


def load_processed_cards():
    if not os.path.exists(PROCESSED_CARDS_FILE):
        return set()
    with open(PROCESSED_CARDS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def main():
    driver = init_driver()
    try:
        console_urls = fetch_console_urls(driver)
        processed_cards = load_processed_cards()
        all_cards_data = []
        first_save = True
        processed_count = 0
        for console_url in console_urls:
            print(f"Processing console: {console_url}")
            card_links = get_card_links_from_console(driver, console_url)
            for i, card_url in enumerate(card_links, 1):
                if card_url in processed_cards:
                    continue
                print(f"Scraping card {i}/{len(card_links)}: {card_url}")
                card_data = fetch_card_data(driver, card_url)
                if card_data:
                    all_cards_data.append(card_data)
                    with open(PROCESSED_CARDS_FILE, "a", encoding="utf-8") as f:
                        f.write(card_url + "\n")
                    processed_cards.add(card_url)
                    processed_count += 1
                if processed_count % 10 == 0:
                    save_to_csv(all_cards_data, write_header=first_save)
                    all_cards_data = []
                    first_save = False
                if processed_count > 0 and processed_count % 500 == 0:
                    zip_csv_file()
                time.sleep(1)
        if all_cards_data:
            save_to_csv(all_cards_data, write_header=first_save)
    finally:
        driver.quit()
        print("Driver closed.")


if __name__ == "__main__":
    main()