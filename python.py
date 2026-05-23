import os  # 匯入 os，用來處理檔案路徑與環境變數
import re  # 匯入 re，用正規表示式搜尋、切割與清理文字
import json  # 匯入 json，用來讀寫 JSON 格式資料
import html  # 匯入 html，用來轉義特殊符號避免 PDF 顯示錯誤
import time  # 匯入 time，用來控制等待時間與 API 重試間隔
import random  # 匯入 random，用來產生隨機等待秒數，降低重試碰撞
import requests  # 匯入 requests，用來向求職網站或搜尋頁發送 HTTP 請求
from bs4 import BeautifulSoup  # 匯入 BeautifulSoup，用來解析 HTML 網頁內容
from urllib.parse import quote, urlparse, parse_qs, unquote  # 匯入網址工具，用來編碼搜尋字與解析轉址連結

from reportlab.lib import colors  # 匯入 PDF 顏色工具
from reportlab.lib.pagesizes import A4  # 匯入 A4 紙張大小設定
from reportlab.lib.styles import ParagraphStyle  # 匯入段落樣式工具，用來設定 PDF 字型與行距
from reportlab.lib.units import mm  # 匯入毫米單位，方便設定 PDF 邊距與寬度
from reportlab.lib.enums import TA_CENTER  # 匯入置中對齊常數
from reportlab.platypus import (
    SimpleDocTemplate,  # 匯入 SimpleDocTemplate，用來建立 PDF 內容元件
    Paragraph,  # 匯入 Paragraph，用來建立 PDF 內容元件
    Spacer,  # 匯入 Spacer，用來建立 PDF 內容元件
    Table,  # 匯入 Table，用來建立 PDF 內容元件
    TableStyle,  # 匯入 TableStyle，用來建立 PDF 內容元件
    KeepTogether,  # 匯入 KeepTogether，用來建立 PDF 內容元件
)
from reportlab.pdfbase import pdfmetrics  # 匯入 PDF 字型註冊工具
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # 匯入支援 Unicode 的 CID 字型

try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
    from google import genai  # 匯入 Gemini API 主套件，讓程式可以呼叫 AI
    from google.genai import types  # 匯入 Gemini 設定型別，後面用來指定生成參數
    GEMINI_INSTALLED = True  # 記錄 Gemini 套件是否成功匯入，後面用來決定是否啟用 AI
except ImportError:  # 如果 Gemini 套件沒有安裝，就進入這裡改用備援模式
    GEMINI_INSTALLED = False  # 記錄 Gemini 套件是否成功匯入，後面用來決定是否啟用 AI


# ============================================================
# Basic Settings
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 取得目前程式檔所在資料夾，讓輸出檔案可以存到同一個專案位置

OUTPUT_PDF = os.path.join(BASE_DIR, "ai_resume.pdf")  # 設定最後產生的履歷 PDF 檔案路徑
OUTPUT_TXT = os.path.join(BASE_DIR, "resume_content.txt")  # 設定履歷文字內容輸出的 txt 檔案路徑
OUTPUT_JSON = os.path.join(BASE_DIR, "resume_ai_content.json")  # 設定 Gemini 或備援邏輯整理後的履歷 JSON 檔案路徑
JOBS_TXT = os.path.join(BASE_DIR, "job_recommendations.txt")  # 設定職缺推薦結果輸出的文字檔路徑
RAW_JOBS_JSON = os.path.join(BASE_DIR, "raw_jobs_fetched.json")  # 設定原始爬蟲職缺資料輸出的 JSON 檔案路徑

PDF_FONT = "HeiseiMin-W3"  # 設定 PDF 內文使用的中文字型名稱
PDF_BOLD = "HeiseiKakuGo-W5"  # 設定 PDF 標題或粗體文字使用的中文字型名稱

pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))  # 把指定字型註冊到 ReportLab，讓 PDF 能正常使用該字型
pdfmetrics.registerFont(UnicodeCIDFont(PDF_BOLD))  # 把指定字型註冊到 ReportLab，讓 PDF 能正常使用該字型

GEMINI_FALLBACK_MODELS = [  # 設定 Gemini 可依序嘗試的模型清單，前一個失敗會換下一個
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

TOTAL_JOBS_TO_FETCH = 50  # 設定整理後最多保留的職缺總數
FETCH_PER_PLATFORM = 50  # 設定每個求職平台最多抓取的職缺數量
OUTPUT_RECOMMEND_LIMIT = 20  # 設定最後輸出的推薦職缺數量上限
MATCH_SCORE_THRESHOLD = 60  # 設定 Gemini 推薦職缺時需要達到的最低分數

BENEFIT_KEYWORDS = {  # 建立福利分類與對應關鍵字，後面用來比對職缺福利內容
    "育兒津貼": ["育兒津貼", "托育補助", "生育補助", "育嬰", "childcare"],  # 設定「育兒津貼」福利分類可比對的關鍵字
    "交通津貼": ["交通津貼", "交通補助", "通勤補助", "車資補助", "停車補助"],  # 設定「交通津貼」福利分類可比對的關鍵字
    "伙食津貼/供餐": ["伙食津貼", "供餐", "餐費補助", "免費午餐", "員工餐廳", "膳食"],  # 設定「伙食津貼/供餐」福利分類可比對的關鍵字
    "員工認股權": ["員工認股", "認股權", "股票選擇權", "員工持股", "分紅配股"],  # 設定「員工認股權」福利分類可比對的關鍵字
    "年終獎金": ["年終獎金", "年終", "績效獎金", "分紅", "獎金"],  # 設定「年終獎金」福利分類可比對的關鍵字
    "員工旅遊": ["員工旅遊", "國內旅遊", "國外旅遊", "旅遊補助", "年度旅遊"],  # 設定「員工旅遊」福利分類可比對的關鍵字
    "員工保險": ["勞保", "健保", "團保", "壽險", "醫療險", "意外險", "員工保險"],  # 設定「員工保險」福利分類可比對的關鍵字
    "三節禮金": ["三節禮金", "端午", "中秋", "春節", "節金", "禮金"],  # 設定「三節禮金」福利分類可比對的關鍵字
    "教育訓練及外部課程": ["教育訓練", "外部課程", "內部訓練", "培訓", "課程補助"],  # 設定「教育訓練及外部課程」福利分類可比對的關鍵字
    "進修補助": ["進修補助", "學習補助", "證照補助", "學費補助", "進修"],  # 設定「進修補助」福利分類可比對的關鍵字
    "其他福利": ["其他福利", "福利制度"],  # 設定「其他福利」福利分類可比對的關鍵字
}

BENEFIT_CATEGORIES = list(BENEFIT_KEYWORDS.keys())  # 把福利分類名稱轉成清單，方便逐項詢問使用者


# ============================================================
# Utility Functions
# ============================================================

def safe_text(value):  # 把輸入值安全轉成去除空白的字串，避免 None 造成錯誤
    if value is None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return ""  # 回傳處理結果給呼叫這個函式的地方使用
    return str(value).strip()  # 回傳處理結果給呼叫這個函式的地方使用


def escape_text(value):  # 把文字做 HTML 轉義，避免特殊符號影響 PDF 顯示
    return html.escape(safe_text(value))  # 回傳處理結果給呼叫這個函式的地方使用


def split_comma_text(text):  # 把使用者用逗號、頓號或換行輸入的文字切成清單
    text = safe_text(text)  # 接收 Gemini 回傳的文字內容
    if not text:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return []  # 回傳空清單，代表目前沒有符合的資料
    parts = re.split(r"[,，、\n]+", text)  # 建立暫存變數，協助完成資料清理、判斷或比對流程
    return [p.strip() for p in parts if p.strip()]  # 回傳處理結果給呼叫這個函式的地方使用


def clean_text(text):  # 清除 HTML 標籤與多餘空白，留下乾淨文字
    if text is None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return ""  # 回傳處理結果給呼叫這個函式的地方使用
    text = BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)  # 接收 Gemini 回傳的文字內容
    text = re.sub(r"\s+", " ", text)  # 接收 Gemini 回傳的文字內容
    return text.strip()  # 回傳處理結果給呼叫這個函式的地方使用


def safe_int(value, default=0):  # 把輸入安全轉成整數，轉換失敗時回傳預設值
    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        cleaned = re.sub(r"[^\d]", "", str(value))  # 建立暫存變數，協助完成資料清理、判斷或比對流程
        return int(cleaned) if cleaned else default  # 回傳處理結果給呼叫這個函式的地方使用
    except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
        return default  # 回傳處理結果給呼叫這個函式的地方使用


def input_positive_salary(prompt):  # 要求使用者輸入正數薪資，直到輸入合法為止
    while True:  # 使用 while 迴圈持續執行，直到條件不成立為止
        value = input(prompt).strip()  # 建立暫存變數，協助完成資料清理、判斷或比對流程
        amount = safe_int(value, 0)  # 建立暫存變數，協助完成資料清理、判斷或比對流程

        if amount > 0:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return str(amount), amount  # 回傳處理結果給呼叫這個函式的地方使用

        print("Salary amount must be a positive number. Please enter again.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度


def input_salary_range():  # 要求使用者輸入最低與最高期望薪資，並檢查範圍是否合法
    while True:  # 使用 while 迴圈持續執行，直到條件不成立為止
        salary_min_text, salary_min = input_positive_salary(
            "Minimum Expected Monthly Salary, for example 40000: "
        )
        salary_max_text, salary_max = input_positive_salary(
            "Maximum Expected Monthly Salary, for example 70000: "
        )

        if salary_max >= salary_min:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return salary_min_text, salary_max_text, salary_min, salary_max  # 回傳處理結果給呼叫這個函式的地方使用

        print("Maximum salary must be greater than or equal to minimum salary. Please enter again.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度


def input_yes_no(prompt):  # 統一處理使用者輸入的 y/n 或中文是/否答案
    while True:  # 使用 while 迴圈持續執行，直到條件不成立為止
        answer = input(prompt).strip().lower()  # 建立暫存變數，協助完成資料清理、判斷或比對流程

        if answer in ["y", "yes", "是", "需要", "要"]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return True  # 回傳處理結果給呼叫這個函式的地方使用

        if answer in ["n", "no", "否", "不需要", "不要", ""]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return False  # 回傳處理結果給呼叫這個函式的地方使用

        print("Please enter y/n.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度


def collect_benefit_preferences():  # 逐項詢問使用者需要哪些福利，並整理成福利偏好資料
    print("\n========== Expected Job Benefits ==========\n")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print("Please answer y/n for each benefit category.\n")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    selected_default_benefits = []  # 設定 selected_default_benefits 變數，供後續流程使用

    for benefit in BENEFIT_CATEGORIES:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        if benefit == "其他福利":  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

        if input_yes_no(f"Require {benefit}? y/n: "):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            selected_default_benefits.append(benefit)  # 把整理好的資料加入清單，供後續輸出或排序使用

    other_benefits_text = input(  # 設定 other_benefits_text 變數，供後續流程使用
        "Other required benefits, separated by commas. Leave blank if none: "
    ).strip()

    other_benefits = split_comma_text(other_benefits_text)  # 設定 other_benefits 變數，供後續流程使用

    return {  # 回傳處理結果給呼叫這個函式的地方使用
        "selected_default_benefits": selected_default_benefits,  # 設定字典欄位，讓資料可以用固定格式保存
        "other_benefits": other_benefits,  # 設定字典欄位，讓資料可以用固定格式保存
        "required_benefits": selected_default_benefits + other_benefits,  # 設定字典欄位，讓資料可以用固定格式保存
    }


def get_required_benefits(benefit_preferences):  # 從福利偏好資料中取出使用者要求的福利清單
    if not isinstance(benefit_preferences, dict):  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return []  # 回傳空清單，代表目前沒有符合的資料

    required = benefit_preferences.get("required_benefits", [])  # 建立暫存變數，協助完成資料清理、判斷或比對流程

    if isinstance(required, str):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        required = split_comma_text(required)  # 建立暫存變數，協助完成資料清理、判斷或比對流程

    result = []  # 建立暫存變數，協助完成資料清理、判斷或比對流程

    for item in required:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        item = safe_text(item)  # 設定 item 變數，供後續流程使用
        if item and item not in result:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            result.append(item)  # 把整理好的資料加入清單，供後續輸出或排序使用

    return result  # 回傳處理結果給呼叫這個函式的地方使用


def benefits_to_text(benefits):  # 把福利清單轉成逗號分隔的文字，方便寫入 PDF 或 txt
    if not benefits:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return "None"  # 回傳處理結果給呼叫這個函式的地方使用

    cleaned = [safe_text(x) for x in benefits if safe_text(x)]  # 建立暫存變數，協助完成資料清理、判斷或比對流程
    return ", ".join(cleaned) if cleaned else "None"  # 回傳處理結果給呼叫這個函式的地方使用


def match_benefits_from_text(text, benefit_preferences):  # 從職缺文字中比對是否包含使用者要求的福利關鍵字
    full_text = safe_text(text).lower()  # 設定 full_text 變數，供後續流程使用
    required_benefits = get_required_benefits(benefit_preferences)  # 設定 required_benefits 變數，供後續流程使用

    matched = []  # 建立暫存變數，協助完成資料清理、判斷或比對流程
    missing = []  # 建立暫存變數，協助完成資料清理、判斷或比對流程

    for benefit in required_benefits:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        keywords = BENEFIT_KEYWORDS.get(benefit, [benefit])  # 設定 keywords 變數，供後續流程使用
        found = False  # 建立暫存變數，協助完成資料清理、判斷或比對流程

        for keyword in keywords:  # 使用迴圈逐一處理清單或資料集合中的每個項目
            if keyword.lower() in full_text:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                found = True  # 建立暫存變數，協助完成資料清理、判斷或比對流程
                break  # 中止目前迴圈，避免繼續處理不需要的資料

        if found:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            matched.append(benefit)  # 把整理好的資料加入清單，供後續輸出或排序使用
        else:  # 前面條件都不符合時，執行這個預設分支
            missing.append(benefit)  # 把整理好的資料加入清單，供後續輸出或排序使用

    return matched, missing  # 回傳處理結果給呼叫這個函式的地方使用


def benefit_match_status(matched, missing):  # 根據福利符合與缺少數量產生文字狀態說明
    if not matched and not missing:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return "No benefit requirement"  # 回傳處理結果給呼叫這個函式的地方使用

    if missing:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return f"Matched {len(matched)} benefit(s), missing {len(missing)} benefit(s)"  # 回傳處理結果給呼叫這個函式的地方使用

    return "All required benefits appear to be matched"  # 回傳處理結果給呼叫這個函式的地方使用


def salary_range_status(salary_text, salary_min, salary_max):  # 判斷職缺薪資是否可能符合使用者期望薪資範圍
    salary_est = estimate_salary_from_text(salary_text)  # 處理薪資相關變數，後面用來判斷是否符合使用者條件

    if salary_min <= 0:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return "No salary requirement"  # 回傳處理結果給呼叫這個函式的地方使用

    if salary_est is None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return "Not clearly shown"  # 回傳處理結果給呼叫這個函式的地方使用

    if salary_max > 0:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        if salary_min <= salary_est <= salary_max:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return "Possibly meets salary range"  # 回傳處理結果給呼叫這個函式的地方使用

        if salary_est > salary_max:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return "Higher than preferred salary range"  # 回傳處理結果給呼叫這個函式的地方使用

        return "May be lower than minimum salary"  # 回傳處理結果給呼叫這個函式的地方使用

    if salary_est >= salary_min:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return "Possibly meets minimum salary"  # 回傳處理結果給呼叫這個函式的地方使用

    return "May be lower than minimum salary"  # 回傳處理結果給呼叫這個函式的地方使用


def apply_user_preferences_to_jobs(jobs, job_title, location, salary_min, salary_max, benefit_preferences):  # 依照使用者職稱、地點、薪資與福利條件重新評分並排序職缺
    for job in jobs:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        score_job_keyword(  # 替目前職缺計算本機關鍵字分數
            job=job,  # 把單一職缺整理成統一格式，方便後續評分與輸出
            job_title=job_title,  # 設定 job_title 變數，供後續流程使用
            location=location,  # 設定 location 變數，供後續流程使用
            salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
            salary_max=salary_max,  # 最高薪資條件，用來判斷職缺是否落在期望薪資範圍
            benefit_preferences=benefit_preferences,  # 設定 benefit_preferences 變數，供後續流程使用
        )

    jobs.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)  # 依照指定分數或條件排序資料
    return jobs  # 回傳整理完成的職缺清單


def build_104_search_url(job_title, location, salary_min):  # 依使用者條件建立 104 求職網站搜尋網址
    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()  # 把職稱、地點與薪資條件組成搜尋關鍵字
    return f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}"  # 回傳整理完成的職缺清單


def build_1111_search_url(job_title, location, salary_min):  # 依使用者條件建立 1111 求職網站搜尋網址
    keyword = f"{job_title} {location} {salary_min if salary_min > 0 else ''}".strip()  # 把職稱、地點與薪資條件組成搜尋關鍵字
    return f"https://www.1111.com.tw/search/job?ks={quote(keyword)}"  # 回傳處理結果給呼叫這個函式的地方使用


def normalize_url(url, base_domain):  # 把相對網址或缺少 https 的網址轉成完整網址
    if not url:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return ""  # 回傳處理結果給呼叫這個函式的地方使用

    if url.startswith("//"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return "https:" + url  # 回傳處理結果給呼叫這個函式的地方使用

    if url.startswith("/"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return base_domain.rstrip("/") + url  # 回傳處理結果給呼叫這個函式的地方使用

    return url  # 回傳處理結果給呼叫這個函式的地方使用


def normalize_duckduckgo_link(href):  # 還原 DuckDuckGo 轉址中真正的目標網址
    if not href:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return ""  # 回傳處理結果給呼叫這個函式的地方使用

    if "uddg=" in href:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        parsed = urlparse(href)  # 設定 parsed 變數，供後續流程使用
        query = parse_qs(parsed.query)  # 設定 query 變數，供後續流程使用
        real_url = query.get("uddg", [""])[0]  # 設定 real_url 變數，供後續流程使用
        return unquote(real_url)  # 回傳處理結果給呼叫這個函式的地方使用

    return href  # 回傳處理結果給呼叫這個函式的地方使用


def extract_json_from_text(text):  # 從 Gemini 回應中取出 JSON，處理被 markdown 包住的情況
    text = text.strip()  # 接收 Gemini 回傳的文字內容

    if text.startswith("```"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()  # 接收 Gemini 回傳的文字內容
        text = re.sub(r"```$", "", text).strip()  # 接收 Gemini 回傳的文字內容

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        return json.loads(text)  # 回傳處理結果給呼叫這個函式的地方使用
    except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
        pass  # 這裡不做任何處理，讓程式可以繼續執行

    start = text.find("{")  # 設定 start 變數，供後續流程使用
    end = text.rfind("}")  # 設定 end 變數，供後續流程使用

    if start != -1 and end != -1 and end > start:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return json.loads(text[start:end + 1])  # 回傳處理結果給呼叫這個函式的地方使用

    raise ValueError("Could not parse JSON from model output.")


def estimate_salary_from_text(text):  # 從薪資文字中擷取數字並估算可比較的薪資金額
    if not text:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return None  # 回傳 None，代表目前沒有可用結果或改走備援流程

    values = []  # 設定 values 變數，供後續流程使用

    nums = re.findall(r"(?<!\d)(\d{2,3}(?:,\d{3})|\d{5,6})(?!\d)", text)  # 設定 nums 變數，供後續流程使用
    for n in nums:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
            v = int(n.replace(",", ""))  # 設定 v 變數，供後續流程使用
            if 20000 <= v <= 300000:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                values.append(v)  # 把整理好的資料加入清單，供後續輸出或排序使用
        except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
            pass  # 這裡不做任何處理，讓程式可以繼續執行

    wan_nums = re.findall(r"(\d+(?:\.\d+)?)\s*萬", text)  # 設定 wan_nums 變數，供後續流程使用
    for n in wan_nums:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
            v = int(float(n) * 10000)  # 設定 v 變數，供後續流程使用
            if 20000 <= v <= 300000:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                values.append(v)  # 把整理好的資料加入清單，供後續輸出或排序使用
        except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
            pass  # 這裡不做任何處理，讓程式可以繼續執行

    k_nums = re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", text)  # 設定 k_nums 變數，供後續流程使用
    for n in k_nums:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
            v = int(float(n) * 1000)  # 設定 v 變數，供後續流程使用
            if 20000 <= v <= 300000:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                values.append(v)  # 把整理好的資料加入清單，供後續輸出或排序使用
        except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
            pass  # 這裡不做任何處理，讓程式可以繼續執行

    return max(values) if values else None  # 回傳處理結果給呼叫這個函式的地方使用


def extract_salary_string(text):  # 從職缺文字中抓出薪資描述，例如月薪、年薪或面議
    patterns = [  # 設定 patterns 變數，供後續流程使用
        r"月薪\s*[0-9,萬Kk~～\-以上]+",
        r"年薪\s*[0-9,萬Kk~～\-以上]+",
        r"時薪\s*[0-9,萬Kk~～\-以上]+",
        r"[0-9,]+元\s*[~～\-]\s*[0-9,]+元",
        r"[0-9.]+萬\s*[~～\-]\s*[0-9.]+萬",
        r"待遇面議",
        r"面議",
    ]

    for p in patterns:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        m = re.search(p, text)  # 設定 m 變數，供後續流程使用
        if m:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            return m.group(0)  # 回傳處理結果給呼叫這個函式的地方使用

    return "Not clearly shown"  # 回傳處理結果給呼叫這個函式的地方使用


def salary_status(salary_text, salary_min, salary_max=0):  # 包裝薪資範圍判斷函式，回傳職缺薪資狀態
    return salary_range_status(salary_text, salary_min, salary_max)  # 回傳處理結果給呼叫這個函式的地方使用


def score_job_keyword(job, job_title, location, salary_min, salary_max=0, benefit_preferences=None):  # 依職稱、地點、薪資與福利關鍵字計算職缺符合程度
    title = job.get("title", "")  # 取得並清理職缺名稱
    company = job.get("company", "")  # 取得並清理公司名稱
    job_location = job.get("location", "")  # 取得並清理職缺地點
    salary = job.get("salary", "")  # 取得並清理職缺薪資文字
    snippet = job.get("snippet", "")  # 取得並清理職缺摘要或工作描述

    full_text = f"{title} {company} {job_location} {salary} {snippet}".lower()  # 設定 full_text 變數，供後續流程使用
    score = 0  # 設定 score 變數，供後續流程使用

    if job_title.lower() in title.lower():  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        score += 8

    if job_title.lower() in full_text:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        score += 3

    if location.lower() in full_text:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        score += 6

    tokens = re.split(r"[\s,，/、]+", job_title)  # 設定 tokens 變數，供後續流程使用
    for token in tokens:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        token = token.strip()  # 設定 token 變數，供後續流程使用
        if token and token.lower() in full_text:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            score += 1

    salary_est = estimate_salary_from_text(salary + " " + snippet)  # 處理薪資相關變數，後面用來判斷是否符合使用者條件

    if salary_min > 0 and salary_est is not None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        if salary_max > 0:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            if salary_min <= salary_est <= salary_max:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                score += 5
            elif salary_est > salary_max:  # 前一個條件不成立時，改檢查這個替代條件
                score += 3
            else:  # 前面條件都不符合時，執行這個預設分支
                score -= 2
        else:  # 前面條件都不符合時，執行這個預設分支
            if salary_est >= salary_min:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                score += 5
            else:  # 前面條件都不符合時，執行這個預設分支
                score -= 2

    matched_benefits, missing_benefits = match_benefits_from_text(
        full_text,
        benefit_preferences,
    )

    score += len(matched_benefits) * 2
    score -= len(missing_benefits)

    job["keyword_score"] = score
    job["salary_est"] = salary_est
    job["salary_status"] = salary_status(salary + " " + snippet, salary_min, salary_max)
    job["salary_min_requirement"] = salary_min
    job["salary_max_requirement"] = salary_max
    job["matched_benefits"] = matched_benefits
    job["missing_benefits"] = missing_benefits
    job["benefit_match_status"] = benefit_match_status(matched_benefits, missing_benefits)

    return score  # 回傳計算完成的職缺分數


# ============================================================
# Gemini Functions
# ============================================================

def make_gemini_client():  # 建立 Gemini API 客戶端，失敗時回傳 None 改用備援內容
    if not GEMINI_INSTALLED:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        print("google-genai is not installed. Using local fallback content.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return None  # 回傳 None，代表目前沒有可用結果或改走備援流程

    api_key = os.getenv("GEMINI_API_KEY")  # 設定 api_key 變數，供後續流程使用

    if not api_key:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        print("GEMINI_API_KEY is not set. Using local fallback content.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return None  # 回傳 None，代表目前沒有可用結果或改走備援流程

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        print("GEMINI_API_KEY loaded successfully.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return genai.Client(api_key=api_key)  # 回傳處理結果給呼叫這個函式的地方使用
    except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
        print("Gemini client failed. Using local fallback content.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        print("Error:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return None  # 回傳 None，代表目前沒有可用結果或改走備援流程


def gemini_generate_with_retry(  # 呼叫 Gemini 產生內容，失敗時會重試並切換備援模型
    client,
    prompt,
    response_json=True,  # 設定 response_json 變數，供後續流程使用
    max_retries=3,  # 設定 max_retries 變數，供後續流程使用
    temperature=0.45,  # 設定 temperature 變數，供後續流程使用
    max_output_tokens=4096,  # 設定 max_output_tokens 變數，供後續流程使用
):
    if client is None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return None  # 回傳 None，代表目前沒有可用結果或改走備援流程

    last_error = None  # 設定 last_error 變數，供後續流程使用
    used_models = []  # 設定 used_models 變數，供後續流程使用

    for model in GEMINI_FALLBACK_MODELS:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        if model in used_models:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

        used_models.append(model)  # 把整理好的資料加入清單，供後續輸出或排序使用

        for attempt in range(max_retries):  # 使用迴圈逐一處理清單或資料集合中的每個項目
            try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
                config_kwargs = {  # 建立 Gemini 生成參數，例如溫度與最大輸出 token
                    "temperature": temperature,  # 設定字典欄位，讓資料可以用固定格式保存
                    "max_output_tokens": max_output_tokens,  # 設定字典欄位，讓資料可以用固定格式保存
                }

                if response_json:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    config_kwargs["response_mime_type"] = "application/json"

                response = client.models.generate_content(  # 設定 response 變數，供後續流程使用
                    model=model,  # 設定 model 變數，供後續流程使用
                    contents=prompt,  # 設定 contents 變數，供後續流程使用
                    config=types.GenerateContentConfig(**config_kwargs),  # 設定 config 變數，供後續流程使用
                )

                if response.text and response.text.strip():  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    return response.text.strip()  # 回傳處理結果給呼叫這個函式的地方使用

                last_error = RuntimeError("Gemini returned empty text.")  # 設定 last_error 變數，供後續流程使用

            except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
                last_error = e  # 設定 last_error 變數，供後續流程使用
                error_text = str(e)  # 設定 error_text 變數，供後續流程使用

                retryable = (  # 設定 retryable 變數，供後續流程使用
                    "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                    or "high demand" in error_text.lower()
                )

                if retryable:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    wait_time = 2 + attempt * 3 + random.random()  # 設定 wait_time 變數，供後續流程使用
                    print(f"Gemini is busy or rate-limited. Retry in {wait_time:.1f} seconds...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
                    time.sleep(wait_time)  # 暫停一小段時間，避免請求過快造成網站或 API 限制
                    continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

                print(f"Gemini model {model} failed:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
                break  # 中止目前迴圈，避免繼續處理不需要的資料

        print("Trying next Gemini model if available...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    print("Gemini failed after retries. Last error:", last_error)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    return None  # 回傳 None，代表目前沒有可用結果或改走備援流程


# ============================================================
# Resume Content Generation
# ============================================================

def build_fallback_resume_content(raw):  # 當 Gemini 無法使用時，用本機邏輯產生基本英文履歷
    skills = split_comma_text(raw["skills"])  # 將使用者輸入的文字整理成清單，方便放入履歷
    certificates = split_comma_text(raw["certificates"])  # 將使用者輸入的文字整理成清單，方便放入履歷
    competitions = split_comma_text(raw["competitions"])  # 將使用者輸入的文字整理成清單，方便放入履歷

    if not skills and raw["specialty"]:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        skills = [raw["specialty"]]  # 將使用者輸入的文字整理成清單，方便放入履歷

    if not certificates:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        certificates = ["None"]  # 將使用者輸入的文字整理成清單，方便放入履歷

    if not competitions:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        competitions = ["None"]  # 將使用者輸入的文字整理成清單，方便放入履歷

    summary = (  # 建立履歷自我介紹文字，後面會依使用者資料持續補充
        f"My name is {raw['name']}. I am currently studying at {raw['school']}, "
        f"majoring in {raw['major']}. I am interested in applying for "
        f"{raw['target_position']}-related positions in {raw['target_location']}, "
        f"with an expected monthly salary range of {raw['expected_monthly_salary']}. "
        f"My main specialty is {raw['specialty']}. During my academic training, I have gradually built "
        "a foundation in problem solving, logical thinking, communication, teamwork, and independent learning. "
        "I am especially interested in connecting what I learn from school with practical workplace requirements, "
        "so I hope to use this resume to present not only my basic background, but also my learning attitude, "
        "professional direction, and potential for future development. "
    )

    if raw["skills"]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        summary += (
            f"My technical and practical skills include {raw['skills']}. "
            "These skills help me understand tasks more quickly, organize information clearly, "
            "and support practical work in a structured way. I also try to improve these abilities through coursework, "
            "self-learning, and hands-on practice, because I believe that entry-level candidates need both basic knowledge "
            "and the ability to keep improving after joining a company. "
        )

    if raw["certificates"]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        summary += (
            f"I have also obtained or prepared certifications such as {raw['certificates']}. "
            "These certificates show that I am willing to strengthen my professional ability outside regular coursework "
            "and that I can set learning goals for myself. "
        )

    if raw["competitions"]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        summary += (
            f"My competition or activity experience includes {raw['competitions']}. "
            "These experiences helped me improve my ability to work under pressure, cooperate with others, "
            "communicate ideas clearly, and complete tasks with a clearer goal. "
        )

    if raw["experience"]:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        summary += (
            f"My previous work or internship experience includes {raw['experience']}. "
            "Through this experience, I learned how to connect classroom knowledge with real workplace needs, "
            "communicate with different people, follow task requirements, and take responsibility for assigned work. "
        )
    else:  # 前面條件都不符合時，執行這個預設分支
        summary += (
            "Although I may not have extensive formal work or internship experience yet, I am willing to learn from practical tasks, "
            "accept feedback, ask questions when necessary, and improve through hands-on training. "
        )

    summary += (
        f"I hope to apply my background, specialty, and learning attitude to a {raw['target_position']}-related role. "
        "In the future, I want to become more familiar with real industry workflows, strengthen my professional skills, "
        "and gradually develop into a reliable team member who can contribute to both daily operations and long-term goals. "
        "I am looking for an opportunity where I can learn from experienced colleagues, build stable working habits, "
        "and grow step by step through real responsibilities."
    )

    return {  # 回傳處理結果給呼叫這個函式的地方使用
        "name": raw["name"],  # 設定履歷姓名欄位
        "target_position": raw["target_position"],  # 設定目標職位欄位
        "headline": f"{raw['target_position']} Candidate",  # 設定履歷標題欄位
        "job_preferences": {  # 設定求職偏好資料欄位
            "target_position": raw["target_position"],  # 設定目標職位欄位
            "target_location": raw["target_location"],  # 設定字典欄位，讓資料可以用固定格式保存
            "expected_monthly_salary": raw["expected_monthly_salary"],  # 設定期望月薪欄位
        },
        "contact": {  # 設定聯絡資料欄位
            "address": raw["address"],  # 設定地址欄位
            "email": raw["email"],  # 設定電子郵件欄位
            "phone": raw["phone"],  # 設定電話欄位
        },
        "profile_summary": summary,  # 設定履歷自我介紹欄位
        "specialty": raw["specialty"],  # 設定主要專長欄位
        "skills": skills,  # 設定技能清單欄位
        "education": [  # 設定學歷資料欄位
            {
                "school": raw["school"],  # 設定字典欄位，讓資料可以用固定格式保存
                "major": raw["major"],  # 設定字典欄位，讓資料可以用固定格式保存
                "description": "Academic background related to the candidate's professional development.",  # 設定字典欄位，讓資料可以用固定格式保存
            }
        ],
        "certificates": certificates,  # 設定證照清單欄位
        "competitions": competitions,  # 設定競賽或活動經驗欄位
        "experience": [  # 設定工作或實習經驗欄位
            {
                "title": "Work / Internship Experience",  # 紀錄職缺名稱
                "description": raw["experience"] if raw["experience"] else "No formal work or internship experience provided.",  # 設定字典欄位，讓資料可以用固定格式保存
            }
        ],
        "strengths": [  # 設定個人優勢欄位
            "Willingness to learn",
            "Communication ability",
            "Teamwork",
            "Analytical thinking",
            "Adaptability",
        ],
        "career_objective": (  # 設定職涯目標欄位
            f"To apply for {raw['target_position']}-related positions in {raw['target_location']}, "
            f"with an expected monthly salary of {raw['expected_monthly_salary']}, "
            "while gaining practical workplace experience and continuing to improve professional skills."
        ),
    }


def generate_resume_content_with_gemini(client, raw):  # 使用 Gemini 將使用者輸入資料整理成正式英文履歷 JSON
    prompt = f"""  # 建立要傳給 Gemini 的完整提示詞
You are a professional resume writing assistant.

The user provided raw resume information. Rewrite and organize it into a polished English resume.

Important rules:
- Return ONLY valid JSON.
- Do not use markdown.
- Do not invent fake experience, fake certificates, fake education, or fake achievements.
- Keep the writing professional and suitable for a student or entry-level candidate.
- If the background does not perfectly match the target position, emphasize transferable skills.
- Make the profile summary around 380 to 520 words.
- The profile summary must be detailed, content-rich, and specific to the candidate.
- Write the profile summary as a complete professional self-introduction, not a short generic paragraph.
- The profile summary should include:
  1. the candidate's academic background,
  2. target position and target location,
  3. expected monthly salary range,
  4. specialty and technical skills,
  5. certificates or competitions if provided,
  6. work, internship, project, or practical experience if provided,
  7. transferable strengths if the candidate lacks direct experience,
  8. career motivation and future development direction.
- Avoid vague sentences such as "I am hardworking" unless they are connected to actual skills, projects, learning experience, or workplace goals.
- Do not invent fake experience, but you may expand the wording based on the provided information.
- Use clear English.
- Keep Chinese names, schools, certificates, or competition names if they are originally Chinese.
- Do not remove target location or expected monthly salary.
- The resume must clearly include target position, preferred work location, and expected monthly salary.

Raw resume information:
{json.dumps(raw, ensure_ascii=False, indent=2)}  # 把 Python 資料轉成 JSON 字串，方便儲存或傳給 Gemini

Return JSON in exactly this structure:

{{
  "name": "candidate name",  # 設定履歷姓名欄位
  "target_position": "target position",  # 設定目標職位欄位
  "headline": "short professional headline",  # 設定履歷標題欄位
  "job_preferences": {{  # 設定求職偏好資料欄位
    "target_position": "target position",  # 設定目標職位欄位
    "target_location": "preferred work location",  # 設定字典欄位，讓資料可以用固定格式保存
    "expected_monthly_salary": "expected monthly salary"  # 設定期望月薪欄位
  }},
  "contact": {{  # 設定聯絡資料欄位
    "address": "address",  # 設定地址欄位
    "email": "email",  # 設定電子郵件欄位
    "phone": "phone"  # 設定電話欄位
  }},
  "profile_summary": "detailed and content-rich professional self introduction, around 380 to 520 words",  # 設定履歷自我介紹欄位
  "specialty": "main specialty",  # 設定主要專長欄位
  "skills": ["skill 1", "skill 2", "skill 3"],  # 設定技能清單欄位
  "education": [  # 設定學歷資料欄位
    {{
      "school": "school name",  # 設定字典欄位，讓資料可以用固定格式保存
      "major": "major",  # 設定字典欄位，讓資料可以用固定格式保存
      "description": "brief education description"  # 設定字典欄位，讓資料可以用固定格式保存
    }}
  ],
  "certificates": ["certificate 1", "certificate 2"],  # 設定證照清單欄位
  "competitions": ["competition 1", "competition 2"],  # 設定競賽或活動經驗欄位
  "experience": [  # 設定工作或實習經驗欄位
    {{
      "title": "experience title",  # 紀錄職缺名稱
      "description": "experience description"  # 設定字典欄位，讓資料可以用固定格式保存
    }}
  ],
  "strengths": ["strength 1", "strength 2", "strength 3"],  # 設定個人優勢欄位
  "career_objective": "career objective"  # 設定職涯目標欄位
}}
"""

    text = gemini_generate_with_retry(  # 接收 Gemini 回傳的文字內容
        client=client,  # 建立 Gemini 客戶端，成功時可呼叫 AI，失敗時用本機備援
        prompt=prompt,  # 建立要傳給 Gemini 的完整提示詞
        response_json=True,  # 設定 response_json 變數，供後續流程使用
        max_retries=3,  # 設定 max_retries 變數，供後續流程使用
        temperature=0.45,  # 設定 temperature 變數，供後續流程使用
        max_output_tokens=4096,  # 設定 max_output_tokens 變數，供後續流程使用
    )

    if not text:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        print("Using local fallback resume content.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return build_fallback_resume_content(raw)  # 回傳處理結果給呼叫這個函式的地方使用

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        data = extract_json_from_text(text)  # 把網站回傳的 JSON 內容轉成 Python 字典

        required_keys = [  # 列出履歷 JSON 必須包含的欄位，用來檢查 AI 回傳格式
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

        for key in required_keys:  # 使用迴圈逐一處理清單或資料集合中的每個項目
            if key not in data:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                raise ValueError(f"Missing key: {key}")

        return data  # 回傳處理結果給呼叫這個函式的地方使用

    except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
        print("Gemini JSON parse failed. Using local fallback content.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        print("Error:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return build_fallback_resume_content(raw)  # 回傳處理結果給呼叫這個函式的地方使用


# ============================================================
# Job Fetching
# ============================================================

def fetch_104_jobs_direct(job_title, location, salary_min, limit=50):  # 直接呼叫 104 搜尋 API 抓取職缺資料
    jobs = []  # 建立空清單，用來存放整理後的職缺資料
    keyword = f"{job_title} {location}".strip()  # 把職稱、地點與薪資條件組成搜尋關鍵字
    api_url = "https://www.104.com.tw/jobs/search/list"  # 設定 104 職缺搜尋 API 的網址

    headers = {  # 設定 HTTP 請求標頭，模擬瀏覽器並避免網站直接拒絕請求
        "User-Agent": "Mozilla/5.0",  # 設定字典欄位，讓資料可以用固定格式保存
        "Referer": build_104_search_url(job_title, location, salary_min),  # 設定字典欄位，讓資料可以用固定格式保存
        "Accept": "application/json, text/plain, */*",  # 設定字典欄位，讓資料可以用固定格式保存
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",  # 設定字典欄位，讓資料可以用固定格式保存
    }

    page = 1  # 設定目前抓取的頁數，後面會逐頁往下抓

    while len(jobs) < limit and page <= 10:  # 使用 while 迴圈持續執行，直到條件不成立為止
        params = {  # 設定送給求職網站 API 的查詢參數
            "ro": "0",  # 設定字典欄位，讓資料可以用固定格式保存
            "kwop": "7",  # 設定字典欄位，讓資料可以用固定格式保存
            "keyword": keyword,  # 設定字典欄位，讓資料可以用固定格式保存
            "expansionType": "area,spec,com,job,wf,wktm",  # 設定字典欄位，讓資料可以用固定格式保存
            "order": "15",  # 設定字典欄位，讓資料可以用固定格式保存
            "asc": "0",  # 設定字典欄位，讓資料可以用固定格式保存
            "page": str(page),  # 設定字典欄位，讓資料可以用固定格式保存
            "mode": "s",  # 設定字典欄位，讓資料可以用固定格式保存
            "jobsource": "joblist_search",  # 設定字典欄位，讓資料可以用固定格式保存
        }

        try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
            res = requests.get(api_url, headers=headers, params=params, timeout=15)  # 發送網路請求並取得網站回應
            res.raise_for_status()  # 如果 HTTP 回應狀態不是成功，就丟出錯誤交給 except 處理
            data = res.json()  # 把網站回傳的 JSON 內容轉成 Python 字典
            job_list = data.get("data", {}).get("list", [])  # 從 API 回傳資料中取出真正的職缺清單

            if not job_list:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
                break  # 中止目前迴圈，避免繼續處理不需要的資料

            for item in job_list:  # 使用迴圈逐一處理清單或資料集合中的每個項目
                if len(jobs) >= limit:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    break  # 中止目前迴圈，避免繼續處理不需要的資料

                title = clean_text(item.get("jobName", ""))  # 取得並清理職缺名稱
                company = clean_text(item.get("custName", ""))  # 取得並清理公司名稱
                job_location = clean_text(  # 取得並清理職缺地點
                    item.get("jobAddrNoDesc", "")
                    or item.get("jobAddress", "")
                    or item.get("areaDesc", "")
                )
                salary = clean_text(item.get("salaryDesc", ""))  # 取得並清理職缺薪資文字
                snippet = clean_text(item.get("description", ""))  # 取得並清理職缺摘要或工作描述

                link = ""  # 先建立空連結變數，後面再放入職缺網址
                raw_link = item.get("link", "")  # 取得網站回傳的原始職缺連結資料

                if isinstance(raw_link, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    link = raw_link.get("job", "") or raw_link.get("cust", "")  # 先建立空連結變數，後面再放入職缺網址
                elif isinstance(raw_link, str):  # 前一個條件不成立時，改檢查這個替代條件
                    link = raw_link  # 先建立空連結變數，後面再放入職缺網址

                link = normalize_url(link, "https://www.104.com.tw")  # 先建立空連結變數，後面再放入職缺網址

                job = {  # 把單一職缺整理成統一格式，方便後續評分與輸出
                    "platform": "104 Job Bank",  # 紀錄職缺來源平台
                    "title": title,  # 紀錄職缺名稱
                    "company": company if company else "Not clearly shown",  # 紀錄公司名稱
                    "location": job_location if job_location else "Not clearly shown",  # 紀錄工作地點
                    "salary": salary if salary else "Not clearly shown",  # 紀錄薪資資訊
                    "snippet": snippet,  # 紀錄職缺摘要或描述
                    "url": link,  # 紀錄職缺網址
                    "source": "104 direct search",  # 紀錄資料取得方式
                }

                score_job_keyword(job, job_title, location, salary_min)  # 替目前職缺計算本機關鍵字分數
                jobs.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用

            page += 1
            time.sleep(0.4)  # 暫停一小段時間，避免請求過快造成網站或 API 限制

        except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
            print("104 direct fetch failed:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
            break  # 中止目前迴圈，避免繼續處理不需要的資料

    return jobs  # 回傳整理完成的職缺清單


def extract_json_ld_jobs(soup):  # 從 HTML 的 JSON-LD 結構化資料中提取 JobPosting 職缺
    jobs = []  # 建立空清單，用來存放整理後的職缺資料

    def walk(obj):  # 定義 walk 函式，供後續程式流程呼叫
        found = []  # 建立暫存變數，協助完成資料清理、判斷或比對流程

        if isinstance(obj, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            obj_type = obj.get("@type", "")  # 設定 obj_type 變數，供後續流程使用

            if isinstance(obj_type, list):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                is_job = "JobPosting" in obj_type  # 設定 is_job 變數，供後續流程使用
            else:  # 前面條件都不符合時，執行這個預設分支
                is_job = obj_type == "JobPosting"  # 設定 is_job 變數，供後續流程使用

            if is_job:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                found.append(obj)  # 把整理好的資料加入清單，供後續輸出或排序使用

            for value in obj.values():  # 使用迴圈逐一處理清單或資料集合中的每個項目
                found.extend(walk(value))  # 把另一個清單的內容接到目前清單後方

        elif isinstance(obj, list):  # 前一個條件不成立時，改檢查這個替代條件
            for item in obj:  # 使用迴圈逐一處理清單或資料集合中的每個項目
                found.extend(walk(item))  # 把另一個清單的內容接到目前清單後方

        return found  # 回傳處理結果給呼叫這個函式的地方使用

    for script in soup.select('script[type="application/ld+json"]'):  # 使用迴圈逐一處理清單或資料集合中的每個項目
        try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
            raw = script.get_text(strip=True)  # 存放 DuckDuckGo 搜尋回來的原始搜尋結果
            if not raw:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            data = json.loads(raw)  # 把網站回傳的 JSON 內容轉成 Python 字典
            job_objects = walk(data)  # 設定 job_objects 變數，供後續流程使用

            for j in job_objects:  # 使用迴圈逐一處理清單或資料集合中的每個項目
                title = clean_text(j.get("title", ""))  # 取得並清理職缺名稱
                url = j.get("url", "") or j.get("sameAs", "")  # 設定 url 變數，供後續流程使用

                company = "Not clearly shown"  # 取得並清理公司名稱
                hiring_org = j.get("hiringOrganization", {})  # 設定 hiring_org 變數，供後續流程使用
                if isinstance(hiring_org, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    company = clean_text(hiring_org.get("name", "")) or "Not clearly shown"  # 取得並清理公司名稱

                location_text = "Not clearly shown"  # 設定 location_text 變數，供後續流程使用
                job_location = j.get("jobLocation", {})  # 取得並清理職缺地點
                if isinstance(job_location, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    address = job_location.get("address", {})  # 設定 address 變數，供後續流程使用
                    if isinstance(address, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                        location_text = clean_text(  # 設定 location_text 變數，供後續流程使用
                            " ".join([
                                str(address.get("addressRegion", "")),
                                str(address.get("addressLocality", "")),
                                str(address.get("streetAddress", "")),
                            ])
                        ) or "Not clearly shown"

                salary = "Not clearly shown"  # 取得並清理職缺薪資文字
                base_salary = j.get("baseSalary", {})  # 設定 base_salary 變數，供後續流程使用
                if isinstance(base_salary, dict):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    salary = clean_text(json.dumps(base_salary, ensure_ascii=False))  # 取得並清理職缺薪資文字

                if title and url:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                    jobs.append({  # 把整理好的資料加入清單，供後續輸出或排序使用
                        "title": title,  # 紀錄職缺名稱
                        "company": company,  # 紀錄公司名稱
                        "location": location_text,  # 紀錄工作地點
                        "salary": salary,  # 紀錄薪資資訊
                        "snippet": "",  # 紀錄職缺摘要或描述
                        "url": normalize_url(url, "https://www.1111.com.tw"),  # 紀錄職缺網址
                    })

        except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
            continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

    return jobs  # 回傳整理完成的職缺清單


def guess_company_from_text(text):  # 用正規表示式從文字中猜測公司名稱
    m = re.search(  # 設定 m 變數，供後續流程使用
        r"([\u4e00-\u9fa5A-Za-z0-9（）()股份有限公司]{2,40}(?:股份有限公司|有限公司|公司))",
        text,
    )
    if m:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return m.group(1)  # 回傳處理結果給呼叫這個函式的地方使用
    return "Not clearly shown"  # 回傳處理結果給呼叫這個函式的地方使用


def fetch_1111_jobs_direct(job_title, location, salary_min, limit=50):  # 抓取 1111 搜尋頁面並解析 JSON-LD 與 HTML 職缺資料
    jobs = []  # 建立空清單，用來存放整理後的職缺資料
    url = build_1111_search_url(job_title, location, salary_min)  # 設定 url 變數，供後續流程使用

    headers = {  # 設定 HTTP 請求標頭，模擬瀏覽器並避免網站直接拒絕請求
        "User-Agent": "Mozilla/5.0",  # 設定字典欄位，讓資料可以用固定格式保存
        "Referer": "https://www.1111.com.tw/",  # 設定字典欄位，讓資料可以用固定格式保存
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",  # 設定字典欄位，讓資料可以用固定格式保存
    }

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        res = requests.get(url, headers=headers, timeout=15)  # 發送網路請求並取得網站回應
        res.raise_for_status()  # 如果 HTTP 回應狀態不是成功，就丟出錯誤交給 except 處理
        soup = BeautifulSoup(res.text, "html.parser")  # 設定 soup 變數，供後續流程使用

        json_ld_jobs = extract_json_ld_jobs(soup)  # 設定 json_ld_jobs 變數，供後續流程使用

        for item in json_ld_jobs:  # 使用迴圈逐一處理清單或資料集合中的每個項目
            if len(jobs) >= limit:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                break  # 中止目前迴圈，避免繼續處理不需要的資料

            job = {  # 把單一職缺整理成統一格式，方便後續評分與輸出
                "platform": "1111 Job Bank",  # 紀錄職缺來源平台
                "title": item.get("title", ""),  # 紀錄職缺名稱
                "company": item.get("company", "Not clearly shown"),  # 紀錄公司名稱
                "location": item.get("location", "Not clearly shown"),  # 紀錄工作地點
                "salary": item.get("salary", "Not clearly shown"),  # 紀錄薪資資訊
                "snippet": item.get("snippet", ""),  # 紀錄職缺摘要或描述
                "url": item.get("url", ""),  # 紀錄職缺網址
                "source": "1111 JSON-LD",  # 紀錄資料取得方式
            }

            score_job_keyword(job, job_title, location, salary_min)  # 替目前職缺計算本機關鍵字分數
            jobs.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用

        seen_urls = set(job["url"] for job in jobs)  # 記錄已經收錄過的職缺網址，避免重複加入

        for a in soup.find_all("a", href=True):  # 使用迴圈逐一處理清單或資料集合中的每個項目
            if len(jobs) >= limit:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                break  # 中止目前迴圈，避免繼續處理不需要的資料

            href = a.get("href", "")  # 設定 href 變數，供後續流程使用
            text = clean_text(a.get_text(" ", strip=True))  # 接收 Gemini 回傳的文字內容

            if not text or len(text) < 2:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            is_job_link = (  # 設定 is_job_link 變數，供後續流程使用
                "/job/" in href.lower()
                or "job-bank/job-description" in href.lower()
                or "job.asp" in href.lower()
            )

            if not is_job_link:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            full_url = normalize_url(href, "https://www.1111.com.tw")  # 把職缺連結轉成完整網址

            if full_url in seen_urls:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            parent = a.find_parent(["article", "li", "div"])  # 取得職缺連結外層區塊，用來抓更多公司、地點與薪資文字
            parent_text = clean_text(parent.get_text(" ", strip=True)) if parent else text  # 清理職缺外層區塊文字，作為 HTML 備援解析依據

            if job_title not in parent_text and job_title not in text:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            job = {  # 把單一職缺整理成統一格式，方便後續評分與輸出
                "platform": "1111 Job Bank",  # 紀錄職缺來源平台
                "title": text,  # 紀錄職缺名稱
                "company": guess_company_from_text(parent_text),  # 紀錄公司名稱
                "location": location if location in parent_text else "Not clearly shown",  # 紀錄工作地點
                "salary": extract_salary_string(parent_text),  # 紀錄薪資資訊
                "snippet": parent_text[:350],  # 紀錄職缺摘要或描述
                "url": full_url,  # 紀錄職缺網址
                "source": "1111 HTML parsing",  # 紀錄資料取得方式
            }

            score_job_keyword(job, job_title, location, salary_min)  # 替目前職缺計算本機關鍵字分數
            jobs.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用
            seen_urls.add(full_url)

    except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
        print("1111 direct fetch failed:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    return jobs  # 回傳整理完成的職缺清單


def search_duckduckgo(keyword, max_results=50):  # 用 DuckDuckGo 當備援搜尋，抓取求職網站上的職缺頁面
    url = f"https://html.duckduckgo.com/html/?q={quote(keyword)}"  # 設定 url 變數，供後續流程使用
    headers = {"User-Agent": "Mozilla/5.0"}  # 設定 HTTP 請求標頭，模擬瀏覽器並避免網站直接拒絕請求
    results = []  # 設定 results 變數，供後續流程使用

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        res = requests.get(url, headers=headers, timeout=15)  # 發送網路請求並取得網站回應
        res.raise_for_status()  # 如果 HTTP 回應狀態不是成功，就丟出錯誤交給 except 處理
        soup = BeautifulSoup(res.text, "html.parser")  # 設定 soup 變數，供後續流程使用

        for block in soup.select(".result"):  # 使用迴圈逐一處理清單或資料集合中的每個項目
            title_tag = block.select_one(".result__a") or block.select_one(".result__title a")  # 設定 title_tag 變數，供後續流程使用
            snippet_tag = block.select_one(".result__snippet")  # 設定 snippet_tag 變數，供後續流程使用

            if not title_tag:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            title = clean_text(title_tag.get_text(" ", strip=True))  # 取得並清理職缺名稱
            link = normalize_duckduckgo_link(title_tag.get("href", ""))  # 先建立空連結變數，後面再放入職缺網址
            snippet = clean_text(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""  # 取得並清理職缺摘要或工作描述

            if title and link:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                results.append({  # 把整理好的資料加入清單，供後續輸出或排序使用
                    "title": title,  # 紀錄職缺名稱
                    "link": link,  # 設定字典欄位，讓資料可以用固定格式保存
                    "snippet": snippet,  # 紀錄職缺摘要或描述
                })

            if len(results) >= max_results:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                break  # 中止目前迴圈，避免繼續處理不需要的資料

    except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
        print("DuckDuckGo fallback failed:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    return results  # 回傳處理結果給呼叫這個函式的地方使用


def fallback_search_platform(platform, domain, job_title, location, salary_min, limit=50):  # 當直接抓取結果太少時，用搜尋引擎備援補足職缺
    query = f'site:{domain} "{job_title}" "{location}"'  # 設定 query 變數，供後續流程使用
    raw = search_duckduckgo(query, max_results=limit)  # 存放 DuckDuckGo 搜尋回來的原始搜尋結果
    jobs = []  # 建立空清單，用來存放整理後的職缺資料

    for item in raw:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        job = {  # 把單一職缺整理成統一格式，方便後續評分與輸出
            "platform": platform,  # 紀錄職缺來源平台
            "title": item["title"],  # 紀錄職缺名稱
            "company": "Not clearly shown",  # 紀錄公司名稱
            "location": location if location in item["title"] + item["snippet"] else "Not clearly shown",  # 紀錄工作地點
            "salary": extract_salary_string(item["title"] + " " + item["snippet"]),  # 紀錄薪資資訊
            "snippet": item["snippet"],  # 紀錄職缺摘要或描述
            "url": item["link"],  # 紀錄職缺網址
            "source": "DuckDuckGo fallback",  # 紀錄資料取得方式
        }

        score_job_keyword(job, job_title, location, salary_min)  # 替目前職缺計算本機關鍵字分數
        jobs.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用

    return jobs  # 回傳整理完成的職缺清單


def get_raw_jobs(job_title, location, salary_min):  # 整合 104 與 1111 的職缺資料，去除重複後排序回傳
    print("Fetching 104 jobs...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    jobs_104 = fetch_104_jobs_direct(  # 設定 jobs_104 變數，供後續流程使用
        job_title=job_title,  # 設定 job_title 變數，供後續流程使用
        location=location,  # 設定 location 變數，供後續流程使用
        salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
        limit=FETCH_PER_PLATFORM,  # 設定 limit 變數，供後續流程使用
    )

    if len(jobs_104) < 10:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        print("104 direct results are too few. Using fallback search...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        jobs_104.extend(  # 把另一個清單的內容接到目前清單後方
            fallback_search_platform(
                platform="104 Job Bank",  # 設定 platform 變數，供後續流程使用
                domain="104.com.tw",  # 設定 domain 變數，供後續流程使用
                job_title=job_title,  # 設定 job_title 變數，供後續流程使用
                location=location,  # 設定 location 變數，供後續流程使用
                salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
                limit=FETCH_PER_PLATFORM,  # 設定 limit 變數，供後續流程使用
            )
        )

    print("Fetching 1111 jobs...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    jobs_1111 = fetch_1111_jobs_direct(  # 設定 jobs_1111 變數，供後續流程使用
        job_title=job_title,  # 設定 job_title 變數，供後續流程使用
        location=location,  # 設定 location 變數，供後續流程使用
        salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
        limit=FETCH_PER_PLATFORM,  # 設定 limit 變數，供後續流程使用
    )

    if len(jobs_1111) < 10:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        print("1111 direct results are too few. Using fallback search...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        jobs_1111.extend(  # 把另一個清單的內容接到目前清單後方
            fallback_search_platform(
                platform="1111 Job Bank",  # 設定 platform 變數，供後續流程使用
                domain="1111.com.tw",  # 設定 domain 變數，供後續流程使用
                job_title=job_title,  # 設定 job_title 變數，供後續流程使用
                location=location,  # 設定 location 變數，供後續流程使用
                salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
                limit=FETCH_PER_PLATFORM,  # 設定 limit 變數，供後續流程使用
            )
        )

    unique = []  # 建立去重後的職缺清單
    seen = set()  # 建立集合記錄已出現職缺，避免同一筆資料重複輸出

    for job in jobs_104 + jobs_1111:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        url = job.get("url", "")  # 設定 url 變數，供後續流程使用
        key = url if url else f"{job.get('platform')}|{job.get('title')}|{job.get('company')}"  # 建立職缺去重用的識別鍵，優先使用網址

        if key in seen:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

        seen.add(key)
        unique.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用

    unique.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)  # 依照指定分數或條件排序資料
    return unique[:TOTAL_JOBS_TO_FETCH]  # 回傳處理結果給呼叫這個函式的地方使用


# ============================================================
# Gemini Job Ranking
# ============================================================

def compact_job_for_gemini(job, index):  # 把完整職缺壓縮成 Gemini 評分需要的精簡格式
    return {  # 回傳處理結果給呼叫這個函式的地方使用
        "job_index": index,  # 提供 Gemini 對應原始職缺的編號
        "platform": job.get("platform", ""),  # 紀錄職缺來源平台
        "title": job.get("title", ""),  # 紀錄職缺名稱
        "company": job.get("company", ""),  # 紀錄公司名稱
        "location": job.get("location", ""),  # 紀錄工作地點
        "salary": job.get("salary", ""),  # 紀錄薪資資訊
        "salary_status": job.get("salary_status", ""),  # 紀錄薪資是否符合條件的判斷結果
        "matched_benefits": job.get("matched_benefits", []),  # 紀錄符合使用者需求的福利
        "missing_benefits": job.get("missing_benefits", []),  # 紀錄職缺中沒有明確出現的福利
        "benefit_match_status": job.get("benefit_match_status", ""),  # 紀錄福利比對的摘要結果
        "keyword_score": job.get("keyword_score", 0),  # 紀錄本機關鍵字評分
        "snippet": job.get("snippet", "")[:300],  # 紀錄職缺摘要或描述
        "url": job.get("url", ""),  # 紀錄職缺網址
    }


def local_relevance_fallback(jobs, limit=20):  # 當 Gemini 評分失敗時，用關鍵字分數產生本機推薦結果
    ranked = []  # 設定 ranked 變數，供後續流程使用

    for job in jobs:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        keyword_score = job.get("keyword_score", 0)  # 設定 keyword_score 變數，供後續流程使用
        match_score = min(100, max(30, keyword_score * 5))  # 取得 Gemini 給出的職缺匹配分數

        new_job = job.copy()  # 設定 new_job 變數，供後續流程使用
        new_job["match_score"] = match_score
        new_job["gemini_reason"] = "Gemini ranking failed. This result is ranked by keyword relevance only."
        new_job["fit_points"] = "Matched by job title, location, salary text, benefit keywords, or keyword similarity."
        new_job["concerns"] = "The relevance was not deeply evaluated by Gemini, so benefit matching is based on keyword text only."

        ranked.append(new_job)  # 把整理好的資料加入清單，供後續輸出或排序使用

    ranked.sort(key=lambda x: x.get("match_score", 0), reverse=True)  # 依照指定分數或條件排序資料
    return ranked[:limit]  # 回傳處理結果給呼叫這個函式的地方使用


def rank_jobs_with_gemini(client, raw_resume, raw_jobs):  # 使用 Gemini 根據履歷與職缺內容進行匹配評分
    if not raw_jobs:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return []  # 回傳空清單，代表目前沒有符合的資料

    if client is None:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)  # 回傳整理完成的職缺清單

    compact_jobs = [  # 把職缺資料壓縮成 Gemini 評分需要的欄位，避免 prompt 過長
        compact_job_for_gemini(job, i + 1)
        for i, job in enumerate(raw_jobs)
    ]

    prompt = f"""  # 建立要傳給 Gemini 的完整提示詞
You are an expert job matching assistant.

Evaluate the relevance between the candidate's resume profile and the fetched job postings.

Candidate profile:
{json.dumps(raw_resume, ensure_ascii=False, indent=2)}  # 把 Python 資料轉成 JSON 字串，方便儲存或傳給 Gemini

Fetched job postings:
{json.dumps(compact_jobs, ensure_ascii=False, indent=2)}  # 把 Python 資料轉成 JSON 字串，方便儲存或傳給 Gemini

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
  "recommendations": [  # 設定字典欄位，讓資料可以用固定格式保存
    {{
      "job_index": 1,  # 提供 Gemini 對應原始職缺的編號
      "match_score": 85,  # 紀錄 Gemini 給出的匹配分數
      "reason": "why this job matches the candidate",  # 設定字典欄位，讓資料可以用固定格式保存
      "fit_points": "specific matching points",  # 紀錄職缺符合履歷條件的重點
      "concerns": "salary uncertainty, experience gap, or other concerns"  # 紀錄可能不符合或需要注意的地方
    }}
  ]
}}
"""

    text = gemini_generate_with_retry(  # 接收 Gemini 回傳的文字內容
        client=client,  # 建立 Gemini 客戶端，成功時可呼叫 AI，失敗時用本機備援
        prompt=prompt,  # 建立要傳給 Gemini 的完整提示詞
        response_json=True,  # 設定 response_json 變數，供後續流程使用
        max_retries=3,  # 設定 max_retries 變數，供後續流程使用
        temperature=0.2,  # 設定 temperature 變數，供後續流程使用
        max_output_tokens=4096,  # 設定 max_output_tokens 變數，供後續流程使用
    )

    if not text:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)  # 回傳整理完成的職缺清單

    try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
        data = extract_json_from_text(text)  # 把網站回傳的 JSON 內容轉成 Python 字典
        recs = data.get("recommendations", [])  # 設定 recs 變數，供後續流程使用
        ranked_jobs = []  # 存放 Gemini 評分後通過門檻的職缺

        for rec in recs:  # 使用迴圈逐一處理清單或資料集合中的每個項目
            try:  # 開始嘗試執行可能會失敗的程式碼，避免整個程式中斷
                job_index = int(rec.get("job_index", 0))  # 取得 Gemini 指定的職缺序號，用來回頭對應原始職缺
                match_score = int(rec.get("match_score", 0))  # 取得 Gemini 給出的職缺匹配分數
            except Exception:  # 發生解析或請求錯誤時進入這裡，避免程式直接停止
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            if job_index < 1 or job_index > len(raw_jobs):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            if match_score < MATCH_SCORE_THRESHOLD:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                continue  # 跳過本次迴圈剩下的程式，直接進入下一輪

            job = raw_jobs[job_index - 1].copy()  # 把單一職缺整理成統一格式，方便後續評分與輸出
            job["match_score"] = match_score
            job["gemini_reason"] = clean_text(rec.get("reason", ""))  # 清理文字中的 HTML 與多餘空白
            job["fit_points"] = clean_text(rec.get("fit_points", ""))  # 清理文字中的 HTML 與多餘空白
            job["concerns"] = clean_text(rec.get("concerns", ""))  # 清理文字中的 HTML 與多餘空白

            ranked_jobs.append(job)  # 把整理好的資料加入清單，供後續輸出或排序使用

        ranked_jobs.sort(  # 依照指定分數或條件排序資料
            key=lambda x: (x.get("match_score", 0), x.get("keyword_score", 0)),  # 建立職缺去重用的識別鍵，優先使用網址
            reverse=True,  # 設定 reverse 變數，供後續流程使用
        )

        if not ranked_jobs:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
            return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)  # 回傳整理完成的職缺清單

        return ranked_jobs[:OUTPUT_RECOMMEND_LIMIT]  # 回傳整理完成的職缺清單

    except Exception as e:  # 捕捉執行過程中的錯誤，讓程式可以顯示錯誤並繼續備援流程
        print("Gemini ranking parse failed. Using local fallback.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        print("Error:", e)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
        return local_relevance_fallback(raw_jobs, OUTPUT_RECOMMEND_LIMIT)  # 回傳整理完成的職缺清單


# ============================================================
# PDF Styles and Components
# ============================================================

def make_styles():  # 建立 PDF 各區塊會使用的文字樣式
    navy = colors.HexColor("#1F3A5F")  # 設定 PDF 視覺設計用的顏色
    teal = colors.HexColor("#2E7D7B")  # 設定 PDF 視覺設計用的顏色
    dark = colors.HexColor("#263238")  # 設定 PDF 視覺設計用的顏色
    gray = colors.HexColor("#546E7A")  # 設定 PDF 視覺設計用的顏色

    return {  # 回傳處理結果給呼叫這個函式的地方使用
        "name": ParagraphStyle(  # 設定履歷姓名欄位
            name="Name",  # 設定 name 變數，供後續流程使用
            fontName=PDF_BOLD,  # 設定 fontName 變數，供後續流程使用
            fontSize=22,  # 設定 fontSize 變數，供後續流程使用
            leading=28,  # 設定 leading 變數，供後續流程使用
            textColor=navy,  # 設定 textColor 變數，供後續流程使用
            alignment=TA_CENTER,  # 設定 alignment 變數，供後續流程使用
            spaceAfter=4,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "headline": ParagraphStyle(  # 設定履歷標題欄位
            name="Headline",  # 設定 name 變數，供後續流程使用
            fontName=PDF_FONT,  # 設定 fontName 變數，供後續流程使用
            fontSize=10.5,  # 設定 fontSize 變數，供後續流程使用
            leading=14,  # 設定 leading 變數，供後續流程使用
            textColor=teal,  # 設定 textColor 變數，供後續流程使用
            alignment=TA_CENTER,  # 設定 alignment 變數，供後續流程使用
            spaceAfter=6,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "section": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="Section",  # 設定 name 變數，供後續流程使用
            fontName=PDF_BOLD,  # 設定 fontName 變數，供後續流程使用
            fontSize=12.5,  # 設定 fontSize 變數，供後續流程使用
            leading=16,  # 設定 leading 變數，供後續流程使用
            textColor=navy,  # 設定 textColor 變數，供後續流程使用
            spaceBefore=8,  # 設定 spaceBefore 變數，供後續流程使用
            spaceAfter=5,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "body": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="Body",  # 設定 name 變數，供後續流程使用
            fontName=PDF_FONT,  # 設定 fontName 變數，供後續流程使用
            fontSize=9,  # 設定 fontSize 變數，供後續流程使用
            leading=13,  # 設定 leading 變數，供後續流程使用
            textColor=dark,  # 設定 textColor 變數，供後續流程使用
            spaceAfter=5,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "body_bold": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="BodyBold",  # 設定 name 變數，供後續流程使用
            fontName=PDF_BOLD,  # 設定 fontName 變數，供後續流程使用
            fontSize=9,  # 設定 fontSize 變數，供後續流程使用
            leading=13,  # 設定 leading 變數，供後續流程使用
            textColor=dark,  # 設定 textColor 變數，供後續流程使用
            spaceAfter=4,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "small": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="Small",  # 設定 name 變數，供後續流程使用
            fontName=PDF_FONT,  # 設定 fontName 變數，供後續流程使用
            fontSize=8.2,  # 設定 fontSize 變數，供後續流程使用
            leading=11,  # 設定 leading 變數，供後續流程使用
            textColor=gray,  # 設定 textColor 變數，供後續流程使用
            spaceAfter=3,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "label": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="Label",  # 設定 name 變數，供後續流程使用
            fontName=PDF_BOLD,  # 設定 fontName 變數，供後續流程使用
            fontSize=8.2,  # 設定 fontSize 變數，供後續流程使用
            leading=11,  # 設定 leading 變數，供後續流程使用
            textColor=navy,  # 設定 textColor 變數，供後續流程使用
            spaceAfter=3,  # 設定 spaceAfter 變數，供後續流程使用
        ),
        "bullet": ParagraphStyle(  # 設定字典欄位，讓資料可以用固定格式保存
            name="Bullet",  # 設定 name 變數，供後續流程使用
            fontName=PDF_FONT,  # 設定 fontName 變數，供後續流程使用
            fontSize=8.8,  # 設定 fontSize 變數，供後續流程使用
            leading=12,  # 設定 leading 變數，供後續流程使用
            leftIndent=9,  # 設定 leftIndent 變數，供後續流程使用
            firstLineIndent=-6,  # 設定 firstLineIndent 變數，供後續流程使用
            textColor=dark,  # 設定 textColor 變數，供後續流程使用
            spaceAfter=2,  # 設定 spaceAfter 變數，供後續流程使用
        ),
    }


def para(text, style):  # 把文字包成 ReportLab Paragraph 段落物件
    return Paragraph(escape_text(text), style)  # 回傳處理結果給呼叫這個函式的地方使用


def section_title(title, styles):  # 建立 PDF 區塊標題表格，讓履歷版面更清楚
    table = Table(  # 建立表格資料結構，後面用來輸出成 PDF 表格
        [[Paragraph(escape_text(title), styles["section"])]],  # 建立 PDF 段落元件，讓文字能依樣式顯示
        colWidths=[170 * mm],  # 設定 colWidths 變數，供後續流程使用
    )

    table.setStyle(TableStyle([  # 設定 PDF 表格的背景、邊框、內距與對齊方式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F1F5")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#A7C7D9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    return table  # 回傳處理結果給呼叫這個函式的地方使用


def info_table(rows, styles, label_width=45 * mm, value_width=125 * mm, bg="#F4F7F6", border="#C5D6D4"):  # 建立 PDF 中兩欄式資訊表格
    data = []  # 把網站回傳的 JSON 內容轉成 Python 字典

    for label, value in rows:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        data.append([  # 把整理好的資料加入清單，供後續輸出或排序使用
            Paragraph(escape_text(label), styles["label"]),  # 建立 PDF 段落元件，讓文字能依樣式顯示
            Paragraph(escape_text(value), styles["small"]),  # 建立 PDF 段落元件，讓文字能依樣式顯示
        ])

    table = Table(data, colWidths=[label_width, value_width])  # 建立表格資料結構，後面用來輸出成 PDF 表格

    table.setStyle(TableStyle([  # 設定 PDF 表格的背景、邊框、內距與對齊方式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(border)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDE7E5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    return table  # 回傳處理結果給呼叫這個函式的地方使用


def bullet_list(items, styles):  # 把清單資料轉成 PDF 條列段落
    story = []  # 建立 PDF 內容清單，後面會依序加入段落、表格與空白

    if not items:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        items = ["None"]  # 設定 items 變數，供後續流程使用

    for item in items:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        story.append(Paragraph(f"- {escape_text(item)}", styles["bullet"]))  # 把整理好的資料加入清單，供後續輸出或排序使用

    return story  # 回傳處理結果給呼叫這個函式的地方使用


def chip_table(items, styles, max_cols=3):  # 把技能等短文字做成 PDF 標籤式表格
    clean_items = [safe_text(x) for x in items if safe_text(x)]  # 設定 clean_items 變數，供後續流程使用

    if not clean_items:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
        clean_items = ["None"]  # 設定 clean_items 變數，供後續流程使用

    rows = []  # 建立表格資料結構，後面用來輸出成 PDF 表格
    row = []  # 建立表格資料結構，後面用來輸出成 PDF 表格

    for item in clean_items:  # 使用迴圈逐一處理清單或資料集合中的每個項目
        row.append(Paragraph(escape_text(item), styles["small"]))  # 把整理好的資料加入清單，供後續輸出或排序使用

        if len(row) == max_cols:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
            rows.append(row)  # 把整理好的資料加入清單，供後續輸出或排序使用
            row = []  # 建立表格資料結構，後面用來輸出成 PDF 表格

    if row:  # 檢查條件是否成立，成立時執行下方縮排的程式碼
        while len(row) < max_cols:  # 使用 while 迴圈持續執行，直到條件不成立為止
            row.append("")  # 把整理好的資料加入清單，供後續輸出或排序使用
        rows.append(row)  # 把整理好的資料加入清單，供後續輸出或排序使用

    table = Table(rows, colWidths=[52 * mm] * max_cols)  # 建立表格資料結構，後面用來輸出成 PDF 表格

    table.setStyle(TableStyle([  # 設定 PDF 表格的背景、邊框、內距與對齊方式
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F0E6")),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9A7")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    return table  # 回傳處理結果給呼叫這個函式的地方使用


def draw_page_background(canvas_obj, doc):  # 繪製 PDF 每頁背景色塊與頁碼
    canvas_obj.saveState()  # 使用 PDF 畫布繪製背景色塊、文字或頁碼

    width, height = A4

    canvas_obj.setFillColor(colors.HexColor("#1F3A5F"))  # 使用 PDF 畫布繪製背景色塊、文字或頁碼
    canvas_obj.rect(0, height - 20 * mm, width, 20 * mm, fill=1, stroke=0)  # 使用 PDF 畫布繪製背景色塊、文字或頁碼

    canvas_obj.setFillColor(colors.HexColor("#5E7C3A"))  # 使用 PDF 畫布繪製背景色塊、文字或頁碼
    canvas_obj.rect(0, 0, width, 6 * mm, fill=1, stroke=0)  # 使用 PDF 畫布繪製背景色塊、文字或頁碼

    canvas_obj.setFont(PDF_FONT, 8)  # 使用 PDF 畫布繪製背景色塊、文字或頁碼
    canvas_obj.setFillColor(colors.white)  # 使用 PDF 畫布繪製背景色塊、文字或頁碼
    canvas_obj.drawRightString(width - 14 * mm, height - 9 * mm, f"Page {doc.page}")  # 使用 PDF 畫布繪製背景色塊、文字或頁碼

    canvas_obj.restoreState()  # 使用 PDF 畫布繪製背景色塊、文字或頁碼


def create_resume_pdf(content, output_path=OUTPUT_PDF):  # 把整理好的履歷內容組成 PDF 並輸出成檔案
    styles = make_styles()  # 建立 PDF 使用的所有文字樣式

    doc = SimpleDocTemplate(  # 建立 PDF 文件物件，設定紙張大小與邊界
        output_path,
        pagesize=A4,  # 設定 pagesize 變數，供後續流程使用
        rightMargin=17 * mm,  # 設定 rightMargin 變數，供後續流程使用
        leftMargin=17 * mm,  # 設定 leftMargin 變數，供後續流程使用
        topMargin=26 * mm,  # 設定 topMargin 變數，供後續流程使用
        bottomMargin=14 * mm,  # 設定 bottomMargin 變數，供後續流程使用
    )

    story = []  # 建立 PDF 內容清單，後面會依序加入段落、表格與空白

    header = Table(  # 建立 PDF 履歷最上方的姓名與標題區塊
        [
            [Paragraph(escape_text(content.get("name", "")), styles["name"])],  # 建立 PDF 段落元件，讓文字能依樣式顯示
            [Paragraph(escape_text(content.get("headline", "")), styles["headline"])],  # 建立 PDF 段落元件，讓文字能依樣式顯示
        ],
        colWidths=[176 * mm],  # 設定 colWidths 變數，供後續流程使用
    )

    header.setStyle(TableStyle([  # 設定 PDF 表格的背景、邊框、內距與對齊方式
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D2DFE5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(header)  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    contact = content.get("contact", {})  # 取出履歷中的聯絡資料
    prefs = content.get("job_preferences", {})  # 取出求職偏好資料，例如職稱、地點、薪資與福利

    story.append(info_table([  # 把整理好的資料加入清單，供後續輸出或排序使用
        ("Address", contact.get("address", "")),
        ("Email", contact.get("email", "")),
        ("Phone", contact.get("phone", "")),
    ], styles, label_width=30 * mm, value_width=140 * mm))

    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(info_table([  # 把整理好的資料加入清單，供後續輸出或排序使用
        ("Target Position", prefs.get("target_position", "")),
        ("Preferred Location", prefs.get("target_location", "")),
        ("Expected Salary Range", prefs.get("expected_salary_range", prefs.get("expected_monthly_salary", ""))),
        ("Required Benefits", prefs.get("required_benefits_text", "None")),
    ], styles, label_width=50 * mm, value_width=120 * mm, bg="#FFF8E6", border="#D8B45A"))

    story.append(Spacer(1, 10))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Profile Summary", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(para(content.get("profile_summary", ""), styles["body"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Skills & Specialty", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Paragraph(f"Specialty: {escape_text(content.get('specialty', ''))}", styles["body_bold"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(chip_table(content.get("skills", []), styles, max_cols=3))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Education", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    for edu in content.get("education", []):  # 使用迴圈逐一處理清單或資料集合中的每個項目
        story.append(Paragraph(escape_text(edu.get("school", "")), styles["body_bold"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
        story.append(Paragraph(f"Major: {escape_text(edu.get('major', ''))}", styles["small"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
        story.append(Paragraph(escape_text(edu.get("description", "")), styles["small"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
        story.append(Spacer(1, 4))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Certificates", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.extend(bullet_list(content.get("certificates", []), styles))  # 把另一個清單的內容接到目前清單後方
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Competitions", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.extend(bullet_list(content.get("competitions", []), styles))  # 把另一個清單的內容接到目前清單後方
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Experience", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    for exp in content.get("experience", []):  # 使用迴圈逐一處理清單或資料集合中的每個項目
        story.append(Paragraph(escape_text(exp.get("title", "Experience")), styles["body_bold"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
        story.append(Paragraph(escape_text(exp.get("description", "")), styles["small"]))  # 把整理好的資料加入清單，供後續輸出或排序使用
        story.append(Spacer(1, 4))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Strengths", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.extend(bullet_list(content.get("strengths", []), styles))  # 把另一個清單的內容接到目前清單後方
    story.append(Spacer(1, 8))  # 把整理好的資料加入清單，供後續輸出或排序使用

    story.append(section_title("Career Objective", styles))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(Spacer(1, 5))  # 把整理好的資料加入清單，供後續輸出或排序使用
    story.append(para(content.get("career_objective", ""), styles["body"]))  # 把整理好的資料加入清單，供後續輸出或排序使用

    doc.build(  # 正式生成 PDF 檔案，並套用每頁背景
        story,
        onFirstPage=draw_page_background,  # 設定 onFirstPage 變數，供後續流程使用
        onLaterPages=draw_page_background,  # 設定 onLaterPages 變數，供後續流程使用
    )

    return output_path  # 回傳輸出檔案路徑，方便主程式顯示或後續使用


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
# Gemini Functions
# ============================================================
# 建立 Gemini API Client
# 這個函式的目的：
# 1. 檢查 Gemini 套件是否存在
# 2. 檢查 API KEY 是否存在
# 3. 建立 Gemini Client
# 4. 如果失敗則回傳 None
def make_gemini_client():

    # 安裝 google-genai 套件
    # True 代表已安裝
    # False 代表未安裝
    if not GEMINI_INSTALLED:
        # 顯示沒安裝的提示訊息
        print("google-genai is not installed. Using local fallback content.")

        # 回傳 None
        # 後續程式會改用本地 fallback 內容
        return None

    # 從系統環境變數中讀取 GEMINI_API_KEY
    # 例如：
    # export GEMINI_API_KEY=xxxx
    api_key = os.getenv("GEMINI_API_KEY")

    # API KEY 不存在的狀況
    if not api_key:
        print("GEMINI_API_KEY is not set. Using local fallback content.")
        return None

    # 嘗試建立 Gemini Client
    try:

        # 顯示成功訊息
        print("GEMINI_API_KEY loaded successfully.")

        # 建立 Gemini Client 物件
        # 後續所有 Gemini API 呼叫都會透過這個 client
        return genai.Client(api_key=api_key)

    # 如果建立失敗
    except Exception as e:

        # 顯示錯誤訊息
        print("Gemini client failed. Using local fallback content.")

        # 印出詳細錯誤內容
        print("Error:", e)
        return None


# 使用 Gemini 生成內容（包含 retry 機制）
#
# 參數說明：
# client            -> Gemini Client
# prompt            -> 要傳給 Gemini 的提示詞
# response_json     -> 是否要求 Gemini 回傳 JSON
# max_retries       -> 每個模型最多重試次數
# temperature       -> 回應創意程度
#
# 功能：
# 1. 嘗試多個 Gemini 模型
# 2. API 忙碌時自動 retry
# 3. 遇到失敗時自動切換模型
def gemini_generate_with_retry(client, prompt, response_json=True, max_retries=3, temperature=0.35):

    # 如果 client 是 None
    # 代表 Gemini 無法使用
    if client is None:
        return None

    # 用來記錄最後一次錯誤
    last_error = None

    # 記錄已使用模型
    # 避免重複使用
    used_models = []

    # 逐一嘗試 fallback 模型
    # GEMINI_FALLBACK_MODELS 通常是模型名稱 list
    # 例如：
    # ["gemini-1.5-pro", "gemini-1.5-flash"]
    for model in GEMINI_FALLBACK_MODELS:

        # 如果模型已經使用過
        if model in used_models:

            # 以 continue 跳過
            continue

        # 加入已使用清單
        used_models.append(model)

        # Retry 機制
        # 每個模型最多嘗試 max_retries 次
        for attempt in range(max_retries):
            try:

                # Gemini 設定參數
                config_kwargs = {"temperature": temperature}

                # 指定回傳格式為 JSON
                if response_json:
                    config_kwargs["response_mime_type"] = "application/json"

                # 呼叫 Gemini API
                response = client.models.generate_content(

                    # 指定模型名稱
                    model=model,

                    # 傳送 Prompt
                    contents=prompt,

                    # 建立 Gemini 設定物件
                    config=types.GenerateContentConfig(**config_kwargs),
                )

                # 如果 Gemini 有成功回傳文字
                if response.text and response.text.strip():

                    # 去除空白後回傳
                    return response.text.strip()

                # 如果 Gemini 回傳空字串
                last_error = RuntimeError("Gemini returned empty text.")

            # 發生其他錯誤
            except Exception as e:
                last_error = e
                error_text = str(e)

                # 判斷是否屬於「可重試錯誤」
                retryable = (
                    "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                    or "high demand" in error_text.lower()
                )

                if retryable:

                    # 計算等待時間
                    # attempt 越大等待越久
                    # random.random() 用來避免所有 request 同時重試
                    wait_time = 2 + attempt * 3 + random.random()

                    # 顯示提示訊息
                    print(f"Gemini is busy or rate-limited. Retry in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)

                    # 繼續 retry loop
                    continue

                print(f"Gemini model {model} failed:", e)

                # 跳出 retry loop
                break

        # 當前模型全部 retry 都失敗後
        # 嘗試下一個模型
        print("Trying next Gemini model if available...")

    # 所有模型都失敗
    print("Gemini failed after retries. Last error:", last_error)
    return None


# ============================================================
# Resume Content Generation
# ============================================================

# 建立本地 fallback 履歷內容
# 功能：
# 當 Gemini 無法使用時
# 用 Python 自動產生基本履歷資料
def build_fallback_resume_content(raw):

    # 將技能字串切割成 list
    #
    # 假設：
    # "Python, SQL, Excel"
    #
    # 會變成：
    # ["Python", "SQL", "Excel"]
    skills = split_comma_text(raw["skills"])

    # 同樣步驟處理考試證照
    certificates = split_comma_text(raw["certificates"])

    # 同樣步驟處理競賽經驗
    competitions = split_comma_text(raw["competitions"])

    # 如果沒有技能但有專長，將專長作為技能
    if not skills and raw["specialty"]:
        skills = [raw["specialty"]]

    # 如果沒有證照
    if not certificates:

        # 放入預設值
        certificates = ["None"]

    # 如果沒有競賽經驗
    if not competitions:
        competitions = ["None"]

    # 建立 summary（自我介紹）
    # 使用 f-string 插入使用者資料
    # 資料包括自我介紹、校系、求職方向、期望薪資等
    summary = (
        f"My name is {raw['name']}. I am currently studying at {raw['school']}, "
        f"majoring in {raw['major']}. I am interested in applying for "
        f"{raw['target_position']}-related positions in {raw['target_location']}. "
        f"My expected monthly salary is {raw['expected_monthly_salary']}. "
        f"My main specialty is {raw['specialty']}. Through academic learning, "
        "project participation, and practical training, I have developed analytical thinking, "
        "communication ability, teamwork, and a strong willingness to keep learning. "
    )

    # 工作經驗描述
    if raw["experience"]:
        summary += f"My previous work or internship experience includes {raw['experience']}. "

    # 結尾
    summary += (
        "I hope to apply my background and strengths in a real workplace, learn from experienced "
        "professionals, and gradually develop into a reliable and responsible team member."
    )

    # 回傳完整履歷的 dictionary
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


def generate_resume_content_with_gemini(client, raw):
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
{json.dumps(raw, ensure_ascii=False, indent=2)}

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

    text = gemini_generate_with_retry(
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
        data = extract_json_from_text(text)

        required_keys = [
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
            if key not in data:
                raise ValueError(f"Missing key: {key}")

        return data

    except Exception as e:
        print("Gemini JSON parse failed. Using local fallback content.")
        print("Error:", e)
        return build_fallback_resume_content(raw)


# ============================================================
# Job Fetching
# ============================================================

# 從 104 API 直接抓取職缺資料
#
# 參數：
# job_title  -> 職位名稱，例如 "Python工程師"
# location   -> 地區，例如 "台中市"
# salary_min -> 最低薪資
# limit      -> 最多抓幾筆資料
#
# 功能：
# 1. 呼叫 104 API
# 2. 解析 JSON
# 3. 整理成統一格式
# 4. 回傳職缺 list
def fetch_104_jobs_direct(job_title, location, salary_min, limit=50):

    # 建立空 list 儲存職缺
    jobs = []

    # 將職位與地區組合成搜尋關鍵字
    #
    # 例如：
    # "Python工程師 台中市"
    #
    # strip() 用來移除前後空白
    keyword = f"{job_title} {location}".strip()

    # 104網站的連結（URL）
    api_url = "https://www.104.com.tw/jobs/search/list"

    # HTTP Header
    # 很多網站會檢查 Header
    # 如果沒有 User-Agent
    # 可能會被擋下來
    headers = {
        # 偽裝成瀏覽器
        "User-Agent": "Mozilla/5.0",

        # Referer 表示從哪個頁面進來
        "Referer": build_104_search_url(job_title, location, salary_min),

        # 接受 JSON
        "Accept": "application/json, text/plain, */*",

        # 語言設定
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    page = 1

    # while 條件：
    #
    # 1. jobs 數量還沒達到 limit
    # 2. 最多抓 10 頁
    while len(jobs) < limit and page <= 10:

        # API Query Parameters
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

            # 發送 GET Request
            res = requests.get(api_url, headers=headers, params=params, timeout=15)

            # 如果 HTTP Status 不是 200
            # 會直接丟出 Exception
            res.raise_for_status()

            # 將 JSON 轉成 Python dict
            data = res.json()

            # 取得職缺 list
            #
            # data 結構：
            # {
            #   "data": {
            #       "list": [...]
            #   }
            # }
            job_list = data.get("data", {}).get("list", [])

            # 如果沒有資料
            if not job_list:

                # 結束 while loop
                break

            for item in job_list:

                # 如果已達上限
                if len(jobs) >= limit:
                    break

                # 取得職位名稱
                title = clean_text(item.get("jobName", ""))

                # 公司名稱
                company = clean_text(item.get("custName", ""))

                # 工作地點
                #
                # or 的意思：
                # 如果前面是空值
                # 就改用後面
                job_location = clean_text(
                    item.get("jobAddrNoDesc", "")
                    or item.get("jobAddress", "")
                    or item.get("areaDesc", "")
                )

                # 薪資資訊
                salary = clean_text(item.get("salaryDesc", ""))

                # 工作描述
                snippet = clean_text(item.get("description", ""))

                # 預設空連結
                link = ""

                # 原始 link 資料
                raw_link = item.get("link", "")

                # 有些 link 是 dict
                if isinstance(raw_link, dict):

                    # 先取 job link
                    # 如果沒有再取 cust link
                    link = raw_link.get("job", "") or raw_link.get("cust", "")

                # 有些 link 是字串
                elif isinstance(raw_link, str):
                    link = raw_link

                # 將相對網址轉成完整網址
                link = normalize_url(link, "https://www.104.com.tw")

                # 建立統一格式職缺資料
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

                # 幫職缺計算關鍵字分數
                #
                # 分數越高代表越符合搜尋條件
                score_job_keyword(job, job_title, location, salary_min)

                # 加入 jobs list
                jobs.append(job)

            page += 1

            # 暫停 0.4 秒
            #
            # 避免太快發 request 被網站封鎖
            time.sleep(0.4)

        # 如果發生錯誤
        except Exception as e:

            # 顯示錯誤訊息
            print("104 direct fetch failed:", e)

            # 停止抓取
            break

    # 回傳所有職缺
    return jobs


# 從 HTML 中提取 JSON-LD 職缺資料
#
# JSON-LD 是網站嵌入的結構化資料
#
# 很多求職網站會在：
# <script type="application/ld+json">
# 中放 JobPosting 資訊
def extract_json_ld_jobs(soup):

    # 儲存職缺為空 list
    jobs = []

    # 遞迴搜尋 JobPosting
    def walk(obj):

        # 儲存找到的 JobPosting
        found = []

        # 如果是 dict
        if isinstance(obj, dict):

            # 取得 @type
            obj_type = obj.get("@type", "")

            # 有些 @type 是 list
            if isinstance(obj_type, list):

                # 判斷是否包含 JobPosting
                is_job = "JobPosting" in obj_type
            else:

                # 單一字串判斷
                is_job = obj_type == "JobPosting"

            # 如果是職缺
            if is_job:

                # 加入 found
                found.append(obj)

            # 遞迴搜尋所有 value
            for value in obj.values():
                found.extend(walk(value))

        # 如果是 list
        elif isinstance(obj, list):

            # 遞迴搜尋每個元素
            for item in obj:
                found.extend(walk(item))

        return found

    # 找所有 JSON-LD script
    for script in soup.select('script[type="application/ld+json"]'):
        try:

            # 取得 script 文字
            raw = script.get_text(strip=True)
            if not raw:
                continue

            # JSON 轉 dict
            data = json.loads(raw)

            # 找出所有 JobPosting
            job_objects = walk(data)

            # 處理每個職缺
            for j in job_objects:

                # 職位名稱
                title = clean_text(j.get("title", ""))

                # URL
                url = j.get("url", "") or j.get("sameAs", "")

                # 預設公司名稱
                company = "Not clearly shown"

                # 取得 hiringOrganization
                hiring_org = j.get("hiringOrganization", {})

                # 如果是 dict
                if isinstance(hiring_org, dict):

                    # 取得公司名稱
                    company = clean_text(hiring_org.get("name", "")) or "Not clearly shown"

                # 預設地點
                location_text = "Not clearly shown"

                # 取得工作地點
                job_location = j.get("jobLocation", {})
                if isinstance(job_location, dict):
                    address = job_location.get("address", {})
                    if isinstance(address, dict):

                        # 將區域資訊組合
                        location_text = clean_text(
                            " ".join([
                                str(address.get("addressRegion", "")),
                                str(address.get("addressLocality", "")),
                                str(address.get("streetAddress", "")),
                            ])
                        ) or "Not clearly shown"

                salary = "Not clearly shown"

                # 基本薪資
                base_salary = j.get("baseSalary", {})

                # 如果存在薪資資訊
                if isinstance(base_salary, dict):

                    # 轉 JSON 字串
                    salary = clean_text(json.dumps(base_salary, ensure_ascii=False))

                # 如果 title 與 url 都存在
                if title and url:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location_text,
                        "salary": salary,
                        "snippet": "",
                        "url": normalize_url(url, "https://www.1111.com.tw"),
                    })

        # JSON 解析失敗
        except Exception:

            # 忽略錯誤
            continue

    return jobs


# ============================================================
# 從文字中猜測公司名稱
# ============================================================

# 功能：
# 從一大段文字中，用 regex 抓出可能的公司名稱
#
# 例如：
# text =
# "台積電股份有限公司誠徵 Python 工程師"
#
# 會抓出：
# "台積電股份有限公司"
def guess_company_from_text(text):

    # re.search()：
    # 在文字中搜尋第一個符合 regex 的內容
    #
    # regex 解釋：
    #
    # [\u4e00-\u9fa5A-Za-z0-9（）()股份有限公司]
    #
    # 允許的字元：
    # 1. 中文
    # 2. 英文大小寫
    # 3. 數字
    # 4. 中文括號（）
    # 5. 英文括號()
    # 6. 「股份有限公司」中的字
    #
    # {2,40}
    # 長度限制 2~40 個字
    #
    # (?:股份有限公司|有限公司|公司)
    #
    # 公司名稱必須以：
    # 1. 股份有限公司
    # 2. 有限公司
    # 3. 公司
    #
    # 作為結尾
    m = re.search(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()股份有限公司]{2,40}(?:股份有限公司|有限公司|公司))",
        text,
    )

    # 如果有找到符合內容
    if m:

        # m.group(1)
        # 代表第一組括號匹配到的內容
       return m.group(1)

    # 如果沒有找到回傳
    return "Not clearly shown"


# ============================================================
# 直接抓取 1111 職缺
# ============================================================

# 功能：
# 1. 建立 1111 搜尋網址
# 2. 抓取 HTML
# 3. 解析 JSON-LD
# 4. 額外解析 HTML 中的職缺連結
# 5. 回傳統一格式職缺資料
#
# 參數：
# job_title  -> 職位名稱
# location   -> 地區
# salary_min -> 最低薪資
# limit      -> 最多抓取數量
def fetch_1111_jobs_direct(job_title, location, salary_min, limit=50):
    jobs = []

    # 建立 1111 搜尋網址
    #
    # 例如：
    # https://www.1111.com.tw/search/job?...
    url = build_1111_search_url(job_title, location, salary_min)

    # HTTP Header
    headers = {

        # 偽裝成瀏覽器
        "User-Agent": "Mozilla/5.0",

        # Referer
        "Referer": "https://www.1111.com.tw/",

        # 語言偏好
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }

    try:

        # 發送 GET Request
        res = requests.get(url, headers=headers, timeout=15)

        # 如果 status code 不是 200
        # 直接丟 Exception
        res.raise_for_status()

        # 建立 BeautifulSoup HTML Parser
        soup = BeautifulSoup(res.text, "html.parser")

        # 從 JSON-LD 提取職缺
        #
        # JSON-LD 是網站內嵌的結構化資料
        json_ld_jobs = extract_json_ld_jobs(soup)

        # 逐一處理 JSON-LD 職缺
        for item in json_ld_jobs:

            # 如果超過上限
            if len(jobs) >= limit:
                break

            # 建立統一格式職缺資料
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

            # 計算關鍵字分數
            #
            # 用來排序職缺相關性
            score_job_keyword(job, job_title, location, salary_min)

            # 加入 jobs
            jobs.append(job)

        # 建立 seen_urls set
        #
        # 用來避免重複職缺
        seen_urls = set(job["url"] for job in jobs)

        # 找所有 <a href="">
        for a in soup.find_all("a", href=True):

            # 如果超過 limit
            if len(jobs) >= limit:
                break

            # 取得 href
            href = a.get("href", "")

            # 取得文字內容
            text = clean_text(a.get_text(" ", strip=True))

            # 如果文字太短
            if not text or len(text) < 2:
                continue

            # 判斷是否像職缺連結
            #
            # 有些網址會包含：
            # /job/
            # job.asp
            # job-description
            is_job_link = (
                "/job/" in href.lower()
                or "job-bank/job-description" in href.lower()
                or "job.asp" in href.lower()
            )

            # 如果不是職缺連結
            if not is_job_link:
                continue

            # 將相對網址轉完整網址
            full_url = normalize_url(href, "https://www.1111.com.tw")

            # 如果已經抓過
            if full_url in seen_urls:
                continue

            # 找 parent 元素
            #
            # 通常整個職缺卡片都在：
            # article / li / div
            parent = a.find_parent(["article", "li", "div"])

            # 取得 parent 文字
            #
            # 如果沒有 parent
            # 就用 text
            parent_text = clean_text(parent.get_text(" ", strip=True)) if parent else text

            # 如果搜尋職位不在文字中
            #
            # 例如搜尋 Python
            # 但這職缺沒提到 Python
            if job_title not in parent_text and job_title not in text:
                continue

            # 建立職缺資料
            job = {
                "platform": "1111 Job Bank",
                "title": text,

                # 從整段文字中用 regex 抓
                "company": guess_company_from_text(parent_text),

                # 工作地點
                #
                # 如果地區有出現在文字中
                # 就使用 location
                "location": location if location in parent_text else "Not clearly shown",

                # 從文字中提取薪資
                "salary": extract_salary_string(parent_text),

                # 工作簡介
                #
                # 只保留前 350 字
                "snippet": parent_text[:350],
                "url": full_url,
                "source": "1111 HTML parsing",
            }

            # 計算關鍵字分數
            score_job_keyword(job, job_title, location, salary_min)

            # 加入 jobs
            jobs.append(job)

            # 加入 seen_urls
            #
            # 避免之後重複
            seen_urls.add(full_url)

    # 如果發生錯誤
    except Exception as e:

        # 印出錯誤
        print("1111 direct fetch failed:", e)

    # 回傳職缺 list
    return jobs


# ============================================================
# 使用 DuckDuckGo 搜尋
# ============================================================

# 功能：
# 使用 DuckDuckGo HTML 搜尋頁面
# 作為 fallback 搜尋來源
def search_duckduckgo(keyword, max_results=50):

    # 建立搜尋網址
    #
    # quote()：
    # URL encode 關鍵字
    #
    # 例如：
    # Python 工程師
    #
    # 會變：
    # Python%20工程師
    url = f"https://html.duckduckgo.com/html/?q={quote(keyword)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []

    try:

        # 發送 Request
        res = requests.get(url, headers=headers, timeout=15)

        # HTTP Error 檢查
        res.raise_for_status()

        # 建立 HTML Parser
        soup = BeautifulSoup(res.text, "html.parser")

        # 搜尋結果區塊
        for block in soup.select(".result"):

            # 標題元素
            title_tag = block.select_one(".result__a") or block.select_one(".result__title a")

            # 摘要元素
            snippet_tag = block.select_one(".result__snippet")

            # 如果沒有 title
            if not title_tag:
                continue

            # 取得標題文字
            title = clean_text(title_tag.get_text(" ", strip=True))

            # 取得連結
            link = normalize_duckduckgo_link(title_tag.get("href", ""))

            # 取得摘要
            snippet = clean_text(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""

            # 如果 title 與 link 都存在
            if title and link:

                # 加入 results
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": snippet,
                })

            # 如果達到上限
            if len(results) >= max_results:
                break

    # 搜尋失敗
    except Exception as e:

        # 顯示錯誤
        print("DuckDuckGo fallback failed:", e)

    # 回傳搜尋結果
    return results


# ============================================================
# Fallback 搜尋平台
# ============================================================

# 功能：
# 當直接抓取 104 / 1111 失敗，
# 或抓到的職缺太少時，
# 改用 DuckDuckGo 搜尋網站內的職缺頁面。
#
# 這是一種「備援搜尋機制（fallback）」。
#
# 例如：
# site:104.com.tw "Python工程師" "台北"
#
# 代表：
# 只搜尋 104 網站中，
# 同時包含「Python工程師」與「台北」的頁面。
#
# 參數：
# platform   -> 平台名稱（104 / 1111）
# domain     -> 搜尋網站 domain
# job_title  -> 職位名稱
# location   -> 地區
# salary_min -> 最低薪資
# limit      -> 最大搜尋數量
def fallback_search_platform(platform, domain, job_title, location, salary_min, limit=50):

    # 建立 DuckDuckGo 搜尋 query
    #
    # site:domain
    # 限制搜尋特定網站
    #
    # 例如：
    # site:104.com.tw "Python工程師" "台北"
    query = f'site:{domain} "{job_title}" "{location}"'

    # 使用 DuckDuckGo 搜尋
    #
    # 回傳格式：
    # [
    #   {
    #       "title": "...",
    #       "link": "...",
    #       "snippet": "..."
    #   }
    # ]
    raw = search_duckduckgo(query, max_results=limit)

    # 儲存整理後的職缺
    jobs = []

    # 逐一處理搜尋結果
    for item in raw:

        # 建立統一格式職缺資料
        job = {

            # 平台名稱
            #
            # 例如：
            # 104 Job Bank
            "platform": platform,

            # 搜尋結果標題
            #
            # 通常會是：
            # "Python工程師｜某某公司｜104人力銀行"
            "title": item["title"],

            # DuckDuckGo 很難穩定抓公司名稱
            #
            # 所以先標記未知
            "company": "Not clearly shown",

            # 判斷 location 是否出現在：
            # 1. title
            # 2. snippet
            #
            # 如果有出現
            # 才認為工作地點符合
            "location": location if location in item["title"] + item["snippet"] else "Not clearly shown",

            # 從 title + snippet 中提取薪資資訊
            #
            # extract_salary_string()
            # 會找：
            # 月薪40,000
            # 年薪80萬
            # 時薪200
            #
            # 等格式
            "salary": extract_salary_string(item["title"] + " " + item["snippet"]),

            # 搜尋結果摘要
            "snippet": item["snippet"],

            # 搜尋結果連結
            "url": item["link"],

            # 資料來源
            #
            # 表示這筆不是官方 API
            # 而是搜尋引擎 fallback
            "source": "DuckDuckGo fallback",
        }

        # 計算職缺關鍵字分數
        #
        # 用於後續排序
        #
        # 分數越高：
        # 表示越符合：
        # 1. 職位名稱
        # 2. 地區
        # 3. 薪資
        score_job_keyword(job, job_title, location, salary_min)

        # 加入 jobs
        jobs.append(job)

    # 回傳整理後職缺
    return jobs


# ============================================================
# 取得所有原始職缺資料
# ============================================================

# 功能：
# 1. 抓取 104
# 2. 抓取 1111
# 3. 如果太少則 fallback
# 4. 去除重複職缺
# 5. 依相關度排序
# 6. 回傳最終職缺列表
#
# 這是整個「職缺蒐集系統」的核心函式。
def get_raw_jobs(job_title, location, salary_min):

    # 顯示目前正在抓取 104
    print("Fetching 104 jobs...")

    # 呼叫 104 抓取函式
    jobs_104 = fetch_104_jobs_direct(
        job_title=job_title,
        location=location,
        salary_min=salary_min,

        # 每平台最大抓取數
        limit=FETCH_PER_PLATFORM,
    )

    # 如果抓到的職缺太少
    #
    # 代表：
    # 1. 104 改版
    # 2. 被限制
    # 3. 搜尋條件太少
    #
    # 就啟用 fallback
    if len(jobs_104) < 10:
        print("104 direct results are too few. Using fallback search...")

        # extend()
        # 將 fallback 結果加入 jobs_104
        jobs_104.extend(
            fallback_search_platform(
                platform="104 Job Bank",
                domain="104.com.tw",
                job_title=job_title,
                location=location,
                salary_min=salary_min,
                limit=FETCH_PER_PLATFORM,
            )
        )


    # ========================================================
    # 抓取 1111
    # ========================================================

    print("Fetching 1111 jobs...")
    jobs_1111 = fetch_1111_jobs_direct(
        job_title=job_title,
        location=location,
        salary_min=salary_min,
        limit=FETCH_PER_PLATFORM,
    )

    # 如果 1111 結果太少
    if len(jobs_1111) < 10:
        print("1111 direct results are too few. Using fallback search...")

        # 加入 fallback 搜尋結果
        jobs_1111.extend(
            fallback_search_platform(
                platform="1111 Job Bank",
                domain="1111.com.tw",
                job_title=job_title,
                location=location,
                salary_min=salary_min,
                limit=FETCH_PER_PLATFORM,
            )
        )


    # ========================================================
    # 去除重複職缺
    # ========================================================

    # 儲存不重複職缺
    unique = []

    # 用來記錄已出現職缺
    #
    # set 查詢速度非常快
    seen = set()

    # 合併 104 + 1111
    for job in jobs_104 + jobs_1111:
        url = job.get("url", "")

        # 建立唯一 key
        #
        # 優先使用 URL
        #
        # 因為同一職缺 URL 通常固定
        #
        # 如果沒有 URL：
        # 使用：
        # platform|title|company
        #
        # 當作替代唯一值
        key = url if url else f"{job.get('platform')}|{job.get('title')}|{job.get('company')}"

        if key in seen:
            continue

        # 加入 seen
        seen.add(key)

        # 加入 unique
        unique.append(job)


    # ========================================================
    # 排序職缺
    # ========================================================

    # 根據 keyword_score 排序
    #
    # reverse=True
    # 代表由大到小
    #
    # 分數高：
    # 表示比較符合搜尋需求
    unique.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)


    # ========================================================
    # 回傳前 N 筆
    # ========================================================
    return unique[:TOTAL_JOBS_TO_FETCH]


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

def write_resume_txt(content, output_path=OUTPUT_TXT):  # 把履歷 JSON 內容輸出成文字檔
    with open(output_path, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        f.write("========== RESUME CONTENT ==========\n\n")  # 把指定文字寫入輸出檔案
        f.write(json.dumps(content, ensure_ascii=False, indent=2))  # 把 Python 資料轉成 JSON 字串，方便儲存或傳給 Gemini


def write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, output_path=JOBS_TXT):  # 把職缺搜尋條件與推薦結果輸出成文字檔
    with open(output_path, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        f.write("========== JOB RECOMMENDATIONS ==========\n\n")  # 把指定文字寫入輸出檔案

        f.write("Search Conditions\n")  # 把指定文字寫入輸出檔案
        f.write("----------------------------------------\n")  # 把指定文字寫入輸出檔案
        f.write(f"Target Position: {raw_resume['target_position']}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Preferred Location: {raw_resume['target_location']}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Expected Monthly Salary: {raw_resume['expected_monthly_salary']}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Salary Min: {raw_resume.get('salary_min', '')}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Salary Max: {raw_resume.get('salary_max', '')}\n")  # 把指定文字寫入輸出檔案

        required_benefits = get_required_benefits(raw_resume.get("benefit_preferences", {}))  # 設定 required_benefits 變數，供後續流程使用
        f.write(f"Required Benefits: {benefits_to_text(required_benefits)}\n\n")  # 把指定文字寫入輸出檔案

        salary_min = safe_int(raw_resume.get("salary_min", raw_resume["expected_monthly_salary"]), 0)  # 最低薪資條件，用來篩選與評分職缺

        f.write("Direct Search Links\n")  # 把指定文字寫入輸出檔案
        f.write("----------------------------------------\n")  # 把指定文字寫入輸出檔案
        f.write(build_104_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n")  # 把指定文字寫入輸出檔案
        f.write(build_1111_search_url(raw_resume["target_position"], raw_resume["target_location"], salary_min) + "\n\n")  # 把指定文字寫入輸出檔案

        f.write("Process Summary\n")  # 把指定文字寫入輸出檔案
        f.write("----------------------------------------\n")  # 把指定文字寫入輸出檔案
        f.write(f"Fetched job postings: {len(raw_jobs)}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Recommended jobs: {len(recommended_jobs)}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Recommendation limit: {OUTPUT_RECOMMEND_LIMIT}\n")  # 把指定文字寫入輸出檔案
        f.write(f"Match score threshold: {MATCH_SCORE_THRESHOLD}\n\n")  # 把指定文字寫入輸出檔案

        f.write("Matched Job Results\n")  # 把指定文字寫入輸出檔案
        f.write("----------------------------------------\n\n")  # 把指定文字寫入輸出檔案

        if not recommended_jobs:  # 判斷資料是否不存在或為空，必要時提早回傳或改用備援處理
            f.write("No recommended jobs were selected.\n")  # 把指定文字寫入輸出檔案
            return

        for idx, job in enumerate(recommended_jobs, start=1):  # 使用迴圈逐一處理清單或資料集合中的每個項目
            f.write(f"{idx}. {job.get('title', 'No title')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Platform: {job.get('platform', 'Not clearly shown')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Company: {job.get('company', 'Not clearly shown')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Location: {job.get('location', 'Not clearly shown')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Salary: {job.get('salary', 'Not clearly shown')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Salary Check: {job.get('salary_status', 'Not clearly shown')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Benefit Check: {job.get('benefit_match_status', 'Not checked')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Matched Benefits: {benefits_to_text(job.get('matched_benefits', []))}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Missing Benefits: {benefits_to_text(job.get('missing_benefits', []))}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Gemini Match Score: {job.get('match_score', 'Not ranked')}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Keyword Score: {job.get('keyword_score', 0)}\n")  # 把指定文字寫入輸出檔案
            f.write(f"Source Method: {job.get('source', 'Unknown')}\n")  # 把指定文字寫入輸出檔案

            if job.get("gemini_reason"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                f.write(f"Gemini Reason: {job.get('gemini_reason')}\n")  # 把指定文字寫入輸出檔案

            if job.get("fit_points"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                f.write(f"Fit Points: {job.get('fit_points')}\n")  # 把指定文字寫入輸出檔案

            if job.get("concerns"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                f.write(f"Concerns: {job.get('concerns')}\n")  # 把指定文字寫入輸出檔案

            if job.get("snippet"):  # 檢查條件是否成立，成立時執行下方縮排的程式碼
                f.write(f"Snippet: {job.get('snippet')}\n")  # 把指定文字寫入輸出檔案

            f.write(f"URL: {job.get('url', '')}\n")  # 把指定文字寫入輸出檔案
            f.write("-" * 70 + "\n\n")  # 把指定文字寫入輸出檔案


# ============================================================
# Main Program
# ============================================================

def main():  # 主程式流程，負責輸入資料、產生履歷、抓職缺、推薦並輸出檔案
    print("========== AI Resume PDF + Job Recommendation Generator ==========\n")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    print("========== Job Target ==========\n")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    target_position = input("Target Position, for example Software Engineer / 軟體工程師: ").strip()  # 設定 target_position 變數，供後續流程使用
    target_location = input("Preferred Work Location, for example Taipei / 台北: ").strip()  # 設定 target_location 變數，供後續流程使用

    salary_min_text, salary_max_text, salary_min_value, salary_max_value = input_salary_range()
    expected_monthly_salary = f"{salary_min_text} - {salary_max_text}"  # 設定 expected_monthly_salary 變數，供後續流程使用

    benefit_preferences = collect_benefit_preferences()  # 設定 benefit_preferences 變數，供後續流程使用

    print("\n========== Resume Information ==========\n")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    name = input("Name: ").strip()  # 設定 name 變數，供後續流程使用
    specialty = input("Specialty: ").strip()  # 設定 specialty 變數，供後續流程使用

    address = input("Address: ").strip()  # 設定 address 變數，供後續流程使用
    email = input("Email: ").strip()  # 設定 email 變數，供後續流程使用
    phone = input("Phone: ").strip()  # 設定 phone 變數，供後續流程使用

    certificates = input("Certificates, separated by commas. Leave blank if none: ").strip()  # 將使用者輸入的文字整理成清單，方便放入履歷
    competitions = input("Competitions, separated by commas. Leave blank if none: ").strip()  # 將使用者輸入的文字整理成清單，方便放入履歷

    school = input("School: ").strip()  # 設定 school 變數，供後續流程使用
    major = input("Major: ").strip()  # 設定 major 變數，供後續流程使用

    skills = input("Skills, separated by commas. Example: Python, Excel, Finance: ").strip()  # 將使用者輸入的文字整理成清單，方便放入履歷
    experience = input("Work / Internship Experience. Leave blank if none: ").strip()  # 設定 experience 變數，供後續流程使用

    raw_resume = {  # 把使用者輸入的履歷與求職條件整理成字典
        "target_position": target_position,  # 設定目標職位欄位
        "target_location": target_location,  # 設定字典欄位，讓資料可以用固定格式保存
        "expected_monthly_salary": expected_monthly_salary,  # 設定期望月薪欄位
        "salary_min": salary_min_text,  # 設定最低期望薪資欄位
        "salary_max": salary_max_text,  # 設定最高期望薪資欄位
        "benefit_preferences": benefit_preferences,  # 設定使用者福利偏好欄位
        "name": name,  # 設定履歷姓名欄位
        "specialty": specialty,  # 設定主要專長欄位
        "address": address,  # 設定地址欄位
        "email": email,  # 設定電子郵件欄位
        "phone": phone,  # 設定電話欄位
        "certificates": certificates,  # 設定證照清單欄位
        "competitions": competitions,  # 設定競賽或活動經驗欄位
        "school": school,  # 設定字典欄位，讓資料可以用固定格式保存
        "major": major,  # 設定字典欄位，讓資料可以用固定格式保存
        "skills": skills,  # 設定技能清單欄位
        "experience": experience,  # 設定工作或實習經驗欄位
    }

    print("\nConnecting to Gemini API...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    client = make_gemini_client()  # 建立 Gemini 客戶端，成功時可呼叫 AI，失敗時用本機備援

    print("Generating polished resume content...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    resume_content = generate_resume_content_with_gemini(client, raw_resume)  # 存放 AI 或備援邏輯產生的履歷內容

    resume_content.setdefault("job_preferences", {})
    resume_content["job_preferences"]["expected_salary_range"] = expected_monthly_salary
    resume_content["job_preferences"]["required_benefits_text"] = benefits_to_text(
        get_required_benefits(benefit_preferences)
    )

    print("Fetching job postings...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    salary_min = salary_min_value  # 最低薪資條件，用來篩選與評分職缺
    salary_max = salary_max_value  # 最高薪資條件，用來判斷職缺是否落在期望薪資範圍
    raw_jobs = get_raw_jobs(target_position, target_location, salary_min)  # 存放從求職網站抓回來並初步整理的職缺資料

    raw_jobs = apply_user_preferences_to_jobs(  # 存放從求職網站抓回來並初步整理的職缺資料
        jobs=raw_jobs,  # 建立空清單，用來存放整理後的職缺資料
        job_title=target_position,  # 設定 job_title 變數，供後續流程使用
        location=target_location,  # 設定 location 變數，供後續流程使用
        salary_min=salary_min,  # 最低薪資條件，用來篩選與評分職缺
        salary_max=salary_max,  # 最高薪資條件，用來判斷職缺是否落在期望薪資範圍
        benefit_preferences=benefit_preferences,  # 設定 benefit_preferences 變數，供後續流程使用
    )

    print(f"Fetched {len(raw_jobs)} jobs.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    print("Ranking jobs by resume relevance...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    recommended_jobs = rank_jobs_with_gemini(client, raw_resume, raw_jobs)  # 存放 Gemini 或本機備援排序後的推薦職缺

    print(f"Recommended {len(recommended_jobs)} jobs.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    print("Writing output files...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        json.dump(resume_content, f, ensure_ascii=False, indent=2)  # 把 Python 字典或清單寫成 JSON 檔案

    with open(RAW_JOBS_JSON, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        json.dump(raw_jobs, f, ensure_ascii=False, indent=2)  # 把 Python 字典或清單寫成 JSON 檔案

    write_resume_txt(resume_content, OUTPUT_TXT)
    write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, JOBS_TXT)


    print("Creating resume PDF...")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    pdf_path = create_resume_pdf(resume_content, OUTPUT_PDF)  # 儲存建立完成的 PDF 路徑

    print("\nDone.")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print("Files saved to:")  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print(OUTPUT_JSON)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print(OUTPUT_TXT)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print(JOBS_TXT)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print(RAW_JOBS_JSON)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度
    print(pdf_path)  # 在終端機顯示提示訊息，讓使用者知道目前程式進度


if __name__ == "__main__":  # 確認這個檔案是被直接執行時，才啟動主程式
    main()  # 呼叫主程式，開始執行完整流程

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

