# 這份檔案是在原本程式碼後方加入 # 註解的版本，程式邏輯未刻意更動。
# 註解主要說明每段程式的用途，方便閱讀、報告或交作業時理解。

import os  # 匯入 os，用來處理檔案路徑與環境變數
import re  # 匯入 re，用來做正規表示式搜尋與清理文字
import json  # 匯入 json，用來讀寫 JSON 資料
import html  # 匯入 html，用來轉義文字避免 PDF 顯示錯誤
import time  # 匯入 time，用來控制等待與重試間隔
import random  # 匯入 random，用來產生重試等待時間的隨機差
import requests  # 匯入 requests，用來向網站或 API 發送請求
from bs4 import BeautifulSoup  # 匯入 BeautifulSoup，用來解析 HTML 網頁內容
from urllib.parse import quote, urlparse, parse_qs, unquote  # 匯入網址工具，用來編碼關鍵字與解析連結

from reportlab.lib import colors  # 匯入 ReportLab 顏色工具，製作 PDF 樣式
from reportlab.lib.pagesizes import A4  # 匯入 A4 紙張大小設定
from reportlab.lib.styles import ParagraphStyle  # 匯入段落樣式設定工具
from reportlab.lib.units import mm  # 匯入毫米單位，方便設定 PDF 邊距與寬度
from reportlab.lib.enums import TA_CENTER  # 匯入置中對齊設定
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.pdfbase import pdfmetrics  # 匯入 PDF 字型註冊工具
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # 匯入支援 Unicode 的中文字型

try:
    from google import genai  # 匯入 Gemini API 主套件
    from google.genai import types  # 匯入 Gemini API 的設定型別
    GEMINI_INSTALLED = True  # 確認 Gemini 套件已成功安裝
except ImportError:
    GEMINI_INSTALLED = False  # 如果 Gemini 套件不存在，就改用本機備援模式


# ============================================================
# Basic Settings
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 取得目前程式所在資料夾

OUTPUT_PDF = os.path.join(BASE_DIR, "ai_resume.pdf")  # 設定履歷 PDF 輸出檔名
OUTPUT_TXT = os.path.join(BASE_DIR, "resume_content.txt")  # 設定履歷文字檔輸出檔名
OUTPUT_JSON = os.path.join(BASE_DIR, "resume_ai_content.json")  # 設定 AI 產生履歷內容的 JSON 檔名
JOBS_TXT = os.path.join(BASE_DIR, "job_recommendations.txt")  # 設定職缺推薦結果文字檔名
RAW_JOBS_JSON = os.path.join(BASE_DIR, "raw_jobs_fetched.json")  # 設定原始職缺資料 JSON 檔名

PDF_FONT = "HeiseiMin-W3"  # 設定 PDF 一般文字字型
PDF_BOLD = "HeiseiKakuGo-W5"  # 設定 PDF 粗體文字字型

pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))  # 註冊 PDF 一般字型
pdfmetrics.registerFont(UnicodeCIDFont(PDF_BOLD))  # 註冊 PDF 粗體字型

GEMINI_FALLBACK_MODELS = [  # 設定 Gemini 模型清單，失敗時會依序嘗試下一個模型
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

TOTAL_JOBS_TO_FETCH = 50  # 設定最後最多保留的職缺數量
FETCH_PER_PLATFORM = 50  # 設定每個求職平台最多抓取的職缺數量
OUTPUT_RECOMMEND_LIMIT = 20  # 設定最後輸出的推薦職缺上限
MATCH_SCORE_THRESHOLD = 60  # 設定 Gemini 推薦分數門檻

BENEFIT_KEYWORDS = {  # 建立福利分類與關鍵字，用來比對職缺福利
    "育兒津貼": ["育兒津貼", "托育補助", "生育補助", "育嬰", "childcare"],
    "交通津貼": ["交通津貼", "交通補助", "通勤補助", "車資補助", "停車補助"],
    "伙食津貼/供餐": ["伙食津貼", "供餐", "餐費補助", "免費午餐", "員工餐廳", "膳食"],
    "員工認股權": ["員工認股", "認股權", "股票選擇權", "員工持股", "分紅配股"],
    "年終獎金": ["年終獎金", "年終", "績效獎金", "分紅", "獎金"],
    "員工旅遊": ["員工旅遊", "國內旅遊", "國外旅遊", "旅遊補助", "年度旅遊"],
    "員工保險": ["勞保", "健保", "團保", "壽險", "醫療險", "意外險", "員工保險"],
    "三節禮金": ["三節禮金", "端午", "中秋", "春節", "節金", "禮金"],
    "教育訓練及外部課程": ["教育訓練", "外部課程", "內部訓練", "培訓", "課程補助"],
    "進修補助": ["進修補助", "學習補助", "證照補助", "學費補助", "進修"],
    "其他福利": ["其他福利", "福利制度"],
}

BENEFIT_CATEGORIES = list(BENEFIT_KEYWORDS.keys())  # 把福利分類名稱整理成清單，方便逐項詢問使用者


# ============================================================
# Utility Functions
# ============================================================

def safe_text(value):  # 將輸入值安全轉成乾淨字串
    if value is None:
        return ""  # 沒有內容時回傳空字串
    return str(value).strip()  # 轉成字串並去除前後空白


def escape_text(value):  # 轉義文字，避免特殊符號影響 PDF 或 HTML 顯示
    return html.escape(safe_text(value))


def split_comma_text(text):  # 把逗號、頓號或換行分隔的文字切成清單
    text = safe_text(text)
    if not text:
        return []
    parts = re.split(r"[,，、\n]+", text)  # 用多種分隔符號切割文字
    return [p.strip() for p in parts if p.strip()]  # 回傳去除空白後的有效項目


def clean_text(text):  # 清除 HTML 標籤與多餘空白
    if text is None:
        return ""  # 沒有內容時回傳空字串
    text = BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)  # 把 HTML 轉成純文字
    text = re.sub(r"\s+", " ", text)  # 把連續空白壓成單一空白
    return text.strip()


def safe_int(value, default=0):  # 安全地把文字轉成整數，失敗時回傳預設值
    try:
        cleaned = re.sub(r"[^\d]", "", str(value))  # 移除非數字字元
        return int(cleaned) if cleaned else default  # 轉成整數後回傳
    except Exception:
        return default


def input_positive_salary(prompt):  # 要求使用者輸入正數薪資
    while True:
        value = input(prompt).strip()  # 讀取使用者輸入並去除空白
        amount = safe_int(value, 0)  # 把薪資輸入轉成數字

        if amount > 0:  # 確認薪資必須大於 0
            return str(amount), amount

        print("Salary amount must be a positive number. Please enter again.")  # 提示使用者薪資必須為正數


def input_salary_range():  # 要求使用者輸入最低與最高期望薪資
    while True:
        salary_min_text, salary_min = input_positive_salary(
            "Minimum Expected Monthly Salary, for example 40000: "
        )
        salary_max_text, salary_max = input_positive_salary(
            "Maximum Expected Monthly Salary, for example 70000: "
        )

        if salary_max >= salary_min:  # 確認最高薪資不可低於最低薪資
            return salary_min_text, salary_max_text, salary_min, salary_max

        print("Maximum salary must be greater than or equal to minimum salary. Please enter again.")


def input_yes_no(prompt):  # 統一處理 y/n 或中文是否輸入
    while True:
        answer = input(prompt).strip().lower()  # 讀取 yes/no 回答並轉小寫

        if answer in ["y", "yes", "是", "需要", "要"]:
            return True

        if answer in ["n", "no", "否", "不需要", "不要", ""]:
            return False

        print("Please enter y/n.")


def collect_benefit_preferences():  # 蒐集使用者想要的工作福利條件
    print("\n========== Expected Job Benefits ==========\n")
    print("Please answer y/n for each benefit category.\n")

    selected_default_benefits = []  # 存放使用者選擇的預設福利

    for benefit in BENEFIT_CATEGORIES:  # 逐一詢問每個福利分類
        if benefit == "其他福利":  # 其他福利另外用文字輸入處理
            continue

        if input_yes_no(f"Require {benefit}? y/n: "):
            selected_default_benefits.append(benefit)

    other_benefits_text = input(  # 讓使用者自行輸入其他福利需求
        "Other required benefits, separated by commas. Leave blank if none: "
    ).strip()

    other_benefits = split_comma_text(other_benefits_text)  # 把其他福利文字切成清單

    return {
        "selected_default_benefits": selected_default_benefits,
        "other_benefits": other_benefits,
        "required_benefits": selected_default_benefits + other_benefits,
    }


def get_required_benefits(benefit_preferences):  # 從福利偏好資料中取出必須福利清單
    if not isinstance(benefit_preferences, dict):
        return []

    required = benefit_preferences.get("required_benefits", [])  # 取得所有必須福利

    if isinstance(required, str):  # 如果資料是文字，就先切成清單
        required = split_comma_text(required)

    result = []

    for item in required:
        item = safe_text(item)
        if item and item not in result:  # 避免空值與重複福利
            result.append(item)

    return result


def benefits_to_text(benefits):  # 把福利清單轉成方便輸出的文字
    if not benefits:
        return "None"

    cleaned = [safe_text(x) for x in benefits if safe_text(x)]
    return ", ".join(cleaned) if cleaned else "None"


def match_benefits_from_text(text, benefit_preferences):  # 從職缺文字中比對是否包含使用者要求的福利
    full_text = safe_text(text).lower()  # 轉小寫方便關鍵字比對
    required_benefits = get_required_benefits(benefit_preferences)

    matched = []  # 存放已符合的福利
    missing = []  # 存放缺少的福利

    for benefit in required_benefits:
        keywords = BENEFIT_KEYWORDS.get(benefit, [benefit])  # 取得福利對應的關鍵字
        found = False

        for keyword in keywords:
            if keyword.lower() in full_text:  # 檢查職缺文字是否包含福利關鍵字
                found = True
                break

        if found:
            matched.append(benefit)
        else:
            missing.append(benefit)

    return matched, missing


def benefit_match_status(matched, missing):  # 根據已符合與缺少福利產生摘要文字
    if not matched and not missing:
        return "No benefit requirement"

    if missing:
        return f"Matched {len(matched)} benefit(s), missing {len(missing)} benefit(s)"

    return "All required benefits appear to be matched"


def salary_range_status(salary_text, salary_min, salary_max):  # 判斷職缺薪資是否可能符合使用者薪資範圍
    salary_est = estimate_salary_from_text(salary_text)  # 先估算職缺薪資數字

    if salary_min <= 0:
        return "No salary requirement"

    if salary_est is None:  # 薪資無法辨識時回傳不明確
        return "Not clearly shown"

    if salary_max > 0:
        if salary_min <= salary_est <= salary_max:
            return "Possibly meets salary range"

        if salary_est > salary_max:
            return "Higher than preferred salary range"

        return "May be lower than minimum salary"

    if salary_est >= salary_min:
        return "Possibly meets minimum salary"

    return "May be lower than minimum salary"


def apply_user_preferences_to_jobs(jobs, job_title, location, salary_min, salary_max, benefit_preferences):  # 依照使用者條件重新替每個職缺評分並排序
    for job in jobs:
        score_job_keyword(
            job=job,
            job_title=job_title,
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            benefit_preferences=benefit_preferences,
        )

    jobs.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)  # 依分數由高到低排序職缺
    return jobs


def build_104_search_url(job_title, location, salary_min):  # 建立 104 求職搜尋網址
    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()  # 組合搜尋關鍵字
    return f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}"  # 將搜尋關鍵字轉成網址安全格式


def build_1111_search_url(job_title, location, salary_min):  # 建立 1111 求職搜尋網址
    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()  # 組合搜尋關鍵字
    return f"https://www.1111.com.tw/search/job?ks={quote(keyword)}"  # 將搜尋關鍵字轉成網址安全格式


def normalize_url(url, base_domain):  # 把相對網址或缺少 https 的網址轉成完整網址
    if not url:
        return ""  # 沒有內容時回傳空字串

    if url.startswith("//"):  # 處理省略 https 的網址
        return "https:" + url

    if url.startswith("/"):  # 處理相對路徑網址
        return base_domain.rstrip("/") + url

    return url


def normalize_duckduckgo_link(href):  # 還原 DuckDuckGo 轉址後真正的目標連結
    if not href:
        return ""  # 沒有內容時回傳空字串

    if "uddg=" in href:  # 判斷是否為 DuckDuckGo 轉址連結
        parsed = urlparse(href)  # 解析網址內容
        query = parse_qs(parsed.query)  # 取出網址查詢參數
        real_url = query.get("uddg", [""])[0]
        return unquote(real_url)

    return href


def extract_json_from_text(text):  # 從 Gemini 回應文字中擷取 JSON 物件
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)  # 嘗試直接解析 JSON
    except Exception:
        pass

    start = text.find("{")  # 尋找 JSON 起始位置
    end = text.rfind("}")  # 尋找 JSON 結束位置

    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("Could not parse JSON from model output.")  # 無法解析時丟出錯誤


def estimate_salary_from_text(text):  # 從薪資文字中估算可比較的數字薪資
    if not text:
        return None

    values = []  # 存放找到的薪資數字

    nums = re.findall(r"(?<!\d)(\d{2,3}(?:,\d{3})|\d{5,6})(?!\d)", text)  # 找出一般數字格式的薪資
    for n in nums:
        try:
            v = int(n.replace(",", ""))
            if 20000 <= v <= 300000:
                values.append(v)
        except Exception:
            pass

    wan_nums = re.findall(r"(\d+(?:\.\d+)?)\s*萬", text)  # 找出一般數字格式的薪資
    for n in wan_nums:
        try:
            v = int(float(n) * 10000)
            if 20000 <= v <= 300000:
                values.append(v)
        except Exception:
            pass

    k_nums = re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", text)  # 找出一般數字格式的薪資
    for n in k_nums:
        try:
            v = int(float(n) * 1000)
            if 20000 <= v <= 300000:
                values.append(v)
        except Exception:
            pass

    return max(values) if values else None  # 回傳找到的最高薪資作為估計值


def extract_salary_string(text):  # 從職缺文字中擷取薪資描述
    patterns = [  # 列出可能的薪資文字格式
        r"月薪\s*[0-9,萬Kk~～\-以上]+",
        r"年薪\s*[0-9,萬Kk~～\-以上]+",
        r"時薪\s*[0-9,萬Kk~～\-以上]+",
        r"[0-9,]+元\s*[~～\-]\s*[0-9,]+元",
        r"[0-9.]+萬\s*[~～\-]\s*[0-9.]+萬",
        r"待遇面議",
        r"面議",
    ]

    for p in patterns:
        m = re.search(p, text)  # 用正規表示式搜尋薪資格式
        if m:
            return m.group(0)  # 回傳符合的薪資文字

    return "Not clearly shown"


def salary_status(salary_text, salary_min, salary_max=0):  # 包裝薪資檢查函式，回傳薪資狀態
    return salary_range_status(salary_text, salary_min, salary_max)


def score_job_keyword(job, job_title, location, salary_min, salary_max=0, benefit_preferences=None):  # 用職稱、地點、薪資與福利關鍵字替職缺計分
    title = job.get("title", "")  # 取得職缺標題
    company = job.get("company", "")  # 取得公司名稱
    job_location = job.get("location", "")  # 取得職缺地點
    salary = job.get("salary", "")  # 取得薪資描述
    snippet = job.get("snippet", "")  # 取得職缺摘要

    full_text = f"{title} {company} {job_location} {salary} {snippet}".lower()
    score = 0  # 初始化職缺分數

    if job_title.lower() in title.lower():
        score += 8  # 職稱高度符合時加分

    if job_title.lower() in full_text:
        score += 3

    if location.lower() in full_text:
        score += 6  # 地點符合時加分

    tokens = re.split(r"[\s,，/、]+", job_title)  # 把職稱切成關鍵字
    for token in tokens:
        token = token.strip()
        if token and token.lower() in full_text:
            score += 1

    salary_est = estimate_salary_from_text(salary + " " + snippet)  # 先估算職缺薪資數字

    if salary_min > 0 and salary_est is not None:
        if salary_max > 0:
            if salary_min <= salary_est <= salary_max:
                score += 5
            elif salary_est > salary_max:
                score += 3
            else:
                score -= 2
        else:
            if salary_est >= salary_min:
                score += 5
            else:
                score -= 2

    matched_benefits, missing_benefits = match_benefits_from_text(
        full_text,
        benefit_preferences,
    )

    score += len(matched_benefits) * 2  # 符合福利越多分數越高
    score -= len(missing_benefits)  # 缺少福利時扣分

    job["keyword_score"] = score  # 把關鍵字分數存回職缺資料
    job["salary_est"] = salary_est
    job["salary_status"] = salary_status(salary + " " + snippet, salary_min, salary_max)
    job["salary_min_requirement"] = salary_min
    job["salary_max_requirement"] = salary_max
    job["matched_benefits"] = matched_benefits
    job["missing_benefits"] = missing_benefits
    job["benefit_match_status"] = benefit_match_status(matched_benefits, missing_benefits)

    return score


# ============================================================
# Gemini Functions
# ============================================================

def make_gemini_client():  # 建立 Gemini API 客戶端
    if not GEMINI_INSTALLED:
        print("google-genai is not installed. Using local fallback content.")
        return None

    api_key = os.getenv("GEMINI_API_KEY")  # 從環境變數讀取 Gemini API Key

    if not api_key:
        print("GEMINI_API_KEY is not set. Using local fallback content.")
        return None

    try:
        print("GEMINI_API_KEY loaded successfully.")
        return genai.Client(api_key=api_key)  # 建立 Gemini 客戶端
    except Exception as e:
        print("Gemini client failed. Using local fallback content.")
        print("Error:", e)
        return None


def gemini_generate_with_retry(client, prompt, response_json=True, max_retries=3, temperature=0.35):  # 呼叫 Gemini，失敗時自動重試與切換模型
    if client is None:
        return None

    last_error = None  # 記錄最後一次錯誤
    used_models = []  # 記錄已經嘗試過的模型

    for model in GEMINI_FALLBACK_MODELS:  # 依序嘗試可用的 Gemini 模型
        if model in used_models:
            continue

        used_models.append(model)

        for attempt in range(max_retries):  # 同一模型失敗時進行多次重試
            try:
                config_kwargs = {"temperature": temperature}  # 設定 Gemini 生成溫度

                if response_json:
                    config_kwargs["response_mime_type"] = "application/json"

                response = client.models.generate_content(  # 呼叫 Gemini 產生內容
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )

                if response.text and response.text.strip():  # 確認 Gemini 有回傳有效文字
                    return response.text.strip()

                last_error = RuntimeError("Gemini returned empty text.")

            except Exception as e:
                last_error = e
                error_text = str(e)

                retryable = (  # 判斷錯誤是否適合重試
                    "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                    or "high demand" in error_text.lower()
                )

                if retryable:
                    wait_time = 2 + attempt * 3 + random.random()
                    print(f"Gemini is busy or rate-limited. Retry in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)  # 等待一段時間後再重試
                    continue

                print(f"Gemini model {model} failed:", e)
                break

        print("Trying next Gemini model if available...")

    print("Gemini failed after retries. Last error:", last_error)
    return None


# ============================================================
# Resume Content Generation
# ============================================================

def build_fallback_resume_content(raw):  # 當 Gemini 失敗時，用本機邏輯產生基本履歷內容
    skills = split_comma_text(raw["skills"])  # 整理使用者輸入的技能
    certificates = split_comma_text(raw["certificates"])  # 整理證照清單
    competitions = split_comma_text(raw["competitions"])  # 整理競賽清單

    if not skills and raw["specialty"]:
        skills = [raw["specialty"]]

    if not certificates:
        certificates = ["None"]

    if not competitions:
        competitions = ["None"]

    summary = (  # 建立備援履歷自我介紹
        f"My name is {raw['name']}. I am currently studying at {raw['school']}, "
        f"majoring in {raw['major']}. I am interested in applying for "
        f"{raw['target_position']}-related positions in {raw['target_location']}. "
        f"My expected monthly salary is {raw['expected_monthly_salary']}. "
        f"My main specialty is {raw['specialty']}. Through academic learning, "
        "project participation, and practical training, I have developed analytical thinking, "
        "communication ability, teamwork, and a strong willingness to keep learning. "
    )

    if raw["experience"]:
        summary += f"My previous work or internship experience includes {raw['experience']}. "

    summary += (
        "I hope to apply my background and strengths in a real workplace, learn from experienced "
        "professionals, and gradually develop into a reliable and responsible team member."
    )

    return {
        "name": raw["name"],
        "target_position": raw["target_position"],
        "headline": f"{raw['target_position']} Candidate",
        "job_preferences": {
            "target_position": raw["target_position"],
            "target_location": raw["target_location"],
            "expected_monthly_salary": raw["expected_monthly_salary"],
        },
        "contact": {
            "address": raw["address"],
            "email": raw["email"],
            "phone": raw["phone"],
        },
        "profile_summary": summary,
        "specialty": raw["specialty"],
        "skills": skills,
        "education": [
            {
                "school": raw["school"],
                "major": raw["major"],
                "description": "Academic background related to the candidate's professional development.",
            }
        ],
        "certificates": certificates,
        "competitions": competitions,
        "experience": [
            {
                "title": "Work / Internship Experience",
                "description": raw["experience"] if raw["experience"] else "No formal work or internship experience provided.",
            }
        ],
        "strengths": [
            "Willingness to learn",
            "Communication ability",
            "Teamwork",
            "Analytical thinking",
            "Adaptability",
        ],
        "career_objective": (
            f"To apply for {raw['target_position']}-related positions in {raw['target_location']}, "
            f"with an expected monthly salary of {raw['expected_monthly_salary']}, "
            "while gaining practical workplace experience and continuing to improve professional skills."
        ),
    }


def generate_resume_content_with_gemini(client, raw):  # 使用 Gemini 將使用者資料改寫成英文履歷內容
    prompt = f"""
You are a professional resume writing assistant.

The user provided raw resume information. Rewrite and organize it into a polished English resume.

Important rules:
- Return ONLY valid JSON.
- Do not use markdown.
- Do not invent fake experience, fake certificates, fake education, or fake achievements.
- Keep the writing professional and suitable for a student or entry-level candidate.
- If the background does not perfectly match the target position, emphasize transferable skills.
- Make the profile summary around 220 to 320 words.
- Use clear English.
- Keep Chinese names, schools, certificates, or competition names if they are originally Chinese.
- Do not remove target location or expected monthly salary.
- The resume must clearly include target position, preferred work location, and expected monthly salary.

Raw resume information:
{json.dumps(raw, ensure_ascii=False, indent=2)}  # 把資料寫成 JSON 格式

Return JSON in exactly this structure:

{{
  "name": "candidate name",
  "target_position": "target position",
  "headline": "short professional headline",
  "job_preferences": {{
    "target_position": "target position",
    "target_location": "preferred work location",
    "expected_monthly_salary": "expected monthly salary"
  }},
  "contact": {{
    "address": "address",
    "email": "email",
    "phone": "phone"
  }},
  "profile_summary": "long professional self introduction, around 220 to 320 words",
  "specialty": "main specialty",
  "skills": ["skill 1", "skill 2", "skill 3"],
  "education": [
    {{
      "school": "school name",
      "major": "major",
      "description": "brief education description"
    }}
  ],
  "certificates": ["certificate 1", "certificate 2"],
  "competitions": ["competition 1", "competition 2"],
  "experience": [
    {{
      "title": "experience title",
      "description": "experience description"
    }}
  ],
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "career_objective": "career objective"
}}
"""

    text = gemini_generate_with_retry(  # 呼叫 Gemini 產生內容
        client=client,
        prompt=prompt,
        response_json=True,
        max_retries=3,
        temperature=0.35,
    )

    if not text:
        print("Using local fallback resume content.")
        return build_fallback_resume_content(raw)

    try:
        data = extract_json_from_text(text)  # 把 Gemini 回應轉成 JSON

        required_keys = [  # 列出履歷 JSON 必須包含的欄位
            "name",
            "target_position",
            "headline",
            "job_preferences",
            "contact",
            "profile_summary",
            "specialty",
            "skills",
            "education",
            "certificates",
            "competitions",
            "experience",
            "strengths",
            "career_objective",
        ]

        for key in required_keys:
            if key not in data:  # 檢查 Gemini 回傳是否缺少欄位
                raise ValueError(f"Missing key: {key}")  # 無法解析時丟出錯誤

        return data

    except Exception as e:
        print("Gemini JSON parse failed. Using local fallback content.")
        print("Error:", e)
        return build_fallback_resume_content(raw)


# ============================================================
# Job Fetching
# ============================================================

def fetch_104_jobs_direct(job_title, location, salary_min, limit=50):  # 直接從 104 搜尋 API 抓取職缺資料
    jobs = []  # 建立職缺清單
    keyword = f"{job_title} {location}".strip()  # 組合搜尋關鍵字
    api_url = "https://www.104.com.tw/jobs/search/list"  # 設定 104 搜尋 API 網址

    headers = {  # 設定請求標頭，模擬一般瀏覽器
        "User-Agent": "Mozilla/5.0",
        "Referer": build_104_search_url(job_title, location, salary_min),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    page = 1

    while len(jobs) < limit and page <= 10:  # 分頁抓取職缺直到達到上限
        params = {
            "ro": "0",
            "kwop": "7",
            "keyword": keyword,
            "expansionType": "area,spec,com,job,wf,wktm",
            "order": "15",
            "asc": "0",
            "page": str(page),
            "mode": "s",
            "jobsource": "joblist_search",
        }

        try:
            res = requests.get(api_url, headers=headers, params=params, timeout=15)  # 向網站發送 GET 請求
            res.raise_for_status()  # 如果 HTTP 回應失敗就拋出錯誤
            data = res.json()  # 把 104 回應解析成 JSON
            job_list = data.get("data", {}).get("list", [])  # 取得 104 職缺列表

            if not job_list:
                break

            for item in job_list:  # 逐筆整理 104 職缺資料
                if len(jobs) >= limit:
                    break

                title = clean_text(item.get("jobName", ""))  # 清理職缺名稱
                company = clean_text(item.get("custName", ""))  # 清理公司名稱
                job_location = clean_text(
                    item.get("jobAddrNoDesc", "")
                    or item.get("jobAddress", "")
                    or item.get("areaDesc", "")
                )
                salary = clean_text(item.get("salaryDesc", ""))  # 清理薪資文字
                snippet = clean_text(item.get("description", ""))

                link = ""
                raw_link = item.get("link", "")

                if isinstance(raw_link, dict):
                    link = raw_link.get("job", "") or raw_link.get("cust", "")
                elif isinstance(raw_link, str):
                    link = raw_link

                link = normalize_url(link, "https://www.104.com.tw")  # 把 104 連結轉成完整網址

                job = {
                    "platform": "104 Job Bank",
                    "title": title,
                    "company": company if company else "Not clearly shown",
                    "location": job_location if job_location else "Not clearly shown",
                    "salary": salary if salary else "Not clearly shown",
                    "snippet": snippet,
                    "url": link,
                    "source": "104 direct search",
                }

                score_job_keyword(job, job_title, location, salary_min)  # 先用關鍵字替職缺初步評分
                jobs.append(job)

            page += 1
            time.sleep(0.4)  # 短暫等待，避免過度頻繁請求

        except Exception as e:
            print("104 direct fetch failed:", e)
            break

    return jobs


def extract_json_ld_jobs(soup):  # 從網頁 JSON-LD 結構化資料中擷取職缺
    jobs = []  # 建立職缺清單

    def walk(obj):  # 遞迴尋找 JSON-LD 裡的 JobPosting
        found = []

        if isinstance(obj, dict):  # 判斷目前資料是否為字典
            obj_type = obj.get("@type", "")

            if isinstance(obj_type, list):
                is_job = "JobPosting" in obj_type
            else:
                is_job = obj_type == "JobPosting"

            if is_job:
                found.append(obj)

            for value in obj.values():
                found.extend(walk(value))

        elif isinstance(obj, list):  # 判斷目前資料是否為清單
            for item in obj:
                found.extend(walk(item))

        return found

    for script in soup.select('script[type="application/ld+json"]'):  # 逐一檢查網頁中的 JSON-LD 區塊
        try:
            raw = script.get_text(strip=True)
            if not raw:
                continue

            data = json.loads(raw)
            job_objects = walk(data)  # 從 JSON-LD 中找出所有職缺物件

            for j in job_objects:
                title = clean_text(j.get("title", ""))
                url = j.get("url", "") or j.get("sameAs", "")

                company = "Not clearly shown"
                hiring_org = j.get("hiringOrganization", {})  # 取得徵才公司資訊
                if isinstance(hiring_org, dict):
                    company = clean_text(hiring_org.get("name", "")) or "Not clearly shown"

                location_text = "Not clearly shown"
                job_location = j.get("jobLocation", {})  # 取得職缺地點資訊
                if isinstance(job_location, dict):
                    address = job_location.get("address", {})
                    if isinstance(address, dict):
                        location_text = clean_text(
                            " ".join([
                                str(address.get("addressRegion", "")),
                                str(address.get("addressLocality", "")),
                                str(address.get("streetAddress", "")),
                            ])
                        ) or "Not clearly shown"

                salary = "Not clearly shown"
                base_salary = j.get("baseSalary", {})  # 取得結構化薪資資訊
                if isinstance(base_salary, dict):
                    salary = clean_text(json.dumps(base_salary, ensure_ascii=False))  # 把資料寫成 JSON 格式

                if title and url:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location_text,
                        "salary": salary,
                        "snippet": "",
                        "url": normalize_url(url, "https://www.1111.com.tw"),
                    })

        except Exception:
            continue

    return jobs


def guess_company_from_text(text):  # 從文字中猜測公司名稱
    m = re.search(  # 用正規表示式搜尋公司名稱
        r"([\u4e00-\u9fa5A-Za-z0-9（）()股份有限公司]{2,40}(?:股份有限公司|有限公司|公司))",
        text,
    )
    if m:
        return m.group(1)
    return "Not clearly shown"


def fetch_1111_jobs_direct(job_title, location, salary_min, limit=50):  # 直接從 1111 搜尋頁解析職缺資料
    jobs = []  # 建立職缺清單
    url = build_1111_search_url(job_title, location, salary_min)  # 建立 1111 搜尋網址

    headers = {  # 設定請求標頭，模擬一般瀏覽器
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.1111.com.tw/",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    try:
        res = requests.get(url, headers=headers, timeout=15)  # 向網站發送 GET 請求
        res.raise_for_status()  # 如果 HTTP 回應失敗就拋出錯誤
        soup = BeautifulSoup(res.text, "html.parser")  # 把網頁 HTML 轉成可解析物件

        json_ld_jobs = extract_json_ld_jobs(soup)  # 先嘗試從 JSON-LD 取得職缺

        for item in json_ld_jobs:
            if len(jobs) >= limit:
                break

            job = {
                "platform": "1111 Job Bank",
                "title": item.get("title", ""),
                "company": item.get("company", "Not clearly shown"),
                "location": item.get("location", "Not clearly shown"),
                "salary": item.get("salary", "Not clearly shown"),
                "snippet": item.get("snippet", ""),
                "url": item.get("url", ""),
                "source": "1111 JSON-LD",
            }

            score_job_keyword(job, job_title, location, salary_min)  # 先用關鍵字替職缺初步評分
            jobs.append(job)

        seen_urls = set(job["url"] for job in jobs)  # 記錄已加入的職缺連結，避免重複

        for a in soup.find_all("a", href=True):  # 從所有超連結中尋找職缺頁
            if len(jobs) >= limit:
                break

            href = a.get("href", "")
            text = clean_text(a.get_text(" ", strip=True))

            if not text or len(text) < 2:
                continue

            is_job_link = (  # 判斷連結是否像職缺頁
                "/job/" in href.lower()
                or "job-bank/job-description" in href.lower()
                or "job.asp" in href.lower()
            )

            if not is_job_link:
                continue

            full_url = normalize_url(href, "https://www.1111.com.tw")

            if full_url in seen_urls:
                continue

            parent = a.find_parent(["article", "li", "div"])  # 取得連結外層區塊，方便抓更多資訊
            parent_text = clean_text(parent.get_text(" ", strip=True)) if parent else text  # 清理外層區塊文字

            if job_title not in parent_text and job_title not in text:
                continue

            job = {
                "platform": "1111 Job Bank",
                "title": text,
                "company": guess_company_from_text(parent_text),
                "location": location if location in parent_text else "Not clearly shown",
                "salary": extract_salary_string(parent_text),
                "snippet": parent_text[:350],
                "url": full_url,
                "source": "1111 HTML parsing",
            }

            score_job_keyword(job, job_title, location, salary_min)  # 先用關鍵字替職缺初步評分
            jobs.append(job)
            seen_urls.add(full_url)

    except Exception as e:
        print("1111 direct fetch failed:", e)

    return jobs


def search_duckduckgo(keyword, max_results=50):  # 使用 DuckDuckGo 作為備援搜尋
    url = f"https://html.duckduckgo.com/html/?q={quote(keyword)}"  # 將搜尋關鍵字轉成網址安全格式
    headers = {"User-Agent": "Mozilla/5.0"}  # 設定請求標頭，模擬一般瀏覽器
    results = []

    try:
        res = requests.get(url, headers=headers, timeout=15)  # 向網站發送 GET 請求
        res.raise_for_status()  # 如果 HTTP 回應失敗就拋出錯誤
        soup = BeautifulSoup(res.text, "html.parser")  # 把網頁 HTML 轉成可解析物件

        for block in soup.select(".result"):
            title_tag = block.select_one(".result__a") or block.select_one(".result__title a")
            snippet_tag = block.select_one(".result__snippet")

            if not title_tag:
                continue

            title = clean_text(title_tag.get_text(" ", strip=True))
            link = normalize_duckduckgo_link(title_tag.get("href", ""))
            snippet = clean_text(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""

            if title and link:
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet,
                })

            if len(results) >= max_results:
                break

    except Exception as e:
        print("DuckDuckGo fallback failed:", e)

    return results


def fallback_search_platform(platform, domain, job_title, location, salary_min, limit=50):  # 當平台直接抓取失敗時，用搜尋引擎找職缺
    query = f'site:{domain} "{job_title}" "{location}"'  # 建立限定網站的備援搜尋關鍵字
    raw = search_duckduckgo(query, max_results=limit)  # 用 DuckDuckGo 搜尋備援職缺
    jobs = []  # 建立職缺清單

    for item in raw:
        job = {
            "platform": platform,
            "title": item["title"],
            "company": "Not clearly shown",
            "location": location if location in item["title"] + item["snippet"] else "Not clearly shown",
            "salary": extract_salary_string(item["title"] + " " + item["snippet"]),
            "snippet": item["snippet"],
            "url": item["link"],
            "source": "DuckDuckGo fallback",
        }

        score_job_keyword(job, job_title, location, salary_min)  # 先用關鍵字替職缺初步評分
        jobs.append(job)

    return jobs


def get_raw_jobs(job_title, location, salary_min):  # 整合 104 與 1111 的原始職缺資料
    print("Fetching 104 jobs...")
    jobs_104 = fetch_104_jobs_direct(  # 抓取 104 職缺
        job_title=job_title,
        location=location,
        salary_min=salary_min,
        limit=FETCH_PER_PLATFORM,
    )

    if len(jobs_104) < 10:
        print("104 direct results are too few. Using fallback search...")
        jobs_104.extend(  # 把 104 備援搜尋結果加入清單
            fallback_search_platform(
                platform="104 Job Bank",
                domain="104.com.tw",
                job_title=job_title,
                location=location,
                salary_min=salary_min,
                limit=FETCH_PER_PLATFORM,
            )
        )

    print("Fetching 1111 jobs...")
    jobs_1111 = fetch_1111_jobs_direct(  # 抓取 1111 職缺
        job_title=job_title,
        location=location,
        salary_min=salary_min,
        limit=FETCH_PER_PLATFORM,
    )

    if len(jobs_1111) < 10:
        print("1111 direct results are too few. Using fallback search...")
        jobs_1111.extend(  # 把 1111 備援搜尋結果加入清單
            fallback_search_platform(
                platform="1111 Job Bank",
                domain="1111.com.tw",
                job_title=job_title,
                location=location,
                salary_min=salary_min,
                limit=FETCH_PER_PLATFORM,
            )
        )

    unique = []  # 建立去重後的職缺清單
    seen = set()  # 記錄已出現過的職缺識別值

    for job in jobs_104 + jobs_1111:
        url = job.get("url", "")
        key = url if url else f"{job.get('platform')}|{job.get('title')}|{job.get('company')}"

        if key in seen:
            continue

        seen.add(key)
        unique.append(job)

    unique.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)
    return unique[:TOTAL_JOBS_TO_FETCH]


# ============================================================
# Gemini Job Ranking
# ============================================================

def compact_job_for_gemini(job, index):  # 把職缺資料縮短成 Gemini 評分需要的格式
    return {
        "job_index": index,
        "platform": job.get("platform", ""),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "salary": job.get("salary", ""),
        "salary_status": job.get("salary_status", ""),
        "matched_benefits": job.get("matched_benefits", []),
        "missing_benefits": job.get("missing_benefits", []),
        "benefit_match_status": job.get("benefit_match_status", ""),
        "keyword_score": job.get("keyword_score", 0),
        "snippet": job.get("snippet", "")[:300],
        "url": job.get("url", ""),
    }


def local_relevance_fallback(jobs, limit=20):  # 當 Gemini 評分失敗時，用本機關鍵字分數排序
    ranked = []

    for job in jobs:
        keyword_score = job.get("keyword_score", 0)
        match_score = min(100, max(30, keyword_score * 5))

        new_job = job.copy()
        new_job["match_score"] = match_score
        new_job["gemini_reason"] = "Gemini ranking failed. This result is ranked by keyword relevance only."
        new_job["fit_points"] = "Matched by job title, location, salary text, benefit keywords, or keyword similarity."
        new_job["concerns"] = "The relevance was not deeply evaluated by Gemini, so benefit matching is based on keyword text only."

        ranked.append(new_job)

    ranked.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return ranked[:limit]


def rank_jobs_with_gemini(client, raw_resume, raw_jobs):  # 用 Gemini 根據履歷與偏好推薦職缺
    if not raw_jobs:
        return []

    if client is None:
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)

    compact_jobs = [  # 將職缺整理成較短格式給 Gemini 評分
        compact_job_for_gemini(job, i + 1)
        for i, job in enumerate(raw_jobs)
    ]

    prompt = f"""
You are an expert job matching assistant.

Evaluate the relevance between the candidate's resume profile and the fetched job postings.

Candidate profile:
{json.dumps(raw_resume, ensure_ascii=False, indent=2)}  # 把資料寫成 JSON 格式

Fetched job postings:
{json.dumps(compact_jobs, ensure_ascii=False, indent=2)}  # 把資料寫成 JSON 格式

Rules:
1. Give each selected job a match_score from 0 to 100.
2. Consider target position, location, salary range, required benefits, specialty, skills, education, certificates, competitions, and experience.
3. Penalize unrelated jobs.
4. If salary or benefits are not clearly shown, do not reject the job automatically, but mention the uncertainty.
5. Prefer jobs that match more required benefits.
6. Return at most {OUTPUT_RECOMMEND_LIMIT} jobs.
7. Prefer match_score >= {MATCH_SCORE_THRESHOLD}.
8. Do not invent job titles, companies, salaries, benefits, or URLs.

Return ONLY valid JSON.

JSON format:
{{
  "recommendations": [
    {{
      "job_index": 1,
      "match_score": 85,
      "reason": "why this job matches the candidate",
      "fit_points": "specific matching points",
      "concerns": "salary uncertainty, experience gap, or other concerns"
    }}
  ]
}}
"""

    text = gemini_generate_with_retry(  # 呼叫 Gemini 產生內容
        client=client,
        prompt=prompt,
        response_json=True,
        max_retries=3,
        temperature=0.2,
    )

    if not text:
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)

    try:
        data = extract_json_from_text(text)  # 把 Gemini 回應轉成 JSON
        recs = data.get("recommendations", [])  # 取得 Gemini 推薦清單
        ranked_jobs = []  # 建立職缺清單

        for rec in recs:
            try:
                job_index = int(rec.get("job_index", 0))
                match_score = int(rec.get("match_score", 0))  # 取得 Gemini 給的配對分數
            except Exception:
                continue

            if job_index < 1 or job_index > len(raw_jobs):
                continue

            if match_score < MATCH_SCORE_THRESHOLD:  # 低於推薦門檻就略過
                continue

            job = raw_jobs[job_index - 1].copy()
            job["match_score"] = match_score
            job["gemini_reason"] = clean_text(rec.get("reason", ""))
            job["fit_points"] = clean_text(rec.get("fit_points", ""))
            job["concerns"] = clean_text(rec.get("concerns", ""))

            ranked_jobs.append(job)

        ranked_jobs.sort(  # 依配對分數排序推薦職缺
            key=lambda x: (x.get("match_score", 0), x.get("keyword_score", 0)),
            reverse=True,
        )

        if not ranked_jobs:
            return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)

        return ranked_jobs[:OUTPUT_RECOMMEND_LIMIT]

    except Exception as e:
        print("Gemini ranking parse failed. Using local fallback.")
        print("Error:", e)
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)


# ============================================================
# PDF Styles and Components
# ============================================================

def make_styles():  # 建立 PDF 內各種文字樣式
    navy = colors.HexColor("#1F3A5F")
    teal = colors.HexColor("#2E7D7B")
    dark = colors.HexColor("#263238")
    gray = colors.HexColor("#546E7A")

    return {
        "name": ParagraphStyle(
            name="Name",
            fontName=PDF_BOLD,
            fontSize=22,
            leading=28,
            textColor=navy,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "headline": ParagraphStyle(
            name="Headline",
            fontName=PDF_FONT,
            fontSize=10.5,
            leading=14,
            textColor=teal,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            name="Section",
            fontName=PDF_BOLD,
            fontSize=12.5,
            leading=16,
            textColor=navy,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            name="Body",
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=dark,
            spaceAfter=5,
        ),
        "body_bold": ParagraphStyle(
            name="BodyBold",
            fontName=PDF_BOLD,
            fontSize=9,
            leading=13,
            textColor=dark,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            name="Small",
            fontName=PDF_FONT,
            fontSize=8.2,
            leading=11,
            textColor=gray,
            spaceAfter=3,
        ),
        "label": ParagraphStyle(
            name="Label",
            fontName=PDF_BOLD,
            fontSize=8.2,
            leading=11,
            textColor=navy,
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            name="Bullet",
            fontName=PDF_FONT,
            fontSize=8.8,
            leading=12,
            leftIndent=9,
            firstLineIndent=-6,
            textColor=dark,
            spaceAfter=2,
        ),
    }


def para(text, style):  # 建立 PDF 段落元件
    return Paragraph(escape_text(text), style)  # 建立安全轉義後的 PDF 段落


def section_title(title, styles):  # 建立 PDF 區塊標題樣式
    table = Table(  # 建立 PDF 表格元件
        [[Paragraph(escape_text(title), styles["section"])]],
        colWidths=[170 * mm],
    )

    table.setStyle(TableStyle([  # 設定 PDF 表格樣式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F1F5")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#A7C7D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    return table


def info_table(rows, styles, label_width=45 * mm, value_width=125 * mm, bg="#F4F7F6", border="#C5D6D4"):
    data = []

    for label, value in rows:
        data.append([
            Paragraph(escape_text(label), styles["label"]),
            Paragraph(escape_text(value), styles["small"]),
        ])

    table = Table(data, colWidths=[label_width, value_width])  # 建立 PDF 表格元件

    table.setStyle(TableStyle([  # 設定 PDF 表格樣式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(border)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDE7E5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    return table


def bullet_list(items, styles):  # 建立 PDF 條列清單
    story = []  # 建立 PDF 內容流程清單

    if not items:
        items = ["None"]

    for item in items:
        story.append(Paragraph(f"- {escape_text(item)}", styles["bullet"]))  # 把元件加入 PDF 內容

    return story


def chip_table(items, styles, max_cols=3):  # 建立 PDF 技能標籤表格
    clean_items = [safe_text(x) for x in items if safe_text(x)]

    if not clean_items:
        clean_items = ["None"]

    rows = []
    row = []

    for item in clean_items:
        row.append(Paragraph(escape_text(item), styles["small"]))

        if len(row) == max_cols:
            rows.append(row)
            row = []

    if row:
        while len(row) < max_cols:
            row.append("")
        rows.append(row)

    table = Table(rows, colWidths=[52 * mm] * max_cols)  # 建立 PDF 表格元件

    table.setStyle(TableStyle([  # 設定 PDF 表格樣式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F0E6")),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9A7")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    return table


def draw_page_background(canvas_obj, doc):  # 繪製 PDF 每頁背景、頁碼與色塊
    canvas_obj.saveState()

    width, height = A4

    canvas_obj.setFillColor(colors.HexColor("#1F3A5F"))
    canvas_obj.rect(0, height - 20 * mm, width, 20 * mm, fill=1, stroke=0)

    canvas_obj.setFillColor(colors.HexColor("#5E7C3A"))
    canvas_obj.rect(0, 0, width, 6 * mm, fill=1, stroke=0)

    canvas_obj.setFont(PDF_FONT, 8)
    canvas_obj.setFillColor(colors.white)
    canvas_obj.drawRightString(width - 14 * mm, height - 9 * mm, f"Page {doc.page}")

    canvas_obj.restoreState()


def create_resume_pdf(content, output_path=OUTPUT_PDF):  # 根據履歷內容建立 PDF 檔案
    styles = make_styles()

    doc = SimpleDocTemplate(  # 建立 PDF 文件物件
        output_path,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=26 * mm,
        bottomMargin=14 * mm,
    )

    story = []  # 建立 PDF 內容流程清單

    header = Table(
        [
            [Paragraph(escape_text(content.get("name", "")), styles["name"])],
            [Paragraph(escape_text(content.get("headline", "")), styles["headline"])],
        ],
        colWidths=[176 * mm],
    )

    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D2DFE5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(header)  # 把元件加入 PDF 內容
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    contact = content.get("contact", {})
    prefs = content.get("job_preferences", {})

    story.append(info_table([  # 把元件加入 PDF 內容
        ("Address", contact.get("address", "")),
        ("Email", contact.get("email", "")),
        ("Phone", contact.get("phone", "")),
    ], styles, label_width=30 * mm, value_width=140 * mm))

    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(info_table([  # 把元件加入 PDF 內容
        ("Target Position", prefs.get("target_position", "")),
        ("Preferred Location", prefs.get("target_location", "")),
        ("Expected Salary Range", prefs.get("expected_salary_range", prefs.get("expected_monthly_salary", ""))),
        ("Required Benefits", prefs.get("required_benefits_text", "None")),
    ], styles, label_width=50 * mm, value_width=120 * mm, bg="#FFF8E6", border="#D8B45A"))

    story.append(Spacer(1, 10))  # 把元件加入 PDF 內容

    story.append(section_title("Profile Summary", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.append(para(content.get("profile_summary", ""), styles["body"]))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(section_title("Skills & Specialty", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.append(Paragraph(f"Specialty: {escape_text(content.get('specialty', ''))}", styles["body_bold"]))  # 把元件加入 PDF 內容
    story.append(chip_table(content.get("skills", []), styles, max_cols=3))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(section_title("Education", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    for edu in content.get("education", []):
        story.append(Paragraph(escape_text(edu.get("school", "")), styles["body_bold"]))  # 把元件加入 PDF 內容
        story.append(Paragraph(f"Major: {escape_text(edu.get('major', ''))}", styles["small"]))  # 把元件加入 PDF 內容
        story.append(Paragraph(escape_text(edu.get("description", "")), styles["small"]))  # 把元件加入 PDF 內容
        story.append(Spacer(1, 4))  # 把元件加入 PDF 內容

    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容

    story.append(section_title("Certificates", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.extend(bullet_list(content.get("certificates", []), styles))
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(section_title("Competitions", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.extend(bullet_list(content.get("competitions", []), styles))
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(section_title("Experience", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    for exp in content.get("experience", []):
        story.append(Paragraph(escape_text(exp.get("title", "Experience")), styles["body_bold"]))  # 把元件加入 PDF 內容
        story.append(Paragraph(escape_text(exp.get("description", "")), styles["small"]))  # 把元件加入 PDF 內容
        story.append(Spacer(1, 4))  # 把元件加入 PDF 內容

    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容

    story.append(section_title("Strengths", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.extend(bullet_list(content.get("strengths", []), styles))
    story.append(Spacer(1, 8))  # 把元件加入 PDF 內容

    story.append(section_title("Career Objective", styles))  # 把元件加入 PDF 內容
    story.append(Spacer(1, 5))  # 把元件加入 PDF 內容
    story.append(para(content.get("career_objective", ""), styles["body"]))  # 把元件加入 PDF 內容

    doc.build(  # 輸出並生成 PDF 檔案
        story,
        onFirstPage=draw_page_background,
        onLaterPages=draw_page_background,
    )

    return output_path


# ============================================================
# Output Files
# ============================================================

def write_resume_txt(content, output_path=OUTPUT_TXT):  # 把履歷 JSON 內容寫成文字檔
    with open(output_path, "w", encoding="utf-8") as f:  # 開啟輸出檔案並準備寫入
        f.write("========== RESUME CONTENT ==========\n\n")  # 寫入文字內容到檔案
        f.write(json.dumps(content, ensure_ascii=False, indent=2))  # 把資料寫成 JSON 格式


def write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, output_path=JOBS_TXT):  # 把職缺推薦結果寫成文字檔
    with open(output_path, "w", encoding="utf-8") as f:  # 開啟輸出檔案並準備寫入
        f.write("========== JOB RECOMMENDATIONS ==========\n\n")  # 寫入文字內容到檔案

        f.write("Search Conditions\n")  # 寫入文字內容到檔案
        f.write("----------------------------------------\n")  # 寫入文字內容到檔案
        f.write(f"Target Position: {raw_resume['target_position']}\n")  # 寫入文字內容到檔案
        f.write(f"Preferred Location: {raw_resume['target_location']}\n")  # 寫入文字內容到檔案
        f.write(f"Expected Monthly Salary: {raw_resume['expected_monthly_salary']}\n")  # 寫入文字內容到檔案
        f.write(f"Salary Min: {raw_resume.get('salary_min', '')}\n")  # 寫入文字內容到檔案
        f.write(f"Salary Max: {raw_resume.get('salary_max', '')}\n")  # 寫入文字內容到檔案

        required_benefits = get_required_benefits(raw_resume.get("benefit_preferences", {}))
        f.write(f"Required Benefits: {benefits_to_text(required_benefits)}\n\n")  # 寫入文字內容到檔案

        salary_min = safe_int(raw_resume.get("salary_min", raw_resume["expected_monthly_salary"]), 0)

        f.write("Direct Search Links\n")  # 寫入文字內容到檔案
        f.write("----------------------------------------\n")  # 寫入文字內容到檔案
        f.write(build_104_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n")  # 寫入文字內容到檔案
        f.write(build_1111_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n\n")  # 寫入文字內容到檔案

        f.write("Process Summary\n")  # 寫入文字內容到檔案
        f.write("----------------------------------------\n")  # 寫入文字內容到檔案
        f.write(f"Fetched job postings: {len(raw_jobs)}\n")  # 寫入文字內容到檔案
        f.write(f"Recommended jobs: {len(recommended_jobs)}\n")  # 寫入文字內容到檔案
        f.write(f"Recommendation limit: {OUTPUT_RECOMMEND_LIMIT}\n")  # 寫入文字內容到檔案
        f.write(f"Match score threshold: {MATCH_SCORE_THRESHOLD}\n\n")  # 寫入文字內容到檔案

        f.write("Matched Job Results\n")  # 寫入文字內容到檔案
        f.write("----------------------------------------\n\n")  # 寫入文字內容到檔案

        if not recommended_jobs:
            f.write("No recommended jobs were selected.\n")  # 寫入文字內容到檔案
            return

        for idx, job in enumerate(recommended_jobs, start=1):
            f.write(f"{idx}. {job.get('title', 'No title')}\n")  # 寫入文字內容到檔案
            f.write(f"Platform: {job.get('platform', 'Not clearly shown')}\n")  # 寫入文字內容到檔案
            f.write(f"Company: {job.get('company', 'Not clearly shown')}\n")  # 寫入文字內容到檔案
            f.write(f"Location: {job.get('location', 'Not clearly shown')}\n")  # 寫入文字內容到檔案
            f.write(f"Salary: {job.get('salary', 'Not clearly shown')}\n")  # 寫入文字內容到檔案
            f.write(f"Salary Check: {job.get('salary_status', 'Not clearly shown')}\n")  # 寫入文字內容到檔案
            f.write(f"Benefit Check: {job.get('benefit_match_status', 'Not checked')}\n")  # 寫入文字內容到檔案
            f.write(f"Matched Benefits: {benefits_to_text(job.get('matched_benefits', []))}\n")  # 寫入文字內容到檔案
            f.write(f"Missing Benefits: {benefits_to_text(job.get('missing_benefits', []))}\n")  # 寫入文字內容到檔案
            f.write(f"Gemini Match Score: {job.get('match_score', 'Not ranked')}\n")  # 寫入文字內容到檔案
            f.write(f"Keyword Score: {job.get('keyword_score', 0)}\n")  # 寫入文字內容到檔案
            f.write(f"Source Method: {job.get('source', 'Unknown')}\n")  # 寫入文字內容到檔案

            if job.get("gemini_reason"):
                f.write(f"Gemini Reason: {job.get('gemini_reason')}\n")  # 寫入文字內容到檔案

            if job.get("fit_points"):
                f.write(f"Fit Points: {job.get('fit_points')}\n")  # 寫入文字內容到檔案

            if job.get("concerns"):
                f.write(f"Concerns: {job.get('concerns')}\n")  # 寫入文字內容到檔案

            if job.get("snippet"):
                f.write(f"Snippet: {job.get('snippet')}\n")  # 寫入文字內容到檔案

            f.write(f"URL: {job.get('url', '')}\n")  # 寫入文字內容到檔案
            f.write("-" * 70 + "\n\n")  # 寫入文字內容到檔案


# ============================================================
# Main Program
# ============================================================

def main():  # 主程式流程，負責串起輸入、AI、職缺抓取與輸出
    print("========== AI Resume PDF + Job Recommendation Generator ==========\n")

    print("========== Job Target ==========\n")

    target_position = input("Target Position, for example Software Engineer / 軟體工程師: ").strip()  # 讀取目標職缺
    target_location = input("Preferred Work Location, for example Taipei / 台北: ").strip()  # 讀取希望工作地點

    salary_min_text, salary_max_text, salary_min_value, salary_max_value = input_salary_range()
    expected_monthly_salary = f"{salary_min_text} - {salary_max_text}"  # 組合期望薪資範圍文字

    benefit_preferences = collect_benefit_preferences()  # 蒐集福利需求

    print("\n========== Resume Information ==========\n")

    name = input("Name: ").strip()  # 讀取姓名
    specialty = input("Specialty: ").strip()  # 讀取專長

    address = input("Address: ").strip()
    email = input("Email: ").strip()
    phone = input("Phone: ").strip()

    certificates = input("Certificates, separated by commas. Leave blank if none: ").strip()
    competitions = input("Competitions, separated by commas. Leave blank if none: ").strip()

    school = input("School: ").strip()
    major = input("Major: ").strip()

    skills = input("Skills, separated by commas. Example: Python, Excel, Finance: ").strip()
    experience = input("Work / Internship Experience. Leave blank if none: ").strip()

    raw_resume = {  # 整理所有履歷輸入資料
        "target_position": target_position,
        "target_location": target_location,
        "expected_monthly_salary": expected_monthly_salary,
        "salary_min": salary_min_text,
        "salary_max": salary_max_text,
        "benefit_preferences": benefit_preferences,
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

    print("\nConnecting to Gemini API...")
    client = make_gemini_client()  # 建立 Gemini 連線

    print("Generating polished resume content...")
    resume_content = generate_resume_content_with_gemini(client, raw_resume)  # 產生履歷內容

    resume_content.setdefault("job_preferences", {})
    resume_content["job_preferences"]["expected_salary_range"] = expected_monthly_salary
    resume_content["job_preferences"]["required_benefits_text"] = benefits_to_text(
        get_required_benefits(benefit_preferences)
    )

    print("Fetching job postings...")
    salary_min = salary_min_value
    salary_max = salary_max_value
    raw_jobs = get_raw_jobs(target_position, target_location, salary_min)  # 抓取原始職缺

    raw_jobs = apply_user_preferences_to_jobs(
        jobs=raw_jobs,
        job_title=target_position,
        location=target_location,
        salary_min=salary_min,
        salary_max=salary_max,
        benefit_preferences=benefit_preferences,
    )

    print(f"Fetched {len(raw_jobs)} jobs.")

    print("Ranking jobs by resume relevance...")
    recommended_jobs = rank_jobs_with_gemini(client, raw_resume, raw_jobs)  # 產生推薦職缺排序

    print(f"Recommended {len(recommended_jobs)} jobs.")

    print("Writing output files...")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resume_content, f, ensure_ascii=False, indent=2)  # 把資料寫成 JSON 格式

    with open(RAW_JOBS_JSON, "w", encoding="utf-8") as f:
        json.dump(raw_jobs, f, ensure_ascii=False, indent=2)  # 把資料寫成 JSON 格式

    write_resume_txt(resume_content, OUTPUT_TXT)
    write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, JOBS_TXT)

    print("Creating resume PDF...")
    pdf_path = create_resume_pdf(resume_content, OUTPUT_PDF)  # 建立履歷 PDF

    print("\nDone.")
    print("Files saved to:")
    print(OUTPUT_JSON)
    print(OUTPUT_TXT)
    print(JOBS_TXT)
    print(RAW_JOBS_JSON)
    print(pdf_path)


if __name__ == "__main__":  # 只有直接執行此檔案時才啟動主程式
    main()  # 呼叫主程式
