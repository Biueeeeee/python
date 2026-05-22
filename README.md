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
