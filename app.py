import streamlit as st
import pandas as pd
import json
import holidays

st.set_page_config(page_title="Invoice Auditor V3", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine V3")

# --- 📍 UI: STATE SELECTION ---
st.subheader("⚙️ Audit Settings")
client_state = st.radio("Select Client State (for Public Holiday logic):", ["NSW", "VIC"], horizontal=True)
st.markdown("---")

# 1. THE V3 MOCK JSON DATA (Updated with itemized surcharges!)
raw_json = """
{
  "summary_rows": [
    {"date": "26/01/2026", "service": "PERSONAL CARE - Alice", "price": 182.6, "qty": 3.0, "subtotal": 547.8},
    {"date": "26/01/2026", "service": "MEALS - Bob", "price": 171.6, "qty": 2.0, "subtotal": 343.2},
    {"date": "27/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
    {"date": "28/01/2026", "service": "RESPITE", "price": 78.0, "qty": 2.0, "subtotal": 156.0},
    {"date": "01/02/2026", "service": "PHARMACY REIMBURSEMENT", "price": 486.95, "qty": 1.0, "subtotal": 486.95},
    {"date": "01/02/2026", "service": "INVOICE SURCHARGE 10%", "price": 48.69, "qty": 1.0, "subtotal": 48.69},
    {"date": "02/02/2026", "service": "UBER TRANSPORT", "price": 50.00, "qty": 1.0, "subtotal": 50.00},
    {"date": "02/02/2026", "service": "UBER SURCHARGE 10%", "price": 5.00, "qty": 1.0, "subtotal": 5.00}
  ],
  "timesheet_hours": [
    {"date": "26/01/2026", "worker": "Alice", "hours": 2.0},
    {"date": "26/01/2026", "worker": "Bob", "hours": 2.0},
    {"date": "27/01/2026", "worker": "Alice", "hours": 3.0},
    {"date": "28/01/2026", "worker": "Alice", "hours": 2.0}
  ],
  "third_party_totals": [
    {"date": "01/02/2026", "vendor": "Chemist Warehouse", "amount": 486.95},
    {"date": "02/02/2026", "vendor": "Uber Receipts", "amount": 45.00}
  ],
  "invoice_totals": {
    "item_total": 1803.64,
    "gst": 32.20,
    "total_due": 1835.84
  }
}
"""
data = json.loads(raw_json)
df = pd.DataFrame(data["summary_rows"])

# --- 🗓️ DYNAMIC HOLIDAY LOGIC ---
state_holidays = holidays.AU(subdiv=client_state, years=2026)

def get_day_type(date_str):
    dt = pd.to_datetime(date_str, format="%d/%m/%Y")
    if dt in state_holidays: return "Public Hol"
    if dt.weekday() == 5: return "Saturday"
    if dt.weekday() == 6: return "Sunday"
    return "Standard"

def get_expected_rate(service, day_type):
    service = service.upper()
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
    if val > 0: return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
    elif val < 0: return 'background-color: #ffffcc; color: #999900; font-weight: bold;'
    return 'color: green;'

# --- ⚙️ PROCESSING CARE DATA ---
df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()

df_care["Day Type"] = df_care["date"].apply(get_day_type)
df_care["Calculated Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if abs(row["price"] - row["Calculated Rate"]) <= 0.05 else "❌ No", axis=1)

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
calc_gst = 32.20 # Mocked
calc_grand = calc_item_total + calc_gst

totals_data = {
    "Metric": ["Item Total", "GST", "Grand Total"],
    "Extracted (Summary Page)": [f"${data['invoice_totals']['item_total']:.2f}", f"${data['invoice_totals']['gst']:.2f}", f"${data['invoice_totals']['total_due']:.2f}"],
    "Calculated (Source of Truth)": [f"${calc_item_total:.2f}", f"${calc_gst:.2f}", f"${calc_grand:.2f}"],
    "Status": [
        "✅ Match" if abs(data['invoice_totals']['item_total'] - calc_item_total) <= 0.05 else "❌ Mismatch",
        "✅ Match",
        "✅ Match" if abs(data['invoice_totals']['total_due'] - calc_grand) <= 0.05 else "❌ Mismatch"
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

daily_extracted = df_care.groupby("date")["qty"].sum().reset_index().rename(columns={"date": "Date", "qty": "Extracted Hours (Summary)"})
timesheet_df = pd.DataFrame(data["timesheet_hours"])
daily_calculated = timesheet_df.groupby("date")["hours"].sum().reset_index().rename(columns={"date": "Date", "hours": "Calculated Hours (Timesheet)"})

recon_df = pd.merge(daily_extracted, daily_calculated, on="Date", how="outer").fillna(0)
recon_df["Variance"] = recon_df["Extracted Hours (Summary)"] - recon_df["Calculated Hours (Timesheet)"]

def get_timesheet_status(variance):
    if variance > 0: return "🚨 Overbilled"
    elif variance < 0: return "⚠️ Underbilled"
    return "✅ Match"

recon_df["Status"] = recon_df["Variance"].apply(get_timesheet_status)
styled_recon = recon_df.style.map(style_variance, subset=['Variance'])
st.dataframe(styled_recon, use_container_width=True, hide_index=True)
st.markdown("---")

# ---------------------------------------------------------
# SECTION 4: ITEMIZED THIRD-PARTY RECEIPTS
# ---------------------------------------------------------
st.header("💊 4. Itemized Third-Party Receipts & Surcharges")
st.write("Line-by-line cross-check of extracted vendor claims vs. actual calculated receipt evidence.")

# A. Calculated Source of Truth (From Physical Receipts)
receipts_df = pd.DataFrame(data["third_party_totals"]).rename(columns={"date": "Date", "vendor": "Receipt Vendor", "amount": "Calculated Base"})
receipts_df["Calculated Surcharge"] = receipts_df["Calculated Base"] * 0.10

# B. Extracted Summary Page (Vendor Claims)
df_tp = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()
is_surcharge = df_tp['service'].str.contains('SURCHARGE', case=False, na=False)

ext_base = df_tp[~is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Base (Summary)"})
ext_sur = df_tp[is_surcharge].groupby('date')['subtotal'].sum().reset_index().rename(columns={"date": "Date", "subtotal": "Extracted Surcharge (Summary)"})

# C. Merge into a single Itemized Matrix based on Date
tp_recon = receipts_df.merge(ext_base, on="Date", how="outer").merge(ext_sur, on="Date", how="outer").fillna(0)

# D. Determine Variances & Status
tp_recon["Base Match"] = tp_recon.apply(lambda r: "✅" if abs(r["Extracted Base (Summary)"] - r["Calculated Base"]) <= 0.05 else f"❌ Mismatch (+${(r['Extracted Base (Summary)'] - r['Calculated Base']):.2f})", axis=1)
tp_recon["Surcharge Match"] = tp_recon.apply(lambda r: "✅" if abs(r["Extracted Surcharge (Summary)"] - r["Calculated Surcharge"]) <= 0.05 else f"❌ Mismatch (+${(r['Extracted Surcharge (Summary)'] - r['Calculated Surcharge']):.2f})", axis=1)

# Format Final Display Table
display_tp = tp_recon[["Date", "Receipt Vendor", "Calculated Base", "Extracted Base (Summary)", "Base Match", "Calculated Surcharge", "Extracted Surcharge (Summary)", "Surcharge Match"]]

st.dataframe(display_tp, use_container_width=True, hide_index=True)
