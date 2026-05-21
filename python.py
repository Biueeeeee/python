# ============================================================
# 這一區負責匯入程式需要的所有套件（libraries）
#
# 這些套件的用途分別是：
#
# - os：處理檔案路徑與系統操作
# - re：正則表達式（用來抓文字、薪資格式）
# - json：處理 JSON 資料
# - html：處理 HTML escape（避免符號錯誤）
# - time / random：控制延遲與隨機行為（爬蟲常用）
# - requests：發送 HTTP 請求（爬網站用）
# - BeautifulSoup：解析 HTML 網頁內容
# - urllib.parse：處理網址編碼與解析
#
# reportlab：
# → 用來生成 PDF 履歷
# ============================================================

import os
import re
import json
import html
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, parse_qs, unquote

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


# ============================================================
# 這一區負責檢查 Gemini AI 是否可以使用

# 用 try-except 保護：
# → 如果成功：GEMINI_INSTALLED = True
# → 如果失敗：GEMINI_INSTALLED = False

# 後面程式就可以依照這個變數決定要不要用 AI
# ============================================================

try:
    from google import genai
    from google.genai import types
    GEMINI_INSTALLED = True
except ImportError:
    GEMINI_INSTALLED = False


# ============================================================
# Basic Settings
# ============================================================

# ============================================================
# 這一區負責設定整個專案的「核心參數」
#
# 包含：
# - 檔案輸出位置（PDF / TXT / JSON）
# - 工作資料儲存檔案
# - PDF 字型設定
# - AI 模型設定
# - 工作數量限制

# ============================================================


# 取得目前 Python 檔案所在資料夾
# → 用來確保輸出檔案都存在正確位置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# 輸出檔案設定
#
# OUTPUT_PDF：
# → 最終生成的 PDF 履歷
#
# OUTPUT_TXT：
# → 純文字履歷內容
#
# OUTPUT_JSON：
# → AI 整理後的履歷資料（結構化）
#
# JOBS_TXT：
# → 工作推薦結果（文字版）
#
# RAW_JOBS_JSON：
# → 爬蟲抓到的原始職缺資料
# ============================================================

OUTPUT_PDF = os.path.join(BASE_DIR, "ai_resume.pdf")
OUTPUT_TXT = os.path.join(BASE_DIR, "resume_content.txt")
OUTPUT_JSON = os.path.join(BASE_DIR, "resume_ai_content.json")
JOBS_TXT = os.path.join(BASE_DIR, "job_recommendations.txt")
RAW_JOBS_JSON = os.path.join(BASE_DIR, "raw_jobs_fetched.json")


# ============================================================
# PDF 字型設定
#
# ReportLab 預設不支援中文
# 所以這裡使用 CIDFont（日文字型）來支援中文顯示
#
# PDF_FONT：
# → 一般文字
#
# PDF_BOLD：
# → 粗體文字
# ============================================================

PDF_FONT = "HeiseiMin-W3"
PDF_BOLD = "HeiseiKakuGo-W5"

pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))
pdfmetrics.registerFont(UnicodeCIDFont(PDF_BOLD))


# ============================================================
# Gemini AI 模型備援清單
# ============================================================

GEMINI_FALLBACK_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


# ============================================================
# 工作搜尋 / 輸出控制參數
#
# TOTAL_JOBS_TO_FETCH：
# → 總共抓幾筆職缺
#
# FETCH_PER_PLATFORM：
# → 每個網站抓幾筆
#
# OUTPUT_RECOMMEND_LIMIT：
# → 最後推薦幾個工作
#
# MATCH_SCORE_THRESHOLD：
# → 工作最低匹配分數門檻
# ============================================================

TOTAL_JOBS_TO_FETCH = 50
FETCH_PER_PLATFORM = 50
OUTPUT_RECOMMEND_LIMIT = 20
MATCH_SCORE_THRESHOLD = 60


# ============================================================
# Utility Functions
# ============================================================


# ============================================================
# 這一區負責「資料清理與格式轉換」
# ============================================================


def safe_text(value):
    # 把 None 轉成空字串，避免後面 .strip() 出錯
    if value is None:
        return ""

    # 強制轉成字串並去除前後空白
    return str(value).strip()


def escape_text(value):
    # 將 HTML 特殊符號轉義（例如 < >）
    # 避免輸出到 HTML/PDF 時格式錯亂
    return html.escape(safe_text(value))


def split_comma_text(text):
    # 將文字依照不同分隔符切成 list
    # 支援：英文逗號 / 中文逗號 / 頓號 / 換行

    text = safe_text(text)

    if not text:
        return []

    parts = re.split(r"[,，、\n]+", text)

    # 去掉空白項目
    return [p.strip() for p in parts if p.strip()]


def clean_text(text):
    # 清理 HTML 與多餘空白

    if text is None:
        return ""

    # 移除 HTML 標籤，只保留純文字
    text = BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

    # 把多個空白變成一個空白
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def safe_int(value, default=0):
    # 安全轉換成整數
    # 會自動移除 $, , 等符號

    try:
        cleaned = re.sub(r"[^\d]", "", str(value))

        return int(cleaned) if cleaned else default

    except Exception:
        return default


# ============================================================
# 這一區負責建立「求職網站搜尋網址」
# → 把使用者輸入轉成 104 / 1111 的搜尋 URL
# ============================================================


def build_104_search_url(job_title, location, salary_min):

    # 把條件組合成搜尋關鍵字
    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()

    # 轉成 URL safe 格式
    return f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}"


def build_1111_search_url(job_title, location, salary_min):

    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()

    return f"https://www.1111.com.tw/search/job?ks={quote(keyword)}"


# ============================================================
# 這一區負責「修正網址格式」
#
# 常見問題：
# 1. //example.com（缺 https）
# 2. /job/123（相對路徑）
# 3. DuckDuckGo 轉址（真正網址藏在 uddg）
# ============================================================


def normalize_url(url, base_domain):

    if not url:
        return ""

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return base_domain.rstrip("/") + url

    return url


def normalize_duckduckgo_link(href):

    if not href:
        return ""

    if "uddg=" in href:

        parsed = urlparse(href)
        query = parse_qs(parsed.query)

        real_url = query.get("uddg", [""])[0]

        return unquote(real_url)

    return href


# ============================================================
# 這一區負責「從 AI 回傳內容中解析 JSON」
# ============================================================


def extract_json_from_text(text):

    text = text.strip()

    if text.startswith("```"):

        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)

    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("Could not parse JSON from model output.")


# ============================================================
# 這一區負責「薪資數字解析」0K
# 最終會轉成統一數字（元）
# ============================================================


def estimate_salary_from_text(text):

    if not text:
        return None

    values = []

    # 抓一般數字薪資
    nums = re.findall(r"(?<!\d)(\d{2,3}(?:,\d{3})|\d{5,6})(?!\d)", text)

    for n in nums:

        try:
            v = int(n.replace(",", ""))

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    # 抓「萬」單位薪資
    wan_nums = re.findall(r"(\d+(?:\.\d+)?)\s*萬", text)

    for n in wan_nums:

        try:
            v = int(float(n) * 10000)

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    # 抓 K 單位薪資
    k_nums = re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", text)

    for n in k_nums:

        try:
            v = int(float(n) * 1000)

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    # 回傳最高薪資（代表可能上限）
    return max(values) if values else None


# ============================================================
# 這一區負責「擷取薪資原始字串」
# ============================================================


def extract_salary_string(text):

    patterns = [
        r"月薪\s*[0-9,萬Kk~～\-以上]+",
        r"年薪\s*[0-9,萬Kk~～\-以上]+",
        r"時薪\s*[0-9,萬Kk~～\-以上]+",
        r"[0-9,]+元\s*[~～\-]\s*[0-9,]+元",
        r"[0-9.]+萬\s*[~～\-]\s*[0-9.]+萬",
        r"待遇面議",
        r"面議",
    ]

    for p in patterns:
        m = re.search(p, text)

        if m:
            return m.group(0)

    return "Not clearly shown"


# ============================================================
# 這一區負責「判斷薪資是否符合最低要求」
#
# 判斷流程：
# 1. 使用者沒設最低薪資 → 不比較
# 2. 抓不到薪資 → 無法判斷
# 3. 有薪資 → 比較是否達標
# ============================================================


def salary_status(salary_text, salary_min):

    salary_est = estimate_salary_from_text(salary_text)

    if salary_min <= 0:
        return "No minimum salary requirement"

    if salary_est is None:
        return "Not clearly shown"

    if salary_est >= salary_min:
        return "Possibly meets minimum salary"

    return "May be lower than minimum salary"


# ============================================================
# 這一區負責「計算工作匹配分數」
#
# 評分依據：
# 1. 職稱是否符合
# 2. 地點是否符合
# 3. 關鍵字是否命中
# 4. 薪資是否符合
#
# 分數越高 → 越適合該使用者
# ============================================================


def score_job_keyword(job, job_title, location, salary_min):

    title = job.get("title", "")
    company = job.get("company", "")
    job_location = job.get("location", "")
    salary = job.get("salary", "")
    snippet = job.get("snippet", "")

    full_text = f"{title} {company} {job_location} {salary} {snippet}".lower()

    score = 0

    if job_title.lower() in title.lower():
        score += 8

    if job_title.lower() in full_text:
        score += 3

    if location.lower() in full_text:
        score += 6

    tokens = re.split(r"[\s,，/、]+", job_title)

    for token in tokens:

        token = token.strip()

        if token and token.lower() in full_text:
            score += 1

    salary_est = estimate_salary_from_text(salary + " " + snippet)

    if salary_min > 0 and salary_est is not None:

        if salary_est >= salary_min:
            score += 5
        else:
            score -= 2

    job["keyword_score"] = score
    job["salary_est"] = salary_est
    job["salary_status"] = salary_status(salary + " " + snippet, salary_min)

    return score