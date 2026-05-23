# Python專題-履歷生成器

## 系統簡介與功能
這是一個可以輔助使用者生成履歷的工具。
使用者輸入個人資料、專長、期望薪資與職缺後，系統會幫助求職者撰寫一份凸顯自己優勢，及適合該職缺特質的履歷。

### 核心功能
#### 一、期望待遇設定和職缺搜尋
使用者可以輸入期望的工作待遇（包含薪資範圍、員工旅遊、員工保險......）及想應徵的職缺，並追蹤符合理想的每家公司的對應職缺。
#### 二、個人資料與經歷編輯
使用者可以新增自己的姓名、聯絡方式、個人經歷、工作經驗、學歷及專長等......，讓使用者能夠了解自己的優勢，並優化個人亮點。 
#### 三、產出履歷
系統透過結合公司職缺及使用者的個人優勢，為使用者產出一份凸顯自己成就的履歷，使其能夠利用自身優勢提升錄取機會。

### 進階功能
#### 一、系統職缺推薦
使用者首先輸入想應徵的工作類型及薪資要求，系統會根據使用者輸入的條件篩選並排序合適的職缺，接著以列點方式呈現結果，最後讓使用者獲得系統推薦的工作職缺。
#### 二、落點分析
系統可依據生成的履歷與使用者設定的應徵職缺，對各職缺進行適配度評分（0–100），再進一步進行落點分析，將職缺分類為夢想職缺、穩健職缺與保底職缺，協助使用者評估投遞策略與錄取機率。

## 環境與安裝需求
### 環境需求
建議使用以下工具進行開發與執行： \
Python（建議 3.10 以上）\
Visual Studio Code（VS Code）\
Terminal / 命令提示字元（用於執行程式與安裝套件）
### 安裝套件
由於本專案包含 AI 生成、網頁爬蟲與 PDF 輸出功能，這些能力 Python 內建無法完全支援，因此需安裝第三方套件。

requests，發送 HTTP 請求，用於抓取職缺網站資料 \
beautifulsoup4，解析 HTML 網頁內容，擷取職缺資訊 \
reportlab，生成 PDF 履歷（排版、表格、字型) \
google-genai，串接 Gemini AI，用於履歷生成與職缺推薦 \
```
pip install requests
pip install beautifulsoup4
pip install reportlab
pip install google-genai
```
### 載入模組
os，檔案與路徑管理 \
re，正規表示式處理 \
json，JSON資料讀寫 \
html，HTML字元轉換 \
time，延遲與重試控制 \
random，隨機延遲 \
urllib.parse，URL編碼與解析
```python=
import os
import re
import json
import html
import time
import random
from urllib.parse import quote, urlparse, parse_qs, unquote
```
網頁爬蟲模組，用於抓取職缺網站資料並解析 HTML
```python=
import requests
from bs4 import BeautifulSoup
```
PDF生成模組，用於生成履歷 PDF 與版面設計
```python=
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
```
AI模組(Gemini)，用於履歷生成與職缺推薦分析
```python=
from google import genai
from google.genai import types
```
## 使用方式
### 1.輸入期望的工作待遇
首先輸入期望月薪，系統會根據所設定的薪資條件，篩選符合需求的職缺，並分析薪資是否符合預期。
```python=
    salary_min_text, salary_max_text, salary_min_value, salary_max_value = input_salary_range()
    expected_monthly_salary = f"{salary_min_text} - {salary_max_text}"  
```
### 2.輸入想應徵的職缺
輸入希望應徵的職位與工作地點，系統會根據輸入內容，自動搜尋 104 與 1111 等求職平台相關職缺並做整理。
```python=
    target_position = input("Target Position, for example Software Engineer / 軟體工程師: ").strip()  
    target_location = input("Preferred Work Location, for example Taipei / 台北: ").strip()  
```
### 3.輸入基本個人資料與經歷
輸入履歷相關資訊，系統會將輸入的資料進行整理，並透過 Gemini AI 自動產生較正式的英文履歷與自我介紹。
```python=
    name = input("Name: ").strip()  
    specialty = input("Specialty: ").strip()  

    address = input("Address: ").strip()  
    email = input("Email: ").strip()  
    phone = input("Phone: ").strip()  

    certificates = input("Certificates, separated by commas. Leave blank if none: ").strip()  
    competitions = input("Competitions, separated by commas. Leave blank if none: ").strip()  

    school = input("School: ").strip()  
    major = input("Major: ").strip()  

    skills = input("Skills, separated by commas. Example: Python, Excel, Finance: ").strip()  
    experience = input("Work / Internship Experience. Leave blank if none: ").strip()  
```
### 4.系統生成履歷PDF檔案
所有資料輸入完成後，系統會自動執行履歷生成與職缺推薦流程，包括: \
• 生成 AI 優化後履歷內容\
• 抓取相關職缺資料\
• 分析履歷與職缺適配度\
• 推薦適合職缺\
• 生成 PDF 履歷檔案\
• 輸出 JSON 與 TXT 分析結果\
```python=
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

    client = make_gemini_client()  # 建立 Gemini 客戶端，成功時可呼叫 AI，失敗時用本機備援

    resume_content = generate_resume_content_with_gemini(client, raw_resume)  # 存放 AI 或備援邏輯產生的履歷內容

    resume_content.setdefault("job_preferences", {})
    resume_content["job_preferences"]["expected_salary_range"] = expected_monthly_salary
    resume_content["job_preferences"]["required_benefits_text"] = benefits_to_text(
        get_required_benefits(benefit_preferences)
    )

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

    recommended_jobs = rank_jobs_with_gemini(client, raw_resume, raw_jobs)  # 存放 Gemini 或本機備援排序後的推薦職缺
```
最後輸出檔案給使用者
```python=
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        json.dump(resume_content, f, ensure_ascii=False, indent=2)  # 把 Python 字典或清單寫成 JSON 檔案

    with open(RAW_JOBS_JSON, "w", encoding="utf-8") as f:  # 開啟輸出檔案，使用 utf-8 避免中文亂碼
        json.dump(raw_jobs, f, ensure_ascii=False, indent=2)  # 把 Python 字典或清單寫成 JSON 檔案

    write_resume_txt(resume_content, OUTPUT_TXT)
    write_jobs_txt(raw_resume, raw_jobs, recommended_jobs, JOBS_TXT)


    pdf_path = create_resume_pdf(resume_content, OUTPUT_PDF)  # 儲存建立完成的 PDF 路徑


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
```
