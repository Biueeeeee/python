# ============================================================
# 這一區負責匯入程式需要的所有套件
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
# 這一區負責「薪資數字解析」
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

# ============================================================
# Gemini Job Ranking
# ============================================================

# 將原始職缺資料整理成 Gemini 比較容易分析的格式
# 並加入 job_index 作為識別編號
def compact_job_for_gemini(job, index):
    return {
        "job_index": index,  # 職缺編號
        "platform": job.get("platform", ""),  # 職缺來源平台
        "title": job.get("title", ""),  # 職缺名稱
        "company": job.get("company", ""),  # 公司名稱
        "location": job.get("location", ""),  # 工作地點
        "salary": job.get("salary", ""),  # 薪資
        "salary_status": job.get("salary_status", ""),  # 薪資是否公開
        "keyword_score": job.get("keyword_score", 0),  # 關鍵字配對分數
        "snippet": job.get("snippet", "")[:300],  # 職缺摘要（限制300字）
        "url": job.get("url", ""),  # 職缺連結
    }


# 當 Gemini 無法使用時，使用本地端關鍵字排序
def local_relevance_fallback(jobs, limit=20):
    ranked = []

    # 遍歷所有職缺
    for job in jobs:

        # 取得原始關鍵字分數
        keyword_score = job.get("keyword_score", 0)

        # 將 keyword_score 轉換成 match_score
        match_score = min(100, max(30, keyword_score * 5))

        # 複製原始職缺資料
        new_job = job.copy()

        # 加入配對分析結果
        new_job["match_score"] = match_score

        # 說明為何使用 fallback
        new_job["gemini_reason"] = (
            "Gemini ranking failed. "
            "This result is ranked by keyword relevance only."
        )

        # 配對原因
        new_job["fit_points"] = (
            "Matched by job title, location, "
            "salary text, or keyword similarity."
        )

        # 缺點或不確定性
        new_job["concerns"] = (
            "The relevance was not deeply evaluated by Gemini."
        )

        ranked.append(new_job)

    # 依 match_score 由大到小排序
    ranked.sort(
        key=lambda x: x.get("match_score", 0),
        reverse=True
    )

    # 回傳前 limit 筆
    return ranked[:limit]


# 使用 Gemini AI 對職缺進行排序與推薦
def rank_jobs_with_gemini(client, raw_resume, raw_jobs):

    # 若沒有職缺直接回傳空列表
    if not raw_jobs:
        return []

    # 若 Gemini client 不存在，改用 fallback
    if client is None:
        return local_relevance_fallback(
            raw_jobs,
            OUTPUT_RECOMMEND_LIMIT
        )

    # 將職缺整理成 Gemini 專用格式
    compact_jobs = [
        compact_job_for_gemini(job, i + 1)
        for i, job in enumerate(raw_jobs)
    ]

    # 建立 Prompt 給 Gemini
    prompt = f"""
You are an expert job matching assistant.

Evaluate the relevance between the candidate's resume profile
and the fetched job postings.

Candidate profile:
{json.dumps(raw_resume, ensure_ascii=False, indent=2)}

Fetched job postings:
{json.dumps(compact_jobs, ensure_ascii=False, indent=2)}

Rules:
1. Give each selected job a match_score from 0 to 100.
2. Consider target position, location, salary, specialty,
   skills, education, certificates, competitions, and experience.
3. Penalize unrelated jobs.
4. If salary is not clearly shown, do not reject it automatically,
   but mention the uncertainty.
5. Return at most {OUTPUT_RECOMMEND_LIMIT} jobs.
6. Prefer match_score >= {MATCH_SCORE_THRESHOLD}.
7. Do not invent job titles, companies, salaries, or URLs.

Return ONLY valid JSON.

JSON format:
{{
  "recommendations": [
    {{
      "job_index": 1,
      "match_score": 85,
      "reason": "why this job matches the candidate",
      "fit_points": "specific matching points",
      "concerns": "salary uncertainty or experience gap"
    }}
  ]
}}
"""

    # 呼叫 Gemini API
    text = gemini_generate_with_retry(
        client=client,
        prompt=prompt,
        response_json=True,
        max_retries=3,
        temperature=0.2,
    )

    # 若 Gemini 無回應
    if not text:
        return local_relevance_fallback(
            raw_jobs,
            OUTPUT_RECOMMEND_LIMIT
        )

    try:
        # 將 Gemini 回傳文字轉成 JSON
        data = extract_json_from_text(text)

        # 取得 recommendations 陣列
        recs = data.get("recommendations", [])

        ranked_jobs = []

        # 處理每一筆推薦
        for rec in recs:

            try:
                job_index = int(rec.get("job_index", 0))
                match_score = int(rec.get("match_score", 0))

            except Exception:
                continue

            # 防止 index 超出範圍
            if job_index < 1 or job_index > len(raw_jobs):
                continue

            # 過濾低於門檻的職缺
            if match_score < MATCH_SCORE_THRESHOLD:
                continue

            # 取得原始職缺資料
            job = raw_jobs[job_index - 1].copy()

            # 加入 Gemini 分析資訊
            job["match_score"] = match_score

            job["gemini_reason"] = clean_text(
                rec.get("reason", "")
            )

            job["fit_points"] = clean_text(
                rec.get("fit_points", "")
            )

            job["concerns"] = clean_text(
                rec.get("concerns", "")
            )

            ranked_jobs.append(job)

        # 依 match_score + keyword_score 排序
        ranked_jobs.sort(
            key=lambda x: (
                x.get("match_score", 0),
                x.get("keyword_score", 0)
            ),
            reverse=True,
        )

        # 若 Gemini 無有效結果
        if not ranked_jobs:
            return local_relevance_fallback(
                raw_jobs,
                OUTPUT_RECOMMEND_LIMIT
            )

        return ranked_jobs[:OUTPUT_RECOMMEND_LIMIT]

    except Exception as e:

        # JSON 解析失敗時 fallback
        print("Gemini ranking parse failed. Using local fallback.")
        print("Error:", e)

        return local_relevance_fallback(
            raw_jobs,
            OUTPUT_RECOMMEND_LIMIT
        )

# ============================================================
# PDF Styles and Components
# ============================================================

# 建立整份 PDF 使用的樣式（字型、顏色、大小等）
def make_styles():

    # 定義常用顏色
    navy = colors.HexColor("#1F3A5F")   # 深藍色
    teal = colors.HexColor("#2E7D7B")   # 青綠色
    dark = colors.HexColor("#263238")   # 深灰色
    gray = colors.HexColor("#546E7A")   # 淺灰藍色

    # 回傳所有 ParagraphStyle
    return {

        # =========================
        # 姓名字體樣式
        # =========================
        "name": ParagraphStyle(
            name="Name",
            fontName=PDF_BOLD,     # 粗體字型
            fontSize=22,           # 字體大小
            leading=28,            # 行距
            textColor=navy,        # 字體顏色
            alignment=TA_CENTER,   # 置中
            spaceAfter=4,          # 下方間距
        ),

        # =========================
        # 履歷標題 / Headline
        # =========================
        "headline": ParagraphStyle(
            name="Headline",
            fontName=PDF_FONT,
            fontSize=10.5,
            leading=14,
            textColor=teal,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),

        # =========================
        # 區塊標題樣式
        # =========================
        "section": ParagraphStyle(
            name="Section",
            fontName=PDF_BOLD,
            fontSize=12.5,
            leading=16,
            textColor=navy,
            spaceBefore=8,
            spaceAfter=5,
        ),

        # =========================
        # 內文樣式
        # =========================
        "body": ParagraphStyle(
            name="Body",
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=dark,
            spaceAfter=5,
        ),

        # =========================
        # 粗體內文樣式
        # =========================
        "body_bold": ParagraphStyle(
            name="BodyBold",
            fontName=PDF_BOLD,
            fontSize=9,
            leading=13,
            textColor=dark,
            spaceAfter=4,
        ),

        # =========================
        # 小字樣式
        # =========================
        "small": ParagraphStyle(
            name="Small",
            fontName=PDF_FONT,
            fontSize=8.2,
            leading=11,
            textColor=gray,
            spaceAfter=3,
        ),

        # =========================
        # 標籤樣式（例如 Email / Phone）
        # =========================
        "label": ParagraphStyle(
            name="Label",
            fontName=PDF_BOLD,
            fontSize=8.2,
            leading=11,
            textColor=navy,
            spaceAfter=3,
        ),

        # =========================
        # 條列式樣式
        # =========================
        "bullet": ParagraphStyle(
            name="Bullet",
            fontName=PDF_FONT,
            fontSize=8.8,
            leading=12,
            leftIndent=9,          # 左縮排
            firstLineIndent=-6,    # 第一行縮排
            textColor=dark,
            spaceAfter=2,
        ),
    }


# ============================================================
# 建立 Paragraph（段落）
# ============================================================

def para(text, style):

    # escape_text 避免特殊字元破壞 PDF
    return Paragraph(
        escape_text(text),
        style
    )


# ============================================================
# 區塊標題（有背景色）
# ============================================================

def section_title(title, styles):

    # 建立一個單列表格當作標題背景
    table = Table(
        [[Paragraph(
            escape_text(title),
            styles["section"]
        )]],
        colWidths=[170 * mm],
    )

    # 設定標題表格樣式
    table.setStyle(TableStyle([

        # 背景顏色
        ("BACKGROUND",
         (0, 0), (-1, -1),
         colors.HexColor("#E8F1F5")),

        # 外框線
        ("BOX",
         (0, 0), (-1, -1),
         0.5,
         colors.HexColor("#A7C7D9")),

        # 左右上下 padding
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    return table


# ============================================================
# 建立資訊表格（聯絡資訊 / 求職條件）
# ============================================================

def info_table(
    rows,
    styles,
    label_width=45 * mm,
    value_width=125 * mm,
    bg="#F4F7F6",
    border="#C5D6D4"
):

    data = []

    # 將資料轉成兩欄格式
    for label, value in rows:

        data.append([
            Paragraph(
                escape_text(label),
                styles["label"]
            ),

            Paragraph(
                escape_text(value),
                styles["small"]
            ),
        ])

    # 建立表格
    table = Table(
        data,
        colWidths=[label_width, value_width]
    )

    # 設定表格樣式
    table.setStyle(TableStyle([

        # 背景色
        ("BACKGROUND",
         (0, 0), (-1, -1),
         colors.HexColor(bg)),

        # 外框
        ("BOX",
         (0, 0), (-1, -1),
         0.5,
         colors.HexColor(border)),

        # 內框線
        ("INNERGRID",
         (0, 0), (-1, -1),
         0.3,
         colors.HexColor("#DDE7E5")),

        # padding
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),

        # 內容靠上
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    return table


# ============================================================
# 條列清單
# ============================================================

def bullet_list(items, styles):

    story = []

    # 若沒有資料則顯示 None
    if not items:
        items = ["None"]

    # 建立每一項 bullet
    for item in items:

        story.append(
            Paragraph(
                f"- {escape_text(item)}",
                styles["bullet"]
            )
        )

    return story


# ============================================================
# 技能 chip 樣式表格
# ============================================================

def chip_table(items, styles, max_cols=3):

    # 清理空值
    clean_items = [
        safe_text(x)
        for x in items
        if safe_text(x)
    ]

    # 若沒有資料
    if not clean_items:
        clean_items = ["None"]

    rows = []
    row = []

    # 每 max_cols 個換一列
    for item in clean_items:

        row.append(
            Paragraph(
                escape_text(item),
                styles["small"]
            )
        )

        # 換行
        if len(row) == max_cols:
            rows.append(row)
            row = []

    # 最後不足 max_cols 補空白
    if row:

        while len(row) < max_cols:
            row.append("")

        rows.append(row)

    # 建立表格
    table = Table(
        rows,
        colWidths=[52 * mm] * max_cols
    )

    # 設定 chip 樣式
    table.setStyle(TableStyle([

        ("BACKGROUND",
         (0, 0), (-1, -1),
         colors.HexColor("#E8F0E6")),

        ("BOX",
         (0, 0), (-1, -1),
         0.3,
         colors.HexColor("#B7C9A7")),

        ("INNERGRID",
         (0, 0), (-1, -1),
         0.3,
         colors.white),

        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),

        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    return table


# ============================================================
# 頁面背景（頁首與頁尾）
# ============================================================

def draw_page_background(canvas_obj, doc):

    canvas_obj.saveState()

    width, height = A4

    # 頁首藍色區塊
    canvas_obj.setFillColor(colors.HexColor("#1F3A5F"))

    canvas_obj.rect(
        0,
        height - 20 * mm,
        width,
        20 * mm,
        fill=1,
        stroke=0
    )

    # 頁尾綠色區塊
    canvas_obj.setFillColor(colors.HexColor("#5E7C3A"))

    canvas_obj.rect(
        0,
        0,
        width,
        6 * mm,
        fill=1,
        stroke=0
    )

    # 頁碼
    canvas_obj.setFont(PDF_FONT, 8)

    canvas_obj.setFillColor(colors.white)

    canvas_obj.drawRightString(
        width - 14 * mm,
        height - 9 * mm,
        f"Page {doc.page}"
    )

    canvas_obj.restoreState()

# ============================================================
# 建立完整履歷 PDF
# ============================================================

def create_resume_pdf(content, output_path=OUTPUT_PDF):

    # 建立所有樣式
    styles = make_styles()

    # 建立 PDF 文件
    doc = SimpleDocTemplate(

        # 輸出檔案名稱
        output_path,

        # A4 尺寸
        pagesize=A4,

        # 邊界設定
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=26 * mm,
        bottomMargin=14 * mm,
    )

    # story 用來存放 PDF 元件
    story = []

    # ============================================================
    # Header 區塊（姓名 + 標題）
    # ============================================================

    header = Table(

        [
            # 第一列：姓名
            [
                Paragraph(
                    escape_text(content.get("name", "")),
                    styles["name"]
                )
            ],

            # 第二列：個人標題 / headline
            [
                Paragraph(
                    escape_text(content.get("headline", "")),
                    styles["headline"]
                )
            ],
        ],

        # 表格寬度
        colWidths=[176 * mm],
    )

    # Header 樣式設定
    header.setStyle(TableStyle([

        # 白色背景
        ("BACKGROUND",
         (0, 0), (-1, -1),
         colors.white),

        # 外框線
        ("BOX",
         (0, 0), (-1, -1),
         0.7,
         colors.HexColor("#D2DFE5")),

        # padding
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    # 加入 story
    story.append(header)

    # 加入空白間距
    story.append(Spacer(1, 8))

    # ============================================================
    # 聯絡資訊區塊
    # ============================================================

    # 取得聯絡資料
    contact = content.get("contact", {})

    # 取得工作偏好資料
    prefs = content.get("job_preferences", {})

    # 建立聯絡資訊表格
    story.append(info_table(

        [
            ("Address", contact.get("address", "")),
            ("Email", contact.get("email", "")),
            ("Phone", contact.get("phone", "")),
        ],

        styles,

        # label 欄寬
        label_width=30 * mm,

        # value 欄寬
        value_width=140 * mm
    ))

    story.append(Spacer(1, 8))

    # ============================================================
    # 求職條件區塊
    # ============================================================

    story.append(info_table(

        [
            (
                "Target Position",
                prefs.get("target_position", "")
            ),

            (
                "Preferred Location",
                prefs.get("target_location", "")
            ),

            (
                "Expected Monthly Salary",
                prefs.get("expected_monthly_salary", "")
            ),
        ],

        styles,

        # 欄寬設定
        label_width=50 * mm,
        value_width=120 * mm,

        # 表格背景色
        bg="#FFF8E6",

        # 外框顏色
        border="#D8B45A"
    ))

    story.append(Spacer(1, 10))

    # ============================================================
    # 個人簡介區塊
    # ============================================================

    # 區塊標題
    story.append(
        section_title(
            "Profile Summary",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 個人介紹內容
    story.append(
        para(
            content.get("profile_summary", ""),
            styles["body"]
        )
    )

    story.append(Spacer(1, 8))

    # ============================================================
    # 技能與專長區塊
    # ============================================================

    story.append(
        section_title(
            "Skills & Specialty",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 專長主題
    story.append(
        Paragraph(

            f"Specialty: "
            f"{escape_text(content.get('specialty', ''))}",

            styles["body_bold"]
        )
    )

    # 技能 chip 表格
    story.append(
        chip_table(
            content.get("skills", []),
            styles,
            max_cols=3
        )
    )

    story.append(Spacer(1, 8))

    # ============================================================
    # 學歷區塊
    # ============================================================

    story.append(
        section_title(
            "Education",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 遍歷所有學歷
    for edu in content.get("education", []):

        # 學校名稱
        story.append(
            Paragraph(
                escape_text(edu.get("school", "")),
                styles["body_bold"]
            )
        )

        # 主修科系
        story.append(
            Paragraph(

                f"Major: "
                f"{escape_text(edu.get('major', ''))}",

                styles["small"]
            )
        )

        # 學歷描述
        story.append(
            Paragraph(
                escape_text(
                    edu.get("description", "")
                ),
                styles["small"]
            )
        )

        story.append(Spacer(1, 4))

    story.append(Spacer(1, 5))

    # ============================================================
    # 證照區塊
    # ============================================================

    story.append(
        section_title(
            "Certificates",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 條列式證照
    story.extend(
        bullet_list(
            content.get("certificates", []),
            styles
        )
    )

    story.append(Spacer(1, 8))

    # ============================================================
    # 比賽經歷區塊
    # ============================================================

    story.append(
        section_title(
            "Competitions",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 條列式比賽
    story.extend(
        bullet_list(
            content.get("competitions", []),
            styles
        )
    )

    story.append(Spacer(1, 8))

    # ============================================================
    # 工作經驗區塊
    # ============================================================

    story.append(
        section_title(
            "Experience",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 遍歷工作經驗
    for exp in content.get("experience", []):

        # 職位名稱
        story.append(
            Paragraph(
                escape_text(
                    exp.get("title", "Experience")
                ),
                styles["body_bold"]
            )
        )

        # 工作描述
        story.append(
            Paragraph(
                escape_text(
                    exp.get("description", "")
                ),
                styles["small"]
            )
        )

        story.append(Spacer(1, 4))

    story.append(Spacer(1, 5))

    # ============================================================
    # 優勢區塊
    # ============================================================

    story.append(
        section_title(
            "Strengths",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 條列式優勢
    story.extend(
        bullet_list(
            content.get("strengths", []),
            styles
        )
    )

    story.append(Spacer(1, 8))

    # ============================================================
    # 職涯目標區塊
    # ============================================================

    story.append(
        section_title(
            "Career Objective",
            styles
        )
    )

    story.append(Spacer(1, 5))

    # 職涯目標內容
    story.append(
        para(
            content.get("career_objective", ""),
            styles["body"]
        )
    )

    # ============================================================
    # 建立 PDF
    # ============================================================

    doc.build(

        # PDF 內容
        story,

        # 第一頁背景
        onFirstPage=draw_page_background,

        # 後續頁背景
        onLaterPages=draw_page_background,
    )

    # 回傳輸出路徑
    return output_path


# Output Files
# ============================================================
# 這一區主要負責「把程式產生的結果寫成檔案」。
# 程式會把履歷內容、職缺推薦結果、搜尋條件、推薦分數等資料
# 分別輸出成 txt、json 或 pdf，方便使用者之後查看。

# 這個函式負責把 Gemini 產生好的履歷內容寫入文字檔。
# content 是履歷資料，通常會是字典或 JSON 類型的資料。
# output_path 是輸出檔案的位置，預設使用 OUTPUT_TXT。
def write_resume_txt(content, output_path=OUTPUT_TXT):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("========== RESUME CONTENT ==========\n\n")
        f.write(json.dumps(content, ensure_ascii=False, indent=2))


# 這個函式負責把職缺推薦結果寫入文字檔。
# raw_resume 是使用者輸入的原始履歷與求職條件。
# raw_jobs 是程式抓到的原始職缺清單。
# recommended_jobs 是經過 Gemini 或關鍵字評分後篩選出的推薦職缺。
# output_path 是輸出檔案的位置，預設使用 JOBS_TXT。
def write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, output_path=JOBS_TXT):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("========== JOB RECOMMENDATIONS ==========\n\n")

        # 寫入使用者一開始設定的求職條件。
        # 包含目標職位、偏好地點、期望薪資。
        f.write("Search Conditions\n")
        f.write("----------------------------------------\n")
        f.write(f"Target Position: {raw_resume['target_position']}\n")
        f.write(f"Preferred Location: {raw_resume['target_location']}\n")
        f.write(f"Expected Monthly Salary: {raw_resume['expected_monthly_salary']}\n\n")

        # 將使用者輸入的期望薪資轉成整數。
        # 如果轉換失敗，就使用 0 作為預設值，避免程式中斷。
        salary_min = safe_int(raw_resume["expected_monthly_salary"], 0)

        # 產生 104 和 1111 人力銀行的搜尋連結。
        # 使用者可以直接開啟這些連結查看相關職缺。
        f.write("Direct Search Links\n")
        f.write("----------------------------------------\n")
        f.write(build_104_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n")
        f.write(build_1111_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n\n")

        # 寫入整體處理摘要。
        # 包含抓到多少職缺、最後推薦多少職缺、推薦上限與分數門檻。
        f.write("Process Summary\n")
        f.write("----------------------------------------\n")
        f.write(f"Fetched job postings: {len(raw_jobs)}\n")
        f.write(f"Recommended jobs: {len(recommended_jobs)}\n")
        f.write(f"Recommendation limit: {OUTPUT_RECOMMEND_LIMIT}\n")
        f.write(f"Match score threshold: {MATCH_SCORE_THRESHOLD}\n\n")

        # 準備寫入推薦職缺的詳細內容。
        f.write("Matched Job Results\n")
        f.write("----------------------------------------\n\n")

        # 如果沒有任何推薦職缺，就寫入提示文字並結束函式。
        if not recommended_jobs:
            f.write("No recommended jobs were selected.\n")
            return

        # 逐筆寫入推薦職缺資料。
        # enumerate(..., start=1) 可以讓職缺編號從 1 開始。
        for idx, job in enumerate(recommended_jobs, start=1):
            f.write(f"{idx}. {job.get('title', 'No title')}\n")
            f.write(f"Platform: {job.get('platform', 'Not clearly shown')}\n")
            f.write(f"Company: {job.get('company', 'Not clearly shown')}\n")
            f.write(f"Location: {job.get('location', 'Not clearly shown')}\n")
            f.write(f"Salary: {job.get('salary', 'Not clearly shown')}\n")
            f.write(f"Salary Check: {job.get('salary_status', 'Not clearly shown')}\n")
            f.write(f"Gemini Match Score: {job.get('match_score', 'Not ranked')}\n")
            f.write(f"Keyword Score: {job.get('keyword_score', 0)}\n")
            f.write(f"Source Method: {job.get('source', 'Unknown')}\n")

            # 如果 Gemini 有提供推薦原因，就寫入檔案。
            if job.get("gemini_reason"):
                f.write(f"Gemini Reason: {job.get('gemini_reason')}\n")

            # 如果職缺有符合使用者的優點，就寫入檔案。
            if job.get("fit_points"):
                f.write(f"Fit Points: {job.get('fit_points')}\n")

            # 如果職缺有需要注意的地方，也寫入檔案。
            if job.get("concerns"):
                f.write(f"Concerns: {job.get('concerns')}\n")

            # 如果有職缺摘要內容，就寫入檔案。
            if job.get("snippet"):
                f.write(f"Snippet: {job.get('snippet')}\n")

            # 寫入職缺連結，並用分隔線區分每一筆職缺。
            f.write(f"URL: {job.get('url', '')}\n")
            f.write("-" * 70 + "\n\n")


# ============================================================
# Main Program
# ============================================================
# 這一區是主程式。
# 程式會從這裡開始執行，依序完成以下事情：
# 1. 讓使用者輸入求職條件與履歷資料。
# 2. 連接 Gemini API。
# 3. 產生優化後的履歷內容。
# 4. 抓取職缺資料。
# 5. 根據履歷與求職條件推薦職缺。
# 6. 輸出 JSON、TXT 和 PDF 檔案。

def main():
    # 顯示程式標題。
    print("========== AI Resume PDF + Job Recommendation Generator ==========\n")

    # 顯示求職目標輸入區塊。
    print("========== Job Target ==========\n")

    # 讓使用者輸入目標職位、工作地點與期望月薪。
    target_position = input("Target Position, for example Software Engineer / 軟體工程師: ").strip()
    target_location = input("Preferred Work Location, for example Taipei / 台北: ").strip()
    expected_monthly_salary = input("Expected Monthly Salary, for example 90000: ").strip()

    # 顯示履歷資料輸入區塊。
    print("\n========== Resume Information ==========\n")

    # 讓使用者輸入基本個人資料。
    name = input("Name: ").strip()
    specialty = input("Specialty: ").strip()

    # 讓使用者輸入聯絡資訊。
    address = input("Address: ").strip()
    email = input("Email: ").strip()
    phone = input("Phone: ").strip()

    # 讓使用者輸入證照與競賽經驗。
    certificates = input("Certificates, separated by commas. Leave blank if none: ").strip()
    competitions = input("Competitions, separated by commas. Leave blank if none: ").strip()

    # 讓使用者輸入學歷資料。
    school = input("School: ").strip()
    major = input("Major: ").strip()

    # 讓使用者輸入技能與工作經驗。
    skills = input("Skills, separated by commas. Example: Python, Excel, Finance: ").strip()
    experience = input("Work / Internship Experience. Leave blank if none: ").strip()

    # 將使用者輸入的所有資料整理成一個字典。
    # 後續產生履歷、搜尋職缺、職缺推薦都會使用這份資料。
    raw_resume = {
        "target_position": target_position,
        "target_location": target_location,
        "expected_monthly_salary": expected_monthly_salary,
        "name": name,
        "specialty": specialty,
        "address": address,
        "email": email,
        "phone": phone,
        "certificates": certificates,
        "competitions": competitions,
        "school": school,
        "major": major,
        "skills": skills,
        "experience": experience,
    }

    # 建立 Gemini API 用戶端，準備呼叫 AI 模型。
    print("\nConnecting to Gemini API...")
    client = make_gemini_client()

    # 使用 Gemini 將使用者輸入的履歷資料整理成更正式的履歷內容。
    print("Generating polished resume content...")
    resume_content = generate_resume_content_with_gemini(client, raw_resume)

    # 根據目標職位、地點與薪資條件抓取職缺。
    print("Fetching job postings...")
    salary_min = safe_int(expected_monthly_salary, 0)
    raw_jobs = get_raw_jobs(target_position, target_location, salary_min)

    # 顯示抓到的職缺數量。
    print(f"Fetched {len(raw_jobs)} jobs.")

    # 使用 Gemini 根據履歷內容排序職缺適合度。
    print("Ranking jobs by resume relevance...")
    recommended_jobs = rank_jobs_with_gemini(client, raw_resume, raw_jobs)

    # 顯示最後推薦的職缺數量。
    print(f"Recommended {len(recommended_jobs)} jobs.")

    # 開始輸出所有結果檔案。
    print("Writing output files...")

    # 將 Gemini 產生的履歷內容存成 JSON 檔。
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resume_content, f, ensure_ascii=False, indent=2)

    # 將抓到的原始職缺資料存成 JSON 檔。
    with open(RAW_JOBS_JSON, "w", encoding="utf-8") as f:
        json.dump(raw_jobs, f, ensure_ascii=False, indent=2)

    # 將履歷內容寫入文字檔。
    write_resume_txt(resume_content, OUTPUT_TXT)

    # 將職缺推薦結果寫入文字檔。
    write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, JOBS_TXT)

    # 將履歷內容製作成 PDF。
    print("Creating resume PDF...")
    pdf_path = create_resume_pdf(resume_content, OUTPUT_PDF)

    # 顯示程式完成訊息與所有輸出檔案位置。
    print("\nDone.")
    print("Files saved to:")
    print(OUTPUT_JSON)
    print(OUTPUT_TXT)
    print(JOBS_TXT)
    print(RAW_JOBS_JSON)
    print(pdf_path)


# 這個判斷式表示：
# 如果這個 Python 檔案是被直接執行，就會呼叫 main()。
# 如果這個檔案是被其他 Python 檔案 import，就不會自動執行 main()。
if __name__ == "__main__":
    main()