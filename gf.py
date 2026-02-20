import asyncio
import logging
import aiohttp
import feedparser
from datetime import datetime, timedelta, time as dt_time
import html
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from google import genai
import requests
import re
import json
import os
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import urllib.parse
from bs4 import BeautifulSoup
import random
import pytz
from urllib.parse import quote_plus
import certifi
import ssl
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import io
import base64
from typing import Dict, List, Optional, Tuple
import statistics
import brotli
import warnings
from bs4 import XMLParsedAsHTMLWarning
import urllib3

# Отключаем предупреждения
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BotStates(StatesGroup):
    waiting_for_new_channel = State()
    waiting_for_channel_category = State()
    waiting_for_channel_posts = State()
    waiting_for_channel_template = State()
    waiting_for_template_file = State()
    waiting_for_auto_post_times = State()
    waiting_for_posts_per_day = State()
    adding_channel_name = State()
    waiting_for_channel_time_mode = State()
    waiting_for_channel_fixed_times = State()
    waiting_for_channel_random_settings = State()
    waiting_for_channel_min_interval = State()
    waiting_for_gemini_key = State()
    waiting_for_ignore_word = State()
    waiting_for_ignore_word_remove = State()
    waiting_for_template_upload = State()
    waiting_for_template_text = State()

class Config:
    BOT_TOKEN = "8513980572:AAHcLPx_RDL9N7BGI2ZOvOx9tFM-_h5ge5o"
    ADMIN_ID = "738224527"
    
    # Максимальная длина подписи в Telegram (с запасом)
    MAX_CAPTION_LENGTH = 1200
    
    # Источники по категориям
    SOURCES_BY_CATEGORY = {
        "it": {
            "gagadget": "https://gagadget.com/feed/",
            "habr": "https://habr.com/ru/rss/news/?fl=ru",
            "google_tech": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pOV1NnQVAB?hl=ru&gl=RU&ceid=RU:ru"
        },
        "games": {
            "stopgame": "https://stopgame.ru/rss/rss_news.xml",
            "playground": "https://www.playground.ru/rss/news.xml",
            "ign": "https://feeds.ign.com/ign/news?format=xml",
            "gamespot": "https://www.gamespot.com/feeds/news/",
            "vgtimes": "https://vgtimes.ru/feeds/news.xml"
        },
        "media": {
            "iz": "https://iz.ru/tag/smi",
            "lenta": "https://lenta.ru/rubrics/media/",
            "tass": "https://tass.ru/rss/v2.xml"
        },
        "economics": {
            "rbc_economics": "https://www.rbc.ru/rubric/economics",
            "tass_economics": "https://tass.ru/ekonomika",
            "rbc_finances": "https://www.rbc.ru/rubric/finances",
            "rbc_rss": "https://rssexport.rbc.ru/rbcnews/news?format=xml"
        }
    }
    
    # Пользовательский агент для запросов
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

    SETTINGS_FILE = "bot_settings.json"
    PROCESSED_NEWS_FILE = "processed_news.json"
    CHANNELS_FILE = "channels.json"
    TEMPLATES_DIR = "templates"
    
    # Ключевые слова для игнора новостей (глобальные)
    IGNORE_KEYWORDS = [
        "amazon", "сериал", "фильм", "шоу", "ebay", 
        "актёры", "актёр", "актриса", "netflix", "disney",
        "hbo", "кинопрокат", "премьера", "режиссёр"
    ]

storage = MemoryStorage()
bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# Модели Gemini
GEMINI_MODELS = {
    "gemini-3-flash-preview": "Gemini 3 Flash Preview (самый быстрый)",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite (оптимальный)",
    "gemini-2.5-flash": "Gemini 2.5 Flash (самый качественный)"
}

processed_news = set()
temp_processed_news_for_test = set()  # Для временного хранения обработанных новостей в тестовых постах

# Настройки бота
bot_settings = {
    "channels": {},
    "templates": {},
    "add_game_links": False,
    "blur_logos": True,
    "get_full_text": True
}

auto_post_tasks = {}
posting_locks = {}
post_schedulers = {}

class NewsItem:
    def __init__(self, title: str, link: str, description: str, pub_date: str, 
                 image_url: str = None, source: str = "", category: str = "", full_text: str = ""):
        self.title = title
        self.link = link
        self.description = description
        self.pub_date = pub_date
        self.image_url = image_url
        self.source = source
        self.category = category
        self.full_text = full_text
        self.guid = link

def extract_markdown_links(text: str) -> str:
    if not text:
        return text
    
    def replace_markdown_link(match):
        link_text = match.group(1)
        link_url = match.group(2)
        return f'<a href="{link_url}">{link_text}</a>'
    
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_markdown_link, text)
    
    url_pattern = r'(https?://[^\s<>]+|[^\s<>]+\.[^\s<>]+)'
    
    def url_replacer(match):
        url = match.group(1)
        if not re.search(r'<a[^>]*>' + re.escape(url) + r'</a>', text):
            return f'<a href="{url}">{url}</a>'
        return url
    
    text = re.sub(url_pattern, url_replacer, text)
    
    return text

def clean_html_tags(html_text: str) -> str:
    if not html_text:
        return ""
    
    try:
        soup = BeautifulSoup(html_text, 'html.parser')
        return str(soup)
    except Exception as e:
        logger.error(f"Ошибка при очистке HTML: {e}")
        return html_text

def fix_html_structure(html_text: str) -> str:
    if not html_text:
        return ""
    
    allowed_tags = {
        'b', 'i', 'u', 'code', 'pre', 'blockquote', 'a',
        'strong', 'em', 'span', 'div', 'p', 'br', 'hr'
    }
    
    closing_tags = {
        'b': '</b>', 'i': '</i>', 'u': '</u>', 'code': '</code>',
        'pre': '</pre>', 'blockquote': '</blockquote>', 'a': '</a>',
        'strong': '</strong>', 'em': '</em>', 'span': '</span>',
        'div': '</div>', 'p': '</p>'
    }
    
    link_pattern = r'<a\s+[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
    links = []
    for match in re.finditer(link_pattern, html_text):
        href = match.group(1)
        text = match.group(2)
        links.append((href, text))
        html_text = html_text.replace(match.group(0), f'__LINK_{len(links)-1}__')
    
    def remove_disallowed_tags(text):
        tags = re.findall(r'<([/a-zA-Z0-9]+)(?:\s[^>]*)?>', text)
        for tag in tags:
            if tag.startswith('/'):
                tag_name = tag[1:].lower()
            else:
                tag_name = tag.lower().split()[0] if ' ' in tag else tag.lower()
            
            if tag_name not in allowed_tags:
                text = re.sub(f'<{tag}(?:\\s[^>]*)?>', '', text)
                text = re.sub(f'</{tag}>', '', text)
        return text
    
    html_text = remove_disallowed_tags(html_text)
    
    stack = []
    result = []
    i = 0
    
    while i < len(html_text):
        if html_text[i] == '<':
            j = html_text.find('>', i)
            if j == -1:
                result.append(html_text[i])
                i += 1
                continue
            
            tag_full = html_text[i:j+1]
            
            if tag_full.startswith('</'):
                tag_name = tag_full[2:-1].split()[0].lower()
                if tag_name in allowed_tags:
                    found = False
                    for idx in range(len(stack)-1, -1, -1):
                        if stack[idx][0] == tag_name:
                            while stack:
                                open_tag_name, open_tag_full = stack.pop()
                                result.append(closing_tags.get(open_tag_name, f'</{open_tag_name}>'))
                                if open_tag_name == tag_name:
                                    found = True
                                    break
                            break
                    
                    if not found:
                        pass
            elif tag_full.endswith('/>'):
                result.append(tag_full)
            else:
                tag_name = tag_full[1:-1].split()[0].lower()
                if tag_name in allowed_tags:
                    stack.append((tag_name, tag_full))
                    result.append(tag_full)
                else:
                    pass
            
            i = j + 1
        else:
            next_tag = html_text.find('<', i)
            if next_tag == -1:
                result.append(html_text[i:])
                break
            result.append(html_text[i:next_tag])
            i = next_tag
    
    while stack:
        tag_name, _ = stack.pop()
        result.append(closing_tags.get(tag_name, f'</{tag_name}>'))
    
    result_text = ''.join(result)
    
    for idx, (href, text) in enumerate(links):
        placeholder = f'__LINK_{idx}__'
        result_text = result_text.replace(placeholder, f'<a href="{href}">{text}</a>')
    
    for tag in allowed_tags:
        result_text = re.sub(f'<{tag}>\\s*</{tag}>', '', result_text)
    
    return result_text

def validate_html(text: str) -> str:
    if not text:
        return text
    
    allowed_tags = {
        'b', 'i', 'u', 'code', 'pre', 'blockquote', 'a',
        'strong', 'em', 'span', 'div', 'p', 'br', 'hr'
    }
    
    try:
        soup = BeautifulSoup(text, 'html.parser')
        
        for tag in soup.find_all(True):
            if tag.name not in allowed_tags:
                tag.unwrap()
            elif tag.name == 'a':
                if 'href' in tag.attrs:
                    href = tag['href']
                    if not href.startswith(('http://', 'https://', 't.me/', 'tg://')):
                        tag.name = 'span'
                        del tag['href']
                else:
                    tag.name = 'span'
            elif tag.name == 'blockquote' and 'expandable' in tag.attrs:
                pass
            else:
                tag.attrs = {}
        
        cleaned = str(soup)
        
        cleaned = cleaned.replace('<html><body>', '').replace('</body></html>', '')
        cleaned = cleaned.replace('<body>', '').replace('</body>', '')
        cleaned = cleaned.replace('<html>', '').replace('</html>', '')
        
        cleaned = fix_html_structure(cleaned)
        
        return cleaned.strip()
        
    except Exception as e:
        logger.error(f"Ошибка валидации HTML: {e}")
        return re.sub(r'<[^>]+>', '', text)

def apply_markdown_formatting(text: str) -> str:
    if not text:
        return text
    
    text = extract_markdown_links(text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
    text = re.sub(r'~~(.*?)~~', r'<u>\1</u>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    
    text = validate_html(text)
    
    return text

def get_default_image() -> str:
    default_images = [
        "https://images.unsplash.com/photo-1518709268805-4e9042af2176",
        "https://images.unsplash.com/photo-1550745165-9bc0b252726f",
        "https://images.unsplash.com/photo-1538481199705-c710c4e965fc",
        "https://images.unsplash.com/photo-1511512578047-dfb367046420",
        "https://images.unsplash.com/photo-1542751371-adc38448a05e",
        "https://images.unsplash.com/photo-1552820728-8b83bb6b773f"
    ]
    return random.choice(default_images)

def get_bing_image_url(query: str) -> str:
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        search_query = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/images/search?q={search_query}&first=1"
        
        ssl._create_default_https_context = ssl._create_unverified_context
        
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        image_elements = soup.find_all('a', class_='iusc')
        
        if not image_elements:
            return get_default_image()
        
        first_image = image_elements[0]
        m_attr = first_image.get('m')
        if m_attr:
            try:
                image_data = json.loads(m_attr)
                image_url = image_data.get('murl')
                if image_url and image_url.startswith(('http://', 'https://')):
                    return image_url
            except:
                pass
        
        return get_default_image()
            
    except Exception as e:
        logger.error(f"Ошибка при получении изображения из Bing: {e}")
        return get_default_image()

def extract_keywords_for_image_search(text: str) -> str:
    clean_text = re.sub(r'<[^>]+>', '', text).lower()
    
    sentences = re.split(r'[.!?]', clean_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return "новости"
    
    title = sentences[0]
    if len(sentences) > 1 and len(title.split()) < 8:
        title += " " + sentences[1]
    
    words = title.split()[:12]
    title = " ".join(words)
    
    stop_words = {
        'и', 'в', 'на', 'с', 'по', 'для', 'не', 'что', 'а', 'то', 'все', '但', 'да', 'вы', 'за', ' бы', 'от', 'о',
        'из', 'у', 'же', 'ну', 'ли', 'если', 'уже', '或', ' ни', 'до', 'вас', 'вам', 'ей', 'они', 'тут', 'где',
        'есть', 'мы', 'тебя', 'их', 'чем', 'сам', 'без', 'раз', 'тоже', 'себе', 'под', 'ж', 'тогда', 'кто', 'этот',
        'того', 'потому', 'какой', 'ここに', 'один', 'мой', 'тем', 'чтобы', 'нее', 'сейчас', 'куда', 'зачем', 'всех',
        'никогда', '可以', 'при', 'два', 'об', 'другой', 'после', 'над', 'больше', 'тот', 'через', 'эти', 'нас',
        'про', 'всего', 'них', 'много', 'три', 'моя', 'хорошо', 'свою', 'этой', 'перед', 'лучше', 'том', 'такой',
        'им', 'более', 'всегда', 'конечно', 'всю', 'meжду'
    }
    
    words = title.split()
    filtered_words = [word for word in words if word.lower() not in stop_words and len(word) > 2]
    
    if not filtered_words:
        return "новости"
    
    keywords = filtered_words[:5]
    text_lower = clean_text.lower()
    theme_keywords = []
    
    if any(word in text_lower for word in ['игр', 'гейм', 'консоль', 'пк', 'приставк', 'steam']):
        theme_keywords.extend(['игры', 'гейминг', 'игровая индустрия'])
    if any(word in text_lower for word in ['новост', 'обновлен', 'анонс', 'релиз']):
        theme_keywords.extend(['новости', 'обновления'])
    if any(word in text_lower for word in ['технолог', 'it', 'программир', 'компьютер']):
        theme_keywords.extend(['технологии', 'it', 'программирование'])
    if any(word in text_lower for word in ['сми', 'медиа', 'новост', 'журнал']):
        theme_keywords.extend(['сми', 'медиа', 'новости'])
    if any(word in text_lower for word in ['экономик', 'финанс', 'бирж', 'акци', 'рубл', 'доллар', 'инвест']):
        theme_keywords.extend(['экономика', 'финансы', 'инвестиции'])
    
    all_keywords = keywords + theme_keywords[:2]
    result = " ".join(all_keywords)
    
    return result if result.strip() else "новости"

def get_relevant_image(query: str) -> str:
    try:
        enhanced_query = f"{query} новости"
        result = get_bing_image_url(enhanced_query)
        
        if result and result.startswith(('http://', 'https://')):
            return result
        else:
            return get_default_image()
            
    except Exception as e:
        logger.error(f"Ошибка при получении изображения: {e}")
        return get_default_image()

def get_msk_now() -> datetime:
    msk_tz = pytz.timezone('Europe/Moscow')
    return datetime.now(msk_tz)

def save_settings():
    try:
        with open(Config.SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bot_settings, f, ensure_ascii=False, indent=2)
        logger.debug("Настройки сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")

def load_settings():
    global bot_settings
    try:
        if os.path.exists(Config.SETTINGS_FILE):
            with open(Config.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for key in bot_settings:
                    if key in loaded:
                        bot_settings[key] = loaded[key]
            logger.info("Настройки загружены")
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")

def save_processed_news():
    try:
        with open(Config.PROCESSED_NEWS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(processed_news), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения обработанных новостей: {e}")

def load_processed_news():
    global processed_news
    try:
        if os.path.exists(Config.PROCESSED_NEWS_FILE):
            with open(Config.PROCESSED_NEWS_FILE, 'r', encoding='utf-8') as f:
                loaded_news = json.load(f)
                processed_news = set(loaded_news)
            logger.info(f"Загружено {len(processed_news)} обработанных новостей")
    except Exception as e:
        logger.error(f"Ошибка загрузки обработанных новостей: {e}")

def save_channels():
    try:
        with open(Config.CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bot_settings["channels"], f, ensure_ascii=False, indent=2)
        logger.debug("Каналы сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения каналов: {e}")

def load_channels():
    try:
        if os.path.exists(Config.CHANNELS_FILE):
            with open(Config.CHANNELS_FILE, 'r', encoding='utf-8') as f:
                bot_settings["channels"] = json.load(f)
            logger.info(f"Загружено {len(bot_settings['channels'])} каналов")
    except Exception as e:
        logger.error(f"Ошибка загрузки каналов: {e}")

def load_templates_from_files():
    templates = {}
    
    if not os.path.exists(Config.TEMPLATES_DIR):
        os.makedirs(Config.TEMPLATES_DIR)
        logger.info(f"Создана папка {Config.TEMPLATES_DIR}")
        return templates
    
    for filename in os.listdir(Config.TEMPLATES_DIR):
        if filename.lower().endswith('.txt'):  # Исправлено: проверяем в нижнем регистре
            template_name = filename[:-4]  # Удаляем .txt (4 символа)
            try:
                with open(os.path.join(Config.TEMPLATES_DIR, filename), 'r', encoding='utf-8') as f:
                    content = f.read()
                    templates[template_name] = content
                logger.info(f"Загружен шаблон: {template_name}")
            except Exception as e:
                logger.error(f"Ошибка загрузки шаблона {filename}: {e}")
    
    bot_settings["templates"] = templates
    return templates

def detect_logo_regions(image: Image.Image) -> list:
    """
    Определяет области, которые могут содержать логотипы и названия сайтов
    """
    img_width, img_height = image.size
    
    # Области, где обычно находятся логотипы и названия сайтов
    logo_regions = [
        # Верхние углы (часто логотипы)
        (0, 0, img_width // 4, img_height // 8),
        (img_width * 3 // 4, 0, img_width, img_height // 8),
        
        # Нижние углы (водяные знаки, копирайты)
        (0, img_height * 7 // 8, img_width // 4, img_height),
        (img_width * 3 // 4, img_height * 7 // 8, img_width, img_height),
        
        # Центр верхней части (названия в статьях)
        (img_width // 4, 0, img_width * 3 // 4, img_height // 10),
        
        # Боковые области (водяные знаки)
        (0, 0, img_width // 10, img_height),
        (img_width * 9 // 10, 0, img_width, img_height),
    ]
    
    return logo_regions

def apply_logo_blur(image_bytes: bytes) -> bytes:
    """
    Применяет размытие к логотипам и названиям сайтов на изображении
    """
    if not bot_settings["blur_logos"]:
        return image_bytes
    
    try:
        # Открываем изображение
        img = Image.open(io.BytesIO(image_bytes))
        img_width, img_height = img.size
        
        # Определяем области с логотипами
        logo_regions = detect_logo_regions(img)
        
        # Создаем маску для размытия
        blurred_img = img.copy()
        
        for region in logo_regions:
            # Вырезаем область
            logo_area = img.crop(region)
            
            # Размываем область (увеличил радиус для лучшего эффекта)
            blurred_area = logo_area.filter(ImageFilter.GaussianBlur(radius=8))
            
            # Вставляем размытую область обратно
            blurred_img.paste(blurred_area, region)
        
        # Конвертируем обратно в bytes
        output = io.BytesIO()
        if image_bytes[:2] == b'\xff\xd8':  # JPEG
            blurred_img.save(output, format='JPEG', quality=90)
        elif image_bytes[:8] == b'\x89PNG\r\n\x1a\n':  # PNG
            blurred_img.save(output, format='PNG')
        else:
            blurred_img.save(output, format='JPEG', quality=90)
        
        output.seek(0)
        
        return output.read()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке логотипов: {e}")
        return image_bytes  # Возвращаем оригинал в случае ошибки

async def fetch_full_article(url: str, source_name: str) -> str:
    """Получает полный текст статьи по ссылке"""
    full_text = ""
    
    try:
        # Для habr используем особый подход из-за проблем с SSL
        if source_name == "habr":
            try:
                response = requests.get(url, headers=Config.HEADERS, timeout=15, verify=False)
                if response.status_code == 200:
                    content = response.text
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Удаляем ненужные элементы
                    for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                        element.decompose()
                    
                    # Для Habr
                    article_content = soup.find('div', class_='tm-article-body')
                    if article_content:
                        paragraphs = article_content.find_all(['p', 'h2', 'h3', 'li'])
                        for p in paragraphs:
                            text = p.get_text(strip=True)
                            if text and len(text) > 20:
                                full_text += text + "\n\n"
            except Exception as e:
                logger.error(f"Ошибка при запросе Habr: {e}")
                return full_text
        
        else:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(headers=Config.HEADERS, connector=connector) as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        content = await response.text()
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # Удаляем ненужные элементы
                        for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                            element.decompose()
                        
                        # Стратегии извлечения текста для разных сайтов
                        if source_name == "stopgame":
                            # Для StopGame
                            article_content = soup.find('article')
                            if not article_content:
                                article_content = soup.find('div', class_=['article-content', 'post-content', 'content'])
                            
                            if article_content:
                                paragraphs = article_content.find_all(['p', 'div'])
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:  # Фильтруем короткие тексты
                                        full_text += text + "\n\n"
                        
                        elif source_name == "playground":
                            # Для Playground.ru
                            article_content = soup.find('div', class_='article-text')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "ign":
                            # Для IGN
                            article_content = soup.find('div', {'data-role': 'articleBody'})
                            if not article_content:
                                article_content = soup.find('div', class_='article-content')
                            
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "gamespot":
                            # Для GameSpot
                            article_content = soup.find('div', class_='js-content-entity-body')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "vgtimes":
                            # Для VGTimes
                            article_content = soup.find('div', class_='news__text')
                            if article_content:
                                paragraphs = article_content.find_all(['p', 'h2', 'h3'])
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "gagadget":
                            # Для Gagadget
                            article_content = soup.find('div', class_='post-content')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "iz":
                            # Для Известий
                            article_content = soup.find('div', class_='text')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "lenta":
                            # Для Ленты.ру
                            article_content = soup.find('div', class_='topic-body__content')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "tass" or source_name == "tass_economics":
                            # Для ТАСС
                            article_content = soup.find('div', class_='text-block')
                            if article_content:
                                paragraphs = article_content.find_all('p')
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        elif source_name == "rbc_economics" or source_name == "rbc_finances":
                            # Для РБК
                            article_content = soup.find('div', class_='article__text')
                            if not article_content:
                                article_content = soup.find('div', class_='l-col-main')
                            
                            if article_content:
                                paragraphs = article_content.find_all(['p', 'h2', 'h3', 'li'])
                                for p in paragraphs:
                                    text = p.get_text(strip=True)
                                    if text and len(text) > 20:
                                        full_text += text + "\n\n"
                        
                        else:
                            # Универсальный метод
                            text_selectors = [
                                'article', 
                                'div[class*="content"]', 
                                'div[class*="article"]',
                                'div[class*="post"]',
                                'div[class*="text"]',
                                'main',
                                '.entry-content',
                                '.post-content',
                                '.article-content'
                            ]
                            
                            for selector in text_selectors:
                                article_content = soup.select_one(selector)
                                if article_content:
                                    paragraphs = article_content.find_all(['p', 'h2', 'h3', 'li'])
                                    for p in paragraphs:
                                        text = p.get_text(strip=True)
                                        if text and len(text) > 20:
                                            full_text += text + "\n\n"
                                    break
                        
                        # Если не нашли по специфичным селекторам, используем общий подход
                        if not full_text:
                            all_paragraphs = soup.find_all(['p', 'div'])
                            for p in all_paragraphs:
                                text = p.get_text(strip=True)
                                if len(text) > 100:
                                    full_text += text + "\n\n"
        
        # Очищаем текст от лишних пробелов и переносов
        full_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', full_text)
        full_text = full_text.strip()
        
        if full_text:
            logger.info(f"✅ Получен полный текст статьи ({len(full_text)} символов)")
        else:
            logger.warning(f"⚠️ Не удалось извлечь полный текст статьи")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении полного текста статьи {url}: {e}")
    
    return full_text

async def parse_rss_feed(url: str, source_name: str, category: str = "") -> list[NewsItem]:
    news_items = []
    
    try:
        # Для habr используем requests из-за проблем с SSL
        if source_name == "habr":
            try:
                response = requests.get(url, headers=Config.HEADERS, timeout=15, verify=False)
                if response.status_code == 200:
                    content = response.text
                else:
                    logger.error(f"Ошибка HTTP {response.status_code} для {url}")
                    return news_items
            except Exception as e:
                logger.error(f"Ошибка при запросе {source_name}: {e}")
                return news_items
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10, headers=Config.HEADERS) as response:
                    if response.status == 200:
                        content = await response.text()
                    else:
                        logger.error(f"Ошибка HTTP {response.status} для {url}")
                        return news_items
        
        feed = feedparser.parse(content)
        
        for entry in feed.entries[:15]:
            try:
                # Проверка на ключевые слова для игнора (глобальные)
                title_lower = entry.title.lower()
                if any(keyword.lower() in title_lower for keyword in Config.IGNORE_KEYWORDS):
                    logger.info(f"⏭️ Пропускаем новость '{entry.title[:50]}...' из-за глобальных ключевых слов для игнора")
                    continue
                
                image_url = None
                if 'media_content' in entry:
                    for media in entry.media_content:
                        if media.get('type', '').startswith('image'):
                            image_url = media['url']
                            break
                
                if not image_url and 'summary' in entry:
                    img_match = re.search(r'<img[^>]+src="([^">]+)"', entry.summary)
                    if img_match:
                        image_url = img_match.group(1)
                
                if not image_url and 'links' in entry:
                    for link in entry.links:
                        if link.get('type', '').startswith('image'):
                            image_url = link.href
                            break
                
                description = ""
                if 'summary' in entry:
                    description = entry.summary
                elif 'description' in entry:
                    description = entry.description
                elif 'content' in entry:
                    if isinstance(entry.content, list) and len(entry.content) > 0:
                        description = entry.content[0].value
                
                description = re.sub(r'<[^>]+>', '', description)
                description = description[:500]
                
                # Для IGN исправляем ссылки
                if source_name == "ign":
                    if entry.link and not entry.link.startswith('http'):
                        entry.link = f"https://www.ign.com{entry.link}"
                
                # Для GameSpot исправляем ссылки
                if source_name == "gamespot":
                    if entry.link and not entry.link.startswith('http'):
                        entry.link = f"https://www.gamespot.com{entry.link}"
                
                # Получаем полный текст статьи
                full_text = ""
                if bot_settings["get_full_text"] and entry.link:
                    logger.info(f"📖 Получаю полный текст статьи из {source_name}...")
                    full_text = await fetch_full_article(entry.link, source_name)
                    if not full_text:
                        full_text = description
                
                news_item = NewsItem(
                    title=entry.title,
                    link=entry.link,
                    description=description,
                    pub_date=entry.get('published', ''),
                    image_url=image_url,
                    source=source_name,
                    category=category,
                    full_text=full_text if full_text else description
                )
                news_items.append(news_item)
                
            except Exception as e:
                logger.error(f"Ошибка обработки записи из {source_name}: {e}")
                continue
        
        logger.info(f"📰 Найдено {len(news_items)} новостей в {source_name}")
                
    except Exception as e:
        logger.error(f"Ошибка парсинга RSS {url}: {e}")
    
    return news_items

async def parse_html_source(url: str, source_name: str, category: str = "") -> list[NewsItem]:
    news_items = []
    
    try:
        # Для некоторых сайтов используем requests из-за проблем с SSL
        if source_name in ["habr", "lenta"]:
            try:
                response = requests.get(url, headers=Config.HEADERS, timeout=15, verify=False)
                if response.status_code == 200:
                    content = response.text
                else:
                    logger.error(f"Ошибка HTTP {response.status_code} для {url}")
                    return news_items
            except Exception as e:
                logger.error(f"Ошибка при запросе {source_name}: {e}")
                return news_items
        else:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(headers=Config.HEADERS, connector=connector) as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        content = await response.text()
                    else:
                        logger.error(f"Ошибка HTTP {response.status} для {url}")
                        return news_items
        
        # Для TASS используем RSS парсер вместо HTML
        if source_name == "tass" or source_name == "tass_economics":
            logger.info(f"Использую RSS парсер для {source_name}")
            feed = feedparser.parse(content)
            
            for entry in feed.entries[:15]:
                try:
                    # Проверка на ключевые слова для игнора (глобальные)
                    title_lower = entry.title.lower()
                    if any(keyword.lower() in title_lower for keyword in Config.IGNORE_KEYWORDS):
                        logger.info(f"⏭️ Пропускаем новость '{entry.title[:50]}...' из-за глобальных ключевых слов для игнора")
                        continue
                    
                    image_url = None
                    description = entry.get('summary', '')
                    
                    # Получаем полный текст статьи
                    full_text = ""
                    if bot_settings["get_full_text"] and entry.link:
                        logger.info(f"📖 Получаю полный текст статьи из TASS...")
                        full_text = await fetch_full_article(entry.link, source_name)
                        if not full_text:
                            full_text = description
                    
                    news_item = NewsItem(
                        title=entry.title,
                        link=entry.link,
                        description=description[:500],
                        pub_date=entry.get('published', ''),
                        image_url=image_url,
                        source=source_name,
                        category=category,
                        full_text=full_text if full_text else description
                    )
                    news_items.append(news_item)
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки записи TASS: {e}")
                    continue
        else:
            # Для остальных HTML источников используем BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            news_elements = []
            
            # Специфичные селекторы для разных источников
            if source_name == "vgtimes":
                selectors = ['.news-item', '.item-news', 'article.news']
            elif source_name == "iz":
                selectors = ['.lenta_news_item', '.rubric_lenta__item', '.lenta_item']
            elif source_name == "lenta":
                selectors = ['.item', '.b-topic-item', '.rubric-page__item']
            elif source_name == "rbc_economics" or source_name == "rbc_finances":
                selectors = ['.item', '.news-item', '.news-feed__item', '.js-news-feed-item']
            else:
                selectors = [
                    '.b-news-item',
                    '.news-item',
                    '.post',
                    'article',
                    '.item',
                    'div[class*="news"]',
                    'div[class*="post"]',
                    '.card',
                    '.news-card'
                ]
            
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    news_elements = elements[:15]
                    break
            
            for element in news_elements:
                try:
                    # Ищем заголовок
                    title_elem = element.find(['h1', 'h2', 'h3', 'h4', '.title', '.name', '.news-title', '.card__title'])
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    
                    # Проверка на ключевые слова для игнора (глобальные)
                    title_lower = title.lower()
                    if any(keyword.lower() in title_lower for keyword in Config.IGNORE_KEYWORDS):
                        logger.info(f"⏭️ Пропускаем новость '{title[:50]}...' из-за глобальных ключевых слов для игнора")
                        continue
                    
                    # Ищем ссылку
                    link_elem = title_elem.find('a') if title_elem else element.find('a')
                    if not link_elem:
                        continue
                    
                    link_url = link_elem.get('href', '')
                    
                    if not title or not link_url:
                        continue
                    
                    # Исправляем относительные ссылки
                    if link_url and not link_url.startswith(('http://', 'https://')):
                        base_url = url.split('/')[0] + '//' + url.split('/')[2]
                        if link_url.startswith('/'):
                            link_url = base_url + link_url
                        else:
                            link_url = base_url + '/' + link_url
                    
                    # Ищем описание
                    description = ""
                    desc_elem = element.find(['p', '.description', '.excerpt', '.preview-text', '.anons', '.card__text', '.article__text'])
                    if desc_elem:
                        description = desc_elem.get_text(strip=True)[:500]
                    
                    # Ищем изображение
                    image_url = None
                    img_elem = element.find('img')
                    if img_elem and img_elem.get('src'):
                        img_src = img_elem.get('src')
                        if img_src and not img_src.startswith('data:'):
                            if img_src.startswith('/'):
                                base_url = url.split('/')[0] + '//' + url.split('/')[2]
                                image_url = base_url + img_src
                            elif not img_src.startswith(('http://', 'https://')):
                                base_url = url.split('/')[0] + '//' + url.split('/')[2]
                                image_url = base_url + '/' + img_src
                            else:
                                image_url = img_src
                    
                    # Получаем полный текст статьи
                    full_text = ""
                    if bot_settings["get_full_text"] and link_url:
                        logger.info(f"📖 Получаю полный текст статьи из {source_name}...")
                        full_text = await fetch_full_article(link_url, source_name)
                        if not full_text:
                            full_text = description
                    
                    news_item = NewsItem(
                        title=title,
                        link=link_url,
                        description=description,
                        pub_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                        image_url=image_url,
                        source=source_name,
                        category=category,
                        full_text=full_text if full_text else description
                    )
                    news_items.append(news_item)
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки элемента в {source_name}: {e}")
                    continue
        
        logger.info(f"📰 Найдено {len(news_items)} новостей в {source_name}")
                
    except Exception as e:
        logger.error(f"Ошибка парсинга HTML {url}: {e}")
    
    return news_items

def extract_main_theme(text: str) -> str:
    clean_text = re.sub(r'<[^>]+>', '', text).lower()
    
    words = re.findall(r'\b\w{4,}\b', clean_text)
    if not words:
        return clean_text[:50]
    
    from collections import Counter
    word_counts = Counter(words)
    top_words = [word for word, count in word_counts.most_common(3)]
    
    return " ".join(top_words)

def find_game_links(game_name: str, context: str = "") -> list[dict]:
    game_links = []
    
    encoded_name = quote_plus(game_name)
    context_lower = context.lower()
    
    if "pc" in context_lower or "steam" in context_lower or "компьютер" in context_lower or not context_lower:
        game_links.append({
            "platform": "Steam",
            "url": f"https://store.steampowered.com/search/?term={encoded_name}",
            "icon": "🎮"
        })
    
    if "playstation" in context_lower or "ps5" in context_lower or "ps4" in context_lower or "ps3" in context_lower or "консоль" in context_lower or not context_lower:
        game_links.append({
            "platform": "PlayStation Store",
            "url": f"https://store.playstation.com/ru-ru/search/{encoded_name}",
            "icon": "🎯"
        })
    
    if "xbox" in context_lower or "xbox one" in context_lower or "xbox series" in context_lower or "консоль" in context_lower or not context_lower:
        game_links.append({
            "platform": "Xbox Store",
            "url": f"https://www.xbox.com/ru-RU/search?q={encoded_name}",
            "icon": "🎪"
        })
    
    if "epic" in context_lower or "epic games" in context_lower or not context_lower:
        game_links.append({
            "platform": "Epic Games",
            "url": f"https://store.epicgames.com/ru/browse?q={encoded_name}",
            "icon": "🎲"
        })
    
    if "nintendo" in context_lower or "switch" in context_lower or not context_lower:
        game_links.append({
            "platform": "Nintendo eShop",
            "url": f"https://www.nintendo.com/store/search/{encoded_name}/",
            "icon": "🎴"
        })
    
    return game_links

def add_game_links_to_text(text: str, context: str = "") -> str:
    if not bot_settings["add_game_links"]:
        return text
    
    game_patterns = [
        r'«([^»]+)»',
        r'"([^"]+)"',
        r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s\d{4}',
        r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b'
    ]
    
    games_found = []
    for pattern in game_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if len(match) > 3 and match not in games_found:
                games_found.append(match)
    
    games_found = list(set(games_found))
    links_added = []
    
    for game in games_found:
        if len(game) < 4 or game.lower() in ['игра', 'новость', 'обновление', 'патч', 'дополнение']:
            continue
        
        game_links = find_game_links(game, context)
        if game_links:
            links_text = ""
            for link in game_links[:3]:
                links_text += f'{link["icon"]} <a href="{link["url"]}">{link["platform"]}</a> | '
            
            if links_text:
                links_text = links_text.rstrip(' | ')
                text = text.replace(game, f'{game} ({links_text})')
                links_added.append(game)
    
    if links_added:
        text += "\n\n🔗 <b>Ссылки на игры:</b> Добавлены автоматически"
    
    return text

def rotate_gemini_model(channel_id: str) -> tuple[bool, str]:
    """
    Вращает модель Gemini для канала при ошибках лимита
    Возвращает (успешно ли сменили модель, новую модель)
    """
    if channel_id not in bot_settings["channels"]:
        return False, ""
    
    channel = bot_settings["channels"][channel_id]
    
    if "gemini_error_count" not in channel:
        channel["gemini_error_count"] = 0
    
    channel["gemini_error_count"] += 1
    
    available_models = list(GEMINI_MODELS.keys())
    
    if channel["gemini_error_count"] == 1:
        # Первая ошибка - просто логируем
        logger.warning(f"⚠️ Первая ошибка Gemini для канала {channel_id}")
        return False, channel.get("gemini_model", available_models[0])
    
    elif channel["gemini_error_count"] == 2:
        # Вторая ошибка - меняем на следующую модель
        current_model = channel.get("gemini_model", available_models[0])
        try:
            current_index = available_models.index(current_model)
            new_index = (current_index + 1) % len(available_models)
            new_model = available_models[new_index]
            channel["gemini_model"] = new_model
            save_channels()
            logger.info(f"🔄 Изменена модель Gemini для канала {channel_id}: {current_model} -> {new_model}")
            return True, new_model
        except ValueError:
            # Если модель не найдена в списке, устанавливаем первую
            new_model = available_models[0]
            channel["gemini_model"] = new_model
            save_channels()
            logger.info(f"🔄 Установлена первая модель Gemini для канала {channel_id}: {new_model}")
            return True, new_model
    
    elif channel["gemini_error_count"] >= 3:
        # Третья и последующие ошибки - удаляем ключ и требуем новый
        if "gemini_api_key" in channel:
            del channel["gemini_api_key"]
            channel["gemini_error_count"] = 0
            save_channels()
            logger.error(f"🗑️ Удален ключ Gemini для канала {channel_id} после 3 ошибок")
            return False, ""
    
    return False, channel.get("gemini_model", available_models[0])

def reset_gemini_error_count(channel_id: str):
    """Сбрасывает счетчик ошибок Gemini для канала"""
    if channel_id in bot_settings["channels"]:
        channel = bot_settings["channels"][channel_id]
        if "gemini_error_count" in channel:
            channel["gemini_error_count"] = 0
            save_channels()
            logger.debug(f"Сброшен счетчик ошибок Gemini для канала {channel_id}")

async def rewrite_with_gemini(source_text: str, style_examples: str = None, channel_id: str = None) -> str:
    """Переписывает текст с помощью Gemini API с повторными попытками при ошибках"""
    
    if not channel_id or channel_id not in bot_settings["channels"]:
        logger.error("❌ Не указан или не найден channel_id для Gemini")
        return None
    
    channel = bot_settings["channels"][channel_id]
    
    # Проверяем наличие ключа API
    if "gemini_api_key" not in channel or not channel["gemini_api_key"]:
        logger.error(f"❌ Для канала {channel_id} не установлен ключ Gemini API")
        return None
    
    # Получаем модель для канала
    gemini_model = channel.get("gemini_model", "gemini-3-flash-preview")
    
    try:
        # Создаем клиент с ключом канала
        gemini_client = genai.Client(api_key=channel["gemini_api_key"])
    except Exception as e:
        logger.error(f"❌ Ошибка создания клиента Gemini для канала {channel_id}: {e}")
        rotate_gemini_model(channel_id)
        return None
    
    if style_examples:
        style_examples = clean_html_tags(style_examples)
    
    prompt = f"""Ты - высококвалифицированный переписчик постов для Telegram. Твоя основная задача - преобразовать исходный текст в новый, уникальный пост, который стилистически идентичен предоставленным примерам стиля.

ЗОЛОТОЕ ПРАВИЛО: СОБЛЮДЕНИЕ СТИЛЯ

Твой вывод должен выглядеть и ощущаться так, как будто он написан тем же автором, который создал примеры. Это не подлежит обсуждению.

Если примеры короткие и агрессивные, твой пост должен быть коротким и агрессивным.
Если примеры длинные и аналитические, твой пост должен быть длинным и аналитическим.
Если примеры используют определенные шаблоны форматирования, ты должен точно воспроизвести эти шаблоны.
Если примеры имеют определенный тон, например, формальный, неформальный, юмористический или драматический, ты должен соответствовать этому тону.

ВАЖНО: СОХРАНЕНИЕ ФОРМАТИРОВАНИЯ

1. СОХРАНЯЙ ВСЕ HTML ТЕГИ: Ты должен сохранять все HTML теги из примеров стиля, включая <a href="URL"> для ссылок.

2. ДОБАВЛЯЙ ССЫЛКИ НА ИГРЫ: Если в тексте упоминаются игры, то пойми про какие игры и на какой площадке идёт речь, добавь соответствующие ссылки на эти игры в нужных магазинах (Steam, PlayStation Store, Xbox Store и т.д.) в формате:
   <a href="URL">Название игры</a> (если название игры и в тексте и в заголовоке то лучше добавить в заголовок)

3. ИСПОЛЬЗУЙ ВСЕ ТЕГИ ИЗ ПРИМЕРОВ: Если в примерах есть теги <b>, <i>, <u>, <code>, <pre>, <blockquote>, <a href="URL">, <blockquote expandable> - используй их в том же стиле.

ТЕГИ ФОРМАТИРОВАНИЯ: ОБЯЗАТЕЛЬНОЕ ИСПОЛЬЗОВАНИЕ

Ты можешь использовать следующие теги. Используй их так же и с такой же частотой, как в примерах.

ЖИРНЫЙ ТЕКСТ: <b>...</b>
ПОДЧЕРКНУТЫЙ ТЕКСТ: <u>...</u>
КУРСИВ: <i>...</i>
КОД: <code>...</code>
БЛОК КОДА: <pre>...</pre>
ЦИТАТА: <blockquote>...</blockquote>
РАСКРЫВАЕМАЯ ЦИТАТА: <blockquote expandable>...</blockquote>
ССЫЛКА: <a href="URL">текст ссылки</a>

ПОЛИТИКА ССЫЛОК:
- НЕЛЬЗЯ писать одну игру, но добавлять ссылку на другую (лучше не добавить ссылку если на эту игру ее нет, чем добавить на несоответствующую) 
- МОЖНО включать ссылки на игры в магазинах, но только корректные
- ПОЛНЫЙ ЗАПРЕТ на использование не валидных ссылок на игры, разрешено использование только настоящих ссылок на ту или те игры про каторые говорится.
- НЕЛЬЗЯ писать название игры и т.п. и рядом в скобочках название магазина с гиперссылкой на эту игру (ссылка в самом названии должна быть)
- МОЖНО опираться на контекст текста и добавлять соответствующие ссылки на игры (к примеру речь идёт о играх на пс, значит в названии игры будет ссылка на нее в пс стор (если не указана платформа то стим))
- НЕЛЬЗЯ писать текст в кучу если такого нет в примере, всё должно быть понятно
- НЕЛЬЗЯ включать ссылки на источники новостей или оригинальные статьи
- НЕЛЬЗЯ упоминать источники или где найти больше информации
- НЕЛЬЗЯ ссылаться на новостные сайты, порталы или источники новостей
- НЕЛЬЗЯ включать фразы типа "читать далее", "подробнее", "источник"

ОБЯЗАТЕЛЬНЫЙ РАБОЧИЙ ПРОЦЕСС

1. АНАЛИЗ ПРИМЕРОВ - Изучи примеры стиля как детектив. Определи структуру предложений и их длину, организацию абзацев, тон и голос, шаблоны форматирования, использование эмодзи и знаков препинания.

2. ДЕКОНСТРУКЦИИ ИСТОЧНИКА - Пойми основное сообщение и ключевые факты. Удали любую информацию об источнике.

3. ПЕРЕПИСЫВАНИЕ С НУЛЯ - Создавай полностью новый контент, изменяя структуру предложений и порядок слов, используя разные грамматические конструкции, перефразируя введения и заключения. Результат должен быть неузнаваемым по сравнению с оригиналом, сохраняя при этом всю ключевую информацию.

4. ПРИМЕНЕНИЕ ФОРМАТИРОВАНИЯ ВЕРНО - Используй теги точно так, как они появляются в примерах.

5. ДОБАВЛЕНИЕ ССЫЛКИ НА ИГРЫ - Если упоминаются игры, добавь соответствующие ссылки на магазины.

6. ФИНАЛЬНАЯ ПРОВЕРКА - Убедись, что пост стилистически идентичен примерам, правильно отформатирован, полностью уникален по сравнению с исходным текстом и содержит всю важную информацию.

ВАЖНО: ОГРАНИЧЕНИЕ ПО ДЛИНЕ - Пост НЕ ДОЛЖЕН превышать 900 символов. Это критическое ограничение Telegram для подписей к фото. Если текст получается длиннее, сократи его, сохраняя ключевую информацию.

СТРОГИЕ ТРЕБОВАНИЯ К ВЫВОДУ

- ВЫВОДИ ТОЛЬКО финальный, переписанный пост в Telegram на русском языке.
- НЕ добавляй никаких введений, вопросов или объяснений.
- НЕ добавляй лишних надписей по типу "Ссылки на игры: добавлены автоматически" и тп. 
- НЕ проси уточнений или дополнительной информации.
- НЕ выдумывай факты и не используй информацию, отсутствующую в исходном текстах.
- НЕ копируй предложения или фразы из исходного текста.
- НЕ используй символы звездочки (*) где-либо в выводе.
- НЕ включай ссылки на источники новостей или оригинальные статьи.
- НЕ отправляй посты без надлежащего форматирования там, где форматирование требуется.

ПРИМЕРЫ СТИЛЯ (твое руководство по стилю - изучи их внимательно):
{style_examples if style_examples else 'Используй стандартный стиль Telegram постов с HTML форматированием.'}

ИСХОДНЫЙ ТЕКСТ ДЛЯ ПЕРЕПИСЫВАНИЯ (Создай новый, уникальный пост в стиле выше, используя эту информацию):
{source_text}
"""
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = gemini_client.models.generate_content(
                model=gemini_model,
                contents=prompt
            )
            
            result = response.text
            
            if not result:
                logger.error(f"❌ Ошибка Gemini API: Пустой ответ (попытка {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # Ждем перед повторной попыткой
                    continue
                return None
            
            result = validate_html(result)
            
            if bot_settings["add_game_links"]:
                result = add_game_links_to_text(result, source_text)
            
            # Сбрасываем счетчик ошибок при успешной генерации
            reset_gemini_error_count(channel_id)
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка Gemini API (попытка {attempt + 1}/{max_retries}): {error_msg}")
            
            if "429" in error_msg or "quota" in error_msg.lower() or "403" in error_msg or "Invalid operation" in error_msg or "text" in error_msg.lower():
                logger.warning("⚠️ Лимит или ошибка Gemini API")
                
                # Вращаем модель при ошибках лимита
                model_changed, new_model = rotate_gemini_model(channel_id)
                if model_changed:
                    logger.info(f"🔄 Модель изменена на {new_model} для канала {channel_id}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return None
            
            if "503" in error_msg or "overloaded" in error_msg.lower():
                logger.warning(f"⚠️ Gemini перегружен, жду перед повторной попыткой...")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5  # Увеличиваем время ожидания с каждой попыткой
                    await asyncio.sleep(wait_time)
                    continue
            
            if attempt == max_retries - 1:
                logger.warning(f"⚠️ Не удалось обработать новость после {max_retries} попыток")
                return None
    
    return None

async def generate_post_content(news_item: NewsItem, template_name: str = None, channel_id: str = None) -> dict:
    try:
        # Используем полный текст статьи для генерации контента
        source_text = f"""
Заголовок: {news_item.title}
Полный текст статьи: {news_item.full_text}
Дата: {news_item.pub_date}
"""
        
        style_examples = None
        if template_name and template_name in bot_settings["templates"]:
            style_examples = bot_settings["templates"][template_name]
            if style_examples:
                logger.info(f"Использую шаблон '{template_name}' для переписывания")
        
        post_text = await rewrite_with_gemini(source_text, style_examples, channel_id)
        
        if post_text is None:
            logger.warning(f"❌ Gemini вернул None для новости: {news_item.title[:50]}...")
            return None
        
        source_keywords = ['источник', 'читать далее', 'подробнее', 'оригинал', 'статья', 'новость от']
        for keyword in source_keywords:
            lines = post_text.split('\n')
            filtered_lines = []
            for line in lines:
                if keyword.lower() not in line.lower():
                    filtered_lines.append(line)
            post_text = '\n'.join(filtered_lines)
        
        final_text = post_text
        
        image_url = news_item.image_url
        if not image_url or not image_url.startswith(('http://', 'https://')):
            img_query = extract_keywords_for_image_search(news_item.title + " " + news_item.description)
            image_url = get_relevant_image(img_query)
        
        return {
            "text": final_text,
            "image_url": image_url,
            "link": news_item.link
        }
    except Exception as e:
        logger.error(f"❌ Ошибка генерации контента: {e}")
        return None

async def download_image(image_url: str) -> bytes | None:
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return None
    
    try:
        # Используем requests для загрузки изображений (более стабильно)
        response = requests.get(image_url, timeout=15, headers=Config.HEADERS, verify=False)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '').lower()
            if 'image' in content_type:
                image_data = response.content
                if len(image_data) > 10 * 1024 * 1024:
                    logger.warning(f"Изображение слишком большое: {len(image_data)} байт")
                    return None
                
                # Применяем размытие логотипов, если включено
                if bot_settings["blur_logos"]:
                    image_data = apply_logo_blur(image_data)
                
                return image_data
            else:
                logger.warning(f"Некорректный Content-Type: {content_type}")
                return None
        else:
            logger.warning(f"Ошибка загрузки изображения: статус {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        logger.warning(f"Таймаут при загрузке изображения: {image_url}")
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки изображения {image_url}: {e}")
        return None

def parse_post_times(times_str: str) -> list[str]:
    times = []
    for time_str in times_str.split(','):
        time_str = time_str.strip()
        if re.match(r'^\d{1,2}:\d{2}$', time_str):
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                times.append(f"{hour:02d}:{minute:02d}")
    
    return sorted(times)

def validate_post_times(times: list[str], min_interval: int = 100) -> bool:
    if len(times) < 2:
        return True
    
    for i in range(len(times) - 1):
        hour1, minute1 = map(int, times[i].split(':'))
        hour2, minute2 = map(int, times[i + 1].split(':'))
        
        minutes1 = hour1 * 60 + minute1
        minutes2 = hour2 * 60 + minute2
        
        if minutes2 - minutes1 < min_interval:
            return False
    
    return True

def generate_random_schedule_for_channel(posts_per_day: int, min_interval: int = 100) -> list[str]:
    times = []
    start_hour = 8
    end_hour = 22
    
    total_minutes = (end_hour - start_hour) * 60
    total_needed = min_interval * (posts_per_day - 1)
    if total_needed > total_minutes:
        posts_per_day = total_minutes // min_interval + 1
        if posts_per_day < 1:
            posts_per_day = 1
    
    used_times = []
    for i in range(posts_per_day):
        attempts = 0
        while attempts < 100:
            hour = random.randint(start_hour, end_hour - 1)
            minute = random.randint(0, 59)
            candidate_time = f"{hour:02d}:{minute:02d}"
            
            valid = True
            for used_time in used_times:
                used_hour, used_minute = map(int, used_time.split(':'))
                candidate_minutes = hour * 60 + minute
                used_minutes = used_hour * 60 + used_minute
                
                if abs(candidate_minutes - used_minutes) < min_interval:
                    valid = False
                    break
            
            if valid:
                times.append(candidate_time)
                used_times.append(candidate_time)
                break
            
            attempts += 1
        
        if attempts == 100:
            if times:
                last_hour, last_minute = map(int, times[-1].split(':'))
                last_minutes = last_hour * 60 + last_minute
                new_minutes = last_minutes + min_interval
                
                if new_minutes < end_hour * 60:
                    new_hour = new_minutes // 60
                    new_minute = new_minutes % 60
                    new_time = f"{new_hour:02d}:{new_minute:02d}"
                    times.append(new_time)
                else:
                    break
    
    return sorted(times)

def generate_schedule_for_channel(channel_id: str) -> list[str]:
    channel = bot_settings["channels"].get(channel_id)
    if not channel:
        return []
    
    time_mode = channel.get("time_mode", "random")
    posts_per_day = channel.get("posts_per_day", 1)
    
    if time_mode == "fixed":
        fixed_times = channel.get("fixed_times", [])
        if fixed_times:
            return fixed_times[:posts_per_day]
        else:
            return []
    else:
        min_interval = channel.get("min_interval", 100)
        return generate_random_schedule_for_channel(posts_per_day, min_interval)

def get_next_post_time_for_channel(channel_id: str) -> datetime | None:
    """Получает следующее время для поста в канале, генерируя новое расписание на следующий день если нужно."""
    channel = bot_settings["channels"].get(channel_id)
    if not channel or not channel.get("auto_post_enabled", False):
        return None
    
    msk_now = get_msk_now()
    today_date = msk_now.date()
    
    should_generate_new_schedule = False
    
    if "last_post_date" not in channel or channel["last_post_date"] != str(today_date):
        should_generate_new_schedule = True
        logger.info(f"📅 Генерируем новое расписание для канала {channel_id} на {today_date}")
    elif "auto_post_schedule" not in channel or not channel["auto_post_schedule"]:
        should_generate_new_schedule = True
        logger.info(f"📅 Расписание пустое для канала {channel_id}, генерируем новое")
    else:
        schedule = channel["auto_post_schedule"]
        has_future_times = False
        for time_str in schedule:
            hour, minute = map(int, time_str.split(':'))
            post_dt = datetime.combine(today_date, dt_time(hour, minute))
            post_dt = pytz.timezone('Europe/Moscow').localize(post_dt)
            
            if post_dt > msk_now:
                has_future_times = True
                break
        
        if not has_future_times:
            should_generate_new_schedule = True
            tomorrow_date = today_date + timedelta(days=1)
            today_date = tomorrow_date
            logger.info(f"📅 Все времена прошли для канала {channel_id}, генерируем на {today_date}")
    
    if should_generate_new_schedule:
        times = generate_schedule_for_channel(channel_id)
        
        schedule = []
        for time_str in times:
            hour, minute = map(int, time_str.split(':'))
            post_dt = datetime.combine(today_date, dt_time(hour, minute))
            post_dt = pytz.timezone('Europe/Moscow').localize(post_dt)
            
            if post_dt > msk_now:
                schedule.append(time_str)
        
        if not schedule:
            tomorrow_date = today_date + timedelta(days=1)
            times = generate_schedule_for_channel(channel_id)
            schedule = []
            for time_str in times:
                hour, minute = map(int, time_str.split(':'))
                post_dt = datetime.combine(tomorrow_date, dt_time(hour, minute))
                post_dt = pytz.timezone('Europe/Moscow').localize(post_dt)
                schedule.append(time_str)
            today_date = tomorrow_date
        
        channel["auto_post_schedule"] = schedule
        channel["last_post_date"] = str(today_date)
        save_channels()
        
        if schedule:
            logger.info(f"📅 Новое расписание для канала {channel_id}: {schedule}")
        else:
            logger.warning(f"⚠️ Не удалось сгенерировать расписание для канала {channel_id}")
            return None
    
    schedule = channel["auto_post_schedule"]
    for time_str in schedule:
        hour, minute = map(int, time_str.split(':'))
        post_date_str = channel["last_post_date"]
        post_date = datetime.strptime(post_date_str, "%Y-%m-%d").date()
        post_dt = datetime.combine(post_date, dt_time(hour, minute))
        post_dt = pytz.timezone('Europe/Moscow').localize(post_dt)
        
        if post_dt > msk_now:
            return post_dt
    
    tomorrow_date = datetime.strptime(channel["last_post_date"], "%Y-%m-%d").date() + timedelta(days=1)
    times = generate_schedule_for_channel(channel_id)
    
    schedule = []
    for time_str in times:
        hour, minute = map(int, time_str.split(':'))
        post_dt = datetime.combine(tomorrow_date, dt_time(hour, minute))
        post_dt = pytz.timezone('Europe/Moscow').localize(post_dt)
        schedule.append(time_str)
    
    if schedule:
        channel["auto_post_schedule"] = schedule
        channel["last_post_date"] = str(tomorrow_date)
        save_channels()
        
        first_time_str = schedule[0]
        hour, minute = map(int, first_time_str.split(':'))
        post_dt = datetime.combine(tomorrow_date, dt_time(hour, minute))
        return pytz.timezone('Europe/Moscow').localize(post_dt)
    
    return None

async def schedule_post_for_time(channel_id: str, post_time: datetime):
    """Создает отдельную задачу для публикации поста в указанное время"""
    try:
        msk_now = get_msk_now()
        wait_seconds = (post_time - msk_now).total_seconds()
        
        if wait_seconds > 0:
            logger.info(f"⏰ Планирую пост для канала {channel_id} в {post_time.strftime('%H:%M:%S')} (через {wait_seconds:.0f} сек)")
            
            async def scheduled_post():
                try:
                    await asyncio.sleep(wait_seconds)
                    
                    channel = bot_settings["channels"].get(channel_id)
                    if not channel or not channel.get("auto_post_enabled", False):
                        logger.info(f"⏹️ Авто-постинг отключен для канала {channel_id}")
                        return
                    
                    logger.info("=" * 50)
                    logger.info(f"🕒 ВРЕМЯ ПУБЛИКОВАТЬ ПОСТ В КАНАЛ {channel_id}!")
                    logger.info(f"📅 Текущее время: {get_msk_now().strftime('%Y-%m-%d %H:%M:%S')}")
                    logger.info(f"⏰ Время поста: {post_time.strftime('%H:%M')}")
                    logger.info("=" * 50)
                    
                    success = await check_news_for_channel(channel_id, ignore_processed=False, is_test_post=False)
                    
                    if success:
                        logger.info(f"✅ Пост опубликован для канала {channel_id}")
                        await start_auto_post_for_channel(channel_id)
                    else:
                        logger.warning(f"⚠️ Не удалось опубликовать пост для канала {channel_id}")
                        channel = bot_settings["channels"].get(channel_id)
                        if channel and "auto_post_schedule" in channel and channel["auto_post_schedule"]:
                            removed_time = channel["auto_post_schedule"].pop(0)
                            logger.info(f"⏰ Удалено время {removed_time} из расписания (публикация не удалась)")
                            save_channels()
                        
                        await start_auto_post_for_channel(channel_id)
                        
                except asyncio.CancelledError:
                    logger.info(f"⏹️ Запланированный пост для канала {channel_id} отменен")
                except Exception as e:
                    logger.error(f"❌ Ошибка в запланированном посте для канала {channel_id}: {e}")
            
            task = asyncio.create_task(scheduled_post())
            post_schedulers[channel_id] = task
            
        else:
            logger.warning(f"⏰ Время {post_time.strftime('%H:%M')} уже прошло, пропускаю")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при планировании поста: {e}")

async def auto_post_scheduler_for_channel(channel_id: str):
    logger.info(f"🚀 Авто-постинг запущен для канала {channel_id}")
    
    try:
        channel = bot_settings["channels"].get(channel_id)
        if not channel or not channel.get("auto_post_enabled", False):
            logger.info(f"⏸️ Авто-постинг выключен для канала {channel_id}")
            return
        
        if channel_id in post_schedulers:
            try:
                post_schedulers[channel_id].cancel()
                await post_schedulers[channel_id]
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Ошибка при отмене предыдущего планировщика: {e}")
        
        next_time = get_next_post_time_for_channel(channel_id)
        
        if not next_time:
            logger.info(f"📭 Нет запланированных постов для канала {channel_id} на сегодня")
            tomorrow = get_msk_now() + timedelta(days=1)
            tomorrow_start = datetime.combine(tomorrow.date(), dt_time(0, 0, 0))
            tomorrow_start = pytz.timezone('Europe/Moscow').localize(tomorrow_start)
            wait_seconds = (tomorrow_start - get_msk_now()).total_seconds()
            
            if wait_seconds > 0:
                logger.info(f"⏰ Проверю завтра в {tomorrow_start.strftime('%H:%M:%S')} (через {wait_seconds:.0f} сек)")
                await asyncio.sleep(wait_seconds)
                await start_auto_post_for_channel(channel_id)
            return
        
        await schedule_post_for_time(channel_id, next_time)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в планировщике для канала {channel_id}: {e}")

async def start_auto_post_for_channel(channel_id: str):
    if channel_id in auto_post_tasks:
        try:
            auto_post_tasks[channel_id].cancel()
            await asyncio.sleep(0.5)
        except:
            pass
    
    auto_post_tasks[channel_id] = asyncio.create_task(auto_post_scheduler_for_channel(channel_id))
    logger.info(f"✅ Планировщик авто-постинга запущен для канала {channel_id}")

async def stop_auto_post_for_channel(channel_id: str):
    if channel_id in post_schedulers:
        try:
            post_schedulers[channel_id].cancel()
            await post_schedulers[channel_id]
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка при остановке планировщика: {e}")
        
        del post_schedulers[channel_id]
    
    if channel_id in auto_post_tasks:
        try:
            auto_post_tasks[channel_id].cancel()
            await auto_post_tasks[channel_id]
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка при остановке главной задачи: {e}")
        
        del auto_post_tasks[channel_id]
    
    logger.info(f"⏹️ Авто-постинг остановлен для канала {channel_id}")

async def start_all_auto_posts():
    for channel_id, channel_data in bot_settings["channels"].items():
        if channel_data.get("auto_post_enabled", False):
            await start_auto_post_for_channel(channel_id)

async def stop_all_auto_posts():
    for channel_id in list(auto_post_tasks.keys()):
        await stop_auto_post_for_channel(channel_id)

async def test_channel_access(channel_id: str) -> tuple[bool, str]:
    try:
        chat = await bot.get_chat(channel_id)
        
        try:
            member = await bot.get_chat_member(channel_id, bot.id)
            
            if chat.type == "channel":
                if member.status in ["administrator", "creator"]:
                    if member.status == "creator" or (hasattr(member, 'can_post_messages') and member.can_post_messages):
                        return True, chat.title
                    else:
                        return False, "❌ Бот не имеет права отправлять сообщения в канал. Назначьте боту права на отправку сообщений."
                else:
                    return False, "❌ Бот не является администратором канала. Назначьте бота администратором."
            else:
                if member.status in ["administrator", "creator"]:
                    return True, chat.title
                else:
                    return False, "❌ Бот не является администратором чата. Назначьте бота администратором."
                    
        except Exception as member_error:
            logger.error(f"Ошибка получения информации о членстве: {member_error}")
            return False, "❌ Не удалось проверить права бота. Убедитесь, что бот добавлен в канал."
        
    except Exception as e:
        logger.error(f"❌ Ошибка доступа к каналу {channel_id}: {e}")
        error_msg = str(e)
        
        if "CHAT_NOT_FOUND" in error_msg:
            return False, "❌ Чат не найден. Убедитесь, что ID канала правильный."
        elif "USER_NOT_PARTICIPANT" in error_msg:
            return False, "❌ Бот не является участником канала. Добавьте бота в канал."
        elif "PEER_ID_INVALID" in error_msg:
            return False, "❌ Неверный ID канала. Проверьте формат (например: @channelname или -1001234567890)."
        elif "CHAT_ADMIN_REQUIRED" in error_msg:
            return False, "❌ Бот не является администратором канала. Назначьте бота администратором."
        elif "FORBIDDEN" in error_msg:
            return False, "❌ Бот заблокирован в канале или не имеет прав."
        else:
            return False, f"❌ Неизвестная ошибка: {error_msg[:100]}"

async def get_channel_statistics(channel_id: str) -> Dict:
    """
    Получает статистику канала: средние просмотры за 24ч, 48ч, 72ч
    """
    try:
        now = get_msk_now()
        
        # Получаем информацию о чате
        try:
            chat = await bot.get_chat(channel_id)
            logger.info(f"Получена информация о чате: {chat.title}")
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате {channel_id}: {e}")
            return None
        
        # В aiogram 3.x для получения статистики канала нужно использовать метод get_chat_history
        # или хранить ID отправленных сообщений
        
        # Попробуем получить историю сообщений через API бота
        # Для этого бот должен быть администратором канала с правом просмотра сообщений
        
        messages = []
        
        try:
            # Используем метод get_chat_history для получения последних сообщений
            from aiogram.methods import GetChatHistory
            
            # Получаем последние 100 сообщений из канала
            history = await bot(GetChatHistory(
                chat_id=channel_id,
                limit=100
            ))
            
            if history and hasattr(history, 'messages'):
                messages = history.messages
                logger.info(f"Получено {len(messages)} сообщений через get_chat_history")
        except Exception as e:
            logger.error(f"Ошибка получения истории чата {channel_id}: {e}")
        
        # Альтернативный способ - использовать get_updates (только для чатов с ботом)
        if not messages:
            try:
                updates = await bot.get_updates(limit=100)
                for update in updates:
                    if update.message and update.message.chat and str(update.message.chat.id) == str(channel_id):
                        messages.append(update.message)
                    elif update.channel_post and update.channel_post.chat and str(update.channel_post.chat.id) == str(channel_id):
                        messages.append(update.channel_post)
                logger.info(f"Получено {len(messages)} сообщений через get_updates")
            except Exception as e:
                logger.error(f"Ошибка получения updates для канала {channel_id}: {e}")
        
        # Если не удалось получить сообщения, возвращаем базовую информацию
        if not messages:
            logger.warning(f"Не удалось получить сообщения для канала {channel_id}")
            
            # Возвращаем базовую статистику
            return {
                '24h': 0,
                '48h': 0,
                '72h': 0,
                'total_messages': 0,
                'analyzed_messages': 0,
                'note': 'Не удалось получить историю сообщений. Бот должен быть администратором канала с правом просмотра сообщений.'
            }
        
        logger.info(f"Получено {len(messages)} сообщений для анализа")
        
        # Фильтруем сообщения по времени и получаем просмотры
        stats_24h = []
        stats_48h = []
        stats_72h = []
        
        for message in messages:
            if not hasattr(message, 'date'):
                continue
            
            message_time = message.date.replace(tzinfo=pytz.UTC)
            message_time_msk = message_time.astimezone(pytz.timezone('Europe/Moscow'))
            
            hours_diff = (now - message_time_msk).total_seconds() / 3600
            
            # Получаем просмотры (для каналов это работает)
            views = getattr(message, 'views', None)
            
            # Для постов в каналах также может быть поле 'forward_count' или 'reply_count'
            if views is not None and views > 0:
                if hours_diff <= 24:
                    stats_24h.append(views)
                if hours_diff <= 48:
                    stats_48h.append(views)
                if hours_diff <= 72:
                    stats_72h.append(views)
        
        # Рассчитываем средние значения
        avg_24h = int(statistics.mean(stats_24h)) if stats_24h else 0
        avg_48h = int(statistics.mean(stats_48h)) if stats_48h else 0
        avg_72h = int(statistics.mean(stats_72h)) if stats_72h else 0
        
        # Если нет данных за последние 24 часа, но есть за 48, используем их
        if avg_24h == 0 and stats_48h:
            avg_24h = int(statistics.mean(stats_48h)) if len(stats_48h) > 5 else 0
        
        result = {
            '24h': avg_24h,
            '48h': avg_48h,
            '72h': avg_72h,
            'total_messages': len(messages),
            'analyzed_messages': len([m for m in messages if hasattr(m, 'views') and getattr(m, 'views', 0) > 0]),
            'periods': {
                '24h_count': len(stats_24h),
                '48h_count': len(stats_48h),
                '72h_count': len(stats_72h)
            }
        }
        
        logger.info(f"Статистика для канала {channel_id}: 24h={avg_24h}, 48h={avg_48h}, 72h={avg_72h}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики канала {channel_id}: {e}")
        import traceback
        traceback.print_exc()
        return {
            '24h': 0,
            '48h': 0,
            '72h': 0,
            'total_messages': 0,
            'analyzed_messages': 0,
            'error': str(e)
        }

# === ОБРАБОТЧИКИ ДЛЯ УПРАВЛЕНИЯ ИСТОЧНИКАМИ ===

@dp.callback_query(F.data.startswith("manage_sources_"))
async def callback_manage_sources(callback: CallbackQuery):
    channel_id = callback.data.replace("manage_sources_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    category = channel.get("category", "games")
    channel_name = channel.get("name", channel_id)
    
    sources = Config.SOURCES_BY_CATEGORY.get(category, {})
    
    if not sources:
        await callback.message.edit_text(f"❌ Нет источников для категории {category}")
        await callback.answer()
        return
    
    disabled_sources = channel.get("disabled_sources", [])
    
    keyboard = InlineKeyboardBuilder()
    
    for source_name in sources.keys():
        if source_name in disabled_sources:
            status = "❌"
        else:
            status = "✅"
        
        source_display_names = {
            "gagadget": "Gagadget",
            "habr": "Habr",
            "google_tech": "Google Tech",
            "stopgame": "StopGame",
            "playground": "Playground",
            "ign": "IGN",
            "gamespot": "GameSpot",
            "vgtimes": "VGTimes",
            "iz": "Известия",
            "lenta": "Лента.ру",
            "tass": "ТАСС",
            "rbc_economics": "РБК Экономика",
            "tass_economics": "ТАСС Экономика",
            "rbc_finances": "РБК Финансы",
            "rbc_rss": "РБК RSS"
        }
        
        display_name = source_display_names.get(source_name, source_name)
        keyboard.button(text=f"{status} {display_name}", callback_data=f"toggle_source|{channel_id}|{source_name}")
    
    keyboard.button(text="📋 Назад к настройкам", callback_data=f"edit_channel_{channel_id}")
    keyboard.adjust(1)
    
    sources_text = f"🌐 Управление источниками для канала <b>{channel_name}</b>\n\n"
    sources_text += f"📊 Категория: {category}\n"
    sources_text += f"✅ - источник включен\n❌ - источник отключен\n\n"
    sources_text += f"Нажмите на источник, чтобы включить/выключить его."
    
    await callback.message.edit_text(
        sources_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_source|"))
async def callback_toggle_source(callback: CallbackQuery):
    data_parts = callback.data.split("|")
    if len(data_parts) != 3:
        await callback.answer("❌ Ошибка данных")
        return
    
    channel_id = data_parts[1]
    source_name = data_parts[2]
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    category = channel.get("category", "games")
    
    sources = Config.SOURCES_BY_CATEGORY.get(category, {})
    if source_name not in sources:
        await callback.answer("❌ Источник не найден")
        return
    
    if "disabled_sources" not in channel:
        channel["disabled_sources"] = []
    
    if source_name in channel["disabled_sources"]:
        channel["disabled_sources"].remove(source_name)
        action = "включен"
    else:
        channel["disabled_sources"].append(source_name)
        action = "отключен"
    
    save_channels()
    
    await callback_manage_sources(callback)
    
    await callback.answer(f"✅ Источник {action}")

@dp.callback_query(F.data.startswith("manage_ignore_words_"))
async def callback_manage_ignore_words(callback: CallbackQuery):
    channel_id = callback.data.replace("manage_ignore_words_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    channel_name = channel.get("name", channel_id)
    
    # Получаем слова для игнора для этого канала
    ignore_words = channel.get("ignore_words", [])
    
    keyboard = InlineKeyboardBuilder()
    
    keyboard.button(text="➕ Добавить слова", callback_data=f"add_ignore_word_{channel_id}")
    
    if ignore_words:
        keyboard.button(text="🗑️ Удалить слово", callback_data=f"remove_ignore_word_{channel_id}")
    
    keyboard.button(text="📋 Назад к настройкам", callback_data=f"edit_channel_{channel_id}")
    keyboard.adjust(1)
    
    words_text = ""
    if ignore_words:
        words_text = f"\n\n📝 Текущие слова для игнора:\n"
        for i, word in enumerate(ignore_words, 1):
            words_text += f"{i}. {word}\n"
    else:
        words_text = "\n\n📭 Список слов для игнора пуст."
    
    await callback.message.edit_text(
        f"🗑️ Управление игнорируемыми словами для канала <b>{channel_name}</b>\n\n"
        f"Слова из этого списка будут игнорироваться при проверке новостей для этого канала.\n"
        f"<i>Можно добавлять несколько слов через запятую</i>.{words_text}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("add_ignore_word_"))
async def callback_add_ignore_word(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("add_ignore_word_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_ignore_word)
    
    await callback.message.edit_text(
        f"Введите слова или фразы для добавления в список игнора:\n\n"
        f"<b>Можно ввести несколько слов через запятую</b>\n"
        f"Пример: <code>политика, выборы, президент</code>\n\n"
        f"<b>Примечание:</b> При проверке новостей, если заголовок или описание содержат "
        f"эти слова (в любом регистре), новость будет пропущена.",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(BotStates.waiting_for_ignore_word)
async def process_ignore_word(message: Message, state: FSMContext):
    words_input = message.text.strip().lower()
    
    if not words_input:
        await message.answer("❌ Слова не могут быть пустыми")
        return
    
    data = await state.get_data()
    channel_id = data.get("channel_id")
    
    if not channel_id or channel_id not in bot_settings["channels"]:
        await message.answer("❌ Ошибка: канал не найден")
        await state.clear()
        return
    
    channel = bot_settings["channels"][channel_id]
    
    if "ignore_words" not in channel:
        channel["ignore_words"] = []
    
    # Разделяем слова по запятым, убираем пробелы и пустые элементы
    new_words = [word.strip() for word in words_input.split(',') if word.strip()]
    
    added_words = []
    skipped_words = []
    
    for word in new_words:
        if word in channel["ignore_words"]:
            skipped_words.append(word)
        else:
            channel["ignore_words"].append(word)
            added_words.append(word)
    
    save_channels()
    
    response_text = ""
    if added_words:
        response_text += f"✅ Добавлены слова: {', '.join(added_words)}\n"
    
    if skipped_words:
        response_text += f"⏭️ Уже есть в списке: {', '.join(skipped_words)}\n"
    
    response_text += f"\n📊 Всего слов в списке: {len(channel['ignore_words'])}"
    
    await message.answer(response_text)
    await state.clear()

@dp.callback_query(F.data.startswith("remove_ignore_word_"))
async def callback_remove_ignore_word(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("remove_ignore_word_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    ignore_words = channel.get("ignore_words", [])
    
    if not ignore_words:
        await callback.message.edit_text("❌ Список слов для игнора пуст")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for word in ignore_words:
        keyboard.button(text=f"🗑️ {word}", callback_data=f"remove_word_{channel_id}_{word}")
    
    keyboard.button(text="📋 Назад", callback_data=f"manage_ignore_words_{channel_id}")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите слово для удаления из списка игнора:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("remove_word_"))
async def callback_remove_word(callback: CallbackQuery):
    data_parts = callback.data.replace("remove_word_", "").split("_", 2)
    if len(data_parts) < 2:
        await callback.answer("❌ Ошибка данных")
        return
    
    channel_id = data_parts[0]
    word = data_parts[1]
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    
    if "ignore_words" not in channel or word not in channel["ignore_words"]:
        await callback.message.edit_text(f"❌ Слово '{word}' не найдено в списке")
        await callback.answer()
        return
    
    channel["ignore_words"].remove(word)
    save_channels()
    
    await callback.message.edit_text(f"✅ Слово '{word}' удалено из списка игнора")
    await callback.answer()

@dp.callback_query(F.data.startswith("upload_template_"))
async def callback_upload_template(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.waiting_for_template_upload)
    
    await callback.message.edit_text(
        "📤 Отправьте текстовый файл (.txt) с шаблоном.\n\n"
        "Файл должен содержать примеры стиля для переписывания новостей.\n"
        "Название файла (без расширения .txt) будет использовано как название шаблона.",
        reply_markup=None
    )
    await callback.answer()

@dp.message(BotStates.waiting_for_template_upload)
async def process_template_upload(message: Message, state: FSMContext):
    if not message.document:
        await message.answer("❌ Пожалуйста, отправьте файл с расширением .txt")
        return
    
    document = message.document
    
    # Исправлено: проверяем расширение в нижнем регистре
    if not document.file_name.lower().endswith('.txt'):
        await message.answer("❌ Файл должен иметь расширение .txt")
        return
    
    # Скачиваем файл
    try:
        file = await bot.get_file(document.file_id)
        
        # Создаем папку для шаблонов, если её нет
        if not os.path.exists(Config.TEMPLATES_DIR):
            os.makedirs(Config.TEMPLATES_DIR)
        
        # Определяем имя шаблона (имя файла без расширения)
        # Исправлено: удаляем последние 4 символа (.txt) независимо от регистра
        template_name = document.file_name[:-4] if document.file_name.lower().endswith('.txt') else document.file_name
        
        # Проверяем, не существует ли уже такой шаблон
        if template_name in bot_settings["templates"]:
            await message.answer(f"❌ Шаблон с именем '{template_name}' уже существует")
            await state.clear()
            return
        
        # Скачиваем файл
        file_path = os.path.join(Config.TEMPLATES_DIR, document.file_name)
        await bot.download(document, destination=file_path)
        
        # Читаем содержимое
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if not content.strip():
            await message.answer("❌ Файл пустой")
            await state.clear()
            return
        
        # Добавляем в настройки
        bot_settings["templates"][template_name] = content
        save_settings()
        
        # Предпросмотр
        preview = content[:200] + "..." if len(content) > 200 else content
        
        await message.answer(
            f"✅ Шаблон '{template_name}' успешно загружен!\n\n"
            f"<b>Предпросмотр:</b>\n{preview}",
            parse_mode=ParseMode.HTML
        )
        
        # Обновляем кнопки
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📋 К списку шаблонов", callback_data="list_templates")
        keyboard.button(text="📤 Загрузить еще", callback_data="upload_template_")
        keyboard.button(text="📋 В меню", callback_data="back_to_menu")
        keyboard.adjust(1)
        
        await message.answer("Выберите действие:", reply_markup=keyboard.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка загрузки шаблона: {e}")
        await message.answer(f"❌ Ошибка загрузки шаблона: {e}")
    
    await state.clear()

@dp.callback_query(F.data.startswith("delete_template_file_"))
async def callback_delete_template_file(callback: CallbackQuery):
    template_name = callback.data.replace("delete_template_file_", "")
    
    if template_name not in bot_settings["templates"]:
        await callback.message.edit_text("❌ Шаблон не найден")
        await callback.answer()
        return
    
    # Удаляем файл (ищем файл с любым регистром расширения)
    file_found = False
    for filename in os.listdir(Config.TEMPLATES_DIR):
        if filename.lower() == f"{template_name}.txt":
            file_path = os.path.join(Config.TEMPLATES_DIR, filename)
            os.remove(file_path)
            file_found = True
            break
    
    # Удаляем из настроек
    del bot_settings["templates"][template_name]
    
    # Обновляем каналы, которые использовали этот шаблон
    for channel_id, channel_data in bot_settings["channels"].items():
        if channel_data.get("template") == template_name:
            channel_data["template"] = None
    
    save_settings()
    save_channels()
    
    await callback.message.edit_text(f"✅ Шаблон '{template_name}' удален")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_channel_"))
async def callback_edit_channel(callback: CallbackQuery):
    channel_id = callback.data.replace("edit_channel_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel_data = bot_settings["channels"][channel_id]
    name = channel_data.get("name", channel_id)
    category = channel_data.get("category", "не указана")
    posts_per_day = channel_data.get("posts_per_day", 0)
    template = channel_data.get("template", "не выбран")
    auto_status = "✅ ВКЛ" if channel_data.get("auto_post_enabled", False) else "❌ ВЫКЛ"
    
    time_mode = channel_data.get("time_mode", "random")
    time_info = ""
    if time_mode == "random":
        min_interval = channel_data.get("min_interval", 100)
        time_info = f"🎲 Случайное время (интервал: {min_interval} мин)"
    else:
        fixed_times = channel_data.get("fixed_times", [])
        time_info = f"🕐 Фиксированное время: {', '.join(fixed_times) if fixed_times else 'не указано'}"
    
    disabled_sources = channel_data.get("disabled_sources", [])
    total_sources = len(Config.SOURCES_BY_CATEGORY.get(category, {}))
    enabled_sources = total_sources - len(disabled_sources)
    sources_info = f"🌐 Источники: {enabled_sources}/{total_sources} включено"
    
    # Информация о словах для игнора
    ignore_words = channel_data.get("ignore_words", [])
    ignore_words_info = f"🗑️ Слов для игнора: {len(ignore_words)}"
    
    # Информация о Gemini
    gemini_key = "✅ Установлен" if channel_data.get("gemini_api_key") else "❌ Не установлен"
    gemini_model = channel_data.get("gemini_model", "gemini-3-flash-preview")
    gemini_model_name = GEMINI_MODELS.get(gemini_model, gemini_model)
    
    # Добавляем кнопку для статистики
    keyboard = InlineKeyboardBuilder()
    
    keyboard.button(text="📊 Статистика канала", callback_data=f"channel_stats_{channel_id}")
    keyboard.button(text="📝 Изменить тематику", callback_data=f"change_category_{channel_id}")
    keyboard.button(text="📊 Изменить кол-во постов", callback_data=f"change_posts_{channel_id}")
    keyboard.button(text="⏰ Настроить время постинга", callback_data=f"set_time_mode_{channel_id}")
    keyboard.button(text="🌐 Управление источниками", callback_data=f"manage_sources_{channel_id}")
    keyboard.button(text="🗑️ Управление игнорируемыми словами", callback_data=f"manage_ignore_words_{channel_id}")
    keyboard.button(text="🎨 Изменить шаблон", callback_data=f"change_template_{channel_id}")
    keyboard.button(text="🔑 Настроить Gemini API", callback_data=f"setup_gemini_{channel_id}")
    
    if channel_data.get("auto_post_enabled", False):
        keyboard.button(text="⏸️ Остановить авто-постинг", callback_data=f"toggle_auto_{channel_id}")
    else:
        keyboard.button(text="▶️ Запустить авто-постинг", callback_data=f"toggle_auto_{channel_id}")
    
    keyboard.button(text="🗑️ Удалить канал", callback_data=f"delete_channel_{channel_id}")
    keyboard.button(text="📋 Назад к списку", callback_data="channel_settings")
    
    keyboard.adjust(1)
    
    info_text = f"⚙️ Настройки канала:\n\n"
    info_text += f"<b>Название:</b> {name}\n"
    info_text += f"<b>ID:</b> {channel_id}\n"
    info_text += f"<b>Тематика:</b> {category}\n"
    info_text += f"<b>Постов/день:</b> {posts_per_day}\n"
    info_text += f"<b>Время постинга:</b> {time_info}\n"
    info_text += f"<b>{sources_info}</b>\n"
    info_text += f"<b>{ignore_words_info}</b>\n"
    info_text += f"<b>Шаблон:</b> {template}\n"
    info_text += f"<b>Gemini API ключ:</b> {gemini_key}\n"
    info_text += f"<b>Gemini модель:</b> {gemini_model_name}\n"
    info_text += f"<b>Авто-постинг:</b> {auto_status}\n\n"
    
    if "auto_post_schedule" in channel_data and channel_data["auto_post_schedule"]:
        info_text += "<b>Расписание на сегодня:</b>\n"
        for i, time_str in enumerate(channel_data["auto_post_schedule"], 1):
            dt = datetime.fromisoformat(f"{datetime.now().date()}T{time_str}:00")
            info_text += f"{i}. {dt.strftime('%H:%M')}\n"
    
    info_text = validate_html(info_text)
    
    await callback.message.edit_text(
        info_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("channel_stats_"))
async def callback_channel_stats(callback: CallbackQuery):
    channel_id = callback.data.replace("channel_stats_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel_data = bot_settings["channels"][channel_id]
    channel_name = channel_data.get("name", channel_id)
    
    await callback.message.edit_text(f"📊 Получаю статистику для канала '{channel_name}'...")
    
    # Получаем статистику
    stats = await get_channel_statistics(channel_id)
    
    if stats is None:
        await callback.message.edit_text(
            f"❌ Не удалось получить статистику для канала '{channel_name}'\n"
            f"Возможно, бот не имеет доступа к истории сообщений или в канале нет сообщений с просмотрами."
        )
        await callback.answer()
        return
    
    # Формируем текст статистики
    stats_text = f"📊 <b>Статистика канала:</b> {channel_name}\n\n"
    
    if stats['24h'] > 0:
        stats_text += f"📈 <b>Средние просмотры:</b>\n"
        stats_text += f"• За 24 часа: {stats['24h']:,} просмотров\n"
        stats_text += f"• За 48 часов: {stats['48h']:,} просмотров\n"
        stats_text += f"• За 72 часа: {stats['72h']:,} просмотров\n\n"
    else:
        stats_text += "📭 <b>Нет данных о просмотрах</b>\n\n"
    
    stats_text += f"📝 <b>Анализ сообщений:</b>\n"
    stats_text += f"• Всего сообщений: {stats['total_messages']:,}\n"
    stats_text += f"• Проанализировано: {stats['analyzed_messages']:,}\n\n"
    
    # Анализ тренда
    if stats['24h'] > 0 and stats['48h'] > 0 and stats['72h'] > 0:
        trend_24_48 = ((stats['24h'] - stats['48h']) / stats['48h'] * 100) if stats['48h'] > 0 else 0
        trend_48_72 = ((stats['48h'] - stats['72h']) / stats['72h'] * 100) if stats['72h'] > 0 else 0
        
        stats_text += f"📊 <b>Тренды:</b>\n"
        
        if trend_24_48 > 0:
            stats_text += f"• Рост за сутки: +{trend_24_48:.1f}% 📈\n"
        elif trend_24_48 < 0:
            stats_text += f"• Спад за сутки: {trend_24_48:.1f}% 📉\n"
        else:
            stats_text += f"• Без изменений за сутки: 0% ➡️\n"
        
        if trend_48_72 > 0:
            stats_text += f"• Рост за двое суток: +{trend_48_72:.1f}% 📈\n"
        elif trend_48_72 < 0:
            stats_text += f"• Спад за двое суток: {trend_48_72:.1f}% 📉\n"
        else:
            stats_text += f"• Без изменений за двое суток: 0% ➡️\n"
    
    # Рекомендации на основе статистики
    if stats['24h'] > 0:
        stats_text += f"\n💡 <b>Рекомендации:</b>\n"
        
        if stats['24h'] < 100:
            stats_text += "• Очень низкая вовлеченность. Попробуйте изменить контент или время публикации.\n"
        elif stats['24h'] < 500:
            stats_text += "• Средняя вовлеченность. Можно улучшить качество контента.\n"
        elif stats['24h'] < 2000:
            stats_text += "• Хорошая вовлеченность. Продолжайте в том же духе!\n"
        else:
            stats_text += "• Отличная вовлеченность! Канал активно развивается.\n"
    
    stats_text += f"\n⏰ <i>Данные обновлены: {get_msk_now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить статистику", callback_data=f"channel_stats_{channel_id}")
    keyboard.button(text="📋 Назад к настройкам", callback_data=f"edit_channel_{channel_id}")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        stats_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("change_category_"))
async def callback_change_category(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("change_category_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_channel_category)
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="💻 IT и технологии", callback_data="category_it")
    keyboard.button(text="🎮 Игры", callback_data="category_games")
    keyboard.button(text="📰 СМИ", callback_data="category_media")
    keyboard.button(text="💰 Экономика и финансы", callback_data="category_economics")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите тематику для канала:\n\n"
        "💻 <b>IT и технологии</b> - новости технологий, программирования, гаджетов\n"
        "🎮 <b>Игры</b> - игровые новости, обзоры, анонсы\n"
        "📰 <b>СМИ</b> - новости медиа, журналистики, СМИ\n"
        "💰 <b>Экономика и финансы</b> - новости экономики, финансов, инвестиций\n\n"
        "<b>Примечание:</b> При смене тематики список отключенных источников будет сброшен.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def callback_set_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("category_", "")
    data = await state.get_data()
    channel_id = data.get("channel_id")
    
    if not channel_id:
        await callback.message.edit_text("❌ Канал не найден")
        await state.clear()
        await callback.answer()
        return
    
    category_names = {
        "it": "IT и технологии",
        "games": "Игры",
        "media": "СМИ",
        "economics": "Экономика и финансы"
    }
    
    category_name = category_names.get(category, category)
    
    if channel_id in bot_settings["channels"]:
        bot_settings["channels"][channel_id]["category"] = category
        bot_settings["channels"][channel_id]["disabled_sources"] = []
        save_channels()
        await callback.message.edit_text(f"✅ Тематика канала изменена на: {category_name}\n\nОтключенные источники сброшены.")
        await state.clear()
    else:
        await state.update_data(category=category, channel_id=channel_id)
        await state.set_state(BotStates.adding_channel_name)
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🚀 Пропустить и использовать ID", callback_data=f"skip_channel_name_{channel_id}")
        keyboard.adjust(1)
        
        await callback.message.edit_text(
            f"✅ Тематика выбрана: {category_name}\n\n"
            "Теперь введите отображаемое название для канала (например: 'Игровые новости'):\n\n"
            "Это название будет отображаться только в панели управления ботом.",
            reply_markup=keyboard.as_markup()
        )
    
    await callback.answer()

@dp.message(BotStates.waiting_for_posts_per_day)
async def process_posts_per_day(message: Message, state: FSMContext):
    try:
        posts = int(message.text)
        if posts < 1:
            await message.answer("Количество постов должно быть не менее 1")
            return
        if posts > 24:
            await message.answer("Максимальное количество постов - 24")
            return
        
        data = await state.get_data()
        channel_id = data.get("channel_id")
        channel_name = data.get("channel_name", channel_id)
        category = data.get("category", "games")
        
        if not channel_id:
            await message.answer("❌ Ошибка: данные канала не найдены")
            await state.clear()
            return
        
        if channel_id in bot_settings["channels"]:
            bot_settings["channels"][channel_id]["posts_per_day"] = posts
            bot_settings["channels"][channel_id]["auto_post_schedule"] = []
            bot_settings["channels"][channel_id]["last_post_date"] = None
            save_channels()
            await message.answer(f"✅ Установлено {posts} постов в день для канала")
        else:
            bot_settings["channels"][channel_id] = {
                "name": channel_name,
                "category": category,
                "posts_per_day": posts,
                "time_mode": "random",
                "min_interval": 100,
                "fixed_times": [],
                "disabled_sources": [],
                "ignore_words": [],
                "template": None,
                "gemini_api_key": None,
                "gemini_model": "gemini-3-flash-preview",
                "gemini_error_count": 0,
                "auto_post_enabled": False,
                "auto_post_schedule": [],
                "last_post_date": None
            }
            
            save_channels()
            
            await message.answer(
                f"✅ Канал <b>{channel_name}</b> успешно добавлен!\n\n"
                f"📊 Настройки канала:\n"
                f"• ID: {channel_id}\n"
                f"• Тематика: {category}\n"
                f"• Постов в день: {posts}\n"
                f"• Режим времени: 🎲 случайное (интервал 100 мин)\n"
                f"• Модель Gemini: {GEMINI_MODELS['gemini-3-flash-preview']}\n"
                f"• Источники: все включены по умолчанию\n"
                f"• Слова для игнора: список пуст\n\n"
                f"📝 Дальнейшие действия:\n"
                f"1. Настройте время постинга в настройках канала\n"
                f"2. Управляйте источниками в настройках канала\n"
                f"3. Управляйте словами для игнора в настройках канала\n"
                f"4. Выберите шаблон стиля в настройках канала\n"
                f"5. Настройте Gemini API ключ для канала\n"
                f"6. Настройте модель Gemini для канала\n"
                f"7. Включите авто-постинг в настройках канала\n"
                f"8. Добавьте шаблоны через меню шаблонов",
                parse_mode=ParseMode.HTML
            )
        
        await state.clear()
        
    except ValueError:
        await message.answer("Укажите число от 1 до 24")

@dp.callback_query(F.data.startswith("setup_gemini_"))
async def callback_setup_gemini(callback: CallbackQuery):
    channel_id = callback.data.replace("setup_gemini_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    channel_name = channel.get("name", channel_id)
    gemini_key_status = "✅ Установлен" if channel.get("gemini_api_key") else "❌ Не установлен"
    gemini_model = channel.get("gemini_model", "gemini-3-flash-preview")
    gemini_model_name = GEMINI_MODELS.get(gemini_model, gemini_model)
    
    keyboard = InlineKeyboardBuilder()
    
    if channel.get("gemini_api_key"):
        keyboard.button(text="🔑 Изменить ключ API", callback_data=f"change_gemini_key_{channel_id}")
        keyboard.button(text="🤖 Изменить модель", callback_data=f"change_gemini_model_{channel_id}")
        keyboard.button(text="🗑️ Удалить ключ API", callback_data=f"delete_gemini_key_{channel_id}")
    else:
        keyboard.button(text="🔑 Установить ключ API", callback_data=f"set_gemini_key_{channel_id}")
    
    keyboard.button(text="📋 Назад к настройкам", callback_data=f"edit_channel_{channel_id}")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        f"🔑 Настройки Gemini API для канала <b>{channel_name}</b>\n\n"
        f"Статус ключа: {gemini_key_status}\n"
        f"Текущая модель: {gemini_model_name}\n\n"
        f"<b>Информация о моделях:</b>\n"
        f"• <b>Gemini 3 Flash Preview</b> - самый быстрый, хорошее качество\n"
        f"• <b>Gemini 2.5 Flash Lite</b> - оптимальный баланс скорости и качества\n"
        f"• <b>Gemini 2.5 Flash</b> - самое высокое качество, немного медленнее\n\n"
        f"<b>Автоматическая ротация моделей:</b>\n"
        f"При ошибках лимита API бот автоматически меняет модель:\n"
        f"1. Первая ошибка - логирование\n"
        f"2. Вторая ошибка - смена на следующую модель\n"
        f"3. Третья ошибка - удаление ключа, требуется новый",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("set_gemini_key_"))
async def callback_set_gemini_key(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("set_gemini_key_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_gemini_key)
    
    await callback.message.edit_text(
        f"🔑 Введите ключ Gemini API для канала:\n\n"
        f"<b>Как получить ключ:</b>\n"
        f"1. Перейдите на <a href='https://makersuite.google.com/app/apikey'>Google AI Studio</a>\n"
        f"2. Войдите в свой Google аккаунт\n"
        f"3. Создайте новый API ключ\n"
        f"4. Скопируйте ключ и вставьте здесь\n\n"
        f"<b>Важно:</b> Ключ будет сохранен только для этого канала.",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("change_gemini_key_"))
async def callback_change_gemini_key(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("change_gemini_key_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_gemini_key)
    
    await callback.message.edit_text(
        f"🔑 Введите новый ключ Gemini API для канала:\n\n"
        f"Старый ключ будет заменен.",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(BotStates.waiting_for_gemini_key)
async def process_gemini_key(message: Message, state: FSMContext):
    api_key = message.text.strip()
    
    if not api_key:
        await message.answer("❌ Ключ API не может быть пустым")
        return
    
    data = await state.get_data()
    channel_id = data.get("channel_id")
    
    if not channel_id or channel_id not in bot_settings["channels"]:
        await message.answer("❌ Ошибка: канал не найден")
        await state.clear()
        return
    
    # Проверяем ключ
    await message.answer("🔑 Проверяю ключ API...")
    
    try:
        test_client = genai.Client(api_key=api_key)
        # Пробуем выполнить простой запрос для проверки
        response = test_client.models.generate_content(
            model="gemini-3-flash-preview",
            contents="Test"
        )
        
        # Если нет исключения, ключ рабочий
        bot_settings["channels"][channel_id]["gemini_api_key"] = api_key
        bot_settings["channels"][channel_id]["gemini_error_count"] = 0  # Сбрасываем счетчик ошибок
        save_channels()
        
        await message.answer(
            f"✅ Ключ Gemini API успешно установлен для канала!\n\n"
            f"Теперь вы можете выбрать модель Gemini в настройках канала.",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg or "403" in error_msg:
            await message.answer(
                "❌ Неверный ключ API. Проверьте ключ и попробуйте снова.\n\n"
                "Убедитесь, что ключ создан в Google AI Studio и активирован.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer(
                f"❌ Ошибка проверки ключа: {error_msg[:200]}",
                parse_mode=ParseMode.HTML
            )
    
    await state.clear()

@dp.callback_query(F.data.startswith("change_gemini_model_"))
async def callback_change_gemini_model(callback: CallbackQuery):
    channel_id = callback.data.replace("change_gemini_model_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    current_model = channel.get("gemini_model", "gemini-3-flash-preview")
    
    keyboard = InlineKeyboardBuilder()
    
    for model_id, model_name in GEMINI_MODELS.items():
        if model_id == current_model:
            prefix = "✅"
        else:
            prefix = "   "
        keyboard.button(text=f"{prefix} {model_name}", callback_data=f"select_gemini_model_{channel_id}_{model_id}")
    
    keyboard.button(text="📋 Назад", callback_data=f"setup_gemini_{channel_id}")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        f"🤖 Выберите модель Gemini для канала:\n\n"
        f"Текущая модель: {GEMINI_MODELS.get(current_model, current_model)}\n\n"
        f"✅ - текущая выбранная модель",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("select_gemini_model_"))
async def callback_select_gemini_model(callback: CallbackQuery):
    data_parts = callback.data.replace("select_gemini_model_", "").split("_")
    if len(data_parts) < 2:
        await callback.answer("❌ Ошибка данных")
        return
    
    channel_id = data_parts[0]
    model_id = data_parts[1]
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    if model_id not in GEMINI_MODELS:
        await callback.message.edit_text("❌ Модель не найдена")
        await callback.answer()
        return
    
    bot_settings["channels"][channel_id]["gemini_model"] = model_id
    save_channels()
    
    await callback.message.edit_text(
        f"✅ Модель Gemini изменена на: {GEMINI_MODELS[model_id]}"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_gemini_key_"))
async def callback_delete_gemini_key(callback: CallbackQuery):
    channel_id = callback.data.replace("delete_gemini_key_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel = bot_settings["channels"][channel_id]
    
    if "gemini_api_key" in channel:
        del channel["gemini_api_key"]
        channel["gemini_error_count"] = 0
        save_channels()
        await callback.message.edit_text("✅ Ключ Gemini API удален")
    else:
        await callback.message.edit_text("❌ Ключ не найден")
    
    await callback.answer()

async def check_news_for_channel(channel_id: str, ignore_processed: bool = False, is_test_post: bool = False):
    if channel_id in posting_locks and posting_locks[channel_id]:
        logger.info(f"⏸️ Постинг для канала {channel_id} заблокирован, ожидание...")
        await asyncio.sleep(30)
        return False
    
    posting_locks[channel_id] = True
    
    try:
        channel = bot_settings["channels"].get(channel_id)
        if not channel:
            logger.error(f"Канал {channel_id} не найден")
            return False
        
        # Проверяем наличие ключа Gemini
        if not channel.get("gemini_api_key"):
            logger.error(f"❌ Для канала {channel_id} не установлен ключ Gemini API")
            await bot.send_message(
                chat_id=Config.ADMIN_ID,
                text=f"❌ Для канала {channel_id} не установлен ключ Gemini API. "
                     f"Установите ключ в настройках канала."
            )
            return False
        
        category = channel.get("category", "games")
        sources = Config.SOURCES_BY_CATEGORY.get(category, {})
        
        if not sources:
            logger.error(f"Нет источников для категории {category}")
            return False
        
        logger.info(f"🔍 Проверяю новости для канала {channel_id} (категория: {category})")
        
        disabled_sources = channel.get("disabled_sources", [])
        
        source_names = [name for name in sources.keys() if name not in disabled_sources]
        random.shuffle(source_names)
        
        if not source_names:
            logger.warning(f"⚠️ Все источники отключены для канала {channel_id}")
            return False
        
        for source_name in source_names:
            url = sources[source_name]
            
            try:
                logger.info(f"📡 Проверяю источник: {source_name} ({url})")
                
                if source_name in ["iz", "lenta", "tass", "tass_economics", "rbc_economics", "rbc_finances"]:
                    news_list = await parse_html_source(url, source_name, category)
                else:
                    news_list = await parse_rss_feed(url, source_name, category)
                
                logger.info(f"📰 Найдено новостей в {source_name}: {len(news_list)}")
                
                if not news_list:
                    continue
                
                for news_item in news_list:
                    # Проверка на обработанные новости
                    if not ignore_processed and news_item.guid in processed_news:
                        logger.info(f"📭 Новость уже обработана: {news_item.title[:50]}...")
                        continue
                    
                    # Для тестовых постов проверяем временное хранилище
                    if is_test_post and news_item.guid in temp_processed_news_for_test:
                        logger.info(f"📭 Новость уже использована в тестовом посте: {news_item.title[:50]}...")
                        continue
                    
                    # Проверка на слова для игнора (канальные)
                    ignore_words = channel.get("ignore_words", [])
                    title_lower = news_item.title.lower()
                    description_lower = news_item.description.lower()
                    
                    should_skip = False
                    for word in ignore_words:
                        if word.lower() in title_lower or word.lower() in description_lower:
                            logger.info(f"⏭️ Пропускаем новость '{news_item.title[:50]}...' из-за канального слова для игнора: {word}")
                            should_skip = True
                            break
                    
                    if should_skip:
                        continue
                    
                    news_theme = extract_main_theme(news_item.title + " " + news_item.description)
                    
                    logger.info(f"🎯 Новая новость: {news_item.title[:50]}...")
                    logger.info(f"📊 Размер полного текста: {len(news_item.full_text)} символов")
                    
                    template_name = channel.get("template")
                    
                    logger.info("🔄 Генерирую контент для поста...")
                    post_content = await generate_post_content(news_item, template_name, channel_id)
                    
                    if post_content is None:
                        logger.info(f"❌ Ошибка генерации контента ИИ для новости: {news_item.title[:50]}..., пропускаем")
                        continue
                    
                    post_text = post_content["text"]
                    image_url = post_content["image_url"]
                    
                    try:
                        image_data = None
                        if image_url:
                            logger.info(f"🖼️ Загружаю изображение: {image_url}")
                            image_data = await download_image(image_url)
                        
                        # Проверяем длину текста для подписи к фото
                        if image_data and len(post_text) > Config.MAX_CAPTION_LENGTH:
                            logger.warning(f"⚠️ Текст слишком длинный для подписи к фото ({len(post_text)} > {Config.MAX_CAPTION_LENGTH}), отправляю как отдельное сообщение")
                            # Сначала отправляем фото без подписи
                            await bot.send_photo(
                                chat_id=channel_id,
                                photo=types.BufferedInputFile(image_data, filename="news.jpg"),
                                caption=""
                            )
                            # Затем отправляем текст отдельно
                            await bot.send_message(
                                chat_id=channel_id,
                                text=post_text,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True
                            )
                        elif image_data:
                            logger.info("📤 Отправляю пост с изображением...")
                            await bot.send_photo(
                                chat_id=channel_id,
                                photo=types.BufferedInputFile(image_data, filename="news.jpg"),
                                caption=post_text,
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            logger.info("📤 Отправляю пост без изображения...")
                            await bot.send_message(
                                chat_id=channel_id,
                                text=post_text,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True
                            )
                        
                        if not ignore_processed:
                            processed_news.add(news_item.guid)
                            save_processed_news()
                        
                        # Для тестовых постов добавляем во временное хранилище
                        if is_test_post:
                            temp_processed_news_for_test.add(news_item.guid)
                        
                        logger.info(f"✅ Опубликована новость в канал {channel_id}")
                        
                        if not ignore_processed and not is_test_post and channel.get("auto_post_enabled", False):
                            if "auto_post_schedule" in channel and channel["auto_post_schedule"]:
                                if channel["auto_post_schedule"]:
                                    removed_time = channel["auto_post_schedule"].pop(0)
                                    logger.info(f"⏰ Удалено время {removed_time} из расписания канала {channel_id}")
                                    save_channels()
                        
                        return True
                                
                    except Exception as e:
                        logger.error(f"❌ Ошибка при отправке в канал {channel_id}: {e}")
                        if "Unauthorized" in str(e) or "401" in str(e):
                            logger.error(f"Ошибка авторизации для канала {channel_id}.")
                            channel["auto_post_enabled"] = False
                            save_channels()
                            if channel_id in auto_post_tasks:
                                await stop_auto_post_for_channel(channel_id)
                            return False
                        continue
                            
            except Exception as e:
                logger.error(f"❌ Ошибка при публикации новости из {source_name}: {e}")
                continue
        
        logger.info(f"📭 Новых новостей не найдено для канала {channel_id}")
        return False
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_news_for_channel для канала {channel_id}: {e}")
        return False
        
    finally:
        posting_locks[channel_id] = False
        logger.info(f"🔓 Снята блокировка постинга для канала {channel_id}")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этому боту.")
        return
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📢 Управление каналами", callback_data="manage_channels")
    keyboard.button(text="📝 Управление шаблонами", callback_data="manage_templates")
    keyboard.button(text="⚙️ Настройки", callback_data="settings")
    keyboard.button(text="📊 Статистика", callback_data="stats")
    keyboard.button(text="❓ Помощь", callback_data="help")
    
    keyboard.adjust(1)
    
    channels_count = len(bot_settings["channels"])
    templates_count = len(bot_settings["templates"])
    
    # Считаем каналы с установленными ключами Gemini
    channels_with_gemini = sum(1 for c in bot_settings["channels"].values() if c.get("gemini_api_key"))
    
    await message.answer(
        f"🤖 Бот для публикации новостей в Telegram\n\n"
        f"📊 Статистика:\n"
        f"• Каналов: {channels_count}\n"
        f"• С ключами Gemini: {channels_with_gemini}\n"
        f"• Шаблонов: {templates_count}\n"
        f"• Обработано новостей: {len(processed_news)}\n"
        f"• Полный текст статей: {'✅ ВКЛЮЧЕНО' if bot_settings['get_full_text'] else '❌ ВЫКЛЮЧЕНО'}\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup()
    )

@dp.message(Command("channels"))
async def cmd_channels(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить канал", callback_data="add_channel")
    
    if bot_settings["channels"]:
        keyboard.button(text="📋 Список каналов", callback_data="list_channels")
        keyboard.button(text="⚙️ Настройки канала", callback_data="channel_settings")
        keyboard.button(text="📝 Пробный пост", callback_data="test_post_menu")
        keyboard.button(text="🗑️ Удалить канал", callback_data="delete_channel")
    
    keyboard.adjust(1)
    
    await message.answer(
        "📢 Управление каналами\n\n"
        f"Всего каналов: {len(bot_settings['channels'])}\n\n"
        "Перед добавлением канала:\n"
        "1. Добавьте бота в канал как администратора\n"
        "2. Дайте боту права на отправку сообщений\n"
        "3. Убедитесь, что бот не заблокирован в канале\n"
        "4. Получите ключ Gemini API для канала",
        reply_markup=keyboard.as_markup()
    )

@dp.message(Command("templates"))
async def cmd_templates(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📤 Загрузить шаблон", callback_data="upload_template_")
    keyboard.button(text="📂 Загрузить шаблон из файла", callback_data="load_template_file")
    keyboard.button(text="📋 Список шаблонов", callback_data="list_templates")
    keyboard.button(text="🗑️ Удалить шаблон", callback_data="delete_template_menu")
    
    keyboard.adjust(1)
    
    await message.answer(
        "📝 Управление шаблонами\n\n"
        f"Всего шаблонов: {len(bot_settings['templates'])}\n\n"
        "Шаблоны можно загрузить двумя способами:\n"
        "1. Отправить текстовый файл боту\n"
        "2. Загрузить из существующего файла в папке 'templates'\n\n"
        "Шаблон должен содержать примеры стиля для переписывания новостей.",
        reply_markup=keyboard.as_markup()
    )

@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    keyboard = InlineKeyboardBuilder()
    
    if bot_settings["add_game_links"]:
        keyboard.button(text="🔗 Выключить ссылки на игры", callback_data="toggle_game_links")
    else:
        keyboard.button(text="🔗 Включить ссылки на игры", callback_data="toggle_game_links")
    
    if bot_settings["blur_logos"]:
        keyboard.button(text="🖼️ Выключить блюр логотипов", callback_data="toggle_blur_logos")
    else:
        keyboard.button(text="🖼️ Включить блюр логотипов", callback_data="toggle_blur_logos")
    
    if bot_settings["get_full_text"]:
        keyboard.button(text="📖 Выключить полный текст статей", callback_data="toggle_full_text")
    else:
        keyboard.button(text="📖 Включить полный текст статей", callback_data="toggle_full_text")
    
    keyboard.button(text="🔄 Перезагрузить шаблоны", callback_data="reload_templates")
    keyboard.button(text="🧹 Очистить обработанные новости", callback_data="clear_processed_news")
    
    keyboard.adjust(1)
    
    game_links_status = "✅ ВКЛЮЧЕНО" if bot_settings["add_game_links"] else "❌ ВЫКЛЮЧЕНО"
    blur_logos_status = "✅ ВКЛЮЧЕНО" if bot_settings["blur_logos"] else "❌ ВЫКЛЮЧЕНО"
    full_text_status = "✅ ВКЛЮЧЕНО" if bot_settings["get_full_text"] else "❌ ВЫКЛЮЧЕНО"
    
    await message.answer(
        f"⚙️ Настройки бота\n\n"
        f"🔗 Автоматические ссылки на игры: {game_links_status}\n"
        f"🖼️ Размытие логотипов на картинках: {blur_logos_status}\n"
        f"📖 Полный текст статей: {full_text_status}\n\n"
        f"При включении полного текста бот будет загружать полные статьи\n"
        f"с сайтов источников, что улучшит качество переписанных постов.",
        reply_markup=keyboard.as_markup()
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    channels_with_auto = sum(1 for c in bot_settings["channels"].values() if c.get("auto_post_enabled", False))
    channels_with_gemini = sum(1 for c in bot_settings["channels"].values() if c.get("gemini_api_key"))
    
    # Статистика по моделям Gemini
    gemini_models_stats = {}
    for channel in bot_settings["channels"].values():
        if channel.get("gemini_api_key"):
            model = channel.get("gemini_model", "gemini-3-flash-preview")
            gemini_models_stats[model] = gemini_models_stats.get(model, 0) + 1
    
    # Статистика по словам для игнора
    total_ignore_words = 0
    for channel in bot_settings["channels"].values():
        total_ignore_words += len(channel.get("ignore_words", []))
    
    stats_text = f"""
📊 Статистика бота:

Каналы:
• Всего: {len(bot_settings['channels'])}
• С авто-постингом: {channels_with_auto}
• С ключами Gemini: {channels_with_gemini}
• Всего слов для игнора: {total_ignore_words}

Шаблоны: {len(bot_settings['templates'])}

Новости:
• Обработано: {len(processed_news)}

Настройки:
• Ссылки на игры: {'✅ ВКЛЮЧЕНО' if bot_settings['add_game_links'] else '❌ ВЫКЛЮЧЕНО'}
• Размытие логотипов: {'✅ ВКЛЮЧЕНО' if bot_settings['blur_logos'] else '❌ ВЫКЛЮЧЕНО'}
• Полный текст статей: {'✅ ВКЛЮЧЕНО' if bot_settings['get_full_text'] else '❌ ВЫКЛЮЧЕНО'}
"""
    
    if gemini_models_stats:
        stats_text += "\n🤖 Модели Gemini:\n"
        for model_id, count in gemini_models_stats.items():
            model_name = GEMINI_MODELS.get(model_id, model_id)
            stats_text += f"• {model_name}: {count} каналов\n"
    
    if bot_settings["channels"]:
        stats_text += "\n📢 Каналы:\n"
        for channel_id, channel_data in bot_settings["channels"].items():
            name = channel_data.get("name", channel_id)
            category = channel_data.get("category", "не указана")
            posts_per_day = channel_data.get("posts_per_day", 0)
            ignore_words_count = len(channel_data.get("ignore_words", []))
            
            time_mode = channel_data.get("time_mode", "random")
            if time_mode == "random":
                min_interval = channel_data.get("min_interval", 100)
                time_info = f"🎲 случайное ({min_interval} мин)"
            else:
                fixed_times = channel_data.get("fixed_times", [])
                time_info = f"🕐 фиксированное ({len(fixed_times)} времен)"
            
            gemini_icon = "🔑" if channel_data.get("gemini_api_key") else "❌"
            
            auto_status = "✅" if channel_data.get("auto_post_enabled", False) else "❌"
            ignore_icon = f"🗑️{ignore_words_count}" if ignore_words_count > 0 else ""
            stats_text += f"• {name} ({category}): {posts_per_day} постов/день, {time_info} {gemini_icon} {ignore_icon} {auto_status}\n"
    
    await message.answer(stats_text)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этому боту.")
        return
    
    help_text = """
🤖 Команды управления ботом:

Основные команды:
/start - Главное меню
/channels - Управление каналов
/templates - Управление шаблонами
/settings - Настройки бота
/stats - Статистика
/help - Помощь

📢 Управление каналами:
1. Добавьте бота в канал как администратора
2. Дайте боту права на отправку сообщений
3. Добавьте канал через меню бота
4. Укажите тематику (IT, игры, СМИ, Экономика и финансы)
5. Установите количество постов в день
6. Настройте время постинга (случайное или фиксированное)
7. Управляйте источниками новостей
8. Управляйте словами для игнора (каждому каналу свой список)
9. Выберите шаблон стиля
10. Установите ключ Gemini API для канала
11. Настройте модель Gemini для канала
12. Включите авто-постинг в настройках канала

💰 Экономика и финансы:
• Новости экономики и финансов
• Источники: РБК Экономика, ТАСС Экономика, РБК Финансы
• Актуальные данные о курсах валют, инвестициях, бизнесе

📖 Полный текст статей:
• Бот загружает полные статьи с сайтов источников
• Улучшает качество переписанных постов
• Можно включать/выключать в настройках
• При отключении используется только краткое описание

🗑️ Управление словами для игнора:
• Каждый канал имеет свой список слов для игнора
• Можно добавлять несколько слов через запятую
• Если заголовок или описание новости содержат слово из списка, новость пропускается
• Можно добавлять и удалять слова через настройки канала

🖼️ Размытие логотипов:
• Бот автоматически размывает логотипы и названия сайтов на картинках
• Можно включать/выключать в настройках бота
• Особенно полезно для новостей из СМИ, где часто добавляют водяные знаки

📊 Статистика канала:
• Показывает средние просмотры за 24ч, 48ч, 72ч
• Анализирует тренды вовлеченности
• Дает рекомендации по улучшению контента

⏰ Настройка времени постинга:
• 🎲 Случайное время - бот сам выбирает время с указанным интервалом
• 🕐 Фиксированное время - вы указываете конкретное время через запятую
  Пример: 09:00,12:00,15:00,18:00,21:00

🌐 Управление источниками:
• Вы можете включать/выключать отдельные источники для каждого канала
• Отключенные источники не будут использоваться при поиске новостей
• При смене категории список отключенных источников сбрасывается

📝 Шаблоны:
• Шаблоны можно загружать двумя способами:
  1. Отправить текстовый файл боту
  2. Загрузить из существующего файла в папке 'templates'
• Файл должен содержать примеры стиля
• Бот будет использовать этот стиль для переписывания

🔑 Gemini API:
• Для каждого канала требуется отдельный ключ Gemini API
• Получите ключ на https://makersuite.google.com/app/apikey
• Можно выбрать одну из трех моделей Gemini
• При ошибках лимита API бот автоматически меняет модель

🤖 Модели Gemini:
• Gemini 3 Flash Preview - самый быстрый, хорошее качество
• Gemini 2.5 Flash Lite - оптимальный баланс скорости и качества
• Gemini 2.5 Flash - самое высокое качество, немного медленнее

⚙️ Автоматическая ротация моделей:
При ошибках лимита API:
1. Первая ошибка - логирование
2. Вторая ошибка - смена на следующую модель
3. Третья ошибка - удаление ключа, требуется новый

⚙️ Настройки:
• Включение/выключение ссылок на игры
• Включение/выключение размытия логотипов
• Включение/выключение полного текста статей
• Очистка обработанных новостей
• Перезагрузка шаблонов

🔗 Особенности:
• Бот сохраняет HTML форматирование из шаблонов
• Автоматически добавляет ссылки на игры (если включено)
• Размывает логотипы на картинках (если включено)
• Загружает полный текст статей (если включено)
• Поддерживает разные тематики новостей
• Гибкое управление источниками для каждого канала
• Индивидуальные списки слов для игнора для каждого канала
• Индивидуальные ключи Gemini API для каждого канала
• Автоматическая ротация моделей при ошибках
"""
    
    await message.answer(help_text)

@dp.message(Command("test_post"))
async def cmd_test_post(message: Message):
    if str(message.from_user.id) != Config.ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    if not bot_settings["channels"]:
        await message.answer("❌ Нет добавленных каналов")
        return
    
    channel_id = list(bot_settings["channels"].keys())[0]
    channel_data = bot_settings["channels"][channel_id]
    category = channel_data.get("category", "games")
    
    await message.answer(f"🔄 Тестовый пост для канала {channel_id} (категория: {category})...")
    
    success = await check_news_for_channel(channel_id, ignore_processed=True, is_test_post=True)
    
    if success:
        await message.answer("✅ Тестовый пост опубликован!")
    else:
        await message.answer("❌ Не удалось опубликовать тестовый пост")

@dp.callback_query(F.data == "manage_channels")
async def callback_manage_channels(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить канал", callback_data="add_channel")
    
    if bot_settings["channels"]:
        keyboard.button(text="📋 Список каналов", callback_data="list_channels")
        keyboard.button(text="⚙️ Настройки канала", callback_data="channel_settings")
        keyboard.button(text="📝 Пробный пост", callback_data="test_post_menu")
        keyboard.button(text="🗑️ Удалить канал", callback_data="delete_channel")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "📢 Управление каналами\n\n"
        f"Всего каналов: {len(bot_settings['channels'])}\n\n"
        "Перед добавлением канала:\n"
        "1. Добавьте бота в канал как администратора\n"
        "2. Дайте боту права на отправку сообщений\n"
        "3. Убедитесь, что бот не заблокирован в канале\n"
        "4. Получите ключ Gemini API для канала",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "test_post_menu")
async def callback_test_post_menu(callback: CallbackQuery):
    if not bot_settings["channels"]:
        await callback.message.edit_text("❌ Нет добавленных каналов")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for channel_id, channel_data in bot_settings["channels"].items():
        name = channel_data.get("name", channel_id)
        keyboard.button(text=f"📝 {name}", callback_data=f"do_test_post_{channel_id}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите канал для пробного поста:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("do_test_post_"))
async def callback_do_test_post(callback: CallbackQuery):
    try:
        channel_id = callback.data.replace("do_test_post_", "")
        
        if channel_id not in bot_settings["channels"]:
            await callback.message.edit_text("❌ Канал не найден")
            await callback.answer()
            return
        
        channel_data = bot_settings["channels"][channel_id]
        name = channel_data.get("name", channel_id)
        category = channel_data.get("category", "games")
        
        await callback.message.edit_text(f"🔄 Пробный пост для канала '{name}' (категория: {category})...")
        await callback.answer()
        
        success = await check_news_for_channel(channel_id, ignore_processed=True, is_test_post=True)
        
        if success:
            await bot.send_message(chat_id=Config.ADMIN_ID, text=f"✅ Пробный пост опубликован в канал '{name}'!")
        else:
            await bot.send_message(chat_id=Config.ADMIN_ID, text=f"❌ Не удалось опубликовать пробный пост в канал '{name}'. Возможно, нет новостей в источниках или не установлен ключ Gemini API.")
    except Exception as e:
        logger.error(f"Ошибка в callback_do_test_post: {e}")
        await bot.send_message(chat_id=Config.ADMIN_ID, text=f"❌ Ошибка при выполнении пробного поста: {e}")

@dp.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.waiting_for_new_channel)
    await callback.message.edit_text(
        "Введите ID канала или юзернейм:\n\n"
        "📌 Форматы:\n"
        "• Юзернейм: @channelname\n"
        "• ID канала: -1001234567890\n\n"
        "📝 Как получить ID канала:\n"
        "1. Добавьте бота @username_to_id_bot в канал\n"
        "2. Перешлите любое сообщение из канала боту\n"
        "3. Бот покажет ID канала\n\n"
        "⚠️ Важно: Бот должен быть администратором канала!\n"
        "⚠️ Также потребуется ключ Gemini API для этого канала.",
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: CallbackQuery):
    if not bot_settings["channels"]:
        await callback.message.edit_text("❌ Нет добавленных каналов")
        await callback.answer()
        return
    
    channels_text = "📋 Список каналов:\n\n"
    
    for channel_id, channel_data in bot_settings["channels"].items():
        name = channel_data.get("name", channel_id)
        category = channel_data.get("category", "не указана")
        posts_per_day = channel_data.get("posts_per_day", 0)
        template = channel_data.get("template", "не выбран")
        auto_status = "✅ ВКЛ" if channel_data.get("auto_post_enabled", False) else "❌ ВЫКЛ"
        gemini_status = "🔑" if channel_data.get("gemini_api_key") else "❌"
        ignore_words_count = len(channel_data.get("ignore_words", []))
        
        time_mode = channel_data.get("time_mode", "random")
        if time_mode == "random":
            min_interval = channel_data.get("min_interval", 100)
            time_info = f"🎲 случайное ({min_interval} мин)"
        else:
            fixed_times = channel_data.get("fixed_times", [])
            time_info = f"🕐 фиксированное: {', '.join(fixed_times) if fixed_times else 'не указано'}"
        
        channels_text += f"<b>{name}</b>\n"
        channels_text += f"ID: {channel_id}\n"
        channels_text += f"Тематика: {category}\n"
        channels_text += f"Постов/день: {posts_per_day}\n"
        channels_text += f"Время: {time_info}\n"
        channels_text += f"Шаблон: {template}\n"
        channels_text += f"Gemini: {gemini_status}\n"
        channels_text += f"Слов для игнора: {ignore_words_count}\n"
        channels_text += f"Авто-постинг: {auto_status}\n\n"
    
    channels_text = validate_html(channels_text)
    
    await callback.message.edit_text(
        channels_text,
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data == "channel_settings")
async def callback_channel_settings(callback: CallbackQuery):
    if not bot_settings["channels"]:
        await callback.message.edit_text("❌ Нет добавленных каналов")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for channel_id, channel_data in bot_settings["channels"].items():
        name = channel_data.get("name", channel_id)
        keyboard.button(text=f"⚙️ {name}", callback_data=f"edit_channel_{channel_id}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите канал для настройки:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("change_posts_"))
async def callback_change_posts(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("change_posts_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_posts_per_day)
    
    current_posts = bot_settings["channels"][channel_id].get("posts_per_day", 1)
    
    await callback.message.edit_text(
        f"Введите количество постов в день (от 1 до 24):\n\n"
        f"Текущее значение: {current_posts}",
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("change_template_"))
async def callback_change_template(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("change_template_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    if not bot_settings["templates"]:
        await callback.message.edit_text("❌ Нет загруженных шаблонов")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    
    keyboard = InlineKeyboardBuilder()
    
    for template_name in bot_settings["templates"].keys():
        keyboard.button(text=f"📝 {template_name}", callback_data=f"select_template_{template_name}")
    
    keyboard.button(text="❌ Без шаблона", callback_data="select_template_none")
    keyboard.adjust(1)
    
    current_template = bot_settings["channels"][channel_id].get("template", "не выбран")
    
    await callback.message.edit_text(
        f"Выберите шаблон для канала:\n\n"
        f"Текущий шаблон: {current_template}",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("select_template_"))
async def callback_select_template(callback: CallbackQuery, state: FSMContext):
    template_name = callback.data.replace("select_template_", "")
    data = await state.get_data()
    channel_id = data.get("channel_id")
    
    if not channel_id or channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await state.clear()
        await callback.answer()
        return
    
    if template_name == "none":
        bot_settings["channels"][channel_id]["template"] = None
        await callback.message.edit_text("✅ Шаблон удален. Будет использован стандартный стиль.")
    elif template_name in bot_settings["templates"]:
        bot_settings["channels"][channel_id]["template"] = template_name
        await callback.message.edit_text(f"✅ Шаблон '{template_name}' установлен для канала.")
    else:
        await callback.message.edit_text("❌ Шаблон не найден")
        await state.clear()
        await callback.answer()
        return
    
    save_channels()
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_auto_"))
async def callback_toggle_auto(callback: CallbackQuery):
    channel_id = callback.data.replace("toggle_auto_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel_data = bot_settings["channels"][channel_id]
    
    if channel_data.get("auto_post_enabled", False):
        channel_data["auto_post_enabled"] = False
        await stop_auto_post_for_channel(channel_id)
        await callback.message.edit_text("✅ Авто-постинг остановлен для канала")
    else:
        if not channel_data.get("category"):
            await callback.message.edit_text("❌ Укажите тематику канала перед включением авто-постинга")
            await callback.answer()
            return
        
        if channel_data.get("posts_per_day", 0) <= 0:
            await callback.message.edit_text("❌ Укажите количество постов в день перед включением авто-постинга")
            await callback.answer()
            return
        
        if not channel_data.get("gemini_api_key"):
            await callback.message.edit_text("❌ Установите ключ Gemini API для канала перед включением авто-постинга")
            await callback.answer()
            return
        
        has_access, _ = await test_channel_access(channel_id)
        if not has_access:
            await callback.message.edit_text("❌ Нет доступа к каналу. Проверьте права бота.")
            await callback.answer()
            return
        
        channel_data["auto_post_enabled"] = True
        channel_data["auto_post_schedule"] = []
        channel_data["last_post_date"] = None
        await start_auto_post_for_channel(channel_id)
        await callback.message.edit_text("✅ Авто-постинг запущен для канала")
    
    save_channels()
    await callback.answer()

@dp.callback_query(F.data == "delete_channel")
async def callback_delete_channel_menu(callback: CallbackQuery):
    if not bot_settings["channels"]:
        await callback.message.edit_text("❌ Нет добавленных каналов")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for channel_id, channel_data in bot_settings["channels"].items():
        name = channel_data.get("name", channel_id)
        keyboard.button(text=f"🗑️ {name}", callback_data=f"delete_channel_{channel_id}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите канал для удаления:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_channel_"))
async def callback_delete_channel_confirm(callback: CallbackQuery):
    channel_id = callback.data.replace("delete_channel_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel_name = bot_settings["channels"][channel_id].get("name", channel_id)
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Да, удалить", callback_data=f"confirm_delete_{channel_id}")
    keyboard.button(text="❌ Нет, отменить", callback_data="manage_channels")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить канал <b>{channel_name}</b>?\n\n"
        "Все настройки канала будут удалены безвозвратно.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def callback_confirm_delete(callback: CallbackQuery):
    channel_id = callback.data.replace("confirm_delete_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    channel_name = bot_settings["channels"][channel_id].get("name", channel_id)
    
    await stop_auto_post_for_channel(channel_id)
    
    del bot_settings["channels"][channel_id]
    save_channels()
    
    await callback.message.edit_text(f"✅ Канал '{channel_name}' удален")
    await callback.answer()

@dp.callback_query(F.data == "manage_templates")
async def callback_manage_templates(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📤 Загрузить шаблон", callback_data="upload_template_")
    keyboard.button(text="📂 Загрузить шаблон из файла", callback_data="load_template_file")
    keyboard.button(text="📋 Список шаблонов", callback_data="list_templates")
    keyboard.button(text="🗑️ Удалить шаблон", callback_data="delete_template_menu")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "📝 Управление шаблонами\n\n"
        f"Всего шаблонов: {len(bot_settings['templates'])}\n\n"
        "Шаблоны можно загрузить двумя способами:\n"
        "1. Отправить текстовый файл боту\n"
        "2. Загрузить из существующего файла в папке 'templates'\n\n"
        "Шаблон должен содержать примеры стиля для переписывания новостей.",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "load_template_file")
async def callback_load_template_file(callback: CallbackQuery):
    if not os.path.exists(Config.TEMPLATES_DIR):
        os.makedirs(Config.TEMPLATES_DIR)
    
    template_files = []
    if os.path.exists(Config.TEMPLATES_DIR):
        # Исправлено: ищем файлы с любым регистром расширения .txt
        for f in os.listdir(Config.TEMPLATES_DIR):
            if f.lower().endswith('.txt'):
                template_files.append(f)
    
    if not template_files:
        await callback.message.edit_text(
            f"❌ В папке '{Config.TEMPLATES_DIR}' нет файлов с шаблонами.\n\n"
            f"Создайте текстовый файл (.txt) в папке '{Config.TEMPLATES_DIR}' "
            f"с примерами стиля для переписивания.",
            reply_markup=None
        )
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for filename in template_files:
        template_name = filename[:-4] if filename.lower().endswith('.txt') else filename
        keyboard.button(text=f"📄 {template_name}", callback_data=f"load_template_{template_name}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите файл для загрузки как шаблон:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("load_template_"))
async def callback_load_template(callback: CallbackQuery):
    template_name = callback.data.replace("load_template_", "")
    
    # Ищем файл с любым регистром расширения
    filename = None
    for f in os.listdir(Config.TEMPLATES_DIR):
        if f.lower() == f"{template_name}.txt":
            filename = f
            break
    
    if not filename:
        filename = f"{template_name}.txt"
    
    filepath = os.path.join(Config.TEMPLATES_DIR, filename)
    
    if not os.path.exists(filepath):
        await callback.message.edit_text(f"❌ Файл {filename} не найден")
        await callback.answer()
        return
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if not content.strip():
            await callback.message.edit_text(f"❌ Файл {filename} пустой")
            await callback.answer()
            return
        
        bot_settings["templates"][template_name] = content
        save_settings()
        
        preview = content[:200] + "..." if len(content) > 200 else content
        
        await callback.message.edit_text(
            f"✅ Шаблон '{template_name}' загружен!\n\n"
            f"<b>Предпросмотр:</b>\n{preview}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка загрузки шаблона: {e}")
    
    await callback.answer()

@dp.callback_query(F.data == "list_templates")
async def callback_list_templates(callback: CallbackQuery):
    if not bot_settings["templates"]:
        await callback.message.edit_text("❌ Нет загруженных шаблонов")
        await callback.answer()
        return
    
    templates_text = "📋 Список шаблонов:\n\n"
    
    for name, content in bot_settings["templates"].items():
        preview = content[:100] + "..." if len(content) > 100 else content
        templates_text += f"<b>{name}</b>\n{preview}\n\n"
    
    templates_text = validate_html(templates_text)
    
    await callback.message.edit_text(
        templates_text,
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data == "delete_template_menu")
async def callback_delete_template_menu(callback: CallbackQuery):
    if not bot_settings["templates"]:
        await callback.message.edit_text("❌ Нет загруженных шаблонов")
        await callback.answer()
        return
    
    keyboard = InlineKeyboardBuilder()
    
    for template_name in bot_settings["templates"].keys():
        keyboard.button(text=f"🗑️ {template_name}", callback_data=f"delete_template_file_{template_name}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "Выберите шаблон для удаления:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "settings")
async def callback_settings(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    
    if bot_settings["add_game_links"]:
        keyboard.button(text="🔗 Выключить ссылки на игры", callback_data="toggle_game_links")
    else:
        keyboard.button(text="🔗 Включить ссылки на игры", callback_data="toggle_game_links")
    
    if bot_settings["blur_logos"]:
        keyboard.button(text="🖼️ Выключить блюр логотипов", callback_data="toggle_blur_logos")
    else:
        keyboard.button(text="🖼️ Включить блюр логотипов", callback_data="toggle_blur_logos")
    
    if bot_settings["get_full_text"]:
        keyboard.button(text="📖 Выключить полный текст статей", callback_data="toggle_full_text")
    else:
        keyboard.button(text="📖 Включить полный текст статей", callback_data="toggle_full_text")
    
    keyboard.button(text="🔄 Перезагрузить шаблоны", callback_data="reload_templates")
    keyboard.button(text="🧹 Очистить обработанные новости", callback_data="clear_processed_news")
    keyboard.button(text="📋 Назад в меню", callback_data="back_to_menu")
    
    keyboard.adjust(1)
    
    game_links_status = "✅ ВКЛЮЧЕНО" if bot_settings["add_game_links"] else "❌ ВЫКЛЮЧЕНО"
    blur_logos_status = "✅ ВКЛЮЧЕНО" if bot_settings["blur_logos"] else "❌ ВЫКЛЮЧЕНО"
    full_text_status = "✅ ВКЛЮЧЕНО" if bot_settings["get_full_text"] else "❌ ВЫКЛЮЧЕНО"
    
    await callback.message.edit_text(
        f"⚙️ Настройки бота\n\n"
        f"🔗 Автоматические ссылки на игры: {game_links_status}\n"
        f"🖼️ Размытие логотипов на картинках: {blur_logos_status}\n"
        f"📖 Полный текст статей: {full_text_status}\n\n"
        f"При включении бот будет добавлять ссылки на магазины "
        f"(Steam, PlayStation Store и т.д.) при упоминании игр.\n"
        f"Размытие логотипов применяется к изображениям из новостей СМИ.\n"
        f"Полный текст статей улучшает качество переписанных постов.",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "toggle_game_links")
async def callback_toggle_game_links(callback: CallbackQuery):
    bot_settings["add_game_links"] = not bot_settings["add_game_links"]
    save_settings()
    
    status = "ВКЛЮЧЕНО" if bot_settings["add_game_links"] else "ВЫКЛЮЧЕНО"
    
    await callback.message.edit_text(f"✅ Автоматические ссылки на игры {status}")
    await callback.answer()

@dp.callback_query(F.data == "toggle_blur_logos")
async def callback_toggle_blur_logos(callback: CallbackQuery):
    bot_settings["blur_logos"] = not bot_settings["blur_logos"]
    save_settings()
    
    status = "ВКЛЮЧЕНО" if bot_settings["blur_logos"] else "ВЫКЛЮЧЕНО"
    
    await callback.message.edit_text(f"✅ Размытие логотипов на картинках {status}")
    await callback.answer()

@dp.callback_query(F.data == "toggle_full_text")
async def callback_toggle_full_text(callback: CallbackQuery):
    bot_settings["get_full_text"] = not bot_settings["get_full_text"]
    save_settings()
    
    status = "ВКЛЮЧЕНО" if bot_settings["get_full_text"] else "ВЫКЛЮЧЕНО"
    
    await callback.message.edit_text(f"✅ Полный текст статей {status}")
    await callback.answer()

@dp.callback_query(F.data == "reload_templates")
async def callback_reload_templates(callback: CallbackQuery):
    old_count = len(bot_settings["templates"])
    load_templates_from_files()
    new_count = len(bot_settings["templates"])
    
    await callback.message.edit_text(
        f"✅ Шаблоны перезагружены!\n\n"
        f"Было: {old_count}\n"
        f"Стало: {new_count}\n\n"
        f"Загружено {new_count - old_count} новых шаблонов."
    )
    await callback.answer()

@dp.callback_query(F.data == "clear_processed_news")
async def callback_clear_processed_news(callback: CallbackQuery):
    global processed_news
    old_count = len(processed_news)
    processed_news.clear()
    save_processed_news()
    
    await callback.message.edit_text(f"✅ Обработанные новости очищены! Удалено {old_count} записей.")
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    channels_with_auto = sum(1 for c in bot_settings["channels"].values() if c.get("auto_post_enabled", False))
    channels_with_gemini = sum(1 for c in bot_settings["channels"].values() if c.get("gemini_api_key"))
    
    # Статистика по моделям Gemini
    gemini_models_stats = {}
    for channel in bot_settings["channels"].values():
        if channel.get("gemini_api_key"):
            model = channel.get("gemini_model", "gemini-3-flash-preview")
            gemini_models_stats[model] = gemini_models_stats.get(model, 0) + 1
    
    # Статистика по словам для игнора
    total_ignore_words = 0
    for channel in bot_settings["channels"].values():
        total_ignore_words += len(channel.get("ignore_words", []))
    
    stats_text = f"""
📊 Статистика бота:

Каналы:
• Всего: {len(bot_settings['channels'])}
• С авто-постингом: {channels_with_auto}
• С ключами Gemini: {channels_with_gemini}
• Всего слов для игнора: {total_ignore_words}

Шаблоны: {len(bot_settings['templates'])}

Новости:
• Обработано: {len(processed_news)}

Настройки:
• Ссылки на игры: {'✅ ВКЛЮЧЕНО' if bot_settings['add_game_links'] else '❌ ВЫКЛЮЧЕНО'}
• Размытие логотипов: {'✅ ВКЛЮЧЕНО' if bot_settings['blur_logos'] else '❌ ВЫКЛЮЧЕНО'}
• Полный текст статей: {'✅ ВКЛЮЧЕНО' if bot_settings['get_full_text'] else '❌ ВЫКЛЮЧЕНО'}
"""
    
    if gemini_models_stats:
        stats_text += "\n🤖 Модели Gemini:\n"
        for model_id, count in gemini_models_stats.items():
            model_name = GEMINI_MODELS.get(model_id, model_id)
            stats_text += f"• {model_name}: {count} каналов\n"
    
    if bot_settings["channels"]:
        stats_text += "\n📢 Каналы:\n"
        for channel_id, channel_data in bot_settings["channels"].items():
            name = channel_data.get("name", channel_id)
            category = channel_data.get("category", "не указана")
            posts_per_day = channel_data.get("posts_per_day", 0)
            ignore_words_count = len(channel_data.get("ignore_words", []))
            
            time_mode = channel_data.get("time_mode", "random")
            if time_mode == "random":
                min_interval = channel_data.get("min_interval", 100)
                time_info = f"🎲 случайное ({min_interval} мин)"
            else:
                fixed_times = channel_data.get("fixed_times", [])
                time_info = f"🕐 фиксированное ({len(fixed_times)} времен)"
            
            gemini_icon = "🔑" if channel_data.get("gemini_api_key") else "❌"
            
            auto_status = "✅" if channel_data.get("auto_post_enabled", False) else "❌"
            ignore_icon = f"🗑️{ignore_words_count}" if ignore_words_count > 0 else ""
            stats_text += f"• {name} ({category}): {posts_per_day} постов/день, {time_info} {gemini_icon} {ignore_icon} {auto_status}\n"
    
    await callback.message.edit_text(stats_text)
    await callback.answer()

@dp.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    help_text = """
🤖 Команды управления ботом:

Основные команды:
/start - Главное меню
/channels - Управление каналов
/templates - Управление шаблонами
/settings - Настройки бота
/stats - Статистика
/help - Помощь

📢 Управление каналами:
1. Добавьте бота в канал как администратора
2. Дайте боту права на отправку сообщений
3. Добавьте канал через меню бота
4. Укажите тематику (IT, игры, СМИ, Экономика и финансы)
5. Установите количество постов в день
6. Настройте время постинга (случайное или фиксированное)
7. Управляйте источниками новостей
8. Управляйте словами для игнора (каждому каналу свой список)
9. Выберите шаблон стиля
10. Установите ключ Gemini API для канала
11. Настройте модель Gemini для канала
12. Включите авто-постинг в настройках канала

💰 Экономика и финансы:
• Новости экономики и финансов
• Источники: РБК Экономика, ТАСС Экономика, РБК Финансы
• Актуальные данные о курсах валют, инвестициях, бизнесе

📖 Полный текст статей:
• Бот загружает полные статьи с сайтов источников
• Улучшает качество переписанных постов
• Можно включать/выключать в настройках
• При отключении используется только краткое описание

🗑️ Управление словами для игнора:
• Каждый канал имеет свой список слов для игнора
• Можно добавлять несколько слов через запятую
• Если заголовок или описание новости содержат слово из списка, новость пропускается
• Можно добавлять и удалять слова через настройки канала

🖼️ Размытие логотипов:
• Бот автоматически размывает логотипы и названия сайтов на картинках
• Можно включать/выключать в настройках бота
• Особенно полезно для новостей из СМИ, где часто добавляют водяные знаки

📊 Статистика канала:
• Показывает средние просмотры за 24ч, 48ч, 72ч
• Анализирует тренды вовлеченности
• Дает рекомендации по улучшению контента

⏰ Настройка времени постинга:
• 🎲 Случайное время - бот сам выбирает время с указанным интервалом
• 🕐 Фиксированное время - вы указываете конкретное время через запятую
  Пример: 09:00,12:00,15:00,18:00,21:00

🌐 Управление источниками:
• Вы можете включать/выключать отдельные источники для каждого канала
• Отключенные источники не будут использоваться при поиске новостей
• При смене категории список отключенных источников сбрасывается

📝 Шаблоны:
• Шаблоны можно загружать двумя способами:
  1. Отправить текстовый файл боту
  2. Загрузить из существующего файла в папке 'templates'
• Файл должен содержать примеры стиля
• Бот будет использовать этот стиль для переписывания

🔑 Gemini API:
• Для каждого канала требуется отдельный ключ Gemini API
• Получите ключ на https://makersuite.google.com/app/apikey
• Можно выбрать одну из трех моделей Gemini
• При ошибках лимита API бот автоматически меняет модель

🤖 Модели Gemini:
• Gemini 3 Flash Preview - самый быстрый, хорошее качество
• Gemini 2.5 Flash Lite - оптимальный баланс скорости и качества
• Gemini 2.5 Flash - самое высокое качество, немного медленнее

⚙️ Автоматическая ротация моделей:
При ошибках лимита API:
1. Первая ошибка - логирование
2. Вторая ошибка - смена на следующую модель
3. Третья ошибка - удаление ключа, требуется новый

⚙️ Настройки:
• Включение/выключение ссылок на игры
• Включение/выключение размытия логотипов
• Включение/выключение полного текста статей
• Очистка обработанных новостей
• Перезагрузка шаблонов

🔗 Особенности:
• Бот сохраняет HTML форматирование из шаблонов
• Автоматически добавляет ссылки на игры (если включено)
• Размывает логотипы на картинках (если включено)
• Загружает полный текст статей (если включено)
• Поддерживает разные тематики новостей
• Гибкое управление источниками для каждого канала
• Индивидуальные списки слов для игнора для каждого канала
• Индивидуальные ключи Gemini API для каждого канала
• Автоматическая ротация моделей при ошибках
"""
    
    await callback.message.edit_text(help_text)
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📢 Управление каналами", callback_data="manage_channels")
    keyboard.button(text="📝 Управление шаблонами", callback_data="manage_templates")
    keyboard.button(text="⚙️ Настройки", callback_data="settings")
    keyboard.button(text="📊 Статистика", callback_data="stats")
    keyboard.button(text="❓ Помощь", callback_data="help")
    
    keyboard.adjust(1)
    
    channels_count = len(bot_settings["channels"])
    templates_count = len(bot_settings["templates"])
    
    # Считаем каналы с установленными ключами Gemini
    channels_with_gemini = sum(1 for c in bot_settings["channels"].values() if c.get("gemini_api_key"))
    
    await callback.message.edit_text(
        f"🤖 Бот для публикации новостей в Telegram\n\n"
        f"📊 Статистика:\n"
        f"• Каналов: {channels_count}\n"
        f"• С ключами Gemini: {channels_with_gemini}\n"
        f"• Шаблонов: {templates_count}\n"
        f"• Обработано новостей: {len(processed_news)}\n"
        f"• Полный текст статей: {'✅ ВКЛЮЧЕНО' if bot_settings['get_full_text'] else '❌ ВЫКЛЮЧЕНО'}\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_channel_name_"))
async def callback_skip_channel_name(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("skip_channel_name_", "")
    data = await state.get_data()
    
    channel_name = channel_id
    category = data.get("category", "games")
    
    if not channel_id:
        await callback.message.edit_text("❌ Ошибка: данные канала не найдены")
        await state.clear()
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id, channel_name=channel_name, category=category)
    await state.set_state(BotStates.waiting_for_posts_per_day)
    
    await callback.message.edit_text(
        f"✅ Название канала: {channel_name}\n\n"
        "Теперь введите количество постов в день (от 1 до 24):",
        reply_markup=None
    )
    await callback.answer()

@dp.message(BotStates.waiting_for_new_channel)
async def process_new_channel(message: Message, state: FSMContext):
    channel_id = message.text.strip()
    
    if not channel_id:
        await message.answer("❌ Введите ID канала или юзернейм")
        return
    
    if channel_id in bot_settings["channels"]:
        await message.answer("❌ Этот канал уже добавлен")
        await state.clear()
        return
    
    await message.answer(f"🔄 Проверяю доступ к каналу {channel_id}...")
    
    has_access, access_info = await test_channel_access(channel_id)
    
    if not has_access:
        await message.answer(f"❌ Не удалось получить доступ к каналу:\n\n{access_info}")
        await state.clear()
        return
    
    try:
        chat = await bot.get_chat(channel_id)
        channel_name = chat.title
        
        await state.update_data(channel_id=channel_id, channel_name=channel_name)
        await state.set_state(BotStates.waiting_for_channel_category)
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="💻 IT и технологии", callback_data="category_it")
        keyboard.button(text="🎮 Игры", callback_data="category_games")
        keyboard.button(text="📰 СМИ", callback_data="category_media")
        keyboard.button(text="💰 Экономика и финансы", callback_data="category_economics")
        keyboard.adjust(1)
        
        await message.answer(
            f"✅ Канал найден: <b>{channel_name}</b>\n\n"
            "Выберите тематику для канала:\n\n"
            "💻 <b>IT и технологии</b> - новости технологий, программирования, гаджетов\n"
            "🎮 <b>Игры</b> - игровые новости, обзоры, анонсы\n"
            "📰 <b>СМИ</b> - новости медиа, журналистики, СМИ\n"
            "💰 <b>Экономика и финансы</b> - новости экономики, финансов, инвестиций",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении информации о канале: {e}")
        await state.clear()

@dp.message(BotStates.adding_channel_name)
async def process_channel_name(message: Message, state: FSMContext):
    channel_name = message.text.strip()
    
    if not channel_name:
        await message.answer("❌ Введите название для канала")
        return
    
    if len(channel_name) > 100:
        await message.answer("❌ Слишком длинное название. Максимум 100 символов.")
        return
    
    data = await state.get_data()
    channel_id = data.get("channel_id")
    
    if not channel_id:
        await message.answer("❌ Ошибка: ID канала не найден. Начните добавление канала заново.")
        await state.clear()
        return
    
    await state.update_data(channel_name=channel_name)
    await state.set_state(BotStates.waiting_for_posts_per_day)
    
    await message.answer(
        f"✅ Название канала сохранено: {channel_name}\n\n"
        "Теперь введите количество постов в день (от 1 до 24):"
    )

@dp.callback_query(F.data.startswith("set_time_mode_"))
async def callback_set_time_mode(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.replace("set_time_mode_", "")
    
    if channel_id not in bot_settings["channels"]:
        await callback.message.edit_text("❌ Канал не найден")
        await callback.answer()
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(BotStates.waiting_for_channel_time_mode)
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🎲 Случайное время", callback_data=f"time_mode_random_{channel_id}")
    keyboard.button(text="🕐 Фиксированное время", callback_data=f"time_mode_fixed_{channel_id}")
    keyboard.adjust(1)
    
    channel_data = bot_settings["channels"][channel_id]
    current_mode = channel_data.get("time_mode", "random")
    current_mode_text = "🎲 случайное" if current_mode == "random" else "🕐 фиксированное"
    
    await callback.message.edit_text(
        f"Выберите режим времени постинга для канала:\n\n"
        f"Текущий режим: {current_mode_text}\n\n"
        f"🎲 <b>Случайное время</b> - бот сам выберет время постов с указанным интервалом\n"
        f"🕐 <b>Фиксированное время</b> - вы указываете конкретное время через запятую (например: 09:00,12:00,15:00)",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("time_mode_"))
async def callback_time_mode_selected(callback: CallbackQuery, state: FSMContext):
    mode_data = callback.data.replace("time_mode_", "")
    mode, channel_id = mode_data.split("_", 1)
    
    data = await state.get_data()
    if not data.get("channel_id"):
        await state.update_data(channel_id=channel_id)
    
    if mode == "random":
        await state.set_state(BotStates.waiting_for_channel_random_settings)
        
        channel_data = bot_settings["channels"][channel_id]
        current_interval = channel_data.get("min_interval", 100)
        current_posts = channel_data.get("posts_per_day", 1)
        
        await callback.message.edit_text(
            f"🎲 Настройки случайного времени\n\n"
            f"Текущие настройки:\n"
            f"• Количество постов в день: {current_posts}\n"
            f"• Минимальный интервал: {current_interval} минут\n\n"
            f"Введите количество постов в день и минимальный интервал через пробел.\n"
            f"Пример: <code>5 120</code> (5 постов в день, интервал 120 минут)",
            parse_mode=ParseMode.HTML
        )
    else:
        await state.set_state(BotStates.waiting_for_channel_fixed_times)
        
        channel_data = bot_settings["channels"][channel_id]
        current_times = channel_data.get("fixed_times", [])
        current_times_text = ", ".join(current_times) if current_times else "не указаны"
        
        await callback.message.edit_text(
            f"🕐 Настройки фиксированного времени\n\n"
            f"Текущее время: {current_times_text}\n\n"
            f"Введите время постов через запятую (формат ЧЧ:ММ).\n"
            f"Пример: <code>09:00,12:00,15:00,18:00,21:00</code>\n\n"
            f"⏰ Время указывается по московскому времени (МСК)\n\n"
            f"<b>Примечание:</b> Для фиксированного времени минимальный интервал не применяется.",
            parse_mode=ParseMode.HTML
        )
    
    await callback.answer()

@dp.message(BotStates.waiting_for_channel_random_settings)
async def process_random_settings(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        channel_id = data.get("channel_id")
        
        if not channel_id or channel_id not in bot_settings["channels"]:
            await message.answer("❌ Ошибка: канал не найден")
            await state.clear()
            return
        
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.answer("❌ Введите два числа через пробел: количество постов и интервал в минутах")
            return
        
        posts_per_day = int(parts[0])
        min_interval = int(parts[1])
        
        if posts_per_day < 1 or posts_per_day > 24:
            await message.answer("❌ Количество постов должно быть от 1 до 24")
            return
        
        if min_interval < 30:
            await message.answer("❌ Минимальный интервал должен быть не менее 30 минут")
            return
        
        channel = bot_settings["channels"][channel_id]
        channel["time_mode"] = "random"
        channel["posts_per_day"] = posts_per_day
        channel["min_interval"] = min_interval
        channel["auto_post_schedule"] = []
        channel["last_post_date"] = None
        
        save_channels()
        
        example_times = generate_random_schedule_for_channel(posts_per_day, min_interval)
        
        await message.answer(
            f"✅ Настройки случайного времени сохранены!\n\n"
            f"📊 Настройки:\n"
            f"• Режим: 🎲 случайное время\n"
            f"• Постов в день: {posts_per_day}\n"
            f"• Минимальный интервал: {min_interval} минут\n\n"
            f"📅 Пример расписания: {', '.join(example_times)}\n\n"
            f"Расписание будет перегенерировано при следующем запуске авто-постинга."
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите два числа через пробел. Пример: 5 120")
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек случайного времени: {e}")
        await message.answer("❌ Ошибка при сохранении настроек")
        await state.clear()

@dp.message(BotStates.waiting_for_channel_fixed_times)
async def process_fixed_times(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        channel_id = data.get("channel_id")
        
        if not channel_id or channel_id not in bot_settings["channels"]:
            await message.answer("❌ Ошибка: канал не найден")
            await state.clear()
            return
    
        times = parse_post_times(message.text)
        
        if not times:
            await message.answer("❌ Некорректный формат времени. Используйте формат ЧЧ:ММ через запятую")
            return
        
        if len(times) != len(set(times)):
            await message.answer("❌ Времена должны быть уникальны")
            return
        
        times = sorted(times)
        
        channel = bot_settings["channels"][channel_id]
        channel["time_mode"] = "fixed"
        channel["fixed_times"] = times
        channel["posts_per_day"] = len(times)
        channel["auto_post_schedule"] = []
        channel["last_post_date"] = None
        
        save_channels()
        
        await message.answer(
            f"✅ Фиксированное время сохранено!\n\n"
            f"📊 Настройки:\n"
            f"• Режим: 🕐 фиксированное время\n"
            f"• Время постов: {', '.join(times)}\n"
            f"• Постов в день: {len(times)}\n\n"
            f"<b>Примечание:</b> Для фиксированного времени минимальный интервал не применяется.\n\n"
            f"Расписание будет обновлено при следующем запуске авто-постинга.",
            parse_mode=ParseMode.HTML
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении фиксированного времени: {e}")
        await message.answer("❌ Ошибка при сохранении времени")
        await state.clear()

async def shutdown():
    await stop_all_auto_posts()
    
    save_settings()
    save_processed_news()
    save_channels()
    
    logger.info("Бот завершил работу")

async def main():
    # Устанавливаем библиотеку brotli для поддержки br кодировки
    try:
        import brotli
        logger.info("✅ Поддержка brotli кодировки включена")
    except ImportError:
        logger.warning("⚠️ Библиотека brotli не установлена. Установите: pip install brotli")
    
    load_settings()
    load_processed_news()
    load_channels()
    load_templates_from_files()
    
    logger.info("=" * 50)
    logger.info("Запуск бота...")
    logger.info(f"Каналов: {len(bot_settings['channels'])}")
    logger.info(f"Шаблонов: {len(bot_settings['templates'])}")
    
    # Считаем каналы с ключами Gemini
    channels_with_gemini = sum(1 for c in bot_settings["channels"].values() if c.get("gemini_api_key"))
    logger.info(f"Каналов с ключами Gemini: {channels_with_gemini}")
    
    logger.info(f"Добавление ссылок на игры: {'ВКЛЮЧЕНО' if bot_settings['add_game_links'] else 'ВЫКЛЮЧЕНО'}")
    logger.info(f"Размытие логотипов: {'ВКЛЮЧЕНО' if bot_settings['blur_logos'] else 'ВЫКЛЮЧЕНО'}")
    logger.info(f"Полный текст статей: {'ВКЛЮЧЕНО' if bot_settings['get_full_text'] else 'ВЫКЛЮЧЕНО'}")
    logger.info(f"Обработано новостей: {len(processed_news)}")
    logger.info("=" * 50)
    
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот запущен: @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
        return
    
    await start_all_auto_posts()
    
    logger.info("🚀 Бот готов к работе!")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения...")
    finally:
        await shutdown()

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(shutdown()))
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        try:
            save_settings()
            save_processed_news()
            save_channels()
        except:
            pass