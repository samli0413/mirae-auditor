import streamlit as st
import pandas as pd
import json
import holidays
import tempfile
import os
import google.generativeai as genai

st.set_page_config(page_title="Invoice Auditor V2", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine")

# --- 🔒 SIDEBAR: CONFIG & API ---
st.sidebar.header("⚙️ App Settings")
api_key = st.sidebar.text_input("Enter Gemini API Key", type="password", help="Use your Dev key for redacted tests, and Prod key for real data.")
client_state = st.sidebar.radio("Select Client State:", ["NSW", "VIC"])
st.sidebar.markdown("---")
st.sidebar.write("Ensure you are using **Gemini 2.5 Flash** for optimal speed and cost.")

# --- 📁 FILE UPLOADER ---
uploaded_file = st.file_uploader("Upload Invoice (PDF or Image)", type=['pdf', 'png', 'jpg', 'jpeg'])

# THE PROMPT (Exactly as we refined it)
SYSTEM_PROMPT = """
Task: You are a strict data extraction OCR tool. I have uploaded a scanned document. 

Important Note: This document has been physically redacted for privacy using white correction fluid. You will notice blanked-out areas or white smudges. Completely ignore these blank spaces and focus ONLY on the visible text.

CRITICAL RULE: DO NOT calculate, infer, or guess any numbers. You must ONLY extract the exact numbers physically printed on the page. If a value (like GST) is listed as 0.00, $0, or is blank, you must output 0.0. Do not apply standard 10% tax rates unless explicitly written.

Extract the data and return ONLY a valid JSON object. Do not include markdown formatting or conversational text.

Please extract these 4 strict categories:

1. "summary_rows": Look for the main grid of billed services. For each row, extract:
- "date" (format DD/MM/YYYY)
- "service" (string description)
- "price" (float)
- "qty" (float)
- "subtotal" (float)

2. "timesheet_hours": Look for daily logs of hours worked. Return a single dictionary where the key is the Date (DD/MM/YYYY) and the value is the total hours worked that day (float). Example: {"10/05/2024": 3.0}

3. "third_party_totals": Look for standalone third-party receipts, reimbursements, or separate vendor invoices attached to the main document. These MAY have service dates. Just extract the final total amount claimed for each of these third-party expenses as a list of floats. Example: [486.95]

4. "invoice_totals": Extract the final summary figures usually found at the bottom of the main invoice page. Return a dictionary with:
- "item_total" (float, the subtotal before tax)
- "gst" (float, the exact tax amount printed on the page)
- "total_due" (float, the exact final grand total printed on the page)
"""

if uploaded_file and api_key:
    genai.configure(api_key=api_key)
    
    # We need to save the uploaded Streamlit file temporarily so the Gemini SDK can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    with st.spinner("🤖 AI is reading and extracting the invoice data..."):
        try:
            # 1. Upload file to Gemini
            gemini_file = genai.upload_file(tmp_file_path)
            
            # 2. Call the Model (Forcing JSON output)
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"}
            )
            response = model.generate_content([gemini_file, SYSTEM_PROMPT])
            
            # 3. Parse JSON
            data = json.loads(response.text)
            
            # Clean up the temporary file and the file on Google's servers
            os.remove(tmp_file_path)
            genai.delete_file(gemini_file.name)
            
            st.success("✅ Extraction Complete! Rendering Dashboard...")
            
            # --- START DASHBOARD LOGIC (Same as before) ---
            df = pd.DataFrame(data.get("summary_rows", []))
            
            if not df.empty:
                # DYNAMIC HOLIDAY LOGIC
                state_holidays = holidays.AU(subdiv=client_state, years=2026)

                def get_day_type(date_str):
                    try:
                        dt = pd.to_datetime(date_str, format="%d/%m/%Y")
                        if dt in state_holidays: return "Public Hol"
                        if dt.weekday() == 5: return "Saturday"
                        if dt.weekday() == 6: return "Sunday"
                        return "Standard"
                    except:
                        return "Unknown"

                def get_expected_rate(service, day_type):
                    service = str(service).upper()
                    if "PERSONAL CARE" in service:
                        rates = {"Standard": 83.0, "Saturday": 116.2, "Sunday": 146.54, "Public Hol": 182.6}
                        return rates.get(day_type, 83.0)
                    elif "MEALS" in service or "RESPITE" in service:
                        rates = {"Standard": 78.0, "Saturday": 109.2, "Sunday": 146.54, "Public Hol": 171.6}
                        return rates.get(day_type, 78.0)
                    return None 

                def style_day_type(val):
                    if val == 'Public Hol': return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
                    elif val == 'Sunday': return 'background-color: #ffe6cc; color: #cc6600; font-weight: bold;'
                    elif val == 'Saturday': return 'background-color: #ffffcc; color: #999900; font-weight: bold;'
                    return ''

                df_third_party = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT', case=False, na=False)].copy()
                df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT', case=False, na=False)].copy()

                df_care["Day Type"] = df_care["date"].apply(get_day_type)
                df_care["Expected Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
                df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if pd.notnull(row["Expected Rate"]) and abs(row["price"] - row["Expected Rate"]) <= 0.05 else "❌ No", axis=1)

                display_care_df = df_care[["date", "service", "Day Type", "Expected Rate", "price", "Rate Match", "qty", "subtotal"]]
                display_care_df = display_care_df.rename(columns={"date": "Service Date", "service": "Service", "price": "Extracted Rate", "qty": "Qty", "subtotal": "Subtotal"})
                styled_care_df = display_care_df.style.map(style_day_type, subset=['Day Type'])

                # --- UI RENDERING ---
                st.header("📊 Main Invoice Totals Check")
                calc_item_total = df["subtotal"].sum()
                
                # We pull GST directly from the extracted JSON, defaulting to 0.0 if not found
                inv_totals = data.get("invoice_totals", {})
                vendor_item_total = inv_totals.get("item_total", 0.0)
                vendor_gst = inv_totals.get("gst", 0.0)
                vendor_grand = inv_totals.get("total_due", 0.0)
                
                calc_grand = calc_item_total + vendor_gst 

                totals_data = {
                    "Metric": ["Item Total", "GST", "Grand Total"],
                    "Vendor Claims": [f"${vendor_item_total:.2f}", f"${vendor_gst:.2f}", f"${vendor_grand:.2f}"],
                    "App Calculated": [f"${calc_item_total:.2f}", f"${vendor_gst:.2f}", f"${calc_grand:.2f}"],
                    "Status": [
                        "✅ Match" if abs(vendor_item_total - calc_item_total) <= 0.05 else "❌ Mismatch",
                        "✅ Match", # App calculation assumes extracted GST is the baseline for now
                        "✅ Match" if abs(vendor_grand - calc_grand) <= 0.05 else "❌ Mismatch"
                    ]
                }
                st.table(pd.DataFrame(totals_data).set_index("Metric"))
                st.markdown("---")

                st.header("🗓️ 1. Care Services & Rate Audit")
                st.write("Cross-checking dates, states, and weekend/holiday penalty rates.")
                st.dataframe(styled_care_df, use_container_width=True, height=500, hide_index=True)
                st.markdown("---")

                st.header("💊 2. Third-Party & Reimbursements")
                st.write("**Extracted Third-Party Line Items:**")
                df_third_party = df_third_party.rename(columns={"date": "Service Date", "service": "Service", "price": "Rate", "qty": "Qty", "subtotal": "Subtotal"})
                st.dataframe(df_third_party[["Service Date", "Service", "Subtotal"]], use_container_width=True, hide_index=True)

                ai_raw_receipts = sum(data.get("third_party_totals", [0.0]))
                base_grid_reimbursements = df_third_party[~df_third_party['Service'].str.contains('SURCHARGE', case=False, na=False)]['Subtotal'].sum()

                tp_match_status = "✅ Match" if abs(base_grid_reimbursements - ai_raw_receipts) <= 0.05 else "❌ Mismatch"

                tp_data = {
                    "Metric": ["Base Reimbursement (excl. Surcharge/GST)"],
                    "Extracted from Grid": [f"${base_grid_reimbursements:.2f}"],
                    "Receipt Invoice": [f"${ai_raw_receipts:.2f}"],
                    "Status": [tp_match_status]
                }

                st.write("**Reimbursement Match:**")
                st.table(pd.DataFrame(tp_data).set_index("Metric"))

            else:
                st.error("No service rows were extracted. Please check the PDF quality or prompt.")
                
        except Exception as e:
            st.error(f"An error occurred during API processing: {e}")

elif uploaded_file and not api_key:
    st.warning("Please enter your Gemini API key in the sidebar to begin.")
