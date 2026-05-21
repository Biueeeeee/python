# ============================================================
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
