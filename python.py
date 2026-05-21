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
