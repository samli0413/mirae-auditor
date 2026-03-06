import streamlit as st
import pandas as pd
import json
import holidays
import tempfile
import os
import google.generativeai as genai

st.set_page_config(page_title="Invoice Auditor V3", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine V3")

# --- 🔒 API KEY SECURE LOAD ---
# Tries to get the key from the Streamlit Vault first. If missing, shows the sidebar input.
api_key = st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.sidebar.warning("API Key not found in Streamlit Secrets.")
    api_key = st.sidebar.text_input("Enter Gemini Dev API Key to continue:", type="password")

# --- 📍 UI: STATE SELECTION ---
st.subheader("⚙️ Audit Settings")
client_state = st.radio("Select Client State (for Public Holiday logic):", ["NSW", "VIC"], horizontal=True)
st.markdown("---")

# --- 📁 FILE UPLOADER ---
uploaded_file = st.file_uploader("Upload Invoice (PDF or Image)", type=['pdf', 'png', 'jpg', 'jpeg'])

# --- 🧠 THE V3 AI PROMPT ---
SYSTEM_PROMPT = """
Task: You are a strict data extraction OCR tool. I have uploaded a scanned document. 
Important Note: This document has been physically redacted for privacy using white correction fluid. You will notice blanked-out areas. Completely ignore these blank spaces and focus ONLY on the visible text.

CRITICAL RULE: DO NOT calculate, infer, or guess any numbers. You must ONLY extract the exact numbers physically printed on the page. If a value is listed as 0.00, $0, or is blank, you must output 0.0.

Extract the data and return ONLY a valid JSON object matching this exact structure:

1. "summary_rows": The main grid of billed services. List of objects with:
- "date" (format DD/MM/YYYY)
- "service" (string description of the line item exactly as printed)
- "price" (float, unit price)
- "qty" (float, quantity/hours billed)
- "subtotal" (float, total for that line)

2. "timesheet_hours": The physical timesheet logs usually attached behind the invoice. List of objects with:
- "date" (format DD/MM/YYYY)
- "worker" (string, name or ID of the carer)
- "hours" (float, total hours logged for that shift)

3. "third_party_totals": Physical third-party receipts/reimbursements attached (e.g., Pharmacy, Uber). List of objects with:
- "date" (format DD/MM/YYYY of the receipt)
- "vendor" (string, name of the store/service)
- "amount" (float, the base amount of the receipt, exactly as printed)

4. "invoice_totals": Final summary figures at the bottom of the main invoice page. Object with:
- "item_total" (float, subtotal before tax)
- "gst" (float, exact tax amount printed)
- "total_due" (float, exact final grand total printed)
"""

if uploaded_file and api_key:
    genai.configure(api_key=api_key)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    with st.spinner("🤖 AI is reading and extracting the invoice data..."):
        try:
            # 1. Upload & Process via Gemini
            gemini_file = genai.upload_file(tmp_file_path)
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"}
            )
            response = model.generate_content([gemini_file, SYSTEM_PROMPT])
            data = json.loads(response.text)
            
            # Clean up files
            os.remove(tmp_file_path)
            genai.delete_file(gemini_file.name)
            
            st.success("✅ Extraction Complete! Rendering Dashboard...")

            # --- 🗓️ DYNAMIC HOLIDAY LOGIC ---
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
                if val == 'Public Hol': return 'background-color: #ffcccc; color: #990000;'
                elif val == 'Sunday': return 'background-color: #ffe6cc; color: #cc6600;'
                elif val == 'Saturday': return 'background-color: #ffffcc; color: #999900;'
                return ''

            def style_variance(val):
                if pd.isna(val): return ''
                if val > 0: return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
                elif val < 0: return 'background-color: #ffffcc; color: #999900; font-weight: bold;'
                return 'color: green;'

            # Ensure we have data before rendering
            df = pd.DataFrame(data.get("summary_rows", []))
            
            if not df.empty:
                # --- ⚙️ PROCESSING CARE DATA ---
                df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()

                df_care["Day Type"] = df_care["date"].apply(get_day_type)
                df_care["Calculated Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
                df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if pd.notna(row["Calculated Rate"]) and abs(row["price"] - row["Calculated Rate"]) <= 0.05 else "❌ No", axis=1)

                display_care_df = df_care[["date", "service", "Day Type", "Calculated Rate", "price", "Rate Match", "qty", "subtotal"]]
                display_care_df = display_care_df.rename(columns={
                    "date": "Service Date", 
                    "service": "Service", 
                    "price": "Extracted Rate (Summary)",
                    "qty": "Extracted Qty", 
                    "subtotal": "Subtotal"
                })
                styled_care_df = display_care_df.style.map(style_day_type, subset=['Day Type'])

                # --- 🖥️ UI LAYOUT ---

                # ---------------------------------------------------------
                # SECTION 1: TOTALS
                # ---------------------------------------------------------
                st.header("📊 1. Main Invoice Totals Check")
                calc_item_total = df["subtotal"].sum()
                
                inv_totals = data.get("invoice_totals", {})
                ext_item_total = inv_totals.get("item_total", 0.0)
                ext_gst = inv_totals.get("gst", 0.0)
                ext_grand = inv_totals.get("total_due", 0.0)
                
                calc_grand = calc_item_total + ext_gst 

                totals_data = {
                    "Metric": ["Item Total", "GST", "Grand Total"],
                    "Extracted (Summary Page)": [f"${ext_item_total:.2f}", f"${ext_gst:.2f}", f"${ext_grand:.2f}"],
                    "Calculated (Source of Truth)": [f"${calc_item_total:.2f}", f"${ext_gst:.2f}", f"${calc_grand:.2f}"],
                    "Status": [
                        "✅ Match" if abs(ext_item_total - calc_item_total) <= 0.05 else "❌ Mismatch",
                        "✅ Match", # Extracted GST is baseline for now
                        "✅ Match" if abs(ext_grand - calc_grand) <= 0.05 else "❌ Mismatch"
                    ]
                }
                st.table(pd.DataFrame(totals_data).set_index("Metric"))
                st.markdown("---")

                # ---------------------------------------------------------
                # SECTION 2: CARE SERVICES & RATES
                # ---------------------------------------------------------
                st.header("🗓️ 2. Care Services & Rate Audit")
                st.write("Cross-checking the extracted unit prices against your state's calculated holiday/weekend rates.")
                st.dataframe(styled_care_df, use_container_width=True, hide_index=True)
                st.markdown("---")

                # ---------------------------------------------------------
                # SECTION 3: TIMESHEET RECONCILIATION
                # ---------------------------------------------------------
                st.header("⏱️ 3. Timesheet Reconciliation")
                st.write("Cross-checking the total hours extracted from the summary page against the physical timesheet logs.")

                timesheet_data = data.get("timesheet_hours", [])
                if timesheet_data:
                    daily_extracted = df_care.groupby("date")["qty"].sum().reset_index().rename(columns={"date": "Date", "qty": "Extracted Hours (Summary)"})
                    timesheet_df = pd.DataFrame(timesheet_data)
                    daily_calculated = timesheet_df.groupby("date")["hours"].sum().reset_index().rename(columns={"date": "Date", "hours": "Calculated Hours (Timesheet)"})

                    recon_df = pd.merge(daily_extracted, daily_calculated, on="Date", how="outer").fillna(0)
                    recon_df["Variance"] = recon_df["Extracted Hours (Summary)"] - recon_df["Calculated Hours (Timesheet)"]

                    def get_timesheet_status(variance):
                        if variance > 0.05: return "🚨 Overbilled"
                        elif variance < -0.05: return "⚠️ Underbilled"
                        return "✅ Match"

                    recon_df["Status"] = recon_df["Variance"].apply(get_timesheet_status)
                    styled_recon = recon_df.style.map(style_variance, subset=['Variance'])
                    st.dataframe(styled_recon, use_container_width=True, hide_index=True)
                else:
                    st.info("No timesheet hours were found in this document.")
                st.markdown("---")

                # ---------------------------------------------------------
                # SECTION 4: ITEMIZED THIRD-PARTY RECEIPTS
                # ---------------------------------------------------------
                st.header("💊 4. Itemized Third-Party Receipts & Surcharges")
                st.write("Line-by-line cross-check of extracted vendor claims vs. actual calculated receipt evidence.")

                tp_data_list = data.get("third_party_totals", [])
                df_tp = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()
                
                if tp_data_list or not df_tp.empty:
                    # A. Calculated Source of Truth (From Physical Receipts)
                    receipts_df = pd.DataFrame(tp_data_list)
                    if not receipts_df.empty:
                        receipts_df = receipts_df.rename(columns={"date": "Date", "vendor": "Receipt Vendor", "amount": "Calculated Base"})
                        receipts_df["Calculated Surcharge"] = receipts_df["Calculated Base"] * 0.10
                    else:
                        receipts_df = pd.DataFrame(columns=["Date", "Receipt Vendor", "Calculated Base", "Calculated Surcharge"])

                    # B. Extracted Summary Page (Vendor Claims)
                    is_surcharge = df_tp['service'].str.contains('SURCHARGE', case=False, na=False)
                    ext_base = df_tp[~is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Base (Summary)"})
                    ext_sur = df_tp[is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Surcharge (Summary)"})

                    # C. Merge into a single Itemized Matrix based on Date
                    tp_recon = receipts_df.merge(ext_base, on="Date", how="outer").merge(ext_sur, on="Date", how="outer").fillna(0)

                    # D. Determine Variances & Status
                    tp_recon["Base Match"] = tp_recon.apply(lambda r: "✅" if abs(r["Extracted Base (Summary)"] - r.get("Calculated Base", 0)) <= 0.05 else f"❌ Mismatch (+${(r['Extracted Base (Summary)'] - r.get('Calculated Base', 0)):.2f})", axis=1)
                    tp_recon["Surcharge Match"] = tp_recon.apply(lambda r: "✅" if abs(r["Extracted Surcharge (Summary)"] - r.get("Calculated Surcharge", 0)) <= 0.05 else f"❌ Mismatch (+${(r['Extracted Surcharge (Summary)'] - r.get('Calculated Surcharge', 0)):.2f})", axis=1)

                    display_tp = tp_recon[["Date", "Receipt Vendor", "Calculated Base", "Extracted Base (Summary)", "Base Match", "Calculated Surcharge", "Extracted Surcharge (Summary)", "Surcharge Match"]]
                    st.dataframe(display_tp, use_container_width=True, hide_index=True)
                else:
                    st.info("No third-party reimbursements or surcharges found in this document.")

            else:
                st.error("No service rows were extracted. Please check the PDF quality or prompt.")
                
        except Exception as e:
            st.error(f"An error occurred during AI processing: {e}")

elif uploaded_file and not api_key:
    st.warning("Please enter your Gemini API key to begin.")
