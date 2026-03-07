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
    
    # --- 🧠 PREVENT AI RE-RUNS ---
    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file_path = tmp_file.name

        with st.spinner("🤖 AI is reading the invoice... (This only happens once per file!)"):
            try:
                gemini_file = genai.upload_file(tmp_file_path)
                model = genai.GenerativeModel(
                    model_name='gemini-2.5-flash',
                    generation_config={"response_mime_type": "application/json"}
                )
                response = model.generate_content([gemini_file, SYSTEM_PROMPT])
                
                # Save raw extraction to memory
                st.session_state.extracted_data = json.loads(response.text)
                st.session_state.current_file = uploaded_file.name
                
                # Initialize Editable DataFrames in Session State
                raw_data = st.session_state.extracted_data
                st.session_state.summary_df = pd.DataFrame(raw_data.get("summary_rows", []))
                st.session_state.timesheet_df = pd.DataFrame(raw_data.get("timesheet_hours", []))
                
                os.remove(tmp_file_path)
                genai.delete_file(gemini_file.name)
                st.toast("Extraction Complete!", icon="✅")
                
            except Exception as e:
                st.error(f"An error occurred during AI processing: {e}")
                st.stop()

    data = st.session_state.extracted_data

    # --- 🗓️ DYNAMIC HOLIDAY LOGIC ---
    client_state = data.get("client_state", "NSW").upper()
    valid_states = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
    if client_state not in valid_states:
        client_state = "NSW" 
        
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

    # --- ⚙️ LIVE MASTER RATE MAPPING (CSV DATABASE) ---
    st.markdown("---")
    with st.expander("📖 Master Rate Dictionary (Click to Edit)"):
        st.write("Add new vendor keywords or update rates here.")
        
        RATE_FILE = "master_rates.csv"

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

        if "master_rates_df" not in st.session_state:
            st.session_state.master_rates_df = pd.read_csv(RATE_FILE)

        edited_rates_df = st.data_editor(
            st.session_state.master_rates_df, 
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="master_rate_editor" 
        )

        if not edited_rates_df.equals(st.session_state.master_rates_df):
            edited_rates_df.to_csv(RATE_FILE, index=False)
            st.session_state.master_rates_df = edited_rates_df
            st.rerun()

    def get_expected_rate(service, day_type):
        service = str(service).upper()
        for index, row in edited_rates_df.iterrows():
            raw_keywords = str(row.get("Keywords (Comma Separated)", ""))
            if raw_keywords.strip() == "" or raw_keywords.upper() == "NAN": continue
            
            keywords = [k.strip().upper() for k in raw_keywords.split(",")]
            if any(k in service for k in keywords if k): 
                if day_type == "Saturday": return float(row["Saturday"])
                elif day_type == "Sunday": return float(row["Sunday"])
                elif day_type == "Public Hol": return float(row["Public Hol"])
                else: return float(row["Standard"])
        return None

    # --- 🎨 STYLING FUNCTIONS ---
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


    # =========================================================================
    # 🧠 THE NEW DATA PIPELINE: Processing Math BEFORE Rendering the UI
    # =========================================================================
    
    # 1. Grab current editable state
    sum_df = st.session_state.summary_df.copy()
    ts_df = st.session_state.timesheet_df.copy()
    
    # 2. Get Daily Verified Timesheet Hours
    if not ts_df.empty and 'date' in ts_df.columns and 'hours' in ts_df.columns:
        ts_df['hours'] = pd.to_numeric(ts_df['hours'], errors='coerce').fillna(0)
        daily_ts = ts_df.groupby("date")["hours"].sum().reset_index().rename(columns={"hours": "Verified TS Hours"})
    else:
        daily_ts = pd.DataFrame(columns=["date", "Verified TS Hours"])

    # 3. Process Summary Data & Run Two-Way Match
    df_care = pd.DataFrame()
    df_tp = pd.DataFrame()
    
    if not sum_df.empty:
        # Split care services from 3rd party reimbursements
        is_tp = sum_df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)
        df_care = sum_df[~is_tp].copy()
        df_tp = sum_df[is_tp].copy()

        if not df_care.empty:
            df_care["Day Type"] = df_care["date"].apply(get_day_type)
            df_care["Calculated Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
            
            # Ensure numbers
            df_care["qty"] = pd.to_numeric(df_care["qty"], errors='coerce').fillna(0)
            df_care["price"] = pd.to_numeric(df_care["price"], errors='coerce').fillna(0)
            df_care["subtotal"] = pd.to_numeric(df_care["subtotal"], errors='coerce').fillna(0)
            
            df_care["Calculated Subtotal (Truth)"] = df_care["Calculated Rate"] * df_care["qty"]
            
            # --- THE TWO-WAY MATCH LOGIC ---
            df_care = pd.merge(df_care, daily_ts, on="date", how="left").fillna(0)
            
            # Calculate total hours claimed per day in the summary
            df_care["Daily Claimed Qty"] = df_care.groupby("date")["qty"].transform("sum")
            
            # Flag if summary claims more hours than the timesheet verifies
            df_care["Evidence Check"] = df_care.apply(
                lambda row: "✅ Verified" if row["Daily Claimed Qty"] <= row["Verified TS Hours"] + 0.05 else "🚨 Missing Timesheet", 
                axis=1
            )
            
            df_care["Rate Match"] = df_care.apply(lambda row: "✅" if pd.notna(row["Calculated Rate"]) and abs(row["price"] - row["Calculated Rate"]) <= 0.05 else "❌", axis=1)

    # 4. Process Third-Party Receipts
    tp_data_list = data.get("third_party_totals", [])
    receipts_df = pd.DataFrame(tp_data_list)
    true_tp_base = 0.0
    true_tp_surcharge = 0.0
    
    if not receipts_df.empty:
        receipts_df["Calculated Base"] = pd.to_numeric(receipts_df["amount"], errors='coerce').fillna(0)
        receipts_df["Calculated Surcharge"] = receipts_df["Calculated Base"] * 0.10
        true_tp_base = receipts_df["Calculated Base"].sum()
        true_tp_surcharge = receipts_df["Calculated Surcharge"].sum()


    # =========================================================================
    # 🖥️ UI RENDERING (Top to Bottom)
    # =========================================================================

    # ---------------------------------------------------------
    # SECTION 1: FORENSIC TOTALS
    # ---------------------------------------------------------
    st.header("📊 1. Forensic Invoice Totals (Source of Truth)")
    st.write("This table calculates the grand total based **ONLY** on the approved rows in the summary table below.")
    
    inv_totals = data.get("invoice_totals", {})
    ext_item_total = inv_totals.get("item_total", 0.0)
    ext_gst = inv_totals.get("gst", 0.0)
    ext_grand = inv_totals.get("total_due", 0.0)
    
    # 1. Base Total (Truth)
    true_care_total = df_care["Calculated Subtotal (Truth)"].sum(skipna=True) if not df_care.empty else 0.0
    true_item_total = true_care_total + true_tp_base + true_tp_surcharge
    
    # 2. Strict 10% GST (Care Services Only)
    true_gst = true_care_total * 0.10
    
    # 3. Grand Total (Truth)
    true_grand_total = true_item_total + true_gst 
    
    variance = ext_grand - true_grand_total

    totals_data = {
        "Metric": ["Item Total", "GST", "Grand Total"],
        "Vendor Claimed (Invoice)": [f"${ext_item_total:.2f}", f"${ext_gst:.2f}", f"${ext_grand:.2f}"],
        "Audited Truth (Master Rates & Receipts)": [f"${true_item_total:.2f}", f"${true_gst:.2f}", f"${true_grand_total:.2f}"],
        "Status": [
            "✅ Match" if abs(ext_item_total - true_item_total) <= 0.05 else "❌ Mismatch",
            "✅ Match" if abs(ext_gst - true_gst) <= 0.05 else "❌ Mismatch",
            "✅ Match" if abs(ext_grand - true_grand_total) <= 0.05 else f"🚨 OVERCHARGED by ${variance:.2f}" if variance > 0.05 else f"⚠️ UNDERCHARGED by ${abs(variance):.2f}"
        ]
    }
    st.table(pd.DataFrame(totals_data).set_index("Metric"))
    st.markdown("---")

    # ---------------------------------------------------------
    # SECTION 2: CARE SERVICES & SUMMARY (NOW EDITABLE)
    # ---------------------------------------------------------
    st.header("🗓️ 2. Care Services & Rate Audit")
    st.write("We cross-checked these rows against the timesheet. **If you see a 🚨 Missing Timesheet warning, click the grey box on the far left of that row and press Delete to reject the faked entry.** The Forensic Totals above will recalculate instantly.")
    
    if not df_care.empty:
        # Select columns to display
        display_care_cols = ["date", "service", "Day Type", "qty", "price", "subtotal", "Verified TS Hours", "Evidence Check", "Calculated Rate", "Calculated Subtotal (Truth)", "Rate Match"]
        display_care_df = df_care[display_care_cols]
        
        styled_care_df = display_care_df.style.map(style_day_type, subset=['Day Type'])
        
        # Make it editable!
        edited_care_df = st.data_editor(
            styled_care_df, 
            use_container_width=True, 
            hide_index=False, # Index must be visible to delete rows!
            key="summary_editor",
            num_rows="dynamic"
        )
        
        # If the core data is edited or a row is deleted, update state and rerun
        core_cols = ["date", "service", "qty", "price", "subtotal"]
        if not edited_care_df[core_cols].equals(display_care_df[core_cols]):
            # Reconstruct the original summary format (care + 3rd party)
            new_care_raw = edited_care_df[core_cols]
            new_summary = pd.concat([new_care_raw, df_tp], ignore_index=True)
            st.session_state.summary_df = new_summary
            st.rerun()
            
    else:
        st.info("No care services extracted.")
    st.markdown("---")

    # ---------------------------------------------------------
    # SECTION 3: TIMESHEET RECONCILIATION
    # ---------------------------------------------------------
    st.header("⏱️ 3. Timesheet Reconciliation")
    st.write("Fix AI reading errors here. Any edits you make will instantly update the `Verified TS Hours` check in the Summary table above!")

    if not ts_df.empty:
        # The editable AI extracted data
        edited_ts_df = st.data_editor(
            ts_df, 
            num_rows="dynamic", 
            use_container_width=True, 
            hide_index=True,
            key="timesheet_editor"
        )
        
        # Save edits to memory
        if not edited_ts_df.equals(ts_df):
            st.session_state.timesheet_df = edited_ts_df
            st.rerun()

    else:
        st.info("No timesheet hours were found in this document.")
    st.markdown("---")

    # ---------------------------------------------------------
    # SECTION 4: ITEMIZED THIRD-PARTY RECEIPTS
    # ---------------------------------------------------------
    st.header("💊 4. Itemized Third-Party Receipts & Surcharges")
    st.write("Line-by-line cross-check of extracted vendor claims vs. actual calculated receipt evidence.")

    if tp_data_list or not df_tp.empty:
        if not receipts_df.empty:
            receipts_df = receipts_df.rename(columns={"date": "Date", "vendor": "Receipt Vendor"})
        else:
            receipts_df = pd.DataFrame(columns=["Date", "Receipt Vendor", "Calculated Base", "Calculated Surcharge"])

        is_surcharge = df_tp['service'].str.contains('SURCHARGE', case=False, na=False)
        ext_base = df_tp[~is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Base (Summary)"})
        ext_sur = df_tp[is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Surcharge (Summary)"})

        tp_recon = receipts_df.merge(ext_base, on="Date", how="outer").merge(ext_sur, on="Date", how="outer").fillna(0)

        tp_recon["Base Match"] = tp_recon.apply(lambda r: "✅" if abs(r.get("Extracted Base (Summary)", 0) - r.get("Calculated Base", 0)) <= 0.05 else f"❌ Mismatch (+${(r.get('Extracted Base (Summary)', 0) - r.get('Calculated Base', 0)):.2f})", axis=1)
        tp_recon["Surcharge Match"] = tp_recon.apply(lambda r: "✅" if abs(r.get("Extracted Surcharge (Summary)", 0) - r.get("Calculated Surcharge", 0)) <= 0.05 else f"❌ Mismatch (+${(r.get('Extracted Surcharge (Summary)', 0) - r.get('Calculated Surcharge', 0)):.2f})", axis=1)

        display_tp = tp_recon[["Date", "Receipt Vendor", "Calculated Base", "Extracted Base (Summary)", "Base Match", "Calculated Surcharge", "Extracted Surcharge (Summary)", "Surcharge Match"]]
        st.dataframe(display_tp, use_container_width=True, hide_index=True)
    else:
        st.info("No third-party reimbursements or surcharges found in this document.")

elif uploaded_file and not api_key:
    st.warning("Please enter your Gemini API key to begin.")
