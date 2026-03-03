import streamlit as st
import pdfplumber
import pandas as pd
import re
import holidays
from datetime import datetime

# --- CONFIGURATION & PRICING ---
PRICE_REF = {
    "CARE MANAGEMENT": {"Standard": 120.0, "Saturday": 168.0, "Sunday": 204.0, "Public Holiday": 264.0},
    "DOMESTIC": {"Standard": 78.0, "Saturday": 109.2, "Sunday": 132.6, "Public Holiday": 171.6},
    "PERSONAL CARE": {"Standard": 83.0, "Saturday": 116.2, "Sunday": 141.1, "Public Holiday": 182.6},
    "RESPITE": {"Standard": 78.0, "Saturday": 109.2, "Sunday": 132.6, "Public Holiday": 171.6},
    "SOCIAL SUPPORT": {"Standard": 86.2, "Saturday": 120.68, "Sunday": 146.54, "Public Holiday": 189.64},
    "MEAL PREP": {"Standard": 78.0, "Saturday": 109.2, "Sunday": 132.6, "Public Holiday": 171.6},
    "TRANSPORT": {"Standard": 70.0, "Saturday": 98.0, "Sunday": 119.0, "Public Holiday": 154.0}
}

# --- HELPER FUNCTIONS ---
def get_day_type_info(date_str, state_code):
    try:
        dt = pd.to_datetime(date_str, dayfirst=True)
        aus_hols = holidays.Australia(subdiv=state_code)
        if dt in aus_hols: return "Public Holiday", aus_hols.get(dt)
        if dt.dayofweek == 5: return "Saturday", None
        if dt.dayofweek == 6: return "Sunday", None
        return "Standard", None
    except: return "Standard", None

def normalize_date(date_str):
    try:
        clean_str = re.sub(r'[-.]', '/', date_str)
        return pd.to_datetime(clean_str, dayfirst=True).strftime('%d/%m/%Y')
    except:
        return date_str

def fetch_val(pat, txt):
    m = re.search(pat, txt, re.I | re.MULTILINE)
    if m: return float(m.group(1).replace(',', ''))
    return 0.0

def highlight_match(val):
    if val == 'MATCH':
        return 'background-color: #d4edda; color: #155724; font-weight: bold;'
    elif val == 'MISMATCH':
        return 'background-color: #f8d7da; color: #721c24; font-weight: bold;'
    return ''

def highlight_day(val):
    if val == 'Standard':
        return 'background-color: #e6f2ff; color: #004085;'
    elif val == 'Saturday':
        return 'background-color: #fff3cd; color: #856404;'
    elif val == 'Sunday':
        return 'background-color: #ffe8cc; color: #854000;'
    elif val == 'Public Holiday':
        return 'background-color: #e2d9f3; color: #381885; font-weight: bold;'
    elif val == 'N/A':
        return 'color: #6c757d; font-style: italic;'
    return ''

# --- CORE EXTRACTION ENGINE ---
def process_pdf(uploaded_file):
    summary_rows = []
    timesheet_hours = {}
    third_party_totals = []
    full_text = ""
    photo_detected = False
    
    current_doc_type = "UNKNOWN"
    mirae_summary_ended = False 

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"
            text_upper = text.upper()
            
            if len(text.strip()) < 50:
                photo_detected = True
                
            text_clean = re.sub(r'\s+', '', text_upper)
            
            # STATE DETECTION
            if "SERVICECONFIRMATION" in text_clean or "TIMESHEET" in text_clean:
                current_doc_type = "TIMESHEET"
            elif "MIRAE" in text_clean and ("TAXINVOICE" in text_clean or "INVOICE" in text_clean):
                current_doc_type = "MIRAE_SUMMARY"
            elif current_doc_type == "MIRAE_SUMMARY":
                if "MIRAE" not in text_clean:
                    current_doc_type = "THIRD_PARTY"
            
            if current_doc_type == "MIRAE_SUMMARY" and mirae_summary_ended:
                current_doc_type = "THIRD_PARTY"
            
            # Mode A: Timesheets 
            if current_doc_type == "TIMESHEET":
                extracted_from_page = False
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 4: continue
                        date_match = re.search(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", str(row[0]))
                        if date_match:
                            date_val = normalize_date(date_match.group(1))
                            hr_match = re.findall(r"(\d+(?:\.\d+)?)", str(row[3]))
                            if hr_match:
                                hours = float(hr_match[-1])
                                timesheet_hours[date_val] = timesheet_hours.get(date_val, 0) + hours
                                extracted_from_page = True

                if not extracted_from_page and text.strip():
                    for line in text.split('\n'):
                        date_match = re.search(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", line)
                        if date_match:
                            date_val = normalize_date(date_match.group(1))
                            hr_match = re.findall(r"\b(\d+(?:\.\d+)?)\b", line[date_match.end():])
                            if hr_match:
                                hours = float(hr_match[-1])
                                if hours > 24 and len(hr_match) > 1: hours = float(hr_match[-2])
                                if 0 < hours <= 24:
                                    timesheet_hours[date_val] = timesheet_hours.get(date_val, 0) + hours

            # Mode B: Mirae Summary
            elif current_doc_type == "MIRAE_SUMMARY":
                for line in text.split('\n'):
                    line = line.strip()
                    if not line: continue
                    line_up = line.upper()
                    
                    if any(x in line_up for x in ["BALANCE DUE", "BANK DETAILS", "HOW TO PAY"]):
                        mirae_summary_ended = True
                        break 
                    
                    if re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", line):
                        parts = line.split()
                        date_val = normalize_date(parts[0])
                        remainder = line[len(parts[0]):].strip()
                        nums_match = re.search(r"((?:\s+[\d,]+\.\d{2}|\s+\d+(?:\.\d+)?)+)$", remainder)
                        
                        if nums_match:
                            nums_str = nums_match.group(1).strip()
                            service_desc = remainder[:-len(nums_match.group(1))].strip()
                            nums = nums_str.split()
                            
                            if len(nums) >= 3: p, q, s = nums[-3], nums[-2], nums[-1]
                            elif len(nums) == 2: p, q, s = nums[0], "1", nums[1]
                            elif len(nums) == 1: p, q, s = nums[0], "1", nums[0]
                            else: p, q, s = "0.00", "0", "0.00"
                            summary_rows.append([date_val, service_desc, p, q, s])

                    else:
                        amt_match = re.search(r"\s+([\d,]+\.\d{2})$", line)
                        if amt_match and "TAX INVOICE" not in line_up:
                            amt = amt_match.group(1)
                            service_desc = line[:-len(amt)].strip()
                            if len(service_desc) > 3 and not re.search(r"ABN|PAGE", service_desc, re.I):
                                summary_rows.append(["", service_desc, "0.00", "1", amt])

            # Mode C: Third Party
            elif current_doc_type == "THIRD_PARTY":
                m = re.search(r"(?:TOTAL|Amount\s+Due|Balance|Payable|Charge|Subtotals).*?\$?\s*([\d,]+\.\d{2})", text, re.I | re.MULTILINE)
                if m: 
                    third_party_totals.append(float(m.group(1).replace(',', '').replace('$', '')))
                else:
                    amounts = re.findall(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b", text)
                    if amounts:
                        floats = [float(a.replace(',', '')) for a in amounts]
                        third_party_totals.append(max(floats))

    df = pd.DataFrame(summary_rows, columns=["Date", "Service", "Price", "Qty", "Subtotal"])
    for col in ['Price', 'Qty', 'Subtotal']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)
    
    return df, timesheet_hours, third_party_totals, full_text, photo_detected

# --- STREAMLIT UI ---
st.set_page_config(page_title="Mirae Smart Auditor", layout="wide")
st.title("Mirae Smart Auditor")

uploaded_file = st.file_uploader("Upload Tax Invoice (PDF)", type="pdf")

if uploaded_file:
    with st.spinner("Extracting and auditing data..."):
        summary_df, auto_timesheet_hours, third_party_totals, full_text, photo_detected = process_pdf(uploaded_file)
        
        if photo_detected:
            st.toast("Scanned timesheet detected! Please verify hours manually in the Timesheet Verification tab.", icon="⚠️")
            
        res_state = "VIC" if re.search(r"\bVIC\b|Victoria", full_text, re.I) else "NSW"

        audit_list = []
        for _, row in summary_df.iterrows():
            is_third_party = (str(row['Date']).strip() == "")
            dtype, _ = get_day_type_info(row['Date'], res_state) if not is_third_party else ("N/A", None)
            
            exp_unit_price = 0.0
            if not is_third_party:
                for key in PRICE_REF:
                    if key in str(row['Service']).upper():
                        exp_unit_price = PRICE_REF[key].get(dtype, 0.0); break
                match_status = "MATCH" if abs(exp_unit_price - row['Price']) < 0.01 else "MISMATCH"
            else:
                exp_unit_price = row['Price'] if row['Price'] > 0 else row['Subtotal']
                match_status = "N/A"
                
            audit_list.append({"Day": dtype, "Expected Unit": exp_unit_price, "Match": match_status})
        
        audit_meta_df = pd.DataFrame(audit_list)

        s_it = fetch_val(r"Item\s*Total\s*[:$]*\s*([\d,]+\.\d{2})", full_text)
        s_gst = fetch_val(r"GST\s*[:$]*\s*([\d,]+\.\d{2})", full_text)
        s_tot = fetch_val(r"(?<!Item\s)Total\s*[:$]*\s*([\d,]+\.\d{2})", full_text)

        st.sidebar.write(f"**Detected State:** {res_state}")

        t1, t2, t3, t4, t5 = st.tabs([
            "1. Summary Data", 
            "2. Unit Price Audit", 
            "3. Timesheet Verification", 
            "4. Third-Party Receipts", 
            "5. Final Financial Audit"
        ])
        
        with t1:
            st.write("### Extracted Summary Table")
            clean_view_df = pd.concat([summary_df.reset_index(drop=True), audit_meta_df[['Day']]], axis=1)
            st.dataframe(clean_view_df, use_container_width=True, hide_index=True)
        
        with t2:
            st.write("### Unit Price Validation")
            display_audit_df = pd.concat([
                summary_df[['Date', 'Service', 'Qty', 'Price']].reset_index(drop=True), 
                audit_meta_df[['Day', 'Expected Unit', 'Match']]
            ], axis=1)
            display_audit_df = display_audit_df.rename(columns={"Price": "Billed Unit"})
            try:
                styled_df = display_audit_df.style.map(highlight_match, subset=['Match']).map(highlight_day, subset=['Day'])
            except AttributeError:
                styled_df = display_audit_df.style.applymap(highlight_match, subset=['Match']).applymap(highlight_day, subset=['Day'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

        with t3:
            st.write("### Source of Truth: Timesheet Verification")
            st.info("💡 **Auditor Input Required:** Verify the hours below. The app will wait for you to finish typing. Click **Confirm & Save Hours** when done.")
            
            summary_dates = [d for d in summary_df['Date'] if str(d).strip() != ""]
            for d in summary_dates:
                if d not in auto_timesheet_hours:
                    auto_timesheet_hours[d] = 0.0 
                    
            init_data = [{"Date": d, "Verified Hours": auto_timesheet_hours[d]} for d in sorted(auto_timesheet_hours.keys())]
            if not init_data: init_data = [{"Date": "", "Verified Hours": 0.0}]
            log_df = pd.DataFrame(init_data)
            
            with st.form("timesheet_form"):
                edited_log_df = st.data_editor(log_df, num_rows="dynamic", use_container_width=True, key="timesheet_editor")
                submit_button = st.form_submit_button("Confirm & Save Hours")
            
            verified_hrs_dict = edited_log_df[edited_log_df['Date'].str.strip() != ""].groupby('Date')['Verified Hours'].sum().to_dict()
            
            st.write("---")
            st.write("#### Timesheet vs Summary Cross-Check")
            sum_hrs = summary_df[summary_df['Date'] != ""].groupby('Date')['Qty'].sum()
            all_dates = sorted(list(set(sum_hrs.index).union(set(verified_hrs_dict.keys()))))
            
            for d in all_dates:
                sh = sum_hrs.get(d, 0.0)
                lh = verified_hrs_dict.get(d, 0.0)
                c_data, c_status = st.columns([6, 1])
                c_data.write(f"**{d}** | Verified Entry: **{lh}** hrs vs Billed Summary: **{sh}** hrs")
                if abs(lh - sh) < 0.01: c_status.success("MATCH")
                else: c_status.error("MISMATCH")

        with t4:
            st.write("### Source of Truth: Third-Party Receipts")
            st.info("💡 **Auditor Input Required:** Verify the raw receipt amounts below. The app will automatically calculate the 10% surcharge for each item.")
            
            # 1. The Raw Input Editor
            tp_init_data = [{"Receipt Ref": f"Extracted Receipt {i+1}", "Raw Amount ($)": val} for i, val in enumerate(third_party_totals)]
            if not tp_init_data: tp_init_data = [{"Receipt Ref": "Manual Entry 1", "Raw Amount ($)": 0.0}]
            tp_df = pd.DataFrame(tp_init_data)
            
            with st.form("third_party_form"):
                edited_tp_df = st.data_editor(tp_df, num_rows="dynamic", use_container_width=True, key="tp_editor")
                st.form_submit_button("Confirm & Calculate")
                
            # 2. The Auto-Calculation Breakdown
            st.write("#### 1. Your Calculated Receipt Breakdown")
            
            # Perform the math row-by-row
            edited_tp_df['10% Surcharge ($)'] = (edited_tp_df['Raw Amount ($)'] * 0.10).round(2)
            edited_tp_df['Total Calculated ($)'] = (edited_tp_df['Raw Amount ($)'] + edited_tp_df['10% Surcharge ($)']).round(2)
            
            # Force Streamlit to display two decimal places for currency
            st.dataframe(
                edited_tp_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "Raw Amount ($)": st.column_config.NumberColumn(format="%.2f"),
                    "10% Surcharge ($)": st.column_config.NumberColumn(format="%.2f"),
                    "Total Calculated ($)": st.column_config.NumberColumn(format="%.2f")
                }
            )
            
            # 3. Vendor's Summary Claim
            st.write("#### 2. Claimed on Vendor Summary")
            summary_tp_df = summary_df[summary_df['Date'] == ''][['Service', 'Subtotal']].rename(columns={"Service": "Billed Item", "Subtotal": "Claimed Total ($)"})
            
            if summary_tp_df.empty:
                st.write("*No third-party items found on the summary page.*")
            else:
                st.dataframe(
                    summary_tp_df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"Claimed Total ($)": st.column_config.NumberColumn(format="%.2f")}
                )
            
            # 4. The Final Cross-Check
            verified_tp_sum = edited_tp_df['Total Calculated ($)'].sum()
            claimed_tp_sum = summary_tp_df['Claimed Total ($)'].sum()
            
            st.write("---")
            st.write("#### 3. Receipts vs Summary Cross-Check")
            
            c_data, c_status = st.columns([6, 1])
            c_data.write(f"**Calculated from Receipts:** **${verified_tp_sum:,.2f}** vs **Billed on Summary:** **${claimed_tp_sum:,.2f}**")
            if abs(verified_tp_sum - claimed_tp_sum) < 0.01: c_status.success("MATCH")
            else: c_status.error("MISMATCH")

        with t5:
            st.write("### Final Financial Reconciliation")
            
            expected_taxable_subtotal = 0.0
            
            # Send the fully calculated total straight to the final math
            expected_nontaxable_subtotal = verified_tp_sum 
            
            available_verified_hrs = verified_hrs_dict.copy()

            for i, row in summary_df.iterrows():
                is_third_party = (str(row['Date']).strip() == "")
                
                if not is_third_party:
                    billed_unit_price = row['Price'] 
                    date_val = row['Date']
                    billed_qty = row['Qty']
                    
                    available = available_verified_hrs.get(date_val, 0.0)
                    qty_to_use = min(billed_qty, available) if billed_qty > 0 else 0.0
                    
                    expected_taxable_subtotal += (billed_unit_price * qty_to_use)
                    available_verified_hrs[date_val] = round(available - qty_to_use, 2)

            calc_gst = round(expected_taxable_subtotal * 0.1, 2)
            calc_grand_total = expected_taxable_subtotal + expected_nontaxable_subtotal + calc_gst
            
            st.markdown(f"""
            **Breakdown of your Verified Math:**
            * **Taxable Services:** ${expected_taxable_subtotal:,.2f} *(Calculated from Tab 3 Hours x Vendor's Unit Price)*
            * **Non-Taxable Items (3rd Party + Surcharges):** ${expected_nontaxable_subtotal:,.2f} *(Pulled strictly from Tab 4 Calculated Totals)*
            """)
            
            col1, col2, col3 = st.columns(3)
            user_it = col1.number_input("PDF Item Total ($)", value=float(s_it), format="%.2f")
            user_gst = col2.number_input("PDF GST ($)", value=float(s_gst), format="%.2f")
            user_tot = col3.number_input("PDF Grand Total ($)", value=float(s_tot), format="%.2f")
            
            st.write("---")
            st.write("#### Bottom-Line Comparison")
            recon_data = [
                {"Metric": "Verified Item Total", "Calc": expected_taxable_subtotal + expected_nontaxable_subtotal, "Summary": user_it},
                {"Metric": "Verified GST (10%)", "Calc": calc_gst, "Summary": user_gst},
                {"Metric": "Verified Grand Total", "Calc": calc_grand_total, "Summary": user_tot}
            ]
            
            for m in recon_data:
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                diff = round(m['Calc'] - m['Summary'], 2)
                c1.write(f"**{m['Metric']}**")
                c2.write(f"System Calculated: ${m['Calc']:,.2f}")
                c3.write(f"Billed by Vendor: ${m['Summary']:,.2f}")
                if abs(diff) < 0.05: c4.success("MATCH")
                else: c4.error(f"OVERCHARGED: ${abs(diff):,.2f}" if diff < 0 else f"UNDERCHARGED: ${diff:,.2f}")
