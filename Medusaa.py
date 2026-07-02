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

TEMPERATURE = 0.6
MOOD = "normal"
RUNNING = True

PLAN_LIMITS = {
    "free": {
        "medusa_credits": 4,
        "images": 3,
        "summaries": 2,
        "searches": 4
    },
    "premium": {
        "medusa_credits": 8,
        "images": 10,
        "summaries": 5,
        "searches": 10
    },
    "max": {
        "medusa_credits": 15,
        "images": 10,
        "summaries": 5,
        "searches": 10
    }
}


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
        r = requests.get("https://api.cyberneurova.ai/v1/models", timeout=5)
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
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
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
        {"command": "ludo", "description": "Create Ludo board race lobby 🎲"},
        {"command": "balance", "description": "Check point balance 💰"},
        {"command": "daily", "description": "Claim daily rewards 🎁"},
        {"command": "gift", "description": "Gift points to a friend 🎁"},
        {"command": "leaderboard", "description": "View richest users 🏆"},
        {"command": "guide", "description": "View full games guidebook 📖"},
        {"command": "check", "description": "Check current mode and limits 📊"},
        {"command": "clear", "description": "Clear your conversation history 🧹"},
        {"command": "search", "description": "Toggle web search 🔍"},
        {"command": "medusa", "description": "Switch to Premium Mode 🌟"},
        {"command": "default", "description": "Switch to Default Mode 🔓"}
    ]
    
    group_admin_cmds = [
        {"command": "help", "description": "Show list of commands ℹ️"},
        {"command": "ludo", "description": "Create Ludo board race lobby 🎲"},
        {"command": "kick", "description": "Kick a member 🥾"},
        {"command": "ban", "description": "Ban a member 🔨"},
        {"command": "unban", "description": "Unban a member 🔓"},
        {"command": "mute", "description": "Mute a member 🔇"},
        {"command": "unmute", "description": "Unmute a member 🔊"}
    ]
    
    bot_admin_cmds = default_cmds + [
        {"command": "admin", "description": "Access Admin Dashboard 👑"},
        {"command": "subadmin", "description": "Promote/demote subadmins 🛠️"},
        {"command": "export", "description": "Export target user profile 📤"},
        {"command": "kick", "description": "Kick a member 🥾"},
        {"command": "ban", "description": "Ban a member 🔨"},
        {"command": "unban", "description": "Unban a member 🔓"},
        {"command": "mute", "description": "Mute a member 🔇"},
        {"command": "unmute", "description": "Unmute a member 🔊"}
    ]
    
    try:
        # Register default
        requests.post(f"https://api.telegram.org/bot{token}/setMyCommands", json={
            "commands": default_cmds,
            "scope": {"type": "default"}
        }, timeout=10)
        
        # Register group admins
        requests.post(f"https://api.telegram.org/bot{token}/setMyCommands", json={
            "commands": group_admin_cmds,
            "scope": {"type": "all_chat_administrators"}
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
# 🎮 GAME & MODERATION GLOBAL STATES & HELPERS
# =================================

active_ludo_games = {}
user_message_times = {}

def is_user_group_admin(token, chat_id, user_id, admin_id, user_data):
    if str(user_id) == str(admin_id):
        return True
    user_rec = user_data.get(str(user_id), {})
    if user_rec.get("role") == "subadmin":
        return True
    if chat_id > 0:
        return True
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getChatMember", params={"chat_id": chat_id, "user_id": user_id}, timeout=5)
        if r.status_code == 200:
            status = r.json().get("result", {}).get("status", "")
            return status in ["creator", "administrator"]
    except Exception as e:
        print(f"Error checking group admin status: {e}")
    return False

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

def ban_user(token, chat_id, user_id):
    url = f"https://api.telegram.org/bot{token}/banChatMember"
    data = {"chat_id": chat_id, "user_id": user_id}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error banning user: {e}")
        return False

def unban_user(token, chat_id, user_id):
    url = f"https://api.telegram.org/bot{token}/unbanChatMember"
    data = {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error unbanning user: {e}")
        return False

def kick_user(token, chat_id, user_id):
    if ban_user(token, chat_id, user_id):
        time.sleep(0.5)
        return unban_user(token, chat_id, user_id)
    return False

def mute_user(token, chat_id, user_id, duration_seconds):
    url = f"https://api.telegram.org/bot{token}/restrictChatMember"
    until_date = int(time.time() + duration_seconds)
    permissions = {"can_send_messages": False}
    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": json.dumps(permissions),
        "until_date": until_date
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error muting user: {e}")
        return False

def unmute_user(token, chat_id, user_id):
    url = f"https://api.telegram.org/bot{token}/restrictChatMember"
    permissions = {
        "can_send_messages": True,
        "can_send_media_messages": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True
    }
    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": json.dumps(permissions)
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error unmuting user: {e}")
        return False

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



def render_ludo_board(game):
    lines = []
    lines.append("🎲 *LUDO BOARD RACE* 🎲")
    lines.append("--------------------------------")
    
    for p_id in game["players"]:
        p_name = game["player_names"][p_id]
        p_pos = game["positions"][p_id]
        p_color = game["colors"][p_id]
        lines.append(f"{p_color} *{p_name}*: Step `{p_pos}/30`" + (" (HOME! 🏆)" if p_pos == 30 else ""))
    
    lines.append("")
    
    def get_step_emoji(step):
        players_here = []
        for p_id in game["players"]:
            if game["positions"][p_id] == step:
                players_here.append(game["colors"][p_id])
        
        if players_here:
            return "".join(players_here)
            
        if step == 0:
            return "🏠"
        elif step == 30:
            return "🏆"
        elif step in [8, 15, 22]:
            return "🛡️"
        elif step == 12:
            return "🚀"
        elif step == 25:
            return "🕸️"
        else:
            return "▫️"
            
    row1 = " ".join(get_step_emoji(i) for i in range(0, 11))
    row2 = " ".join(get_step_emoji(i) for i in range(11, 21))
    row3 = " ".join(get_step_emoji(i) for i in range(21, 31))
    
    lines.append(f"🏁 `{row1}`")
    lines.append(f"   `{row2}`")
    lines.append(f"👉 `{row3}`")
    lines.append("")
    
    lines.append("`🏠:Start | 🛡️:Safe | 🚀:Boost | 🕸️:Trap | 🏆:Home`")
    lines.append("--------------------------------")
    
    if game.get("last_roll"):
        lines.append(f"🎲 *{game['last_roller']}* rolled a `{game['last_roll']}`!")
    
    active_player_id = game["players"][game["turn_idx"]]
    active_player_name = game["player_names"][active_player_id]
    active_player_color = game["colors"][active_player_id]
    lines.append(f"➡️ Turn: {active_player_color} *{active_player_name}*")
    
    return "\n".join(lines)


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

                # =================================
                # 🖱 CALLBACK QUERIES (Admin Panel)
                # =================================
                if "callback_query" in update:
                    callback_query = update["callback_query"]
                    callback_data = callback_query.get("data", "")
                    sender_id = callback_query["from"]["id"]
                    chat_id = callback_query["message"]["chat"]["id"]
                    msg_id = callback_query["message"]["message_id"]

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

                    # -------- USER-INITIATED: Plan Upgrade requests --------
                    if callback_data.startswith("req_upg_") and str(sender_id) != str(admin_id):
                        requested_plan = callback_data.split("req_upg_")[1]
                        upg_data = load_user_data()
                        upg_rec = upg_data.get(str(sender_id), {})
                        upg_name = upg_rec.get("first_name", "User")
                        upg_username = upg_rec.get("username", "")
                        
                        notify_admin_upgrade_request(token, admin_id, str(sender_id), upg_name, upg_username, requested_plan)
                        
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": "Upgrade request sent!"}
                        )
                        price = "$3" if requested_plan == "premium" else "$10"
                        send_message(
                            token, chat_id,
                            f"Your upgrade request for the *{requested_plan.capitalize()} Plan ({price})* has been sent to the Admin.\n\n"
                            f"Please complete the {price} payment using the method your admin provides. "
                            "Your account will be upgraded as soon as it is verified."
                        )
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

                    elif callback_data.startswith("approve_upg_"):
                        parts = callback_data.split("_")
                        target_plan = parts[2]
                        target_id = parts[3]
                        
                        user_data = load_user_data()
                        if target_id in user_data:
                            user_data[target_id]["plan"] = target_plan
                            user_data[target_id]["images_today"] = 0
                            user_data[target_id]["summaries_today"] = 0
                            user_data[target_id]["searches_today"] = 0
                            user_data[target_id]["credits_used"] = 0
                            user_data[target_id]["last_reset"] = time.time()
                            save_user_data(user_data)
                            
                            tgt_name = user_data[target_id].get("first_name", "User")
                            price = "$3" if target_plan == "premium" else "$10"
                            send_message(
                                token, int(target_id),
                                f"🎉 *Upgrade Approved!*\n\n"
                                f"Your {price} upgrade has been verified. You now have *{target_plan.capitalize()} Plan* access. "
                                f"Check your new limits using `/check`!"
                            )
                            msg_text = f"Upgrade to {target_plan} approved for {tgt_name}!"
                        else:
                            msg_text = "User not found!"

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": msg_text}
                        )

                    elif callback_data.startswith("deny_upg_"):
                        parts = callback_data.split("_")
                        target_plan = parts[2]
                        target_id = parts[3]
                        
                        user_data = load_user_data()
                        tgt_name = user_data.get(target_id, {}).get("first_name", "User")
                        
                        send_message(
                            token, int(target_id),
                            f"Your upgrade request for the *{target_plan.capitalize()} Plan* was not approved at this time. "
                            "Please contact the admin if you believe this is a mistake."
                        )
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": f"Upgrade denied for {tgt_name}."}
                        )

                    elif callback_data.startswith("approve_upgrade_"):
                        target_id = callback_data.split("approve_upgrade_")[1]
                        user_data = load_user_data()
                        if target_id in user_data:
                            user_data[target_id]["unlimited"] = True
                            save_user_data(user_data)
                            tgt_name = user_data[target_id].get("first_name", "User")
                            send_message(
                                token, int(target_id),
                                "Upgrade Approved!\n\n"
                                "Your $2 upgrade has been verified. You now have Unlimited Premium access. "
                                "No daily limits apply to you anymore. Enjoy! \U0001f680\u267e\ufe0f"
                            )
                            msg_text = f"Upgrade approved for {tgt_name}!"
                        else:
                            msg_text = "User not found!"

                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": msg_text}
                        )

                    elif callback_data.startswith("deny_upgrade_"):
                        target_id = callback_data.split("deny_upgrade_")[1]
                        user_data = load_user_data()
                        tgt_name = user_data.get(target_id, {}).get("first_name", "User")
                        send_message(
                            token, int(target_id),
                            "Your upgrade request was not approved at this time. "
                            "Please contact the admin if you believe this is a mistake."
                        )
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            data={"callback_query_id": callback_query["id"], "text": f"Upgrade denied for {tgt_name}."}
                        )

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



                    # -------- LUDO GAMEPLAY CALLBACKS --------
                    elif callback_data.startswith("ludo_join_") or callback_data.startswith("ludo_start_") or callback_data.startswith("ludo_cancel_") or callback_data.startswith("ludo_roll_"):
                        target_chat_id = int(callback_data.split("_")[-1])
                        
                        if target_chat_id not in active_ludo_games:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                data={"callback_query_id": callback_query["id"], "text": "Game lobby not found or has expired! 🚫"}
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/editMessageReplyMarkup", json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": None})
                            continue
                            
                        game = active_ludo_games[target_chat_id]
                        sender_str = str(sender_id)
                        sender_name = user_data.get(sender_str, {}).get("first_name", "User")
                        
                        if "ludo_join_" in callback_data:
                            if game["status"] != "lobby":
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Game is already in progress!"})
                                continue
                            
                            db_data = load_user_data()
                            if sender_str not in db_data:
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                                    data={
                                        "callback_query_id": callback_query["id"],
                                        "text": "⚠️ You must first start/message the bot in private chat to register before you can join!",
                                        "show_alert": True
                                    }
                                )
                                continue

                            if sender_str in game["players"]:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "You already joined!"})
                                continue
                            if len(game["players"]) >= 4:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Lobby is full!"})
                                continue
                                
                            game["players"].append(sender_str)
                            game["player_names"][sender_str] = sender_name
                            game["positions"][sender_str] = 0
                            
                            player_list = "\n".join(f"{idx+1}. *{game['player_names'][p]}*" for idx, p in enumerate(game["players"]))
                            lobby_text = (
                                "🎲 *LUDO BOARD RACE - LOBBY* 🎲\n"
                                "-------------------------------------\n"
                                f"Host: *{game['player_names'][game['host_id']]}*\n\n"
                                "👥 *Joined Players*:\n"
                                f"{player_list}\n\n"
                                "Click below to join!"
                            )
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "➕ Join Lobby", "callback_data": f"ludo_join_{target_chat_id}"},
                                        {"text": "🚀 Start Game", "callback_data": f"ludo_start_{target_chat_id}"}
                                    ],
                                    [
                                        {"text": "❌ Cancel Game", "callback_data": f"ludo_cancel_{target_chat_id}"}
                                    ]
                                ]
                            }
                            requests.post(
                                f"https://api.telegram.org/bot{token}/editMessageText",
                                data={"chat_id": chat_id, "message_id": msg_id, "text": markdown_to_html(lobby_text), "parse_mode": "HTML", "reply_markup": json.dumps(reply_markup)}
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Joined successfully!"})
                            
                        elif "ludo_start_" in callback_data:
                            if game["status"] != "lobby":
                                continue
                            if sender_str != game["host_id"]:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Only the host can start the game! 🚫", "show_alert": True})
                                continue
                            if len(game["players"]) < 2:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Need at least 2 players to start! 👥", "show_alert": True})
                                continue
                                
                            colors = ["🔴", "🔵", "🟢", "🟡"]
                            for idx, p in enumerate(game["players"]):
                                game["colors"][p] = colors[idx]
                                game["positions"][p] = 0
                            
                            game["status"] = "playing"
                            game["turn_idx"] = 0
                            
                            board_text = render_ludo_board(game)
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "🎲 Roll Dice", "callback_data": f"ludo_roll_{target_chat_id}"}
                                    ]
                                ]
                            }
                            requests.post(
                                f"https://api.telegram.org/bot{token}/editMessageText",
                                data={"chat_id": chat_id, "message_id": msg_id, "text": markdown_to_html(board_text), "parse_mode": "HTML", "reply_markup": json.dumps(reply_markup)}
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Game started!"})
                            
                        elif "ludo_cancel_" in callback_data:
                            is_admin = is_user_group_admin(token, chat_id, sender_id, admin_id, user_data)
                            if sender_str != game["host_id"] and not is_admin:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "Only host or admins can cancel! 🚫", "show_alert": True})
                                continue
                                
                            active_ludo_games.pop(target_chat_id)
                            requests.post(
                                f"https://api.telegram.org/bot{token}/editMessageText",
                                data={"chat_id": chat_id, "message_id": msg_id, "text": "❌ Ludo game lobby cancelled.", "reply_markup": None}
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"]})
                            
                        elif "ludo_roll_" in callback_data:
                            active_player_id = game["players"][game["turn_idx"]]
                            if sender_str != active_player_id:
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "It is not your turn, mortal! 🚫", "show_alert": True})
                                continue
                                
                            import random
                            roll = random.randint(1, 6)
                            cur_pos = game["positions"][sender_str]
                            new_pos = cur_pos + roll
                            
                            log_msg = ""
                            if new_pos > 30:
                                new_pos = cur_pos
                            else:
                                game["positions"][sender_str] = new_pos
                                
                                if new_pos not in [0, 8, 15, 22, 30]:
                                    kicked_players = []
                                    for other_id in game["players"]:
                                        if other_id != sender_str and game["positions"][other_id] == new_pos:
                                            game["positions"][other_id] = 0
                                            kicked_players.append(game["player_names"][other_id])
                                    if kicked_players:
                                        pass
                                
                                if new_pos == 12:
                                    game["positions"][sender_str] = 18
                                elif new_pos == 25:
                                    game["positions"][sender_str] = 10
                                    
                            game["last_roll"] = roll
                            game["last_roller"] = sender_name
                            
                            if new_pos == 30:
                                active_ludo_games.pop(target_chat_id)
                                winner_rec = user_data.get(sender_str, {})
                                winner_rec["points"] = winner_rec.get("points", 500) + 1000
                                save_single_user(sender_str, winner_rec)
                                
                                win_text = (
                                    "🏆 *LUDO BOARD RACE - GAME OVER* 🏆\n"
                                    "-------------------------------------\n"
                                    f"🎉 *{sender_name}* ({game['colors'][sender_str]}) has reached Home (step 30) and won the game!\n"
                                    f"Grand prize: `1,000 points`!\n"
                                    f"New Balance: `{winner_rec['points']} points`"
                                )
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/editMessageText",
                                    data={"chat_id": chat_id, "message_id": msg_id, "text": markdown_to_html(win_text), "parse_mode": "HTML", "reply_markup": None}
                                )
                                requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": "You won the game! 🎉"})
                                continue
                                
                            game["turn_idx"] = (game["turn_idx"] + 1) % len(game["players"])
                            board_text = render_ludo_board(game)
                            
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "🎲 Roll Dice", "callback_data": f"ludo_roll_{target_chat_id}"}
                                    ]
                                ]
                            }
                            requests.post(
                                f"https://api.telegram.org/bot{token}/editMessageText",
                                data={"chat_id": chat_id, "message_id": msg_id, "text": markdown_to_html(board_text), "parse_mode": "HTML", "reply_markup": json.dumps(reply_markup)}
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data={"callback_query_id": callback_query["id"], "text": f"Rolled a {roll}!"})
                        
                        continue

                    continue

                # =================================
                # 💬 TEXT MESSAGES
                # =================================
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    sender_id = message["from"]["id"]
                    first_name = message["from"].get("first_name", "User")
                    username = message["from"].get("username", "")
                    sender_str = str(sender_id)

                    # -------- WELCOME & LEFT GREETINGS --------
                    if "new_chat_members" in message:
                        for member in message["new_chat_members"]:
                            if bot_username and member.get("username", "").lower() == bot_username.lower():
                                send_message(token, chat_id, "🐍 *Medusa has entered the chat.* Type `/help` for commands!")
                                continue
                            m_name = member.get("first_name", "User")
                            m_username = f" (@{member['username']})" if member.get("username") else ""
                            welcome_msg = (
                                f"👋 *Welcome to the group, {m_name}{m_username}!* 🐍✨\n"
                                f"I am Medusa. Type `/help` to see my commands, play games, and earn points!"
                            )
                            send_message(token, chat_id, welcome_msg)
                        continue

                    if "left_chat_member" in message:
                        member = message["left_chat_member"]
                        m_name = member.get("first_name", "User")
                        left_msg = f"👋 *Goodbye, {m_name}.* The serpent's watch over you ends. 🐍"
                        send_message(token, chat_id, left_msg)
                        continue

                    session_key = str(chat_id) if chat_id > 0 else f"{chat_id}_{sender_id}"

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
                            "summaries_today": 0,
                            "searches_today": 0,
                            "last_reset_date": current_date_str,
                            "points": 500,
                            "role": "user",
                            "inventory": {"coal": 0, "iron": 0, "gold": 0, "diamond": 0, "medusite": 0},
                            "pickaxe": "wooden",
                            "last_mine_time": 0.0,
                            "last_daily_claim": 0.0
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
                    if "summaries_today" not in user_record:
                        user_record["summaries_today"] = 0
                        modified = True
                    if "searches_today" not in user_record:
                        user_record["searches_today"] = 0
                        modified = True
                    if "last_reset_date" not in user_record:
                        user_record["last_reset_date"] = current_date_str
                        modified = True
                    if "points" not in user_record:
                        user_record["points"] = 500
                        modified = True
                    if "role" not in user_record:
                        user_record["role"] = "user"
                        modified = True
                    if "inventory" not in user_record:
                        user_record["inventory"] = {"coal": 0, "iron": 0, "gold": 0, "diamond": 0, "medusite": 0}
                        modified = True
                    if "pickaxe" not in user_record:
                        user_record["pickaxe"] = "wooden"
                        modified = True
                    if "last_mine_time" not in user_record:
                        user_record["last_mine_time"] = 0.0
                        modified = True
                    if "last_daily_claim" not in user_record:
                        user_record["last_daily_claim"] = 0.0
                        modified = True
                        
                    # Handle daily reset check
                    if user_record.get("last_reset_date", "") != current_date_str:
                        user_record["images_today"] = 0
                        user_record["summaries_today"] = 0
                        user_record["searches_today"] = 0
                        user_record["credits_used"] = 0
                        user_record["last_reset_date"] = current_date_str
                        modified = True
                        
                    if modified:
                        user_data[sender_str] = user_record
                        save_single_user(sender_str, user_record)

                    # -------- DOCUMENT MESSAGE --------
                    if "document" in message:
                        # If in group, check if bot is mentioned in caption or replied to
                        if chat_id < 0:
                            is_mentioned = False
                            caption = message.get("caption", "").strip()
                            if bot_username and f"@{bot_username.lower()}" in caption.lower():
                                is_mentioned = True
                            elif "reply_to_message" in message:
                                reply_to = message["reply_to_message"]
                                if reply_to.get("from", {}).get("username", "").lower() == bot_username.lower():
                                    is_mentioned = True
                            if not is_mentioned:
                                continue

                        doc = message["document"]
                        file_id = doc["file_id"]
                        file_name = doc.get("file_name", "document")
                        
                        plan = user_record.get("plan", "free")
                        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                        is_admin = (str(sender_id) == str(admin_id))
                        is_unltd = user_record.get("unlimited", False) or is_admin
                        
                        if not is_unltd and user_record.get("summaries_today", 0) >= limits["summaries"]:
                            send_message(
                                token, chat_id,
                                f"⚠️ *Daily limit reached!* You have used all *{limits['summaries']}* document summaries for today on the *{plan.capitalize()}* plan.\n\n"
                                f"Upgrade your plan or request a reset from Admin."
                            )
                            continue
                        
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
                                eloquence_text = ""
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
                                    save_user_data(user_data)
                                    
                                    send_message(token, chat_id, reply)
                                else:
                                    send_message(token, chat_id, "⚠️ Could not read any text from the document. Please ensure it is not empty or scanned/image-only.")
                            else:
                                send_message(token, chat_id, "⚠️ Failed to fetch file path from Telegram.")
                        except Exception as e:
                            print(f"Error handling document: {e}")
                            send_message(token, chat_id, f"💥 *Error processing document*: {e}")
                        continue

                    # -------- PHOTO MESSAGE --------
                    if "photo" in message:
                        # If in group, check if bot is mentioned in caption or replied to
                        if chat_id < 0:
                            is_mentioned = False
                            caption = message.get("caption", "").strip()
                            if bot_username and f"@{bot_username.lower()}" in caption.lower():
                                is_mentioned = True
                            elif "reply_to_message" in message:
                                reply_to = message["reply_to_message"]
                                if reply_to.get("from", {}).get("username", "").lower() == bot_username.lower():
                                    is_mentioned = True
                            if not is_mentioned:
                                continue

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

                    # Enforce mention requirement for group queries (non-commands)
                    if cmd is None and chat_id < 0:
                        is_mentioned = False
                        if bot_username and f"@{bot_username.lower()}" in text.lower():
                            is_mentioned = True
                            text = re.sub(rf"@{re.escape(bot_username)}", "", text, flags=re.IGNORECASE).strip()
                        elif "reply_to_message" in message:
                            reply_to = message["reply_to_message"]
                            if reply_to.get("from", {}).get("username", "").lower() == bot_username.lower():
                                is_mentioned = True
                        if not is_mentioned:
                            continue

                    # -------- SPAM DETECTION (Groups Only) --------
                    if chat_id < 0:
                        now_ts = time.time()
                        if chat_id not in user_message_times:
                            user_message_times[chat_id] = {}
                        if sender_id not in user_message_times[chat_id]:
                            user_message_times[chat_id][sender_id] = []
                        
                        user_message_times[chat_id][sender_id].append(now_ts)
                        user_message_times[chat_id][sender_id] = [t for t in user_message_times[chat_id][sender_id] if now_ts - t <= 5]
                        
                        if len(user_message_times[chat_id][sender_id]) > 5:
                            warnings = user_record.get("spam_warnings", 0) + 1
                            user_record["spam_warnings"] = warnings
                            save_single_user(sender_str, user_record)
                            
                            mention = f"@{username}" if username else first_name
                            if warnings >= 3:
                                user_record["spam_warnings"] = 0
                                save_single_user(sender_str, user_record)
                                if mute_user(token, chat_id, sender_id, 600):
                                    send_message(token, chat_id, f"🔇 *Spam Limit Exceeded!* {mention} has been muted for 10 minutes. Please follow group rules.")
                                else:
                                    send_message(token, chat_id, f"⚠️ *Spam Limit Exceeded!* Please slow down, {mention} (Failed to mute, make sure I am admin).")
                            else:
                                send_message(token, chat_id, f"⚠️ *Spam Warning!* {mention}, slow down. Warning `{warnings}/3`.")
                            continue

                    # -------- KICK / BAN / UNBAN / MUTE / UNMUTE (Group Moderation) --------
                    if cmd in ["kick", "ban", "unban", "mute", "unmute"]:
                        if chat_id >= 0:
                            send_message(token, chat_id, "⚠️ Moderation commands can only be used in group chats!")
                            continue
                            
                        is_authorized = is_user_group_admin(token, chat_id, sender_id, admin_id, user_data)
                        if not is_authorized:
                            send_message(token, chat_id, "🚫 *You are not authorized to use moderation commands.*")
                            continue
                            
                        tgt_id, tgt_name, tgt_username = resolve_target_user(message, args, user_data)
                        if not tgt_id:
                            send_message(token, chat_id, f"⚠️ Specify a user to {cmd} (reply to their message or provide `@username`/`user_id`).")
                            continue
                            
                        if tgt_id == sender_str:
                            send_message(token, chat_id, f"😏 Gifting a {cmd} to yourself? Not happening.")
                            continue
                            
                        if str(tgt_id) == str(admin_id):
                            send_message(token, chat_id, "⚠️ You cannot moderate the bot owner!")
                            continue
                            
                        success = False
                        if cmd == "ban":
                            success = ban_user(token, chat_id, tgt_id)
                            msg = f"🔨 *{tgt_name}* (@{tgt_username or 'no_username'}) has been banned from the group."
                        elif cmd == "unban":
                            success = unban_user(token, chat_id, tgt_id)
                            msg = f"🔓 *{tgt_name}* (@{tgt_username or 'no_username'}) has been unbanned."
                        elif cmd == "kick":
                            success = kick_user(token, chat_id, tgt_id)
                            msg = f"🥾 *{tgt_name}* (@{tgt_username or 'no_username'}) has been kicked from the group."
                        elif cmd == "mute":
                            duration = 600
                            if len(args) > 1:
                                try:
                                    duration = int(args[1]) * 60
                                    if duration <= 0:
                                        duration = 600
                                except:
                                    pass
                            success = mute_user(token, chat_id, tgt_id, duration)
                            msg = f"🔇 *{tgt_name}* (@{tgt_username or 'no_username'}) has been muted for {duration//60} minutes."
                        elif cmd == "unmute":
                            success = unmute_user(token, chat_id, tgt_id)
                            msg = f"🔊 *{tgt_name}* (@{tgt_username or 'no_username'}) has been unmuted."
                            
                        if success:
                            send_message(token, chat_id, msg)
                        else:
                            send_message(token, chat_id, f"⚠️ Failed to {cmd} user. Make sure I am an administrator with appropriate privileges.")
                        continue

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

                    # -------- HELP --------
                    if cmd == "help":
                        commands = (
                            "🐍 *Medusa Bot Commands*:\n"
                            "• `/start` - Wake up the bot\n"
                            "• `/help` - Show this help menu\n"
                            "• `/default` - Switch to Default Mode 🔓\n"
                            "• `/medusa` - Switch to Premium Mode 🌟\n"
                            "• `/check` - Check mode and limits 📊\n"
                            "• `/clear` - Reset your conversation history 🧹\n"
                            "• `/search` - Toggle automatic web search mode 🔍\n"
                            "• `/mood <normal|angry>` - Adjust mood 🎭\n"
                            "• `/temp <0.1-1.0>` - Adjust creativity 🌡️\n\n"
                            "🎮 *Games & Economy*:\n"
                            "• `/ludo` - Create Ludo board race lobby 🎲\n"
                            "• `/balance` - Check point balance 💰\n"
                            "• `/daily` - Claim daily point reward 🎁\n"
                            "• `/gift <user> <amount>` - Transfer points 🎁\n"
                            "• `/leaderboard` - See richest users 🏆\n"
                            "• `/guide` - View full games guidebook 📖"
                        )
                        is_sub = (user_record.get("role") == "subadmin")
                        if sender_str == str(admin_id) or is_sub:
                            commands += "\n\n👑 *Admin/Subadmin Commands*:\n"
                            commands += "• `/admin` - Access Admin Dashboard\n"
                            commands += "• `/subadmin` - Promote/demote/list subadmins\n"
                            commands += "• `/export <user>` - Export target user database profile\n"
                            commands += "• Moderation: `/kick`, `/ban`, `/unban`, `/mute [mins]`, `/unmute`"
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
                            f"\U0001f4b3 *Credits:* {credit_info}\n"
                            f"💰 *Wallet:* `{user_record.get('points', 500)} points`\n\n"
                            "Use `/help` to see all active commands, mortal. Enjoy the games!"
                        )

                        send_message(token, chat_id, info_card)
                        continue

                    # -------- POINTS & BALANCE --------
                    if cmd in ["balance", "bal", "wallet"]:
                        pts = user_record.get("points", 500)
                        send_message(token, chat_id, f"💰 *{first_name}'s Balance*:\nYou have `{pts} points`.")
                        continue

                    # -------- DAILY CLAIM --------
                    if cmd == "daily":
                        now = time.time()
                        last_daily = user_record.get("last_daily_claim", 0.0)
                        cooldown = 86400
                        if now - last_daily < cooldown:
                            remaining = cooldown - (now - last_daily)
                            hours = int(remaining // 3600)
                            minutes = int((remaining % 3600) // 60)
                            send_message(token, chat_id, f"⏳ You have already claimed your daily points, mortal! Come back in `{hours}h {minutes}m`.")
                        else:
                            reward = 200
                            user_record["points"] = user_record.get("points", 500) + reward
                            user_record["last_daily_claim"] = now
                            save_single_user(sender_str, user_record)
                            send_message(token, chat_id, f"🎉 *Daily Claim Successful!*\nMedusa has granted you `{reward} points`! Current balance: `{user_record['points']} points`.")
                        continue

                    # -------- GIFT POINTS --------
                    if cmd in ["gift", "transfer"]:
                        if len(args) < 2:
                            send_message(token, chat_id, "⚠️ Usage: `/gift <reply | @username | user_id> <amount>`")
                            continue
                        try:
                            amount = int(args[-1])
                            if amount <= 0:
                                raise ValueError
                        except:
                            send_message(token, chat_id, "⚠️ Please specify a valid positive amount of points to gift.")
                            continue
                        
                        target_args = args[:-1]
                        tgt_id, tgt_name, tgt_username = resolve_target_user(message, target_args, user_data)
                        if not tgt_id:
                            send_message(token, chat_id, "⚠️ Target user not found. Reply to their message or specify `@username` / `user_id`.")
                            continue
                        
                        if tgt_id == sender_str:
                            send_message(token, chat_id, "😏 Gifting points to yourself? Medusa is not amused.")
                            continue
                        
                        my_pts = user_record.get("points", 500)
                        if my_pts < amount:
                            send_message(token, chat_id, f"⚠️ You do not have enough points. Balance: `{my_pts} points`.")
                            continue
                        
                        tgt_record = user_data.get(tgt_id)
                        if not tgt_record:
                            tgt_record = {
                                "credits_used": 0,
                                "last_reset": time.time(),
                                "username": tgt_username,
                                "first_name": tgt_name,
                                "active_mode": "groq",
                                "preferences": {},
                                "history": [],
                                "plan": "free",
                                "images_today": 0,
                                "summaries_today": 0,
                                "searches_today": 0,
                                "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
                                "points": 500,
                                "role": "user",
                                "inventory": {"coal": 0, "iron": 0, "gold": 0, "diamond": 0, "medusite": 0},
                                "pickaxe": "wooden",
                                "last_mine_time": 0.0,
                                "last_daily_claim": 0.0
                            }
                        
                        user_record["points"] = my_pts - amount
                        tgt_record["points"] = tgt_record.get("points", 500) + amount
                        
                        save_single_user(sender_str, user_record)
                        save_single_user(tgt_id, tgt_record)
                        
                        send_message(token, chat_id, f"🎁 *Gift Successful!*\nYou gifted `{amount} points` to *{tgt_name}* (@{tgt_username or 'no_username'}).")
                        continue

                    # -------- LEADERBOARD --------
                    if cmd in ["leaderboard", "rich"]:
                        sorted_users = sorted(user_data.items(), key=lambda x: x[1].get("points", 500), reverse=True)
                        lines = ["🏆 *MEDUSA POINTS LEADERBOARD* 🏆", "--------------------------------------"]
                        for idx, (uid, info) in enumerate(sorted_users[:10], 1):
                            name = info.get("first_name", "User")
                            pts = info.get("points", 500)
                            lines.append(f"{idx}. *{name}* — `{pts} pts`")
                        send_message(token, chat_id, "\n".join(lines))
                        continue

                    # -------- GUIDE --------
                    if cmd in ["guide", "games"]:
                        guide = (
                            "📖 *MEDUSA COMPREHENSIVE GAME BOOK* 🐍\n"
                            "====================================\n\n"
                            "💰 *POINTS & ECONOMY*\n"
                            "• `/balance` (or `/bal`) - Check your current wallet points.\n"
                            "• `/daily` - Claim 200 points every 24 hours.\n"
                            "• `/gift <user> <amount>` - Gift points to another user.\n"
                            "• `/leaderboard` (or `/rich`) - View top 10 richest players.\n\n"
                            "🎲 *LUDO BOARD RACE*\n"
                            "A fast-paced board race on a 30-step path played with inline buttons!\n"
                            "1. Start a lobby with `/ludo` in a group chat.\n"
                            "2. Other players click `➕ Join Lobby` (up to 4 players total). **Every player must first message the bot in private to register!**\n"
                            "3. Host starts the game using `🚀 Start Game`.\n"
                            "4. Take turns clicking `🎲 Roll Dice` to move 1-6 spaces.\n"
                            "   - *Safe Zones* (Steps 0, 8, 15, 22): You cannot be kicked here.\n"
                            "   - *Kicking*: Landing on an opponent resets them to 0 (unless they are on a Safe Zone).\n"
                            "   - *Boost Shortcut*: Step 12 automatically launches you to Step 18.\n"
                            "   - *Trap Net*: Step 25 pulls you backward to Step 10.\n"
                            "5. Win: You must reach step 30 exactly. Winner gets `1,000 points`!"
                        )
                        send_message(token, chat_id, guide)
                        continue



                    # -------- LUDO --------
                    if cmd == "ludo":
                        ludo_cmd = args[0].lower() if args else "create"
                        
                        if ludo_cmd == "create":
                            if chat_id in active_ludo_games:
                                send_message(token, chat_id, "⚠️ A Ludo game lobby or active match is already running in this chat.")
                                continue
                            
                            active_ludo_games[chat_id] = {
                                "status": "lobby",
                                "players": [sender_str],
                                "player_names": {sender_str: first_name},
                                "positions": {sender_str: 0},
                                "colors": {},
                                "turn_idx": 0,
                                "last_roll": 0,
                                "last_roller": None,
                                "host_id": sender_str,
                                "lobby_msg_id": None
                            }
                            
                            lobby_text = (
                                "🎲 *LUDO BOARD RACE - NEW LOBBY* 🎲\n"
                                "-------------------------------------\n"
                                f"Host: *{first_name}*\n\n"
                                "👥 *Joined Players*:\n"
                                f"1. *{first_name}*\n\n"
                                "Waiting for players to join (2 to 4 players required). Click below to join!"
                            )
                            
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "➕ Join Lobby", "callback_data": f"ludo_join_{chat_id}"},
                                        {"text": "🚀 Start Game", "callback_data": f"ludo_start_{chat_id}"}
                                    ],
                                    [
                                        {"text": "❌ Cancel Game", "callback_data": f"ludo_cancel_{chat_id}"}
                                    ]
                                ]
                            }
                            
                            url = f"https://api.telegram.org/bot{token}/sendMessage"
                            data = {
                                "chat_id": chat_id,
                                "text": markdown_to_html(lobby_text),
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(reply_markup)
                            }
                            try:
                                r = requests.post(url, data=data, timeout=10).json()
                                lobby_msg_id = r.get("result", {}).get("message_id")
                                active_ludo_games[chat_id]["lobby_msg_id"] = lobby_msg_id
                            except Exception as e:
                                print(f"Error starting ludo lobby: {e}")
                                active_ludo_games.pop(chat_id, None)
                                
                        elif ludo_cmd == "join":
                            if chat_id not in active_ludo_games:
                                send_message(token, chat_id, "⚠️ No active Ludo lobby found in this chat. Start one with `/ludo`!")
                                continue
                            
                            game = active_ludo_games[chat_id]
                            if game["status"] != "lobby":
                                send_message(token, chat_id, "⚠️ Game is already running!")
                                continue
                            
                            if sender_str in game["players"]:
                                send_message(token, chat_id, "⚠️ You have already joined this lobby!")
                                continue
                                
                            if len(game["players"]) >= 4:
                                send_message(token, chat_id, "⚠️ Lobby is full (max 4 players)!")
                                continue
                                
                            game["players"].append(sender_str)
                            game["player_names"][sender_str] = first_name
                            game["positions"][sender_str] = 0
                            
                            player_list = "\n".join(f"{idx+1}. *{game['player_names'][p]}*" for idx, p in enumerate(game["players"]))
                            lobby_text = (
                                "🎲 *LUDO BOARD RACE - LOBBY* 🎲\n"
                                "-------------------------------------\n"
                                f"Host: *{game['player_names'][game['host_id']]}*\n\n"
                                "👥 *Joined Players*:\n"
                                f"{player_list}\n\n"
                                "Click below to join!"
                            )
                            
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "➕ Join Lobby", "callback_data": f"ludo_join_{chat_id}"},
                                        {"text": "🚀 Start Game", "callback_data": f"ludo_start_{chat_id}"}
                                    ],
                                    [
                                        {"text": "❌ Cancel Game", "callback_data": f"ludo_cancel_{chat_id}"}
                                    ]
                                ]
                            }
                            
                            url = f"https://api.telegram.org/bot{token}/editMessageText"
                            data = {
                                "chat_id": chat_id,
                                "message_id": game["lobby_msg_id"],
                                "text": markdown_to_html(lobby_text),
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(reply_markup)
                            }
                            try:
                                requests.post(url, data=data, timeout=10)
                            except:
                                pass
                                
                        elif ludo_cmd == "start":
                            if chat_id not in active_ludo_games:
                                send_message(token, chat_id, "⚠️ No Ludo lobby to start. Create one with `/ludo`!")
                                continue
                            game = active_ludo_games[chat_id]
                            if game["status"] != "lobby":
                                continue
                            if sender_str != game["host_id"]:
                                send_message(token, chat_id, "⚠️ Only the host can start the game.")
                                continue
                            if len(game["players"]) < 2:
                                send_message(token, chat_id, "⚠️ Need at least 2 players to start!")
                                continue
                                
                            colors = ["🔴", "🔵", "🟢", "🟡"]
                            for idx, p in enumerate(game["players"]):
                                game["colors"][p] = colors[idx]
                                game["positions"][p] = 0
                            
                            game["status"] = "playing"
                            game["turn_idx"] = 0
                            
                            board_text = render_ludo_board(game)
                            reply_markup = {
                                "inline_keyboard": [
                                    [
                                        {"text": "🎲 Roll Dice", "callback_data": f"ludo_roll_{chat_id}"}
                                    ]
                                ]
                            }
                            
                            url = f"https://api.telegram.org/bot{token}/editMessageText"
                            data = {
                                "chat_id": chat_id,
                                "message_id": game["lobby_msg_id"],
                                "text": markdown_to_html(board_text),
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(reply_markup)
                            }
                            try:
                                requests.post(url, data=data, timeout=10)
                            except:
                                send_message(token, chat_id, board_text, reply_markup)
                                
                        elif ludo_cmd == "cancel":
                            if chat_id not in active_ludo_games:
                                continue
                            game = active_ludo_games[chat_id]
                            is_admin = is_user_group_admin(token, chat_id, sender_id, admin_id, user_data)
                            if sender_str != game["host_id"] and not is_admin:
                                send_message(token, chat_id, "⚠️ Only host or admins can cancel.")
                                continue
                            active_ludo_games.pop(chat_id)
                            send_message(token, chat_id, "❌ Ludo game lobby has been cancelled.")
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
                        sum_used = user_record.get("summaries_today", 0)
                        search_used = user_record.get("searches_today", 0)
                        
                        is_unltd = user_record.get("unlimited", False) or (sender_str == str(admin_id))
                        
                        if is_unltd:
                            img_status = "Unlimited ♾️"
                            sum_status = "Unlimited ♾️"
                            search_status = "Unlimited ♾️"
                        else:
                            img_status = f"{img_used}/{limits['images']}"
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
                            f"• *Reset Timer*: `{reset_str}` ⏳\n"
                            f"• *Wallet*: `{user_record.get('points', 500)} points` 💰\n\n"
                            "*Daily Limit Usage*:\n"
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
                                "   • Image Analysis: 3 per day 🖼️\n"
                                "   • Document Summary: 2 per day 📄\n"
                                "   • Web Search: 4 per day 🔍\n"
                                "   • Medusa Mode: 4 credits per day 🌟\n\n"
                                "⭐ *Premium Plan* - $3 one-time\n"
                                "   • Unlimited Chat (Default Mode)\n"
                                "   • Image Analysis: 10 per day 🖼️\n"
                                "   • Document Summary: 5 per day 📄\n"
                                "   • Web Search: 10 per day 🔍\n"
                                "   • Medusa Mode: 8 credits per day 🌟\n\n"
                                "🔥 *Max Plan* - $10 one-time\n"
                                "   • Unlimited Chat (Default Mode)\n"
                                "   • Image Analysis: 10 per day 🖼️\n"
                                "   • Document Summary: 5 per day 📄\n"
                                "   • Web Search: 10 per day 🔍\n"
                                "   • Medusa Mode: 15 credits per day 🌟\n\n"
                                "Select the plan below to request an upgrade from the Admin."
                            )
                            upgrade_btn = {
                                "inline_keyboard": [
                                    [
                                        {"text": "Request Premium Upgrade ($3)", "callback_data": "req_upg_premium"},
                                        {"text": "Request Max Upgrade ($10)", "callback_data": "req_upg_max"}
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

                    # -------- AUTO BROWSER SEARCH / AUTO DETECTION --------
                    custom_context = ""
                    should_search = search_modes.get(chat_id, False)
                    
                    if not should_search:
                        # Automatically check if the query requires real-time search
                        should_search = needs_web_search(groq_keys, gemini_keys, text)
                        if should_search:
                            plan = user_record.get("plan", "free")
                            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
                            is_admin = (sender_str == str(admin_id))
                            is_unltd = user_record.get("unlimited", False) or is_admin
                            
                            if not is_unltd and user_record.get("searches_today", 0) >= limits["searches"]:
                                send_message(
                                    token, chat_id,
                                    f"⚠️ *Daily limit reached!* Auto-detect skipped search as you have used all *{limits['searches']}* web searches for today on the *{plan.capitalize()}* plan."
                                )
                                should_search = False
                            else:
                                send_message(token, chat_id, f"🔍 *Auto-detected need for real-time info. Searching for:* `{text}`...")
                            
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
