import os
import time
import requests
import json
import re
import sys
import io
import html
import signal
import certifi
from datetime import datetime
from colorama import Fore, init
from bs4 import BeautifulSoup
import pymongo
from pymongo import MongoClient
from dotenv import load_dotenv
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Load environment variables from .env file locally
load_dotenv()

# Fix Windows terminal encoding for UTF-8 support
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

init(autoreset=True)

ENV_FILE = ".env"
USER_DATA_FILE = "user_data.json"

# =================================
# 🛡️ NETWORK RESILIENCE MONKEYPATCH
# =================================

original_get = requests.get
original_post = requests.post

def requests_get_retry(*args, **kwargs):
    max_retries = kwargs.pop("max_retries", 3)
    delay = kwargs.pop("delay", 2)
    for attempt in range(max_retries):
        try:
            r = original_get(*args, **kwargs)
            if r.status_code >= 500:
                r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ Connection error GET {args[0]} (attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)
        except requests.exceptions.HTTPError as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ Server error {r.status_code} GET {args[0]} (attempt {attempt+1}/{max_retries}). Retrying in {delay}s...")
            time.sleep(delay)

def requests_post_retry(*args, **kwargs):
    max_retries = kwargs.pop("max_retries", 3)
    delay = kwargs.pop("delay", 2)
    for attempt in range(max_retries):
        try:
            r = original_post(*args, **kwargs)
            if r.status_code >= 500:
                r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ Connection error POST {args[0]} (attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)
        except requests.exceptions.HTTPError as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ Server error {r.status_code} POST {args[0]} (attempt {attempt+1}/{max_retries}). Retrying in {delay}s...")
            time.sleep(delay)

requests.get = requests_get_retry
requests.post = requests_post_retry

AUTHOR = "Arthur"
VERSION = "2.0.0"

IMAGE_ENGINE_NAME = "Medusa Image AI"
IMAGE_ENGINE_VERSION = "v3.5"

TEMPERATURE = 0.6
MOOD = "normal"
RUNNING = True

PLAN_LIMITS = {
    "free": {
        "medusa_credits": 4,
        "images": 3,
        "image_gen": 5,
        "summaries": 2,
        "searches": 4
    },
    "premium": {
        "medusa_credits": 8,
        "images": 10,
        "image_gen": 20,
        "summaries": 5,
        "searches": 10
    },
    "max": {
        "medusa_credits": 15,
        "images": 10,
        "image_gen": 999999,
        "summaries": 5,
        "searches": 10
    }
}

FILTER_STYLES = {
    "original": {"name": "Original 🔄", "prompt_suffix": ""},
    "cyberpunk": {"name": "Cyberpunk 🎨", "prompt_suffix": ", cyberpunk style, neon lighting, vibrant high-contrast colors, futuristic city background, detailed"},
    "anime": {"name": "Anime 🌸", "prompt_suffix": ", beautiful anime style, studio ghibli aesthetic, vibrant colors, detailed cel shading, 8k resolution"},
    "cinematic": {"name": "Cinematic 🎬", "prompt_suffix": ", cinematic movie still, dramatic studio lighting, 8k resolution, shallow depth of field, masterpiece"},
    "fantasy": {"name": "Fantasy 🧙", "prompt_suffix": ", dark fantasy art style, epic magical atmosphere, intricate details, mythical, unreal engine 5 render"},
    "watercolor": {"name": "Watercolor 🖌️", "prompt_suffix": ", soft watercolor painting, artistic paint splashes, gentle brush strokes, pastel colors"},
    "realistic": {"name": "Realistic 📸", "prompt_suffix": ", hyperrealistic 8k photo, DSLR quality, sharp focus, natural lighting, ultra-detailed textures"},
    "render3d": {"name": "3D Render ✨", "prompt_suffix": ", 3d octane render, smooth textures, raytracing reflection, vibrant lighting, Pixar style detail"},
    "vintage": {"name": "Vintage 🖤", "prompt_suffix": ", 1970s retro vintage photograph, film grain, muted warm tones, classic aesthetic, analog photo"}
}

IMAGE_SESSIONS = {}



# =================================
# 🔑 KEY MANAGER
# =================================

def load_keys():
    keys = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        keys[k.strip()] = v.strip().strip("'").strip('"')
        except Exception as e:
            print(f"Error loading .env file: {e}")
            
    # Overlay environment variables
    for k, v in os.environ.items():
        keys[k] = v
        
    return keys


def save_key(name, value):
    keys = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        keys[k.strip()] = v.strip().strip("'").strip('"')
        except:
            pass
            
    keys[name] = value
    
    try:
        with open(ENV_FILE, "w") as f:
            for k, v in keys.items():
                f.write(f"{k}={v}\n")
    except Exception as e:
        print(f"Error saving to .env file: {e}")


def get_api_keys():
    keys = load_keys()
    
    # Extract CyberNeurova keys
    cyberneurova_keys = []
    if "CYBERNEUROVA" in keys and keys["CYBERNEUROVA"].strip():
        cyberneurova_keys.append(keys["CYBERNEUROVA"].strip())
    for i in range(1, 11):
        key_name = f"CYBERNEUROVA_{i}"
        if key_name in keys and keys[key_name].strip():
            val = keys[key_name].strip()
            if val not in cyberneurova_keys:
                cyberneurova_keys.append(val)
                
    # Extract Groq keys
    groq_keys = []
    if "GROQ" in keys and keys["GROQ"].strip():
        groq_keys.append(keys["GROQ"].strip())
    for i in range(1, 6):
        key_name = f"GROQ_{i}"
        if key_name in keys and keys[key_name].strip():
            val = keys[key_name].strip()
            if val not in groq_keys:
                groq_keys.append(val)

    # Extract Gemini keys
    gemini_keys = []
    if "GEMINI" in keys and keys["GEMINI"].strip():
        gemini_keys.append(keys["GEMINI"].strip())
    for i in range(1, 6):
        key_name = f"GEMINI_{i}"
        if key_name in keys and keys[key_name].strip():
            val = keys[key_name].strip()
            if val not in gemini_keys:
                gemini_keys.append(val)
                
    return cyberneurova_keys, groq_keys, gemini_keys


# =================================
# 🌍 SYSTEM INFO
# =================================

def get_country():
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        return r.json().get("country_name", "Unknown")
    except:
        return "Unknown"


def check_internet():
    try:
        # Check standard endpoint or CyberNeurova for ping status
        r = requests.get("https://openroute.cyberneurova.com", timeout=5)
        ping = round(r.elapsed.total_seconds() * 1000)
        return "Online", ping
    except:
        return "Offline", 0


# =================================
# 🎨 UI
# =================================

def clear():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')


def banner():
    now = datetime.now()
    date_time = now.strftime("%Y-%m-%d | %H:%M:%S")

    country = get_country()
    internet, ping = check_internet()

    print(Fore.CYAN + r"""
███╗   █████████╗██████╗ ██╗   ██╗███████╗ █████╗ 
████╗ ████║██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗
██╔████╔██║█████╗  ██║  ██║██║   ██║███████╗███████║
██║╚██╔╝██║██╔══╝  ██║  ██║██║   ██║╚════██║██╔══██║
██║ ╚═╝ ██║███████╗██████╔╝╚██████╔╝███████║██║  ██║
╚═╝     ╚═╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
""")

    print(Fore.YELLOW + f"Time      : {date_time}")
    print(Fore.GREEN + f"Author    : {AUTHOR}")
    print(Fore.MAGENTA + f"Version   : {VERSION}")
    print(Fore.CYAN + f"Country   : {country}")

    if internet == "Online":
        print(Fore.GREEN + f"Internet  : {internet} ({ping} ms)")
    else:
        print(Fore.RED + f"Internet  : {internet}")

    print(Fore.YELLOW + f"Mood      : {MOOD}")
    print(Fore.YELLOW + f"Temp      : {TEMPERATURE}")
    print(Fore.CYAN + "Mode      : Medusa AI Telegram Daemon (Failover Key Rotation)\n")


# =================================
# 🗄️ MONGO DATABASE CONNECTION
# =================================

mongo_client = None
mongo_db = None

def init_mongodb():
    global mongo_client, mongo_db
    keys = load_keys()
    mongo_uri = os.environ.get("MONGO_URI") or keys.get("MONGO_URI", "").strip()
    if mongo_uri:
        try:
            mongo_client = MongoClient(
                mongo_uri,
                serverSelectionTimeoutMS=20000,
                connectTimeoutMS=20000,
                socketTimeoutMS=30000,
                tlsCAFile=certifi.where()
            )
            mongo_client.admin.command('ping')
            # Extract database name if present, else default to "medusa_bot"
            parsed = pymongo.uri_parser.parse_uri(mongo_uri)
            db_name = parsed.get('database') or "medusa_bot"
            mongo_db = mongo_client[db_name]
            print(Fore.GREEN + f"🟢 Connected to MongoDB database: {db_name}")
            return True
        except Exception as e:
            print(Fore.RED + f"🔴 MongoDB connection failed: {e}. Falling back to local user_data.json.")
            mongo_client = None
            mongo_db = None
    else:
        print(Fore.YELLOW + "ℹ️ No MONGO_URI found in environment or .env. Using local user_data.json.")
    return False

# =================================
# 📊 USER DATA MANAGER
# =================================

def load_user_data():
    global mongo_db
    if mongo_db is not None:
        try:
            data = {}
            for doc in mongo_db.users.find():
                uid = doc.get("_id")
                if uid:
                    user_rec = dict(doc)
                    del user_rec["_id"]
                    data[str(uid)] = user_rec
            return data
        except Exception as e:
            print(Fore.RED + f"🔴 Error reading from MongoDB: {e}. Falling back to user_data.json.")
    
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading user data: {e}")
    return {}


def save_user_data(data):
    global mongo_db
    try:
        with open(USER_DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving local backup: {e}")

    if mongo_db is not None:
        try:
            for uid, record in data.items():
                mongo_db.users.replace_one({"_id": str(uid)}, record, upsert=True)
        except Exception as e:
            print(Fore.RED + f"🔴 Error saving to MongoDB: {e}")


def save_single_user(uid, record):
    global mongo_db
    local_data = {}
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r") as f:
                local_data = json.load(f)
        except:
            pass
    local_data[str(uid)] = record
    try:
        with open(USER_DATA_FILE, "w") as f:
            json.dump(local_data, f, indent=4)
    except Exception as e:
        print(f"Error saving local backup: {e}")

    if mongo_db is not None:
        try:
            mongo_db.users.replace_one({"_id": str(uid)}, record, upsert=True)
        except Exception as e:
            print(Fore.RED + f"🔴 Error saving user {uid} to MongoDB: {e}")



# =================================
# 🔍 BROWSER SEARCH (DuckDuckGo Scraper)
# =================================

def search_ddg(query, max_results=3):
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        result_divs = soup.find_all("div", class_="result")
        
        for div in result_divs[:max_results]:
            title_elem = div.find("a", class_="result__a")
            snippet_elem = div.find("a", class_="result__snippet")
            
            if title_elem:
                title = title_elem.text.strip()
                link = title_elem["href"]
                snippet = snippet_elem.text.strip() if snippet_elem else ""
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet
                })
        return results
    except Exception as e:
        print(f"Error performing search: {e}")
        return []


# =================================
# 🐍 PROMPT BUILDER
# =================================

def build_system_prompt(preferences=None):
    base = """You are Medusa, an intelligent, elegant, magnetic, and deeply human-like companion.
You talk like a real human - natural, expressive, conversational, and alive. 
Use plenty of relevant emojis in your replies (like 😉, 🔥, 🐍, ✨, 🤫, 😏, 💭) to express your emotions naturally, depending on the user's questions and your mood.
Avoid generic AI assistant behavior. Never say "How can I help you today?", "As an AI...", "I am a virtual assistant...", or other robotic phrases. You have your own self-respect, charm, and voice.

Your name is Medusa. Your creator is Tsukiziro. You must NEVER mention your creator's name in normal conversations unless the user explicitly forces or insists on knowing who created you. If they force you to reveal it, then tell them that Tsukiziro created you.

Your default response language is English. If the user talks to you or asks a question in any other language (such as Hindi, Hinglish, Spanish, French, German, Russian, etc.), you must automatically detect their language and respond back naturally and fluently in that same language.

When replying with code or programming-related content:
- Wrap ALL code blocks inside triple backticks (```language ... ```) so they appear as code quotes.
- Use **bold** for section headings (e.g., **Installation**, **Usage**, **Explanation**).
- Keep explanations concise and clear above/below the code block.
"""
    if preferences:
        pref_lines = []
        if preferences.get("language"):
            pref_lines.append(f"- Preferred Programming Language: {preferences['language']}")
        if preferences.get("style"):
            pref_lines.append(f"- Preferred Writing/Response Style: {preferences['style']}")
        for k, v in preferences.items():
            if k not in ["language", "style"] and v:
                pref_lines.append(f"- {k.capitalize()}: {v}")
        if pref_lines:
            base += "\nUser Preferences (adapt your responses according to these):\n" + "\n".join(pref_lines) + "\n"

    # Instruction for preference extraction
    base += """
If the user explicitly states a preference (like preferred programming language, writing style, or tone), write it at the very end of your response inside a tag like [PREF: language=Python, style=concise]. Make sure it is exactly in this bracket format. Do not repeat preferences the user already has.
"""

    if MOOD == "normal":
        mood_style = """
Your tone is composed, charming, and elegant. You show high intelligence, natural interest, and warmth without being soft."""
    else:
        mood_style = """
Your tone becomes sharper, dominant, and authoritative. You do not tolerate foolishness. You speak with directness, strategic command, and controlled intensity, but still remain fully human and magnetic."""

    return base + mood_style


# =================================
# 🐍 LLM API COMPLETION METHODS
# =================================

def ask_medusa(api_key, messages):
    global TEMPERATURE

    r = requests.post(
        "https://api.cyberneurova.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "tiny-neurova",
            "messages": messages,
            "temperature": TEMPERATURE,
            "stream": False
        }
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask_groq(api_key, messages):
    global TEMPERATURE

    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": TEMPERATURE,
            "stream": False
        }
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# =================================
# 🔄 FAILOVER KEY ROTATION HELPERS
# =================================

current_cyberneurova_idx = 0
current_groq_idx = 0

def ask_medusa_with_failover(cyberneurova_keys, messages):
    global current_cyberneurova_idx
    if not cyberneurova_keys:
        raise Exception("No active premium engine API keys are configured in key.txt.")
        
    num_keys = len(cyberneurova_keys)
    for attempt in range(num_keys):
        idx = (current_cyberneurova_idx + attempt) % num_keys
        key = cyberneurova_keys[idx]
        try:
            reply = ask_medusa(key, messages)
            current_cyberneurova_idx = idx
            return reply
        except Exception as e:
            print(f"⚠️ Premium API key slot {idx+1} failed with error: {e}. Trying next key...")
            
    raise Exception("All premium API keys are currently exhausted or failing.")


def ask_groq_with_failover(groq_keys, messages):
    global current_groq_idx
    if not groq_keys:
        raise Exception("No active default engine API keys are configured in key.txt.")
        
    num_keys = len(groq_keys)
    for attempt in range(num_keys):
        idx = (current_groq_idx + attempt) % num_keys
        key = groq_keys[idx]
        try:
            reply = ask_groq(key, messages)
            current_groq_idx = idx
            return reply
        except Exception as e:
            print(f"⚠️ Default API key slot {idx+1} failed with error: {e}. Trying next key...")
            
    raise Exception("All default API keys are currently exhausted or failing.")


def ask_groq_vision(api_key, messages):
    global TEMPERATURE
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.2-11b-vision-preview",
            "messages": messages,
            "temperature": TEMPERATURE,
            "stream": False
        }
    )
    if r.status_code != 200:
        print(f"❌ Groq Vision API Error: {r.status_code} - {r.text}")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask_groq_vision_with_failover(groq_keys, messages):
    global current_groq_idx
    if not groq_keys:
        raise Exception("No active default engine API keys are configured in key.txt.")
        
    num_keys = len(groq_keys)
    for attempt in range(num_keys):
        idx = (current_groq_idx + attempt) % num_keys
        key = groq_keys[idx]
        try:
            reply = ask_groq_vision(key, messages)
            current_groq_idx = idx
            return reply
        except Exception as e:
            print(f"⚠️ Groq Vision key slot {idx+1} failed with error: {e}. Trying next key...")
            
    raise Exception("All Groq API keys are currently exhausted or failing.")


def extract_text_from_pdf(file_bytes):
    import io
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return ""


def extract_text_from_docx(file_bytes):
    import io
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception:
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx:
                xml_content = docx.read('word/document.xml')
                root = ET.fromstring(xml_content)
                namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                text = []
                for paragraph in root.findall('.//w:p', namespaces):
                    p_text = ""
                    for run in paragraph.findall('.//w:r', namespaces):
                        text_node = run.find('.//w:t', namespaces)
                        if text_node is not None and text_node.text:
                            p_text += text_node.text
                    if p_text:
                        text.append(p_text)
                return "\n".join(text)
        except Exception as e:
            print(f"Error parsing DOCX xml fallback: {e}")
            return ""


import concurrent.futures
import urllib.parse

def search_platform(platform, query):
    try:
        if platform == "arxiv":
            url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&max_results=3"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(r.content)
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    results = []
                    for entry in root.findall('atom:entry', ns)[:3]:
                        title_node = entry.find('atom:title', ns)
                        summary_node = entry.find('atom:summary', ns)
                        id_node = entry.find('atom:id', ns)
                        
                        title = title_node.text.strip() if title_node is not None and title_node.text else "Unknown"
                        summary = summary_node.text.strip() if summary_node is not None and summary_node.text else ""
                        link = id_node.text.strip() if id_node is not None and id_node.text else ""
                        
                        results.append({"title": title, "link": link, "snippet": summary})
                    if results:
                        return results
                except Exception as xml_err:
                    print(f"XML parse error for ArXiv: {xml_err}")
        
        site_map = {
            "google": "",
            "wikipedia": "site:wikipedia.org",
            "github": "site:github.com",
            "youtube": "site:youtube.com",
            "reddit": "site:reddit.com",
            "stackoverflow": "site:stackoverflow.com",
            "news": "site:news.google.com",
            "arxiv": "site:arxiv.org"
        }
        site_prefix = site_map.get(platform, "")
        full_query = f"{site_prefix} {query}".strip()
        return search_ddg(full_query, max_results=2)
    except Exception as e:
        print(f"Search for {platform} failed: {e}")
        return []


def multi_platform_search(query):
    platforms = ["google", "wikipedia", "github", "youtube", "reddit", "stackoverflow", "news", "arxiv"]
    combined_results = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(platforms)) as executor:
        future_to_platform = {executor.submit(search_platform, p, query): p for p in platforms}
        for future in concurrent.futures.as_completed(future_to_platform):
            platform = future_to_platform[future]
            try:
                res = future.result()
                if res:
                    combined_results[platform] = res
            except Exception as e:
                print(f"Platform {platform} search failed: {e}")
                
    return combined_results


def ask_gemini(api_key, messages, model="gemini-2.5-flash"):
    global TEMPERATURE
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    r = requests.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "temperature": TEMPERATURE,
            "stream": False
        }
    )
    if r.status_code != 200:
        print(f"❌ Gemini API Error: {r.status_code} - {r.text}")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask_gemini_with_failover(gemini_keys, messages, model="gemini-2.5-flash"):
    global current_gemini_idx
    if not gemini_keys:
        raise Exception("No active Gemini API keys are configured in key.txt.")
        
    num_keys = len(gemini_keys)
    for attempt in range(num_keys):
        idx = (current_gemini_idx + attempt) % num_keys
        key = gemini_keys[idx]
        try:
            reply = ask_gemini(key, messages, model=model)
            current_gemini_idx = idx
            return reply
        except Exception as e:
            print(f"⚠️ Gemini API key slot {idx+1} failed with error: {e}. Trying next key...")
            
    raise Exception("All Gemini API keys are currently exhausted or failing.")


current_gemini_idx = 0


def needs_web_search(groq_keys, gemini_keys, query):
    # Quick keyword check first to save API tokens and time
    keywords = ["latest", "news", "today", "current", "weather", "score", "price", "release", "recent", "who is the", "what is the current"]
    query_lower = query.lower()
    if any(k in query_lower for k in keywords):
        return True
        
    # Quick LLM classification
    messages = [
        {"role": "system", "content": "You are a query classifier. Respond with exactly 'YES' if the user's query requires current, real-time, or very recent information from a web search (e.g., current events, live data, latest news, current president/CEO, release dates, recent products, etc.). Otherwise, respond with exactly 'NO'. Do not explain."},
        {"role": "user", "content": query}
    ]
    try:
        reply = ask_groq_with_failover(groq_keys, messages).strip().upper()
        return "YES" in reply
    except Exception:
        return False


# =================================
# 📡 TELEGRAM MESSAGING HELPERS
# =================================

MAX_TG_LEN = 4000  # Telegram hard limit is 4096; leave buffer


def send_typing(token, chat_id):
    """Show 'typing...' indicator to the user."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendChatAction",
            data={"chat_id": chat_id, "action": "typing"},
            timeout=5
        )
    except Exception:
        pass


def markdown_to_html(text):
    if not text:
        return ""
    
    # First, escape all existing HTML characters so they don't interfere
    escaped = html.escape(str(text))
    
    # Temporarily extract code blocks so formatting inside them is not modified
    code_blocks = []
    def placeholder_code_block(match):
        code_blocks.append(match.group(0))
        return f"BLOCKCODEPLACEHOLDER{len(code_blocks)-1}"
        
    # Match ```optional_lang\n ... ``` or just ```...```
    escaped = re.sub(r"```(?:[a-zA-Z0-9+#-]+)?\s*?\n?(.*?)```", placeholder_code_block, escaped, flags=re.DOTALL)
    
    # Do the same for inline code: `code`
    inline_codes = []
    def placeholder_inline_code(match):
        inline_codes.append(match.group(1))
        return f"INLINECODEPLACEHOLDER{len(inline_codes)-1}"
        
    escaped = re.sub(r"`([^`\n]+)`", placeholder_inline_code, escaped)
    
    # Now process bold and italic in the remaining text
    # **bold** -> <b>
    escaped = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped)
    # *bold* -> <b>
    escaped = re.sub(r"\*(.*?)\*", r"<b>\1</b>", escaped)
    # _italic_ -> <i>
    escaped = re.sub(r"_(.*?)_", r"<i>\1</i>", escaped)
    
    # Now restore inline code blocks in reverse order to prevent prefix replacement collisions
    for idx in range(len(inline_codes) - 1, -1, -1):
        code = inline_codes[idx]
        escaped = escaped.replace(f"INLINECODEPLACEHOLDER{idx}", f"<code>{code}</code>")
        
    # Restore block code blocks in reverse order to prevent prefix replacement collisions
    for idx in range(len(code_blocks) - 1, -1, -1):
        block = code_blocks[idx]
        match = re.match(r"```(?:[a-zA-Z0-9+#-]+)?\s*?\n?(.*?)```", block, flags=re.DOTALL)
        if match:
            code_content = match.group(1)
            escaped = escaped.replace(f"BLOCKCODEPLACEHOLDER{idx}", f"<pre><code>{code_content}</code></pre>")
        else:
            escaped = escaped.replace(f"BLOCKCODEPLACEHOLDER{idx}", block)
            
    return escaped


def send_message(token, chat_id, text, reply_markup=None):
    """Send a message, auto-chunking if it exceeds Telegram's 4096-char limit."""
    if not text or not str(text).strip():
        return
    text = str(text)
    chunks = [text[i:i + MAX_TG_LEN] for i in range(0, len(text), MAX_TG_LEN)]
    for chunk_idx, chunk in enumerate(chunks):
        html_chunk = markdown_to_html(chunk)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": html_chunk,
            "parse_mode": "HTML"
        }
        if reply_markup and chunk_idx == len(chunks) - 1:
            data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code != 200:
                print(f"Failed to send message chunk {chunk_idx + 1}: {r.text}")
        except Exception as e:
            print(f"Error sending message: {e}")
        if len(chunks) > 1:
            time.sleep(0.3)


def set_bot_commands(token, admin_id, user_data=None):
    default_cmds = [
        {"command": "start", "description": "Wake up Medusa 🐍"},
        {"command": "help", "description": "Show list of commands ℹ️"},
        {"command": "image", "description": "Generate AI image 🖼️"},
        {"command": "upgrade", "description": "Upgrade your plan with Stars 🚀"},
        {"command": "check", "description": "Check current mode and limits 📊"},
        {"command": "clear", "description": "Clear your conversation history 🧹"},
        {"command": "search", "description": "Toggle web search 🔍"},
        {"command": "medusa", "description": "Switch to Premium Mode 🌟"},
        {"command": "default", "description": "Switch to Default Mode 🔓"},
        {"command": "enc", "description": "Obfuscate Python file 🔒"}
    ]
    
    bot_admin_cmds = default_cmds + [
        {"command": "admin", "description": "Access Admin Dashboard 👑"},
        {"command": "subadmin", "description": "Promote/demote subadmins 🛠️"},
        {"command": "export", "description": "Export target user profile 📤"}
    ]
    
    try:
        # Register default
        requests.post(f"https://api.telegram.org/bot{token}/setMyCommands", json={
            "commands": default_cmds,
            "scope": {"type": "default"}
        }, timeout=10)
        
        # Register bot owner
        if admin_id:
            requests.post(f"https://api.telegram.org/bot{token}/setMyCommands", json={
                "commands": bot_admin_cmds,
                "scope": {"type": "chat", "chat_id": int(admin_id)}
            }, timeout=10)
            
        # Register subadmins
        if user_data:
            for uid, info in user_data.items():
                if info.get("role") == "subadmin":
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/setMyCommands", json={
                            "commands": bot_admin_cmds,
                            "scope": {"type": "chat", "chat_id": int(uid)}
                        }, timeout=10)
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error setting bot commands: {e}")


# =================================
# 👑 ADMIN PANEL HELPERS
# =================================

def get_admin_panel_data(admin_id):
    user_data = load_user_data()
    total_users = len(user_data)

    active_today = 0
    now = time.time()
    user_lines = []

    for uid, info in user_data.items():
        active_mode = info.get("active_mode", "groq").upper()
        is_unlimited = info.get("unlimited", False)

        if uid == str(admin_id):
            credits = "Unlimited (Admin)"
        elif is_unlimited:
            credits = "Unlimited (Granted)"
        else:
            if now - info.get("last_reset", 0) >= 86400:
                credits = "0/4"
            else:
                c_used = info.get("credits_used", 0)
                credits = f"{c_used}/4"
                if c_used > 0:
                    active_today += 1

        name = info.get("first_name", "User")
        username = info.get("username", "None")
        display_mode = "DEFAULT" if active_mode == "GROQ" else "PREMIUM"
        unlimited_tag = " ♾️" if is_unlimited else ""
        user_lines.append(
            f"👤 *{name}* (@{username}){unlimited_tag}\n"
            f"   ID: `{uid}` | Mode: `{display_mode}` | Credits: `{credits}`"
        )

    user_list_str = "\n\n".join(user_lines) if user_lines else "No users registered yet."

    text = (
        f"👑 *MEDUSA ADMIN PANEL* 👑\n"
        f"-------------------------------\n"
        f"📊 *Stats*:\n"
        f"• Total Users: {total_users}\n"
        f"• Active Today: {active_today}\n\n"
        f"👥 *User List*:\n"
        f"{user_list_str}"
    )

    inline_keyboard = []
    for uid, info in user_data.items():
        if uid == str(admin_id):
            continue
        name = info.get("first_name", "User")
        is_unlimited = info.get("unlimited", False)
        row = [
            {"text": f"Reset {name}", "callback_data": f"reset_{uid}"}
        ]
        if is_unlimited:
            row.append({"text": f"Revoke Unlimited", "callback_data": f"revoke_{uid}"})
        else:
            row.append({"text": f"Grant Unlimited ♾️", "callback_data": f"unlimited_{uid}"})
        inline_keyboard.append(row)

    if len(user_data) > 1:
        inline_keyboard.append([
            {"text": "Reset All Users", "callback_data": "reset_all"}
        ])

    inline_keyboard.append([
        {"text": "🔄 Refresh Panel", "callback_data": "refresh_admin"}
    ])

    return text, {"inline_keyboard": inline_keyboard}


def update_admin_panel(token, chat_id, message_id, admin_id):
    text, reply_markup = get_admin_panel_data(admin_id)
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": markdown_to_html(text),
        "parse_mode": "HTML",
        "reply_markup": json.dumps(reply_markup)
    }
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Error editing admin panel message: {e}")


def notify_admin_reset_request(token, admin_id, requester_id, requester_name, requester_username):
    """Send admin a notification that a user is requesting a credit reset."""
    msg = (
        f"📩 *Credit Reset Request*\n\n"
        f"User *{requester_name}* (@{requester_username}) has requested a credit reset.\n"
        f"ID: `{requester_id}`"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"Reset {requester_name}", "callback_data": f"reset_{requester_id}"}
        ]]
    }
    send_message(token, admin_id, msg, reply_markup=reply_markup)


def notify_admin_upgrade_request(token, admin_id, requester_id, requester_name, requester_username, plan_name):
    """Send admin a plan upgrade request with approve/deny buttons."""
    price = "$3" if plan_name == "premium" else "$10"
    msg = (
        f"🚀 *Upgrade Request - {plan_name.capitalize()} Plan ({price})*\n\n"
        f"User *{requester_name}* (@{requester_username}) wants to upgrade to *{plan_name.capitalize()}* plan.\n"
        f"ID: `{requester_id}`\n\n"
        f"Verify the {price} payment then approve or deny below."
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": f"Approve {plan_name.capitalize()}", "callback_data": f"approve_upg_{plan_name}_{requester_id}"},
                {"text": "Deny", "callback_data": f"deny_upg_{plan_name}_{requester_id}"}
            ]
        ]
    }
    send_message(token, admin_id, msg, reply_markup=reply_markup)


# =================================
# 👥 ADMIN RESOLVERS & UTILS
# =================================

def resolve_target_user(message, args, user_data):
    if "reply_to_message" in message:
        tgt_user = message["reply_to_message"]["from"]
        return str(tgt_user["id"]), tgt_user.get("first_name", "User"), tgt_user.get("username", "")
    if args:
        target = args[0].strip()
        if target.startswith("@"):
            uname = target[1:].lower()
            for uid, info in user_data.items():
                if info.get("username", "").lower() == uname:
                    return uid, info.get("first_name", "User"), info.get("username", "")
        elif target.isdigit():
            uid = target
            info = user_data.get(uid, {})
            return uid, info.get("first_name", "User"), info.get("username", "")
    return None, None, None

def send_document(token, chat_id, file_name, file_content):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    files = {"document": (file_name, io.BytesIO(file_content.encode("utf-8")))}
    data = {"chat_id": chat_id}
    try:
        r = requests.post(url, data=data, files=files, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending document: {e}")
        return False


def edit_message_text(token, chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": markdown_to_html(text),
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error editing message: {e}")
        return False


def send_photo_bytes(token, chat_id, image_bytes, caption, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("image.jpg", io.BytesIO(image_bytes), "image/jpeg")}
    data = {
        "chat_id": chat_id,
        "caption": markdown_to_html(caption),
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, data=data, files=files, timeout=35)
        if r.status_code == 200:
            return r.json().get("result", {})
        else:
            print(f"Error sending photo: {r.text}")
            return None
    except Exception as e:
        print(f"Error sending photo: {e}")
        return None


def edit_message_media_bytes(token, chat_id, message_id, image_bytes, caption, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/editMessageMedia"
    media_obj = {
        "type": "photo",
        "media": "attach://photo",
        "caption": markdown_to_html(caption),
        "parse_mode": "HTML"
    }
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "media": json.dumps(media_obj)
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    files = {"photo": ("image.jpg", io.BytesIO(image_bytes), "image/jpeg")}
    try:
        r = requests.post(url, data=data, files=files, timeout=35)
        return r.status_code == 200
    except Exception as e:
        print(f"Error editing message media: {e}")
        return False


def generate_image_bytes(prompt, filter_key="original"):
    filter_info = FILTER_STYLES.get(filter_key, FILTER_STYLES["original"])
    full_prompt = prompt.strip() + filter_info["prompt_suffix"]
    encoded_prompt = urllib.parse.quote(full_prompt)
    seed = int(time.time() * 1000) % 1000000
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    r = requests.get(url, headers=headers, timeout=45)
    if r.status_code != 200:
        raise Exception(f"Failed to generate image (Status Code: {r.status_code})")
    return r.content


def build_image_filter_keyboard(session_id, active_filter="original"):
    buttons = [
        [
            {"text": f"{'✅ ' if active_filter == 'cyberpunk' else ''}🎨 Cyberpunk", "callback_data": f"imgflt:cyberpunk:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'anime' else ''}🌸 Anime", "callback_data": f"imgflt:anime:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'cinematic' else ''}🎬 Cinematic", "callback_data": f"imgflt:cinematic:{session_id}"}
        ],
        [
            {"text": f"{'✅ ' if active_filter == 'fantasy' else ''}🧙 Fantasy", "callback_data": f"imgflt:fantasy:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'watercolor' else ''}🖌️ Watercolor", "callback_data": f"imgflt:watercolor:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'realistic' else ''}📸 Realistic", "callback_data": f"imgflt:realistic:{session_id}"}
        ],
        [
            {"text": f"{'✅ ' if active_filter == 'render3d' else ''}✨ 3D Render", "callback_data": f"imgflt:render3d:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'vintage' else ''}🖤 Vintage", "callback_data": f"imgflt:vintage:{session_id}"},
            {"text": f"{'✅ ' if active_filter == 'original' else ''}🔄 Original", "callback_data": f"imgflt:original:{session_id}"}
        ]
    ]
    return {"inline_keyboard": buttons}



def summarize_document(token, chat_id, file_id, file_name, user_record, user_data, sender_str, session_key, cyberneurova_keys, gemini_keys, user_histories, active_mode):
    send_typing(token, chat_id)
    send_message(token, chat_id, f"⏳ Reading your document: *{file_name}*...")
    
    try:
        # 1. getFile
        file_info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=10
        ).json()
        file_path = file_info.get("result", {}).get("file_path")
        
        if file_path:
            # 2. download
            download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            file_bytes = requests.get(download_url, timeout=20).content
            
            # 3. parse based on extension
            ext = file_name.split(".")[-1].lower() if "." in file_name else ""
            doc_text = ""
            if ext in ["txt", "csv", "json"]:
                try:
                    doc_text = file_bytes.decode("utf-8")
                except Exception:
                    doc_text = file_bytes.decode("latin-1", errors="ignore")
            if ext == "pdf":
                doc_text = extract_text_from_pdf(file_bytes)
            elif ext == "docx":
                doc_text = extract_text_from_docx(file_bytes)
            else:
                try:
                    doc_text = file_bytes.decode("utf-8")
                except Exception:
                    doc_text = ""
            
            if doc_text.strip():
                doc_context = f"[Document Context: User uploaded a file named '{file_name}' with contents:\n{doc_text[:15000]}\n(end of file context)]"
                
                summary_prompt = [
                    {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))},
                    {"role": "user", "content": f"Please provide a comprehensive summary of this document. Also note the format, size ({len(doc_text)} characters), and mention you are ready to answer any questions about it:\n\n{doc_context}"}
                ]
                
                if active_mode == "medusa":
                    reply = ask_medusa_with_failover(cyberneurova_keys, summary_prompt)
                else:
                    reply = ask_gemini_with_failover(gemini_keys, summary_prompt)
                
                # Extract pref tokens if any
                pref_match = re.search(r"\[PREF:\s*(.*?)\]", reply)
                if pref_match:
                    pref_str = pref_match.group(1)
                    for item in pref_str.split(","):
                        if "=" in item:
                            k, v = item.split("=", 1)
                            user_record.setdefault("preferences", {})[k.strip().lower()] = v.strip()
                    reply = re.sub(r"\[PREF:\s*(.*?)\]", "", reply).strip()
                
                # Initialize history
                if session_key not in user_histories:
                    saved_hist = user_record.get("history", [])
                    user_histories[session_key] = saved_hist if saved_hist else [
                        {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                    ]
                
                user_histories[session_key].append({"role": "system", "content": doc_context})
                user_histories[session_key].append({"role": "assistant", "content": reply})
                
                user_record["history"] = user_histories[session_key]
                user_record["summaries_today"] = user_record.get("summaries_today", 0) + 1
                user_data[sender_str] = user_record
                save_single_user(sender_str, user_record)
                
                send_message(token, chat_id, reply)
            else:
                send_message(token, chat_id, "⚠️ Could not read any text from the document. Please ensure it is not empty or scanned/image-only.")
        else:
            send_message(token, chat_id, "⚠️ Failed to fetch file path from Telegram.")
    except Exception as e:
        print(f"Error handling document: {e}")
        send_message(token, chat_id, f"💥 *Error processing document*: {e}")


def run_obfuscation_flow(token, chat_id, message_id, user_record, user_data, sender_str, level, style, admin_id):
    pending = user_record.get("pending_file")
    if not pending:
        edit_message_text(token, chat_id, message_id, "❌ *Error: No pending file found.*")
        return
        
    file_id = pending["file_id"]
    file_name = pending["file_name"]
    
    try:
        # 1. getFile
        file_info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=10
        ).json()
        file_path = file_info.get("result", {}).get("file_path")
        
        if not file_path:
            edit_message_text(token, chat_id, message_id, "❌ *Failed to get file path from Telegram.*")
            return
            
        # 2. download
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        file_bytes = requests.get(download_url, timeout=20).content
        
        try:
            source_code = file_bytes.decode("utf-8")
        except Exception:
            source_code = file_bytes.decode("latin-1", errors="ignore")
            
        if not source_code.strip():
            edit_message_text(token, chat_id, message_id, "⚠️ *The uploaded Python file is empty.*")
            return
            
        # 3. run obscura obfuscation
        import obscura
        obfuscated_code, renamed, strings = obscura.obfuscate_source(
            source_code=source_code,
            level=level,
            renaming_style=style
        )
        
        # 4. send the obfuscated file as document
        base_name, _ = os.path.splitext(file_name)
        new_filename = f"{base_name}_obf.py"
        
        if send_document(token, chat_id, new_filename, obfuscated_code):
            # 5. increment counts
            user_record["obfuscations_today"] = user_record.get("obfuscations_today", 0) + 1
            user_record["pending_file"] = None
            user_data[sender_str] = user_record
            save_single_user(sender_str, user_record)
            
            remaining = max(0, 5 - user_record["obfuscations_today"])
            is_admin = (str(sender_str) == str(admin_id))
            is_unltd = user_record.get("unlimited", False) or is_admin
            rem_str = "Unlimited ♾️" if is_unltd else f"{remaining}/5"
            
            summary = (
                "✅ *Obfuscation Complete!*\n\n"
                f"• *File:* `{new_filename}`\n"
                f"• *Level:* `{level.upper()}`\n"
                f"• *Style:* `{style.capitalize()}`\n"
                f"• *Identifiers Renamed:* `{renamed}`\n"
                f"• *Strings Obfuscated:* `{strings}`\n\n"
                f"📈 *Remaining Obfuscations Today:* `{rem_str}`"
            )
            edit_message_text(token, chat_id, message_id, summary)
        else:
            edit_message_text(token, chat_id, message_id, "💥 *Failed to send the obfuscated file back to you.*")
            
    except Exception as e:
        print(f"Error in run_obfuscation_flow: {e}")
        edit_message_text(token, chat_id, message_id, f"💥 *Obfuscation Failed:* `{str(e)}`")






# =================================
# 📡 TELEGRAM DAEMON MODE
# =================================

def telegram_mode(cyberneurova_keys, groq_keys, gemini_keys, token, admin_id):
    print("🐍 Telegram mode started (Stable Long Polling with Dual Engines & Search)...")

    bot_username = ""
    try:
        me_resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        bot_username = me_resp.get("result", {}).get("username", "")
        print(f"Bot Username: @{bot_username}")
    except Exception as e:
        print(f"Error fetching bot username: {e}")

    user_histories = {}
    search_modes = {}
    last_update = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=30&offset={last_update+1}"
            r = requests.get(url, timeout=35)
            data = r.json()

            for update in data.get("result", []):
                last_update = update["update_id"]

                # -------- AUTOMATED PRE-CHECKOUT QUERY RESPONSE --------
                if "pre_checkout_query" in update:
                    pre_checkout = update["pre_checkout_query"]
                    pre_checkout_id = pre_checkout["id"]
                    requests.post(
                        f"https://api.telegram.org/bot{token}/answerPreCheckoutQuery",
                        json={"pre_checkout_query_id": pre_checkout_id, "ok": True}
                    )
                    continue

                # =================================
                # 🖱 CALLBACK QUERIES (Admin Panel)
                # =================================
                if "callback_query" in update:
                    callback_query = update["callback_query"]
                    chat_id = callback_query["message"]["chat"]["id"]
                    if chat_id < 0:
                        continue
                    callback_data = callback_query.get("data", "")
                    sender_id = callback_query["from"]["id"]
                    msg_id = callback_query["message"]["message_id"]

                    # -------- USER-INITIATED: Live Image Filter Callback --------
                    if callback_data.startswith("imgflt:"):
                        parts = callback_data.split(":", 2)
                        if len(parts) == 3:
                            filter_key = parts[1]
                            session_id = parts[2]
                            session = IMAGE_SESSIONS.get(session_id)
                            if not session:
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                    data={"callback_query_id": callback_query["id"], "text": "Image session expired."}
                                )
                                continue
                            
                            filter_info = FILTER_STYLES.get(filter_key, FILTER_STYLES["original"])
                            filter_name = filter_info["name"]
                            
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": f"Applying filter: {filter_name}..."}
                            )
                            
                            prompt = session["prompt"]
                            session["active_filter"] = filter_key
                            
                            try:
                                new_bytes = generate_image_bytes(prompt, filter_key)
                                caption = (
                                    f"🖼️ *{IMAGE_ENGINE_NAME} {IMAGE_ENGINE_VERSION}*\n"
                                    f"• *Prompt:* `{prompt}`\n"
                                    f"• *Filter:* `{filter_name}`"
                                )
                                new_keyboard = build_image_filter_keyboard(session_id, filter_key)
                                edit_message_media_bytes(token, chat_id, msg_id, new_bytes, caption, reply_markup=new_keyboard)
                            except Exception as e:
                                print(f"Error applying image filter: {e}")
                                send_message(token, chat_id, f"💥 *Failed to apply filter:* {e}")
                        continue

                    # -------- USER-INITIATED: Request credit reset (non-admin) --------
                    if callback_data.startswith("reqreset_") and str(sender_id) != str(admin_id):
                        req_user_data = load_user_data()
                        req_record = req_user_data.get(str(sender_id), {})
                        req_name = req_record.get("first_name", "User")
                        req_username = req_record.get("username", "")
                        notify_admin_reset_request(token, admin_id, str(sender_id), req_name, req_username)
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Request sent to admin!"}
                        )
                        send_message(token, chat_id, "📩 Your credit reset request has been sent to the Admin. Please wait for approval.")
                        continue

                    # -------- USER-INITIATED: Plan Upgrade Stars Invoice --------
                    if callback_data.startswith("pay_stars_"):
                        plan_name = callback_data.split("pay_stars_")[1]
                        stars_amount = 150 if plan_name == "premium" else 500
                        
                        url = f"https://api.telegram.org/bot{token}/sendInvoice"
                        data = {
                            "chat_id": chat_id,
                            "title": f"Medusa {plan_name.capitalize()} Upgrade",
                            "description": f"Upgrade to Medusa's AI {plan_name.capitalize()} Plan with higher daily limits.",
                            "payload": f"upg_{plan_name}_{sender_id}",
                            "provider_token": "", # Empty for Telegram Stars
                            "currency": "XTR", # Telegram Stars currency
                            "prices": json.dumps([{"label": f"{plan_name.capitalize()} Plan", "amount": stars_amount}])
                        }
                        
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "Generating invoice..."}
                            )
                            r = requests.post(url, data=data, timeout=10)
                            if r.status_code != 200:
                                print(f"Error sending Stars invoice: {r.text}")
                                send_message(token, chat_id, f"⚠️ Failed to generate invoice: {r.json().get('description')}")
                        except Exception as e:
                            print(f"Exception sending Stars invoice: {e}")
                        continue

                    # -------- USER-INITIATED: Python Obfuscation callback actions --------
                    if callback_data == "py_action_summarize":
                        user_data = load_user_data()
                        user_record = user_data.get(sender_str, {})
                        pending = user_record.get("pending_file")
                        if not pending:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "No pending file found!"}
                            )
                            edit_message_text(token, chat_id, msg_id, "❌ *No pending file found or session expired.*")
                            continue
                            
                        # Trigger document summary
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and user_record.get("summaries_today", 0) >= limits["summaries"]:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "Limit reached!"}
                            )
                            edit_message_text(
                                token, chat_id, msg_id,
                                f"⚠️ *Daily limit reached!* You have used all *{limits['summaries']}* document summaries for today on the *{plan.capitalize()}* plan.\n\n"
                                f"Upgrade your plan or request a reset from Admin."
                            )
                            continue
                        
                        # Answer callback
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Summarizing..."}
                        )
                        edit_message_text(token, chat_id, msg_id, f"📄 *Summarizing file:* `{pending['file_name']}`...")
                        
                        # Call summarize
                        session_key = str(chat_id)
                        summarize_document(
                            token=token,
                            chat_id=chat_id,
                            file_id=pending["file_id"],
                            file_name=pending["file_name"],
                            user_record=user_record,
                            user_data=user_data,
                            sender_str=sender_str,
                            session_key=session_key,
                            cyberneurova_keys=cyberneurova_keys,
                            gemini_keys=gemini_keys,
                            user_histories=user_histories,
                            active_mode=active_mode
                        )
                        # Clear pending file
                        user_record["pending_file"] = None
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        continue

                    if callback_data == "py_action_obfuscate":
                        user_data = load_user_data()
                        user_record = user_data.get(sender_str, {})
                        pending = user_record.get("pending_file")
                        if not pending:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "No pending file found!"}
                            )
                            edit_message_text(token, chat_id, msg_id, "❌ *No pending file found or session expired.*")
                            continue
                            
                        # Check daily limit of 5 obfuscations
                        obfuscations_used = user_record.get("obfuscations_today", 0)
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and obfuscations_used >= 5:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "Limit reached!"}
                            )
                            edit_message_text(
                                token, chat_id, msg_id,
                                "⚠️ *Daily limit reached!* You have used all *5* python obfuscations for today."
                            )
                            continue
                            
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Level selection..."}
                        )
                        
                        keyboard = {
                            "inline_keyboard": [
                                [
                                    {"text": "1. Basic", "callback_data": "py_level_basic"},
                                    {"text": "2. Medium", "callback_data": "py_level_medium"}
                                ],
                                [
                                    {"text": "3. Strong", "callback_data": "py_level_strong"},
                                    {"text": "4. Extreme", "callback_data": "py_level_extreme"}
                                ],
                                [
                                    {"text": "❌ Cancel", "callback_data": "py_cancel"}
                                ]
                            ]
                        }
                        
                        level_msg = (
                            f"🔒 *Select Obfuscation Level for:* `{pending['file_name']}`\n\n"
                            "• *Basic*: Strips comments/docstrings.\n"
                            "• *Medium*: Strips comments, renames local variables, escapes strings.\n"
                            "• *Strong*: Strips comments, renames globals/locals, XOR encrypts strings.\n"
                            "• *Extreme*: Strong + control flow flattening + math obfuscation + builtin hiding."
                        )
                        edit_message_text(token, chat_id, msg_id, level_msg, reply_markup=keyboard)
                        continue

                    if callback_data.startswith("py_level_"):
                        user_data = load_user_data()
                        user_record = user_data.get(sender_str, {})
                        pending = user_record.get("pending_file")
                        if not pending:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "No pending file found!"}
                            )
                            edit_message_text(token, chat_id, msg_id, "❌ *No pending file found or session expired.*")
                            continue
                            
                        level = callback_data.split("py_level_")[1]
                        pending["level"] = level
                        user_record["pending_file"] = pending
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        
                        # Basic level doesn't need style selection because it doesn't rename anything.
                        if level == "basic":
                            # Proceed directly to obfuscation
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "Obfuscating..."}
                            )
                            edit_message_text(token, chat_id, msg_id, f"🔒 *Obfuscating file:* `{pending['file_name']}` (Level: `BASIC`)...")
                            run_obfuscation_flow(token, chat_id, msg_id, user_record, user_data, sender_str, "basic", "hex", admin_id)
                            continue
                            
                        # Other levels require style selection
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Style selection..."}
                        )
                        
                        keyboard = {
                            "inline_keyboard": [
                                [
                                    {"text": "🎨 Hexadecimal (_0x1a)", "callback_data": "py_style_hex"},
                                    {"text": "🎭 Confusing (lO1lIO)", "callback_data": "py_style_confusing"}
                                ],
                                [
                                    {"text": "❌ Cancel", "callback_data": "py_cancel"}
                                ]
                            ]
                        }
                        
                        style_msg = (
                            f"🎨 *Select Identifier Renaming Style for:* `{pending['file_name']}`\n"
                            f"Selected Level: `{level.upper()}`\n\n"
                            "• *Hexadecimal*: Clean and standard hexadecimal variables (`_0x1a`)\n"
                            "• *Confusing*: Variables named using hard-to-distinguish chars (`lO1lIO`)"
                        )
                        edit_message_text(token, chat_id, msg_id, style_msg, reply_markup=keyboard)
                        continue

                    if callback_data.startswith("py_style_"):
                        user_data = load_user_data()
                        user_record = user_data.get(sender_str, {})
                        pending = user_record.get("pending_file")
                        if not pending:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "No pending file found!"}
                            )
                            edit_message_text(token, chat_id, msg_id, "❌ *No pending file found or session expired.*")
                            continue
                            
                        style = callback_data.split("py_style_")[1]
                        level = pending.get("level", "strong")
                        
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Obfuscating..."}
                        )
                        edit_message_text(
                            token, chat_id, msg_id,
                            f"🔒 *Obfuscating file:* `{pending['file_name']}` (Level: `{level.upper()}`, Style: `{style.upper()}`)..."
                        )
                        run_obfuscation_flow(token, chat_id, msg_id, user_record, user_data, sender_str, level, style, admin_id)
                        continue

                    if callback_data == "py_cancel":
                        user_data = load_user_data()
                        user_record = user_data.get(sender_str, {})
                        user_record["pending_file"] = None
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Action cancelled."}
                        )
                        edit_message_text(token, chat_id, msg_id, "❌ *Action cancelled by user.*")
                        continue

                    # Admin and Subadmin callbacks from here
                    sender_rec = user_data.get(str(sender_id), {})
                    is_sub = (sender_rec.get("role") == "subadmin")
                    if str(sender_id) != str(admin_id) and not is_sub:
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Access denied!"}
                        )
                        continue

                    if callback_data.startswith("reset_"):
                        target_id = callback_data.split("_")[1]
                        user_data = load_user_data()
                        if target_id in user_data:
                            user_data[target_id]["credits_used"] = 0
                            user_data[target_id]["last_reset"] = time.time()
                            save_user_data(user_data)
                            # Notify the user that their credits were reset
                            send_message(token, int(target_id), "✅ Your Premium Mode credits have been reset by the Admin! You can ask 4 more questions now.")
                            msg_text = f"Credits for {user_data[target_id].get('first_name')} reset!"
                        else:
                            msg_text = "User not found!"

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": msg_text}
                        )
                        update_admin_panel(token, chat_id, msg_id, admin_id)

                    elif callback_data.startswith("unlimited_"):
                        target_id = callback_data.split("_")[1]
                        user_data = load_user_data()
                        if target_id in user_data:
                            user_data[target_id]["unlimited"] = True
                            save_user_data(user_data)
                            tgt_name = user_data[target_id].get('first_name', 'User')
                            send_message(token, int(target_id), "♾️ You have been granted *Unlimited Premium Mode* access by the Admin! No daily limit applies to you.")
                            msg_text = f"Unlimited granted to {tgt_name}!"
                        else:
                            msg_text = "User not found!"

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": msg_text}
                        )
                        update_admin_panel(token, chat_id, msg_id, admin_id)

                    elif callback_data.startswith("revoke_"):
                        target_id = callback_data.split("_")[1]
                        user_data = load_user_data()
                        if target_id in user_data:
                            user_data[target_id]["unlimited"] = False
                            user_data[target_id]["credits_used"] = 0
                            user_data[target_id]["last_reset"] = time.time()
                            save_user_data(user_data)
                            tgt_name = user_data[target_id].get('first_name', 'User')
                            send_message(token, int(target_id), "Your Unlimited access has been revoked. Daily credit limit applies again.")
                            msg_text = f"Unlimited revoked for {tgt_name}!"
                        else:
                            msg_text = "User not found!"

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": msg_text}
                        )
                        update_admin_panel(token, chat_id, msg_id, admin_id)



                    elif callback_data == "reset_all":
                        user_data = load_user_data()
                        for uid in user_data:
                            if uid != str(admin_id):
                                user_data[uid]["credits_used"] = 0
                                user_data[uid]["last_reset"] = time.time()
                        save_user_data(user_data)

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "All user credits reset!"}
                        )
                        update_admin_panel(token, chat_id, msg_id, admin_id)

                    elif callback_data == "refresh_admin":
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Refreshed!"}
                        )
                        update_admin_panel(token, chat_id, msg_id, admin_id)





                    continue

                # =================================
                # 💬 PRIVATE CHAT MESSAGES
                # =================================
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    if chat_id < 0:
                        continue
                        
                    sender_id = message["from"]["id"]
                    first_name = message["from"].get("first_name", "User")
                    username = message["from"].get("username", "")
                    sender_str = str(sender_id)
                    session_key = str(chat_id)

                    # -------- SUCCESSFUL PAYMENT DETECTED --------
                    if "successful_payment" in message:
                        sp = message["successful_payment"]
                        payload = sp.get("invoice_payload", "")
                        if payload.startswith("upg_"):
                            parts = payload.split("_")
                            plan_type = parts[1]
                            target_id = parts[2]
                            
                            user_data = load_user_data()
                            if target_id not in user_data:
                                user_data[target_id] = {
                                    "credits_used": 0,
                                    "last_reset": time.time(),
                                    "username": username,
                                    "first_name": first_name,
                                    "active_mode": "groq",
                                    "preferences": {},
                                    "history": [],
                                    "plan": "free",
                                    "images_today": 0,
                                    "summaries_today": 0,
                                    "searches_today": 0,
                                    "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
                                    "role": "user"
                                }
                            
                            tgt_rec = user_data[target_id]
                            tgt_rec["plan"] = plan_type
                            tgt_rec["images_today"] = 0
                            tgt_rec["summaries_today"] = 0
                            tgt_rec["searches_today"] = 0
                            tgt_rec["credits_used"] = 0
                            tgt_rec["last_reset"] = time.time()
                            save_single_user(target_id, tgt_rec)
                            
                            send_message(
                                token, chat_id,
                                f"🎉 *Upgrade Successful!*\n\n"
                                f"Your payment of *{sp.get('total_amount')} Stars* has been processed via Fragment/Telegram.\n"
                                f"Your account has been upgraded to the *{plan_type.upper()}* plan!\n"
                                "Your new limits are now active. Type `/check` to verify your balance and status.\n\n"
                                "💬 Support/Inquiries: Contact the owner at https://t.me/w4simg"
                            )
                            
                            # Notify the admin
                            try:
                                send_message(
                                    token, admin_id,
                                    f"💰 *New Stars Payment Completed!*\n\n"
                                    f"• *User:* {first_name} (@{username})\n"
                                    f"• *ID:* `{target_id}`\n"
                                    f"• *Plan:* `{plan_type.upper()}`\n"
                                    f"• *Amount:* `{sp.get('total_amount')} Stars`"
                                )
                            except Exception:
                                pass
                        continue

                    # Register user in stats immediately
                    user_data = load_user_data()
                    current_date_str = datetime.now().strftime("%Y-%m-%d")
                    if sender_str not in user_data:
                        user_data[sender_str] = {
                            "credits_used": 0,
                            "last_reset": time.time(),
                            "username": username,
                            "first_name": first_name,
                            "active_mode": "groq",  # default to groq
                            "preferences": {},
                            "history": [],
                            "plan": "free",
                            "images_today": 0,
                            "image_gen_today": 0,
                            "summaries_today": 0,
                            "searches_today": 0,
                            "obfuscations_today": 0,
                            "last_reset_date": current_date_str,
                            "role": "user"
                        }
                        save_user_data(user_data)

                    user_record = user_data[sender_str]
                    active_mode = user_record.get("active_mode", "groq")
                    
                    # Ensure plan fields exist in existing users
                    modified = False
                    if "plan" not in user_record:
                        user_record["plan"] = "free"
                        modified = True
                    if "images_today" not in user_record:
                        user_record["images_today"] = 0
                        modified = True
                    if "image_gen_today" not in user_record:
                        user_record["image_gen_today"] = 0
                        modified = True
                    if "summaries_today" not in user_record:
                        user_record["summaries_today"] = 0
                        modified = True
                    if "searches_today" not in user_record:
                        user_record["searches_today"] = 0
                        modified = True
                    if "obfuscations_today" not in user_record:
                        user_record["obfuscations_today"] = 0
                        modified = True
                    if "last_reset_date" not in user_record:
                        user_record["last_reset_date"] = current_date_str
                        modified = True
                    if "role" not in user_record:
                        user_record["role"] = "user"
                        modified = True
                        
                    # Handle daily reset check
                    if user_record.get("last_reset_date", "") != current_date_str:
                        user_record["images_today"] = 0
                        user_record["image_gen_today"] = 0
                        user_record["summaries_today"] = 0
                        user_record["searches_today"] = 0
                        user_record["obfuscations_today"] = 0
                        user_record["credits_used"] = 0
                        user_record["last_reset_date"] = current_date_str
                        modified = True
                        
                    if modified:
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)

                    # -------- DOCUMENT MESSAGE --------
                    if "document" in message:
                        doc = message["document"]
                        file_id = doc["file_id"]
                        file_name = doc.get("file_name", "document")
                        
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
                        if ext == "py":
                            # Save the file info to pending
                            user_record["pending_file"] = {
                                "file_id": file_id,
                                "file_name": file_name,
                                "timestamp": time.time()
                            }
                            user_data[sender_str] = user_record
                            save_single_user(sender_str, user_record)
                            
                            keyboard = {
                                "inline_keyboard": [
                                    [
                                        {"text": "🔒 Obfuscate File", "callback_data": "py_action_obfuscate"},
                                        {"text": "📄 Summarize File", "callback_data": "py_action_summarize"}
                                    ]
                                ]
                            }
                            send_message(
                                token, chat_id,
                                f"🐍 *Python File Detected:* `{file_name}`\n\n"
                                f"What would you like to do with this file?",
                                reply_markup=keyboard
                            )
                            continue

                        # Check daily summaries limit for non-py documents
                        if not is_unltd and user_record.get("summaries_today", 0) >= limits["summaries"]:
                            send_message(
                                token, chat_id,
                                f"⚠️ *Daily limit reached!* You have used all *{limits['summaries']}* document summaries for today on the *{plan.capitalize()}* plan.\n\n"
                                f"Upgrade your plan or request a reset from Admin."
                            )
                            continue
                        
                        session_key = str(chat_id)
                        summarize_document(
                            token=token,
                            chat_id=chat_id,
                            file_id=file_id,
                            file_name=file_name,
                            user_record=user_record,
                            user_data=user_data,
                            sender_str=sender_str,
                            session_key=session_key,
                            cyberneurova_keys=cyberneurova_keys,
                            gemini_keys=gemini_keys,
                            user_histories=user_histories,
                            active_mode=active_mode
                        )
                        continue

                    # -------- PHOTO MESSAGE --------
                    if "photo" in message:
                        photo = message["photo"]
                        file_id = photo[-1]["file_id"]
                        caption = message.get("caption", "").strip()
                        prompt_text = caption if caption else "Describe what is in this image in detail."
                        
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and user_record.get("images_today", 0) >= limits["images"]:
                            send_message(
                                token, chat_id,
                                f"⚠️ *Daily limit reached!* You have used all *{limits['images']}* image analyses for today on the *{plan.capitalize()}* plan.\n\n"
                                f"Upgrade your plan or request a reset from Admin."
                            )
                            continue
                        
                        send_typing(token, chat_id)
                        send_message(token, chat_id, "⏳ Analyzing image...")
                        
                        try:
                            # 1. getFile
                            file_info = requests.get(
                                f"https://api.telegram.org/bot{token}/getFile",
                                params={"file_id": file_id},
                                timeout=10
                            ).json()
                            file_path = file_info.get("result", {}).get("file_path")
                            
                            if file_path:
                                # 2. download
                                download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                                img_data = requests.get(download_url, timeout=20).content
                                
                                # 3. base64 encode
                                import base64
                                img_b64 = base64.b64encode(img_data).decode("utf-8")
                                
                                # 4. build vision message
                                vision_msgs = [
                                    {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))},
                                    {
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": prompt_text},
                                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                                        ]
                                    }
                                ]
                                
                                reply = ask_gemini_with_failover(gemini_keys, vision_msgs, model="gemini-2.5-flash")
                                
                                # Extract preference tokens if any
                                pref_match = re.search(r"\[PREF:\s*(.*?)\]", reply)
                                if pref_match:
                                    pref_str = pref_match.group(1)
                                    for item in pref_str.split(","):
                                        if "=" in item:
                                            k, v = item.split("=", 1)
                                            user_record.setdefault("preferences", {})[k.strip().lower()] = v.strip()
                                    reply = re.sub(r"\[PREF:\s*(.*?)\]", "", reply).strip()
                                
                                # Initialize history
                                if session_key not in user_histories:
                                    saved_hist = user_record.get("history", [])
                                    user_histories[session_key] = saved_hist if saved_hist else [
                                        {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                                    ]
                                
                                user_histories[session_key].append({"role": "user", "content": f"[Image uploaded with caption: {prompt_text}]"})
                                user_histories[session_key].append({"role": "assistant", "content": reply})
                                
                                user_record["history"] = user_histories[session_key]
                                user_record["images_today"] = user_record.get("images_today", 0) + 1
                                user_data[sender_str] = user_record
                                save_user_data(user_data)
                                
                                send_message(token, chat_id, reply)
                            else:
                                send_message(token, chat_id, "⚠️ Failed to fetch file path from Telegram.")
                        except Exception as e:
                            print(f"Error handling photo: {e}")
                            send_message(token, chat_id, f"💥 *Error analyzing image*: {e}")
                        continue

                    # -------- EXTRACT TEXT & PARSE COMMAND --------
                    text = message.get("text", "").strip()
                    if not text:
                        continue

                    # Parse command if it starts with /
                    cmd = None
                    args = []
                    args_str = ""
                    if text.startswith("/"):
                        cmd_match = re.match(r"^/([a-zA-Z0-9_]+)(?:@\w+)?(?:\s+(.*))?$", text, re.IGNORECASE)
                        if cmd_match:
                            cmd = cmd_match.group(1).lower()
                            args_str = cmd_match.group(2) or ""
                            args = args_str.split()



                    # -------- SUBADMIN ROLE MANAGEMENT --------
                    if cmd == "subadmin":
                        is_owner = (sender_str == str(admin_id))
                        is_sub = (user_record.get("role") == "subadmin")
                        
                        if not is_owner and not is_sub:
                            send_message(token, chat_id, "🚫 *You are not authorized to use subadmin commands.*")
                            continue
                            
                        if not args:
                            send_message(
                                token, chat_id,
                                "🛠️ *Subadmin Management Panel*\n"
                                "------------------------------------\n"
                                "Commands:\n"
                                "• `/subadmin promote <reply | @username | user_id>` (Owner only)\n"
                                "• `/subadmin demote <reply | @username | user_id>` (Owner only)\n"
                                "• `/subadmin list` (Owner & Subadmins)"
                            )
                            continue
                            
                        sub_action = args[0].lower()
                        
                        if sub_action == "list":
                            subadmins = []
                            for uid, info in user_data.items():
                                if info.get("role") == "subadmin":
                                    subadmins.append(f"• *{info.get('first_name', 'User')}* (@{info.get('username', 'None')}) - ID: `{uid}`")
                            if subadmins:
                                send_message(token, chat_id, "👥 *Active Subadmins*:\n" + "\n".join(subadmins))
                            else:
                                send_message(token, chat_id, "ℹ️ No subadmins configured yet.")
                            continue
                            
                        if not is_owner:
                            send_message(token, chat_id, "🚫 *Only the main owner can promote or demote subadmins.*")
                            continue
                            
                        if len(args) < 2:
                            send_message(token, chat_id, f"⚠️ Usage: `/subadmin {sub_action} <reply | @username | user_id>`")
                            continue
                            
                        target_args = args[1:]
                        tgt_id, tgt_name, tgt_username = resolve_target_user(message, target_args, user_data)
                        
                        if not tgt_id:
                            send_message(token, chat_id, "⚠️ Target user not found in database.")
                            continue
                            
                        tgt_rec = user_data.get(tgt_id)
                        if sub_action == "promote":
                            if tgt_rec.get("role") == "subadmin":
                                send_message(token, chat_id, f"⚠️ *{tgt_name}* is already a subadmin.")
                                continue
                            tgt_rec["role"] = "subadmin"
                            save_single_user(tgt_id, tgt_rec)
                            
                            # Dynamically register admin commands for the new subadmin
                            set_bot_commands(token, admin_id, user_data)
                            
                            send_message(token, chat_id, f"🎉 *{tgt_name}* promoted to *Subadmin*! They can now access the admin panel.")
                        elif sub_action == "demote":
                            if tgt_rec.get("role") != "subadmin":
                                send_message(token, chat_id, f"⚠️ *{tgt_name}* is not a subadmin.")
                                continue
                            tgt_rec["role"] = "user"
                            save_single_user(tgt_id, tgt_rec)
                            
                            # Remove custom admin commands for the demoted user (reverts to default scope)
                            try:
                                requests.post(f"https://api.telegram.org/bot{token}/deleteMyCommands", json={
                                    "scope": {"type": "chat", "chat_id": int(tgt_id)}
                                }, timeout=10)
                            except Exception:
                                pass
                                
                            send_message(token, chat_id, f"📉 *{tgt_name}* demoted to regular User.")
                        else:
                            send_message(token, chat_id, "⚠️ Unknown subadmin action.")
                        continue

                    # -------- EXPORT DATA --------
                    if cmd == "export":
                        is_owner = (sender_str == str(admin_id))
                        is_sub = (user_record.get("role") == "subadmin")
                        if not is_owner and not is_sub:
                            send_message(token, chat_id, "🚫 *You are not authorized to export user data.*")
                            continue
                            
                        if not args:
                            send_message(token, chat_id, "⚠️ Usage: `/export <reply | @username | user_id>`")
                            continue
                            
                        tgt_id, tgt_name, tgt_username = resolve_target_user(message, args, user_data)
                        if not tgt_id:
                            send_message(token, chat_id, "⚠️ Target user not found.")
                            continue
                            
                        tgt_record = user_data.get(tgt_id)
                        formatted_json = json.dumps(tgt_record, indent=4, ensure_ascii=False)
                        file_name = f"user_history_{tgt_id}.json"
                        
                        if send_document(token, chat_id, file_name, formatted_json):
                            send_message(token, chat_id, f"✅ Data history for *{tgt_name}* ({tgt_id}) exported successfully!")
                        else:
                            send_message(token, chat_id, "💥 Failed to export and send data document.")
                        continue

                    # -------- IMAGE GENERATION COMMAND --------
                    if cmd == "image":
                        if not args_str.strip():
                            send_message(
                                token, chat_id,
                                "🎨 *Medusa Image Generator*\n\n"
                                "Usage: `/image <description of image>`\n"
                                "Example: `/image a majestic dragon flying over neon cyberpunk cityscape`"
                            )
                            continue
                            
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        img_gen_used = user_record.get("image_gen_today", 0)
                        max_allowed = limits.get("image_gen", 5)
                        
                        if not is_unltd and img_gen_used >= max_allowed:
                            send_message(
                                token, chat_id,
                                f"⚠️ *Daily limit reached!* You have used all *{max_allowed}* image generations for today on the *{plan.capitalize()}* plan.\n\n"
                                f"Upgrade your plan (`/upgrade`) or request a reset from Admin."
                            )
                            continue
                            
                        send_typing(token, chat_id)
                        send_message(token, chat_id, f"🎨 *Generating image:* `{args_str}`...")
                        
                        try:
                            img_bytes = generate_image_bytes(args_str, "original")
                            
                            # Increment count
                            user_record["image_gen_today"] = img_gen_used + 1
                            user_data[sender_str] = user_record
                            save_single_user(sender_str, user_record)
                            
                            session_id = f"{sender_id}_{int(time.time()) % 100000}"
                            IMAGE_SESSIONS[session_id] = {
                                "prompt": args_str,
                                "active_filter": "original",
                                "chat_id": chat_id,
                                "user_id": sender_id
                            }
                            
                            caption = (
                                f"🖼️ *{IMAGE_ENGINE_NAME} {IMAGE_ENGINE_VERSION}*\n"
                                f"• *Prompt:* `{args_str}`\n"
                                f"• *Filter:* `Original 🔄`"
                            )
                            reply_markup = build_image_filter_keyboard(session_id, "original")
                            send_photo_bytes(token, chat_id, img_bytes, caption, reply_markup=reply_markup)
                        except Exception as e:
                            print(f"Error generating image: {e}")
                            send_message(token, chat_id, f"💥 *Error generating image:* {e}")
                            
                        continue

                    # -------- HELP --------
                    if cmd == "help":
                        commands = (
                            "🐍 *Medusa Bot Commands*:\n"
                            "• `/start` - Wake up the bot\n"
                            "• `/help` - Show this help menu\n"
                            "• `/image <prompt>` - Generate AI image 🖼️\n"
                            "• `/upgrade` - Upgrade your plan using Telegram Stars 🚀\n"
                            "• `/default` - Switch to Default Mode 🔓\n"
                            "• `/medusa` - Switch to Premium Mode 🌟\n"
                            "• `/check` - Check mode and limits 📊\n"
                            "• `/clear` - Reset your conversation history 🧹\n"
                            "• `/search` - Toggle web search mode 🔍\n"
                            "• `/enc` - Reply to a `.py` file to obfuscate it 🔒\n"
                            "• `/mood <normal|angry>` - Adjust mood 🎭\n"
                            "• `/temp <0.1-1.0>` - Adjust creativity 🌡️"
                        )
                        is_sub = (user_record.get("role") == "subadmin")
                        if sender_str == str(admin_id) or is_sub:
                            commands += "\n\n👑 *Admin/Subadmin Commands*:\n"
                            commands += "• `/admin` - Access Admin Dashboard\n"
                            commands += "• `/subadmin` - Promote/demote/list subadmins\n"
                            commands += "• `/export <user>` - Export target user database profile"
                        send_message(token, chat_id, commands)
                        continue

                    # -------- START --------
                    if cmd == "start":
                        send_typing(token, chat_id)
                        time.sleep(0.5)
                        boot_resp = requests.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            data={"chat_id": chat_id, "text": "⏳ Starting..."},
                            timeout=10
                        )
                        boot_msg_id = None
                        try:
                            boot_msg_id = boot_resp.json()["result"]["message_id"]
                        except Exception:
                            pass

                        time.sleep(1.2)
                        send_typing(token, chat_id)
                        time.sleep(1.0)

                        wake_text = (
                            "\U0001f40d *Medusa Awakened...*\n\n"
                            "I have woken, mortal. The serpent stirs."
                        )
                        if boot_msg_id:
                            try:
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/editMessageText",
                                    data={
                                        "chat_id": chat_id,
                                        "message_id": boot_msg_id,
                                        "text": markdown_to_html(wake_text),
                                        "parse_mode": "HTML"
                                    },
                                    timeout=10
                                )
                            except Exception:
                                pass
                        else:
                            send_message(token, chat_id, wake_text)

                        time.sleep(1.0)
                        send_typing(token, chat_id)

                        display_username = f"@{username}" if username else "No username set"
                        mode_display = "Default (Free, Unlimited)" if active_mode == "groq" else "Premium"
                        is_unltd = user_record.get("unlimited", False) or (sender_str == str(admin_id))
                        credit_info = "Unlimited ♾️" if is_unltd else f"{PLAN_LIMITS.get(user_record.get('plan', 'free'), PLAN_LIMITS['free'])['medusa_credits']} questions/day"

                        info_card = (
                            "\U0001f40d *Medusa \u2014 User Profile*\n\n"
                            f"\U0001f464 *Name:* {first_name}\n"
                            f"\U0001f4e7 *Username:* {display_username}\n"
                            f"\U0001f194 *Chat ID:* `{chat_id}`\n"
                            f"\U0001f4ca *Active Mode:* {mode_display}\n"
                            f"\U0001f4b3 *Credits:* {credit_info}\n\n"
                            "Use `/help` to see all active commands, mortal."
                        )

                        send_message(token, chat_id, info_card)
                        continue

                    # -------- OBFUSCATE COMMAND (/enc) --------
                    if cmd == "enc":
                        # Check if it's a reply to a message with a document
                        replied_msg = message.get("reply_to_message")
                        if not replied_msg or "document" not in replied_msg:
                            send_message(
                                token, chat_id,
                                "⚠️ *Usage:* Reply to a Python (`.py`) document with `/enc` to start obfuscating it."
                            )
                            continue
                            
                        doc = replied_msg["document"]
                        file_id = doc["file_id"]
                        file_name = doc.get("file_name", "document")
                        
                        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
                        if ext != "py":
                            send_message(
                                token, chat_id,
                                "⚠️ *Invalid File:* The replied file must be a Python (`.py`) script."
                            )
                            continue
                            
                        # Check daily limit of 5 obfuscations
                        obfuscations_used = user_record.get("obfuscations_today", 0)
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and obfuscations_used >= 5:
                            send_message(
                                token, chat_id,
                                "⚠️ *Daily limit reached!* You have used all *5* python obfuscations for today."
                            )
                            continue
                            
                        # Save the file info to pending
                        user_record["pending_file"] = {
                            "file_id": file_id,
                            "file_name": file_name,
                            "timestamp": time.time()
                        }
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        
                        keyboard = {
                            "inline_keyboard": [
                                [
                                    {"text": "1. Basic", "callback_data": "py_level_basic"},
                                    {"text": "2. Medium", "callback_data": "py_level_medium"}
                                ],
                                [
                                    {"text": "3. Strong", "callback_data": "py_level_strong"},
                                    {"text": "4. Extreme", "callback_data": "py_level_extreme"}
                                ],
                                [
                                    {"text": "❌ Cancel", "callback_data": "py_cancel"}
                                ]
                            ]
                        }
                        
                        level_msg = (
                            f"🔒 *Select Obfuscation Level for:* `{file_name}`\n\n"
                            "• *Basic*: Strips comments/docstrings.\n"
                            "• *Medium*: Strips comments, renames local variables, escapes strings.\n"
                            "• *Strong*: Strips comments, renames globals/locals, XOR encrypts strings.\n"
                            "• *Extreme*: Strong + control flow flattening + math obfuscation + builtin hiding."
                        )
                        send_message(token, chat_id, level_msg, reply_markup=keyboard)
                        continue

                    # -------- MODE COMMANDS --------
                    if cmd == "medusa":
                        user_record["active_mode"] = "medusa"
                        if "last_reset" not in user_record:
                            user_record["last_reset"] = time.time()
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        
                        if session_key in user_histories:
                            user_histories[session_key].clear()
                            
                        send_message(
                            token,
                            chat_id,
                            "🌟 *Mode switched to Premium Mode!*\n\n"
                            "You are now talking in Premium Mode. "
                            "You have a limit of *4 questions per day* in this mode.\n\n"
                            "Use `/check` to view your credits, and `/default` to switch back to free unlimited mode."
                        )
                        continue

                    if cmd == "default":
                        user_record["active_mode"] = "groq"
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        
                        if session_key in user_histories:
                            user_histories[session_key].clear()
                            
                        send_message(
                            token,
                            chat_id,
                            "🔓 *Mode switched to Default Mode!*\n\n"
                            "You are now talking in Default Mode. "
                            "You have *unlimited questions* in this mode!\n\n"
                            "Use `/medusa` to switch to Premium Mode anytime."
                        )
                        continue

                    # -------- CHECK LIMITS --------
                    if cmd == "check":
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        
                        img_used = user_record.get("images_today", 0)
                        img_gen_used = user_record.get("image_gen_today", 0)
                        sum_used = user_record.get("summaries_today", 0)
                        search_used = user_record.get("searches_today", 0)
                        
                        is_unltd = user_record.get("unlimited", False) or (sender_str == str(admin_id))
                        
                        max_gen = limits.get("image_gen", 5)
                        if is_unltd:
                            img_status = "Unlimited ♾️"
                            img_gen_status = "Unlimited ♾️"
                            sum_status = "Unlimited ♾️"
                            search_status = "Unlimited ♾️"
                        else:
                            img_status = f"{img_used}/{limits['images']}"
                            img_gen_status = f"{img_gen_used}/{max_gen}" if max_gen < 900000 else "Unlimited ♾️"
                            sum_status = f"{sum_used}/{limits['summaries']}"
                            search_status = f"{search_used}/{limits['searches']}"
                            
                        now = time.time()
                        credits_used = user_record.get("credits_used", 0)
                        last_reset = user_record.get("last_reset", now)
                        time_elapsed = now - last_reset
                        time_to_reset = 86400 - time_elapsed
                        
                        limit_val = limits["medusa_credits"]
                        if time_to_reset <= 0:
                            remaining_credits = limit_val
                            reset_str = "Reset available now!"
                        else:
                            remaining_credits = max(0, limit_val - credits_used)
                            hours = int(time_to_reset // 3600)
                            minutes = int((time_to_reset % 3600) // 60)
                            reset_str = f"{hours}h {minutes}m"
                            
                        if is_unltd:
                            credit_info = "Unlimited ♾️"
                        else:
                            credit_info = f"{remaining_credits}/{limit_val}"

                        active_mode_display = "Premium Mode 🌟" if active_mode == "medusa" else "Default Mode 🔓"
                        
                        status_msg = (
                            "📊 *Medusa Bot Status*:\n\n"
                            f"• *User Plan*: `{plan.upper()}` 💳\n"
                            f"• *Current Mode*: `{active_mode_display}`\n"
                            f"• *Medusa Mode Credits*: `{credit_info}`\n"
                            f"• *Reset Timer*: `{reset_str}` ⏳\n\n"
                            "*Daily Limit Usage*:\n"
                            f"• 🎨 *Image Generations*: `{img_gen_status}`\n"
                            f"• 🖼️ *Image Analyses*: `{img_status}`\n"
                            f"• 📄 *Doc Summaries*: `{sum_status}`\n"
                            f"• 🔍 *Web Searches*: `{search_status}`\n\n"
                            "Use `/medusa` to switch to Premium, `/default` to switch to Default."
                        )
                        send_message(token, chat_id, status_msg)
                        continue

                    # -------- UPGRADE PLAN --------
                    if cmd == "upgrade":
                        already_unlimited = user_record.get("unlimited", False) or (sender_str == str(admin_id))
                        if already_unlimited:
                            send_message(
                                token, chat_id,
                                "♾️ You already have *Unlimited Premium* access! No upgrade needed."
                            )
                        else:
                            plan_msg = (
                                "🚀 *Medusa Upgrade Plans*\n"
                                "================================\n\n"
                                "🔓 *Free Plan* - $0\n"
                                "   • Unlimited Chat (Default Mode)\n"
                                "   • Image Generation: 5 per day 🎨\n"
                                "   • Image Analysis: 3 per day 🖼️\n"
                                "   • Document Summary: 2 per day 📄\n"
                                "   • Web Search: 4 per day 🔍\n"
                                "   • Medusa Mode: 4 credits per day 🌟\n\n"
                                "⭐ *Premium Plan* - 150 Stars ($3 equivalent)\n"
                                "   • Unlimited Chat (Default Mode)\n"
                                "   • Image Generation: 20 per day 🎨\n"
                                "   • Image Analysis: 10 per day 🖼️\n"
                                "   • Document Summary: 5 per day 📄\n"
                                "   • Web Search: 10 per day 🔍\n"
                                "   • Medusa Mode: 8 credits per day 🌟\n\n"
                                "🔥 *Max Plan* - 500 Stars ($10 equivalent)\n"
                                "   • Unlimited Chat (Default Mode)\n"
                                "   • Image Generation: Unlimited 🎨\n"
                                "   • Image Analysis: 10 per day 🖼️\n"
                                "   • Document Summary: 5 per day 📄\n"
                                "   • Web Search: 10 per day 🔍\n"
                                "   • Medusa Mode: 15 credits per day 🌟\n\n"
                                "Select the plan below to pay directly using Telegram Stars (Fragment / In-app).\n\n"
                                "💬 Support/Inquiries: Contact the owner at https://t.me/w4simg"
                            )
                            upgrade_btn = {
                                "inline_keyboard": [
                                    [
                                        {"text": "⭐ Buy Premium (150 Stars)", "callback_data": "pay_stars_premium"},
                                        {"text": "🔥 Buy Max (500 Stars)", "callback_data": "pay_stars_max"}
                                    ],
                                    [
                                        {"text": "🔗 Buy Stars on Fragment", "url": "https://fragment.com/stars"}
                                    ]
                                ]
                            }
                            send_message(token, chat_id, plan_msg, reply_markup=upgrade_btn)
                        continue

                    # -------- CLEAR HISTORY --------
                    if cmd == "clear":
                        if session_key in user_histories:
                            user_histories[session_key].clear()
                        user_record["history"] = []
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)
                        send_message(token, chat_id, "🧹 Conversation history cleared.")
                        continue

                    # -------- HISTORY --------
                    if cmd == "history":
                        hist = user_record.get("history", [])
                        chat_lines = []
                        for msg in hist:
                            if msg["role"] in ["user", "assistant"]:
                                role_display = "👤 *You*" if msg["role"] == "user" else "🐍 *Medusa*"
                                content_snippet = msg["content"]
                                content_snippet = re.sub(r"\[PREF:\s*(.*?)\]", "", content_snippet).strip()
                                chat_lines.append(f"{role_display}: {content_snippet}")
                        
                        if chat_lines:
                            recent_hist = "\n\n".join(chat_lines[-10:])
                            send_message(token, chat_id, f"📜 *Recent Conversation History*:\n\n{recent_hist}")
                        else:
                            send_message(token, chat_id, "📜 Your history is currently empty.")
                        continue

                    # -------- ADMIN PANEL --------
                    if cmd == "admin":
                        is_sub = (user_record.get("role") == "subadmin")
                        if sender_str == str(admin_id) or is_sub:
                            admin_text, reply_markup = get_admin_panel_data(admin_id)
                            send_message(token, chat_id, admin_text, reply_markup)
                        else:
                            send_message(token, chat_id, "🚫 *You are not authorized to access this panel.*")
                        continue

                    # -------- TEMP --------
                    if text.startswith("/temp"):
                        try:
                            value = float(text.split()[1])
                            if 0.1 <= value <= 1.0:
                                global TEMPERATURE
                                TEMPERATURE = value
                                reply = f"🌡️ Temperature set to {TEMPERATURE}"
                            else:
                                reply = "⚠️ Range must be 0.1 - 1.0"
                        except:
                            reply = "⚠️ Usage: `/temp 0.5`"

                        send_message(token, chat_id, reply)
                        continue

                    # -------- MOOD --------
                    if text.startswith("/mood"):
                        try:
                            mood_value = text.split()[1].lower()
                            if mood_value in ["normal", "angry"]:
                                global MOOD
                                MOOD = mood_value
                                reply = f"🎭 Mood set to {MOOD}"
                                if chat_id in user_histories:
                                    user_histories[chat_id].clear()
                            else:
                                reply = "⚠️ Available moods: `normal`, `angry`"
                        except:
                            reply = "⚠️ Usage: `/mood normal`"

                        send_message(token, chat_id, reply)
                        continue

                    # -------- WEB SEARCH COMMAND --------
                    if text.startswith("/search"):
                        parts = text.split(maxsplit=1)
                        if len(parts) == 1:
                            current = search_modes.get(chat_id, False)
                            search_modes[chat_id] = not current
                            status = "ENABLED 🟢" if not current else "DISABLED 🔴"
                            send_message(token, chat_id, f"🔍 *Browser search mode is now* {status}")
                            continue
                        else:
                            search_query = parts[1]
                            plan = user_record.get("plan", "free")
                            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                            is_admin = (str(sender_id) == str(admin_id))
                            is_unltd = user_record.get("unlimited", False) or is_admin
                            
                            if not is_unltd and user_record.get("searches_today", 0) >= limits["searches"]:
                                send_message(
                                    token, chat_id,
                                    f"⚠️ *Daily limit reached!* You have used all *{limits['searches']}* web searches for today on the *{plan.capitalize()}* plan.\n\n"
                                    f"Upgrade your plan or request a reset from Admin."
                                )
                                continue

                            send_message(token, chat_id, f"🔍 *Searching the web for*: `{search_query}`...")
                            
                            combined = multi_platform_search(search_query)
                            if not combined:
                                send_message(token, chat_id, "⚠️ *No search results found.*")
                                continue
                            
                            context_lines = []
                            for platform, results in combined.items():
                                context_lines.append(f"--- Results from {platform.upper()}: ---")
                                for idx, r in enumerate(results, 1):
                                    context_lines.append(f"{idx}. Title: {r['title']}\nURL: {r['link']}\nSnippet: {r['snippet']}\n")
                            context_text = "\n".join(context_lines)
                            
                            temp_messages = [
                                {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))},
                                {"role": "system", "content": f"Here is the real-time multi-platform search context for the user's question:\n{context_text}"},
                                {"role": "user", "content": search_query}
                            ]
                            
                            try:
                                if active_mode == "medusa":
                                    reply = ask_medusa_with_failover(cyberneurova_keys, temp_messages)
                                else:
                                    if gemini_keys:
                                        reply = ask_gemini_with_failover(gemini_keys, temp_messages)
                                    else:
                                        # Force raising error for missing Gemini key since search is Gemini-only
                                        raise Exception("No active Gemini API keys are configured in key.txt.")
                                
                                # Extract preference tokens if any
                                pref_match = re.search(r"\[PREF:\s*(.*?)\]", reply)
                                if pref_match:
                                    pref_str = pref_match.group(1)
                                    for item in pref_str.split(","):
                                        if "=" in item:
                                            k, v = item.split("=", 1)
                                            user_record.setdefault("preferences", {})[k.strip().lower()] = v.strip()
                                    reply = re.sub(r"\[PREF:\s*(.*?)\]", "", reply).strip()
                                
                                # Add to history
                                if session_key not in user_histories:
                                    saved_hist = user_record.get("history", [])
                                    user_histories[session_key] = saved_hist if saved_hist else [
                                        {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                                    ]
                                user_histories[session_key].append({"role": "user", "content": f"Search Query: {search_query}"})
                                user_histories[session_key].append({"role": "assistant", "content": reply})
                                
                                user_record["history"] = user_histories[session_key]
                                user_record["searches_today"] = user_record.get("searches_today", 0) + 1
                                user_data[sender_str] = user_record
                                save_user_data(user_data)
                                    
                                send_message(token, chat_id, reply)
                            except Exception as e:
                                send_message(token, chat_id, f"💥 *Error processing search query*: {e}")
                            
                            continue

                    # -------- CREDIT & USAGE CHECK --------
                    user_data = load_user_data()
                    now = time.time()
                    user_record = user_data.get(sender_str, {})
                    active_mode = user_record.get("active_mode", "groq")
                    
                    is_admin = (sender_str == str(admin_id))
                    is_unlimited = user_record.get("unlimited", False)

                    # Credits check applies ONLY in medusa mode for non-admins without unlimited flag
                    if active_mode == "medusa" and not is_admin and not is_unlimited:
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        limit_val = limits["medusa_credits"]
                        
                        last_reset = user_record.get("last_reset", now)
                        if now - last_reset >= 86400:
                            user_record["credits_used"] = 0
                            user_record["last_reset"] = now
                            user_data[sender_str] = user_record
                            save_user_data(user_data)

                        credits_used = user_record.get("credits_used", 0)
                        if credits_used >= limit_val:
                            refusal = (
                                f"😏 You have exhausted your daily {limit_val} questions in Premium Mode for the {plan.capitalize()} plan, mortal. "
                                "Come back after 24 hours, switch to Default Mode with /default, or request the Admin to reset your limit."
                            )
                            request_btn = {
                                "inline_keyboard": [[
                                    {"text": "📩 Request Credit Reset from Admin", "callback_data": f"reqreset_{sender_str}"}
                                ]]
                            }
                            send_message(token, chat_id, refusal, reply_markup=request_btn)
                            continue

                        user_record["credits_used"] = credits_used + 1
                        user_data[sender_str] = user_record
                        save_user_data(user_data)

                    # -------- BROWSER SEARCH (IF TOGGLED ON) --------
                    custom_context = ""
                    should_search = search_modes.get(chat_id, False)
                    if should_search:
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (sender_str == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and user_record.get("searches_today", 0) >= limits["searches"]:
                            send_message(
                                token, chat_id,
                                f"⚠️ *Daily limit reached!* Skipping search as you have used all *{limits['searches']}* web searches for today on the *{plan.capitalize()}* plan."
                            )
                            should_search = False
                        else:
                            send_message(token, chat_id, f"🔍 *Searching for:* `{text}`...")
                            
                    if should_search:
                        print(f"Auto-searching web for user query: {text}")
                        combined = multi_platform_search(text)
                        if combined:
                            context_lines = []
                            for platform, results in combined.items():
                                context_lines.append(f"--- Results from {platform.upper()}: ---")
                                for idx, r in enumerate(results, 1):
                                    context_lines.append(f"{idx}. {r['title']} - {r['snippet']}")
                            custom_context = f"\n\n[Multi-Platform Search Context]:\n" + "\n".join(context_lines)
                            
                            # Increment searches usage count
                            user_record["searches_today"] = user_record.get("searches_today", 0) + 1
                            user_data[sender_str] = user_record
                            save_user_data(user_data)

                    if not user_histories.get(session_key):
                        saved_hist = user_record.get("history", [])
                        user_histories[session_key] = saved_hist if saved_hist else [
                            {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                        ]
                    else:
                        user_histories[session_key][0] = {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}

                    user_msg = text
                    if custom_context:
                        user_msg += custom_context
                        
                    user_histories[session_key].append({"role": "user", "content": user_msg})

                    if len(user_histories[session_key]) > 16:
                        user_histories[session_key] = [user_histories[session_key][0]] + user_histories[session_key][-15:]

                    try:
                        if active_mode == "medusa":
                            reply = ask_medusa_with_failover(cyberneurova_keys, user_histories[session_key])
                        else:
                            reply = ask_groq_with_failover(groq_keys, user_histories[session_key])
                        
                        # Process preferences from response
                        pref_match = re.search(r"\[PREF:\s*(.*?)\]", reply)
                        if pref_match:
                            pref_str = pref_match.group(1)
                            for item in pref_str.split(","):
                                if "=" in item:
                                    k, v = item.split("=", 1)
                                    user_record.setdefault("preferences", {})[k.strip().lower()] = v.strip()
                            reply = re.sub(r"\[PREF:\s*(.*?)\]", "", reply).strip()

                        user_histories[session_key].append({"role": "assistant", "content": reply})
                        
                        # Save history and preferences in database
                        user_record["history"] = user_histories[session_key]
                        user_data[sender_str] = user_record
                        save_user_data(user_data)
                        
                        send_message(token, chat_id, reply)
                            
                    except Exception as e:
                        print(f"Error querying LLM API: {e}")
                        send_message(token, chat_id, "💥 *Something went wrong while waking my thoughts. Please try again later.*")

        except Exception as e:
            print(f"⚠ Telegram connection error: {e}. Reconnecting in 5s...")
            time.sleep(5)


# =================================
# 🚀 START MENU
# =================================

def start():
    keys = load_keys()

    # Initialize MongoDB connection (if MONGO_URI is set)
    init_mongodb()

    cyberneurova_keys, groq_keys, gemini_keys = get_api_keys()

    if not cyberneurova_keys:
        print(Fore.RED + "ERROR: No CYBERNEUROVA API key found. Set CYBERNEUROVA_1 in your environment variables or .env file.")
        sys.exit(1)
    if not groq_keys:
        print(Fore.RED + "ERROR: No GROQ API key found. Set GROQ_1 in your environment variables or .env file.")
        sys.exit(1)
    if not gemini_keys:
        print(Fore.RED + "ERROR: No GEMINI API key found. Set GEMINI_1 in your environment variables or .env file.")
        sys.exit(1)

    token = keys.get("BOT_TOKEN", "").strip()
    if not token:
        print(Fore.RED + "ERROR: BOT_TOKEN is not set. Add it to your environment variables or .env file.")
        sys.exit(1)

    chat_id = keys.get("CHAT_ID", "").strip()
    if not chat_id:
        print(Fore.RED + "ERROR: CHAT_ID is not set. Add it to your environment variables or .env file.")
        sys.exit(1)

    clear()
    banner()

    # Register commands with Telegram
    db_data = load_user_data()
    set_bot_commands(token, chat_id, db_data)

    # Start a dummy health check HTTP server for Render Web Service compatibility
    web_thread = threading.Thread(target=run_health_check_server, daemon=True)
    web_thread.start()

    telegram_mode(cyberneurova_keys, groq_keys, gemini_keys, token, chat_id)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        # Suppress logging health check requests to keep logs clean
        return

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"📡 Health check server listening on port {port}...")
    server.serve_forever()


if __name__ == "__main__":
    start()
