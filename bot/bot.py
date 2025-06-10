import os
import time
import requests
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException

# ——— Настройки ———————————————————————————————————————————————
TOKEN = "7396044228:AAEdPkMYqWCQGKdGBRY4ctXEOZSEp_LPYV8"
CHROME_PATH = r"D:\chrome\chrome-win64\chrome.exe"
CHROMEDRIVER_PATH = r"D:\chrome\chromedriver-win64\chromedriver.exe"

# Максимальное число одновременных обработок (число потоков)
MAX_WORKERS = 3

# Создаём глобальный ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


# ——— Утилитарные функции для Selenium ——————————————————————————

def setup_driver():
    """
    Создаёт и возвращает экземпляр undetected_chromedriver.Chrome в headless-режиме.
    """
    options = uc.ChromeOptions()
    options.binary_location = CHROME_PATH
    options.add_argument("--headless=new")
    service = Service(CHROMEDRIVER_PATH)
    driver = uc.Chrome(service=service, options=options)
    return driver


def process_image_sync(image_path: str, resolution: str = "2K") -> str:
    """
    Синхронно: открывает WebDriver, загружает на iloveimg.com, ждёт обработки,
    скачивает результат и сохраняет его в файл. Возвращает путь к готовому файлу.

    Если возникает TimeoutException при выборе 4K, выбрасывает Exception с текстом ошибки.
    """
    start_time = time.time()
    driver = setup_driver()
    try:
        # 1) Открываем новую вкладку для апскейла
        driver.execute_script("window.open('https://www.iloveimg.com/upscale-image', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])

        # Проверим, что файл есть
        absolute_image_path = os.path.abspath(image_path)
        if not os.path.exists(absolute_image_path):
            raise FileNotFoundError(f"Файл {absolute_image_path} не найден")

        # 2) Загружаем изображение на страницу
        upload_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        upload_input.send_keys(absolute_image_path)

        # 3) Дождаться, пока появится элемент с апскейленым изображением (preliminary view)
        enhanced_image = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".img-comparison-slider__second img"))
        )

        # 4) Если пользователь выбрал 4K, нажимаем соответствующий множитель
        if resolution == "4K":
            try:
                multiplier_4x = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "li[data-name='multiplier'][data-value='4']"))
                )
                old_src = enhanced_image.get_attribute("src")
                multiplier_4x.click()
                # Ждём, пока src у картинки реально поменяется на новый (4K результат)
                WebDriverWait(driver, 60).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, ".img-comparison-slider__second img").get_attribute("src") != old_src
                )
            except TimeoutException:
                raise Exception("Не удалось выбрать 4x. Возможно, требуется премиум-аккаунт.")

        # 5) Получаем URL готовой картинки (после апскейла)
        enhanced_image = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".img-comparison-slider__second img"))
        )
        enhanced_image_url = enhanced_image.get_attribute("src")

        # 6) Пытаемся найти прямую кнопку «Download»
        try:
            download_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='download']"))
            )
            full_image_url = download_button.get_attribute("href")
            # Если ссылка не blob, используем её
            if full_image_url and not full_image_url.startswith("blob:"):
                enhanced_image_url = full_image_url
        except TimeoutException:
            # Если прямой ссылки нет — будем вытаскивать через blob
            pass

        # 7) Скачиваем данные картинки
        if enhanced_image_url.startswith("blob:"):
            # извлечение base64 из blob-URI
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
                raise Exception("Не удалось получить данные изображения через blob.")
            base64_string = enhanced_image_data.split(",")[1]
            img_data = base64.b64decode(base64_string)
        else:
            response = requests.get(enhanced_image_url, stream=True)
            response.raise_for_status()
            img_data = response.content

        # 8) Сохраняем результат в файл
        enhanced_image_path = os.path.abspath(f"enhanced_image_{resolution}_{int(time.time())}.jpg")
        with open(enhanced_image_path, "wb") as f:
            f.write(img_data)

        return enhanced_image_path

    finally:
        # Закрываем вкладку и уменьшаем количество открытых драйверов
        try:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass
        driver.quit()


# ——— Асинхронные обработчики сообщений бота —————————————————————————

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправьте изображение, и я его апскейлю до 2K или 4K.")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    При получении фото: скачиваем во временный файл, сохраняем по message_id в chat_data,
    предлагаем выбрать разрешение (2K/4K).
    """
    photo = update.message.photo[-1]
    file = await photo.get_file()

    image_path = os.path.abspath(f"input_image_{update.message.message_id}.jpg")
    await file.download_to_drive(image_path)
    context.chat_data[update.message.message_id] = image_path

    button_list = [
        InlineKeyboardButton("2K", callback_data=f"2K_{update.message.message_id}"),
        InlineKeyboardButton("4K", callback_data=f"4K_{update.message.message_id}")
    ]
    reply_markup = InlineKeyboardMarkup([button_list])
    await update.message.reply_text("Выберите разрешение:", reply_markup=reply_markup)


async def handle_resolution_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка нажатия кнопки с выбором разрешения.
    Запускаем фоновый поток с process_image_sync и, когда файл готов — отправляем фото/документ.
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    resolution, msg_id_str = data.split("_")
    message_id = int(msg_id_str)

    image_path = context.chat_data.get(message_id)
    if not image_path:
        await query.message.reply_text("Изображение не найдено или устарело.")
        return

    # Удаляем сообщение с кнопками
    await query.message.delete()

    # Отправляем сообщение о начале обработки
    processing_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Обрабатываю изображение (это может занять до 1 минуты)..."
    )

    chat_id = query.message.chat_id
    bot = context.bot

    # Функция-обёртка для фонового запуска в executor
    def background_task(path: str, res: str):
        """
        Этот код выполнится в потоке: запустит процессинг и вернёт путь к готовому файлу.
        Если будет исключение, оно всплывёт в Future и попадёт в done_callback.
        """
        # Здесь мы вызываем синхронный процессинг
        return process_image_sync(path, res)

    loop = asyncio.get_event_loop()
    # Запускаем process_image_sync в пуле потоков
    future = loop.run_in_executor(executor, background_task, image_path, resolution)

    # Когда фоновой поток вернёт результат (или исключение), мы попадём в этот callback
    def on_done(fut: asyncio.Future):
        """
        Этот callback выполняется в потоке-менеджере asyncio после завершения process_image_sync.
        Здесь мы вызываем асинхронную отправку результата.
        """
        try:
            enhanced_path = fut.result()  # если было исключение — сюда провалится
            # Запускаем асинхронную функцию для отправки результата
            asyncio.create_task(send_result_and_cleanup(
                bot=bot,
                chat_id=chat_id,
                enhanced_image_path=enhanced_path,
                orig_image_path=image_path,
                processing_message_id=processing_message.message_id,
                message_id_key=message_id,
                context=context,
                resolution=resolution
            ))
        except Exception as e:
            # В случае ошибки тоже отправим пользователю сообщение
            asyncio.create_task(send_error_and_cleanup(
                bot=bot,
                chat_id=chat_id,
                error_message=str(e),
                processing_message_id=processing_message.message_id,
                orig_image_path=image_path,
                message_id_key=message_id,
                context=context
            ))

    # Привязываем callback
    future.add_done_callback(on_done)


async def send_result_and_cleanup(
    bot,
    chat_id: int,
    enhanced_image_path: str,
    orig_image_path: str,
    processing_message_id: int,
    message_id_key: int,
    context: ContextTypes.DEFAULT_TYPE,
    resolution: str
):
    """
    Асинхронная функция, которой мы передаём готовый файл: отправляем фото и документ,
    удаляем временные файлы, удаляем запись из chat_data и удаляем сообщение 'обрабатываю'.
    """
    try:
        # 1) Отправляем изображение как фото
        with open(enhanced_image_path, "rb") as photo_file:
            await bot.send_photo(chat_id=chat_id, photo=photo_file)

        # 2) Отправляем изображение как документ (чтобы было удобно скачать исходник)
        with open(enhanced_image_path, "rb") as doc_file:
            await bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                filename=f"enhanced_image_{resolution}.jpg"
            )
    except Exception as e:
        # Если что-то пошло не так при отправке результата
        await bot.send_message(chat_id=chat_id, text=f"Ошибка при отправке результата: {str(e)}")

    finally:
        # 3) Удаляем сообщение "Обрабатываю..."
        try:
            await bot.delete_message(chat_id=chat_id, message_id=processing_message_id)
        except:
            pass

        # 4) Удаляем временные файлы
        try:
            os.remove(orig_image_path)
        except:
            pass
        try:
            os.remove(enhanced_image_path)
        except:
            pass

        # 5) Удаляем запись из chat_data
        if message_id_key in context.chat_data:
            del context.chat_data[message_id_key]


async def send_error_and_cleanup(
    bot,
    chat_id: int,
    error_message: str,
    processing_message_id: int,
    orig_image_path: str,
    message_id_key: int,
    context: ContextTypes.DEFAULT_TYPE
):
    """
    Асинхронно сообщаем пользователю об ошибке, очищаем временные файлы и запись в chat_data.
    """
    # 1) Удаляем сообщение "Обрабатываю..."
    try:
        await bot.delete_message(chat_id=chat_id, message_id=processing_message_id)
    except:
        pass

    # 2) Отправляем ошибку
    await bot.send_message(chat_id=chat_id, text=f"Произошла ошибка при обработке: {error_message}")

    # 3) Удаляем временные файлы
    try:
        os.remove(orig_image_path)
    except:
        pass

    # 4) Удаляем запись из chat_data
    if message_id_key in context.chat_data:
        del context.chat_data[message_id_key]


def main():
    """
    Точка входа: создаём Application, регистрируем хендлеры и запускаем polling.
    """
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CallbackQueryHandler(handle_resolution_choice))

    application.run_polling()


if __name__ == "__main__":
    main()
