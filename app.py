import streamlit as st
import pandas as pd
import json
import holidays
import tempfile
import os
import google.generativeai as genai

st.set_page_config(page_title="Invoice Auditor Pro", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine")

# --- 🔒 API KEY SECURE LOAD ---
api_key = st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.sidebar.warning("API Key not found in Streamlit Secrets.")
    api_key = st.sidebar.text_input("Enter Gemini API Key to continue:", type="password")

# --- 📁 FILE UPLOADER ---
st.markdown("---")
uploaded_file = st.file_uploader("Upload Invoice (PDF or Image)", type=['pdf', 'png', 'jpg', 'jpeg'])

# --- 🧠 THE PROD AI PROMPT ---
SYSTEM_PROMPT = """
Task: You are a strict data extraction OCR tool. I have uploaded a scanned document. 
Important Note: This document has been physically redacted for privacy using white correction fluid. Completely ignore these blank spaces and focus ONLY on the visible text.

CRITICAL RULE: DO NOT calculate, infer, or guess any numbers. Extract ONLY the exact numbers physically printed on the page. If a value is listed as 0.00, $0, or is blank, output 0.0.

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

3. "third_party_totals": Physical third-party receipts/reimbursements attached (e.g., Pharmacy, Uber). 
CRITICAL RULE: DO NOT extract handwritten dollar amounts or notes found on the timesheets. ONLY extract totals from official, separate printed vendor receipts.
List of objects with:
- "date" (format DD/MM/YYYY of the receipt)
- "vendor" (string, name of the store/service)
- "amount" (float, the base amount of the receipt, exactly as printed)

4. "invoice_totals": Final summary figures at the bottom of the main invoice page. Object with:
- "item_total" (float, subtotal before tax)
- "gst" (float, exact tax amount printed)
- "total_due" (float, exact final grand total printed)

5. "client_state": Look for the specific address belonging to the client receiving the care. It is often explicitly labeled with "Address". CRITICAL: Ignore the vendor's billing address and your company's address. Extract ONLY the 2 or 3 letter Australian state abbreviation for the client (e.g., "NSW", "VIC", "QLD").
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
            
            st.toast("Extraction Complete! Rendering Dashboard...", icon="✅")

            # --- 🗓️ DYNAMIC HOLIDAY LOGIC (Auto-Detected State) ---
            client_state = data.get("client_state", "NSW").upper()
            
            # Fallback cleanup just in case the AI grabs punctuation
            valid_states = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
            if client_state not in valid_states:
                client_state = "NSW" # Safe default
                
            st.info(f"📍 **Auto-Detected Client State:** {client_state}")

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
                
            # --- ⚙️ LIVE MASTER RATE MAPPING (CSV DATABASE) ---
            st.markdown("---")
            st.subheader("📖 Master Rate Dictionary")
            st.write("Add new vendor keywords or update rates here. Changes are saved permanently.")
            
            RATE_FILE = "master_rates.csv"

            # 1. If the CSV doesn't exist yet, create it with the default pre-populated data
            if not os.path.exists(RATE_FILE):
                initial_data = {
                    "Keywords (Comma Separated)": [
                        "MANAGEMENT, CARE MGT",
                        "SOCIAL, SUPPORT",
                        "PERSONAL, PC",
                        "DOMESTIC, CLEANING, LAUNDRY, RESPITE, MEAL",
                        "TRANSPORT, TRIP, TRAVEL, KM"
                    ],
                    "Standard": [120.00, 86.20, 83.00, 78.00, 70.00],
                    "Saturday": [168.00, 120.68, 116.20, 109.20, 98.00],
                    "Sunday": [204.00, 146.54, 141.10, 132.60, 119.00],
                    "Public Hol": [264.00, 189.64, 182.60, 171.60, 154.00]
                }
                pd.DataFrame(initial_data).to_csv(RATE_FILE, index=False)

            # 2. Load the current rates from the CSV file
            rate_mapping_df = pd.read_csv(RATE_FILE)

            # 3. Render the editable data grid
            edited_rates_df = st.data_editor(
                rate_mapping_df, 
                num_rows="dynamic", # Allows adding/deleting rows
                use_container_width=True,
                hide_index=True
            )

            # 4. Save changes back to the CSV instantly if your wife edits the table
            if not edited_rates_df.equals(rate_mapping_df):
                edited_rates_df.to_csv(RATE_FILE, index=False)
                st.toast("💾 Master rates saved permanently!", icon="✅")

            # 5. The dynamic checking function (using the live edited data)
            def get_expected_rate(service, day_type):
                service = str(service).upper()
                for index, row in edited_rates_df.iterrows():
                    keywords = [k.strip().upper() for k in str(row["Keywords (Comma Separated)"]).split(",")]
                    if any(k in service for k in keywords if k): 
                        if day_type == "Saturday": return float(row["Saturday"])
                        elif day_type == "Sunday": return float(row["Sunday"])
                        elif day_type == "Public Hol": return float(row["Public Hol"])
                        else: return float(row["Standard"])
                return None
                
            df = pd.DataFrame(data.get("summary_rows", []))
            
            if not df.empty:
                # --- ⚙️ PROCESSING CARE DATA ---
                df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()

                df_care["Day Type"] = df_care["date"].apply(get_day_type)
                df_care["Calculated Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
                
                # New Logic: Subtotal Math Validation
                df_care["Calculated Subtotal (Truth)"] = df_care["Calculated Rate"] * df_care["qty"]
                
                # Matches
                df_care["Rate Match"] = df_care.apply(lambda row: "✅" if pd.notna(row["Calculated Rate"]) and abs(row["price"] - row["Calculated Rate"]) <= 0.05 else "❌", axis=1)
                df_care["Subtotal Match"] = df_care.apply(lambda row: "✅" if pd.notna(row["Calculated Subtotal (Truth)"]) and abs(row["subtotal"] - row["Calculated Subtotal (Truth)"]) <= 0.05 else "❌", axis=1)

                display_care_df = df_care[["date", "service", "Day Type", "Calculated Rate", "price", "Rate Match", "qty", "Calculated Subtotal (Truth)", "subtotal", "Subtotal Match"]]
                display_care_df = display_care_df.rename(columns={
                    "date": "Service Date", 
                    "service": "Service", 
                    "price": "Extracted Rate (Summary)",
                    "qty": "Extracted Qty", 
                    "subtotal": "Extracted Subtotal (Summary)"
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
                        "✅ Match",
                        "✅ Match" if abs(ext_grand - calc_grand) <= 0.05 else "❌ Mismatch"
                    ]
                }
                st.table(pd.DataFrame(totals_data).set_index("Metric"))
                st.markdown("---")

                # ---------------------------------------------------------
                # SECTION 2: CARE SERVICES & RATES
                # ---------------------------------------------------------
                st.header("🗓️ 2. Care Services & Rate Audit")
                st.write("Cross-checking rates and ensuring the line-item math (`Rate` × `Qty`) equals the printed subtotal.")
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
                    receipts_df = pd.DataFrame(tp_data_list)
                    if not receipts_df.empty:
                        receipts_df = receipts_df.rename(columns={"date": "Date", "vendor": "Receipt Vendor", "amount": "Calculated Base"})
                        receipts_df["Calculated Surcharge"] = receipts_df["Calculated Base"] * 0.10
                    else:
                        receipts_df = pd.DataFrame(columns=["Date", "Receipt Vendor", "Calculated Base", "Calculated Surcharge"])

                    is_surcharge = df_tp['service'].str.contains('SURCHARGE', case=False, na=False)
                    ext_base = df_tp[~is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Base (Summary)"})
                    ext_sur = df_tp[is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Surcharge (Summary)"})

                    tp_recon = receipts_df.merge(ext_base, on="Date", how="outer").merge(ext_sur, on="Date", how="outer").fillna(0)

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
