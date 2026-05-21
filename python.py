# ============================================================
# 這一區負責匯入程式需要的套件
# 包含：
# - 基本資料處理
# - 網頁爬蟲
# - PDF 履歷生成
# - Gemini AI
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
# 這一區負責檢查 Gemini AI 是否成功安裝
# 如果沒有安裝，程式會改用 fallback 模式
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
# 這一區負責設定整個專案的基本參數
# 包含：
# - 輸出檔案位置
# - PDF 字型
# - AI 模型
# - 工作數量限制
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_PDF = os.path.join(BASE_DIR, "ai_resume.pdf")
OUTPUT_TXT = os.path.join(BASE_DIR, "resume_content.txt")
OUTPUT_JSON = os.path.join(BASE_DIR, "resume_ai_content.json")
JOBS_TXT = os.path.join(BASE_DIR, "job_recommendations.txt")
RAW_JOBS_JSON = os.path.join(BASE_DIR, "raw_jobs_fetched.json")

PDF_FONT = "HeiseiMin-W3"
PDF_BOLD = "HeiseiKakuGo-W5"

pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))
pdfmetrics.registerFont(UnicodeCIDFont(PDF_BOLD))

GEMINI_FALLBACK_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

TOTAL_JOBS_TO_FETCH = 50
FETCH_PER_PLATFORM = 50
OUTPUT_RECOMMEND_LIMIT = 20
MATCH_SCORE_THRESHOLD = 60

# ============================================================
# Utility Functions
# ============================================================ 

# ============================================================
# 這一區負責處理基本文字清理與格式轉換
# 避免資料格式錯誤影響後續程式
# ============================================================

def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def escape_text(value):
    return html.escape(safe_text(value))


def split_comma_text(text):
    text = safe_text(text)

    if not text:
        return []

    parts = re.split(r"[,，、\n]+", text)

    return [p.strip() for p in parts if p.strip()]


def clean_text(text):

    if text is None:
        return ""

    text = BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def safe_int(value, default=0):

    try:
        cleaned = re.sub(r"[^\d]", "", str(value))
        return int(cleaned) if cleaned else default

    except Exception:
        return default


# ============================================================
# 這一區負責建立求職網站搜尋網址
# 會依照：
# - 職位名稱
# - 地區
# - 最低薪資
# 自動組成搜尋連結
# ============================================================

def build_104_search_url(job_title, location, salary_min):

    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()

    return f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}"


def build_1111_search_url(job_title, location, salary_min):

    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()

    return f"https://www.1111.com.tw/search/job?ks={quote(keyword)}"


# ============================================================
# 這一區負責修正網址格式
# 避免爬到：
# - 相對路徑
# - 不完整網址
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
# 這一區負責從 AI 回傳內容中擷取 JSON
# 避免 AI 多回傳 markdown 或其他文字
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
# 這一區負責分析薪資數字
# ============================================================

def estimate_salary_from_text(text):

    if not text:
        return None

    values = []

    nums = re.findall(r"(?<!\d)(\d{2,3}(?:,\d{3})|\d{5,6})(?!\d)", text)

    for n in nums:

        try:
            v = int(n.replace(",", ""))

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    wan_nums = re.findall(r"(\d+(?:\.\d+)?)\s*萬", text)

    for n in wan_nums:

        try:
            v = int(float(n) * 10000)

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    k_nums = re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", text)

    for n in k_nums:

        try:
            v = int(float(n) * 1000)

            if 20000 <= v <= 300000:
                values.append(v)

        except Exception:
            pass

    return max(values) if values else None


# ============================================================
# 這一區負責擷取原始薪資文字
# 例如：
# - 月薪 50000
# - 待遇面議
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
# 這一區負責判斷薪資是否符合使用者需求
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
# 這一區負責計算工作匹配分數
# 會根據：
# - 職稱
# - 地區
# - 關鍵字
# - 薪資
# 來判斷這份工作適不適合使用者
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