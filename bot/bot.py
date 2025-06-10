import os
import time
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException

# Токен вашего Telegram-бота
TOKEN = "7396044228:AAEdPkMYqWCQGKdGBRY4ctXEOZSEp_LPYV8"

# Пути к Chrome и ChromeDriver
CHROME_PATH = r"D:\chrome\chrome-win64\chrome.exe"
CHROMEDRIVER_PATH = r"D:\chrome\chromedriver-win64\chromedriver.exe"

# Настройка Selenium с undetected-chromedriver
def setup_driver():
    options = uc.ChromeOptions()
    options.binary_location = CHROME_PATH
    options.add_argument("--headless=new")  # Новый headless-режим
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-sync")
    # Прокси (раскомментируйте и укажите свой прокси, если есть)
    # options.add_argument("--proxy-server=http://your_proxy:port")
    service = Service(CHROMEDRIVER_PATH)
    driver = uc.Chrome(service=service, options=options)
    return driver

# Функция для загрузки и улучшения изображения
def process_image(image_path):
    start_time = time.time()
    driver = setup_driver()
    try:
        # Проверяем существование файла
        absolute_image_path = os.path.abspath(image_path)
        if not os.path.exists(absolute_image_path):
            raise FileNotFoundError(f"Файл {absolute_image_path} не найден")
        
        print(f"Абсолютный путь к изображению: {absolute_image_path}")
        print(f"Запуск браузера: {time.time() - start_time:.2f} сек")

        # Пытаемся загрузить сайт с повтором
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                driver.get("https://www.iloveimg.com/upscale-image")
                print(f"Сайт открыт (попытка {attempt + 1}): {time.time() - start_time:.2f} сек")
                break
            except TimeoutException:
                print(f"Попытка {attempt + 1} не удалась, повтор...")
                if attempt == max_attempts - 1:
                    raise Exception("Не удалось загрузить сайт после нескольких попыток")

        # Ждём появления input для загрузки файла
        upload_input = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        upload_input.send_keys(absolute_image_path)
        print(f"Изображение загружено: {time.time() - start_time:.2f} сек")

        # Ждём появления улучшенного изображения
        enhanced_image = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".img-comparison-slider__second img"))
        )
        enhanced_image_url = enhanced_image.get_attribute("src")
        print(f"URL улучшенного изображения: {enhanced_image_url}")
        print(f"Изображение обработано: {time.time() - start_time:.2f} сек")

        # Проверяем, есть ли ссылка на полное изображение
        try:
            download_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='download']"))
            )
            full_image_url = download_button.get_attribute("href")
            if full_image_url and not full_image_url.startswith("blob:"):
                enhanced_image_url = full_image_url
                print(f"Найдена прямая ссылка на полное изображение: {enhanced_image_url}")
        except TimeoutException:
            print("Прямая ссылка на скачивание не найдена, используем blob URL")

        # Скачиваем изображение
        if enhanced_image_url.startswith("blob:"):
            # Для blob URL используем JavaScript
            enhanced_image_data = driver.execute_script("""
                return fetch(arguments[0])
                    .then(response => response.blob())
                    .then(blob => new Promise(resolve => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    }));
            """, enhanced_image_url)
            if not enhanced_image_data.startswith("data:image"):
                raise Exception("Не удалось получить данные изображения")
            base64_string = enhanced_image_data.split(",")[1]
            img_data = base64.b64decode(base64_string)
        else:
            # Для прямой ссылки используем requests
            response = requests.get(enhanced_image_url, stream=True)
            response.raise_for_status()
            img_data = response.content

        # Сохраняем изображение
        enhanced_image_path = os.path.abspath("enhanced_image.jpg")
        with open(enhanced_image_path, "wb") as f:
            f.write(img_data)
        print(f"Изображение сохранено: {time.time() - start_time:.2f} сек")

        return enhanced_image_path
    finally:
        driver.quit()
        print(f"Браузер закрыт: {time.time() - start_time:.2f} сек")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправьте изображение, и я улучшу его!")

# Обработчик изображений
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    # Получаем изображение от пользователя
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    # Сохраняем изображение на диск
    image_path = os.path.abspath("input_image.jpg")
    await file.download_to_drive(image_path)

    # Сообщаем пользователю, что изображение обрабатывается
    processing_message = await update.message.reply_text("Обрабатываю изображение, пожалуйста, подождите...")

    try:
        # Обрабатываем изображение (функция process_image уже существует)
        enhanced_image_path = process_image(image_path)

        # Отправляем изображение как фото
        with open(enhanced_image_path, "rb") as photo_file:
            await update.message.reply_photo(photo=photo_file)

        # Отправляем изображение как документ
        with open(enhanced_image_path, "rb") as doc_file:
            await update.message.reply_document(document=doc_file, filename="enhanced_image.jpg")

        # Удаляем сообщение об обработке
        await processing_message.delete()

        # Удаляем временные файлы
        os.remove(image_path)
        os.remove(enhanced_image_path)
    except Exception as e:
        # В случае ошибки удаляем сообщение об обработке и сообщаем об ошибке
        await processing_message.delete()
        await update.message.reply_text(f"Произошла ошибка: {str(e)}")

def main():
    # Инициализация бота
    application = Application.builder().token(TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()