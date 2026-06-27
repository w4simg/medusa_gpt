import os
import time
import requests
import json
import re
import sys
import io
import html
import signal
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
            mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
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
        print(Fore.YELLOW + "ℹ️ No MONGO_URI found in environment or key.txt. Using local user_data.json.")
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
    
    # Now restore inline code blocks
    for idx, code in enumerate(inline_codes):
        escaped = escaped.replace(f"INLINECODEPLACEHOLDER{idx}", f"<code>{code}</code>")
        
    # Restore block code blocks
    for idx, block in enumerate(code_blocks):
        # Extract the content inside backticks again
        match = re.match(r"```(?:[a-zA-Z0-9+#-]+)?\s*?\n?(.*?)```", block, flags=re.DOTALL)
        if match:
            code_content = match.group(1)
            # Wrap in <pre><code>
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


def set_bot_commands(token):
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "start", "description": "Wake up Medusa 🐍"},
        {"command": "help", "description": "Show list of commands ℹ️"},
        {"command": "medusa", "description": "Switch to Premium Mode (4 credits/day) 🌟"},
        {"command": "default", "description": "Switch to Default Mode (Free, Unlimited) 🔓"},
        {"command": "upgrade", "description": "Upgrade to Unlimited Premium for $2 🚀"},
        {"command": "check", "description": "Check current mode and remaining limit 📊"},
        {"command": "clear", "description": "Clear your conversation history 🧹"},
        {"command": "search", "description": "Toggle web search / search directly 🔍"}
    ]
    try:
        r = requests.post(url, json={"commands": commands}, timeout=10)
        if r.status_code == 200:
            print("Successfully registered bot commands with Telegram.")
        else:
            print(f"Failed to register bot commands: {r.text}")
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
# 📡 TELEGRAM DAEMON MODE
# =================================

def telegram_mode(cyberneurova_keys, groq_keys, gemini_keys, token, admin_id):
    print("🐍 Telegram mode started (Stable Long Polling with Dual Engines & Search)...")

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

                    # Admin-only callbacks from here
                    if str(sender_id) != str(admin_id):
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
                            "last_reset_date": current_date_str
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
                        save_user_data(user_data)

                    # -------- DOCUMENT MESSAGE --------
                    if "document" in message:
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
                                elif ext == "pdf":
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
                                    if chat_id not in user_histories:
                                        saved_hist = user_record.get("history", [])
                                        user_histories[chat_id] = saved_hist if saved_hist else [
                                            {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                                        ]
                                    
                                    user_histories[chat_id].append({"role": "system", "content": doc_context})
                                    user_histories[chat_id].append({"role": "assistant", "content": reply})
                                    
                                    user_record["history"] = user_histories[chat_id]
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
                                if chat_id not in user_histories:
                                    saved_hist = user_record.get("history", [])
                                    user_histories[chat_id] = saved_hist if saved_hist else [
                                        {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                                    ]
                                
                                user_histories[chat_id].append({"role": "user", "content": f"[Image uploaded with caption: {prompt_text}]"})
                                user_histories[chat_id].append({"role": "assistant", "content": reply})
                                
                                user_record["history"] = user_histories[chat_id]
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

                    # -------- EXTRACT TEXT --------
                    text = message.get("text", "").strip()
                    if not text:
                        continue

                    # -------- HELP --------
                    if text == "/help":
                        commands = (
                            "🐍 *Medusa Bot Commands*:\n"
                            "• `/start` - Wake up the bot\n"
                            "• `/help` - Show this help menu\n"
                            "• `/default` - Switch to Default Mode (Free, Unlimited) 🔓\n"
                            "• `/medusa` - Switch to Premium Mode (Premium, 4 queries/day) 🌟\n"
                            "• `/check` - Check current mode and remaining credits 📊\n"
                            "• `/clear` - Reset your conversation history 🧹\n"
                            "• `/search` - Toggle automatic web search mode 🔍\n"
                            "• `/search <query>` - Run a direct web search query 🔍\n"
                            "• `/mood <normal|angry>` - Adjust Medusa's mood 🎭\n"
                            "• `/temp <0.1-1.0>` - Adjust creativity temperature 🌡️\n"
                        )
                        if sender_str == str(admin_id):
                            commands += "• `/admin` - Access Admin Dashboard 👑\n"
                        send_message(token, chat_id, commands)
                        continue

                    # -------- START --------
                    if text == "/start":
                        # Step 1 — Show typing indicator then send "Starting..."
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

                        # Step 2 — Pause then show typing again, edit to wake message
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

                        # Step 3 — Short pause then send info card
                        time.sleep(1.0)
                        send_typing(token, chat_id)

                        # Step 4 — Build and send user info card
                        display_username = f"@{username}" if username else "No username set"
                        mode_display = "Default (Free, Unlimited)" if active_mode == "groq" else "Premium"
                        is_unltd = user_record.get("unlimited", False) or (sender_str == str(admin_id))
                        credit_info = "Unlimited ♾️" if is_unltd else "4 questions/day (Premium Mode)"

                        info_card = (
                            "\U0001f40d *Medusa \u2014 User Profile*\n\n"
                            f"\U0001f464 *Name:* {first_name}\n"
                            f"\U0001f4e7 *Username:* {display_username}\n"
                            f"\U0001f194 *Chat ID:* `{chat_id}`\n"
                            f"\U0001f4ca *Active Mode:* {mode_display}\n"
                            f"\U0001f4b3 *Credits:* {credit_info}\n\n"
                            "You are in *Default Mode* with unlimited free questions \U0001f513\n\n"
                            "\u2022 /medusa \u2014 Switch to Premium Mode \U0001f31f\n"
                            "\u2022 /upgrade \u2014 Unlock Unlimited for $2 \U0001f680\n"
                            "\u2022 /help \u2014 View all commands \u2139\ufe0f"
                        )

                        send_message(token, chat_id, info_card)
                        continue

                    # -------- MODE COMMANDS --------
                    if text == "/medusa":
                        user_record["active_mode"] = "medusa"
                        if "last_reset" not in user_record:
                            user_record["last_reset"] = time.time()
                        user_data[sender_str] = user_record
                        save_user_data(user_data)
                        
                        if chat_id in user_histories:
                            user_histories[chat_id].clear()
                            
                        send_message(
                            token,
                            chat_id,
                            "🌟 *Mode switched to Premium Mode!*\n\n"
                            "You are now talking in Premium Mode. "
                            "You have a limit of *4 questions per day* in this mode.\n\n"
                            "Use `/check` to view your credits, and `/default` to switch back to free unlimited mode."
                        )
                        continue

                    if text == "/default":
                        user_record["active_mode"] = "groq"
                        user_data[sender_str] = user_record
                        save_user_data(user_data)
                        
                        if chat_id in user_histories:
                            user_histories[chat_id].clear()
                            
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
                    if text == "/check":
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
                            
                        # Medusa mode credit status
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
                            f"• 🖼️ *Image Analyses*: `{img_status}`\n"
                            f"• 📄 *Doc Summaries*: `{sum_status}`\n"
                            f"• 🔍 *Web Searches*: `{search_status}`\n\n"
                            "Use `/medusa` to switch to Premium, `/default` to switch to Default."
                        )
                        send_message(token, chat_id, status_msg)
                        continue

                    # -------- UPGRADE PLAN --------
                    if text == "/upgrade":
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
                    if text == "/clear":
                        if chat_id in user_histories:
                            user_histories[chat_id].clear()
                        user_record["history"] = []
                        user_data[sender_str] = user_record
                        save_user_data(user_data)
                        send_message(token, chat_id, "🧹 Conversation history cleared.")
                        continue

                    # -------- HISTORY --------
                    if text == "/history":
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
                    if text == "/admin":
                        if sender_str == str(admin_id):
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
                                if chat_id not in user_histories:
                                    saved_hist = user_record.get("history", [])
                                    user_histories[chat_id] = saved_hist if saved_hist else [
                                        {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                                    ]
                                user_histories[chat_id].append({"role": "user", "content": f"Search Query: {search_query}"})
                                user_histories[chat_id].append({"role": "assistant", "content": reply})
                                
                                user_record["history"] = user_histories[chat_id]
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

                    if not user_histories.get(chat_id):
                        saved_hist = user_record.get("history", [])
                        user_histories[chat_id] = saved_hist if saved_hist else [
                            {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}
                        ]
                    else:
                        user_histories[chat_id][0] = {"role": "system", "content": build_system_prompt(user_record.get("preferences", {}))}

                    user_msg = text
                    if custom_context:
                        user_msg += custom_context
                        
                    user_histories[chat_id].append({"role": "user", "content": user_msg})

                    if len(user_histories[chat_id]) > 16:
                        user_histories[chat_id] = [user_histories[chat_id][0]] + user_histories[chat_id][-15:]

                    try:
                        if active_mode == "medusa":
                            reply = ask_medusa_with_failover(cyberneurova_keys, user_histories[chat_id])
                        else:
                            reply = ask_groq_with_failover(groq_keys, user_histories[chat_id])
                        
                        # Process preferences from response
                        pref_match = re.search(r"\[PREF:\s*(.*?)\]", reply)
                        if pref_match:
                            pref_str = pref_match.group(1)
                            for item in pref_str.split(","):
                                if "=" in item:
                                    k, v = item.split("=", 1)
                                    user_record.setdefault("preferences", {})[k.strip().lower()] = v.strip()
                            reply = re.sub(r"\[PREF:\s*(.*?)\]", "", reply).strip()

                        user_histories[chat_id].append({"role": "assistant", "content": reply})
                        
                        # Save history and preferences in database
                        user_record["history"] = user_histories[chat_id]
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
        cyberneurova = input("Enter CyberNeurova API key 1: ")
        save_key("CYBERNEUROVA_1", cyberneurova)
    if not groq_keys:
        groq_key = input("Enter Groq API key 1: ")
        save_key("GROQ_1", groq_key)
    if not gemini_keys:
        gemini_key = input("Enter Gemini API key 1: ")
        save_key("GEMINI_1", gemini_key)

    # Re-read keys after potential input prompts
    cyberneurova_keys, groq_keys, gemini_keys = get_api_keys()

    if "BOT_TOKEN" not in keys:
        token = input("Enter Telegram Bot Token: ")
        save_key("BOT_TOKEN", token)
    else:
        token = keys["BOT_TOKEN"]

    if "CHAT_ID" not in keys:
        chat_id = input("Enter Telegram Admin ID: ")
        save_key("CHAT_ID", chat_id)
    else:
        chat_id = keys["CHAT_ID"]

    clear()
    banner()

    # Register commands with Telegram
    set_bot_commands(token)

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
