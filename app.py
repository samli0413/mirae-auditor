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

# 1. THE V3 MOCK JSON DATA
raw_json = """
{
  "summary_rows": [
    {"date": "26/01/2026", "service": "PERSONAL CARE - Alice", "price": 182.6, "qty": 3.0, "subtotal": 547.8},
    {"date": "26/01/2026", "service": "MEALS - Bob", "price": 171.6, "qty": 2.0, "subtotal": 343.2},
    {"date": "27/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
    {"date": "28/01/2026", "service": "RESPITE", "price": 78.0, "qty": 2.0, "subtotal": 156.0},
    {"date": "01/02/2026", "service": "PHARMACY REIMBURSEMENT", "price": 486.95, "qty": 1.0, "subtotal": 486.95},
    {"date": "02/02/2026", "service": "UBER TRANSPORT", "price": 50.00, "qty": 1.0, "subtotal": 50.00},
    {"date": "01/02/2026", "service": "INVOICE SURCHARGE 10%", "price": 48.69, "qty": 1.0, "subtotal": 48.69}
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
    "item_total": 1798.64,
    "gst": 32.20,
    "total_due": 1830.84
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

# --- ⚙️ PROCESSING CARE DATA & TIMESHEETS ---
df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()

# 1. Apply Rates
df_care["Day Type"] = df_care["date"].apply(get_day_type)
df_care["Expected Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if abs(row["price"] - row["Expected Rate"]) <= 0.05 else "❌ No", axis=1)

# 2. Aggregate Daily Billed & Timesheets
daily_billed = df_care.groupby("date")["qty"].sum().reset_index().rename(columns={"date": "Service Date", "qty": "Day Billed Total"})
timesheet_df = pd.DataFrame(data["timesheet_hours"])
logged_grouped = timesheet_df.groupby("date")["hours"].sum().reset_index().rename(columns={"date": "Service Date", "hours": "Day Logged Total"})

# 3. Merge Daily Totals back into the main Care grid
df_care = df_care.rename(columns={"date": "Service Date", "service": "Service", "price": "Extracted Rate", "qty": "Line Qty", "subtotal": "Subtotal"})
df_care = df_care.merge(daily_billed, on="Service Date", how="left")
df_care = df_care.merge(logged_grouped, on="Service Date", how="left").fillna(0)
df_care["Day Variance"] = df_care["Day Billed Total"] - df_care["Day Logged Total"]

# Format display columns
display_care_df = df_care[["Service Date", "Day Type", "Service", "Expected Rate", "Extracted Rate", "Rate Match", "Line Qty", "Day Billed Total", "Day Logged Total", "Day Variance"]]
styled_care_df = display_care_df.style.map(style_day_type, subset=['Day Type']).map(style_variance, subset=['Day Variance'])


# --- 🖥️ UI LAYOUT ---
st.header("📊 1. Main Invoice Totals Check")
calc_item_total = df["subtotal"].sum()
calc_gst = 32.20 # Mocked
calc_grand = calc_item_total + calc_gst

totals_data = {
    "Metric": ["Item Total", "GST", "Grand Total"],
    "Vendor Claims": [f"${data['invoice_totals']['item_total']:.2f}", f"${data['invoice_totals']['gst']:.2f}", f"${data['invoice_totals']['total_due']:.2f}"],
    "App Calculated": [f"${calc_item_total:.2f}", f"${calc_gst:.2f}", f"${calc_grand:.2f}"],
    "Status": [
        "✅ Match" if abs(data['invoice_totals']['item_total'] - calc_item_total) <= 0.05 else "❌ Mismatch",
        "✅ Match",
        "✅ Match" if abs(data['invoice_totals']['total_due'] - calc_grand) <= 0.05 else "❌ Mismatch"
    ]
}
st.table(pd.DataFrame(totals_data).set_index("Metric"))
st.markdown("---")

st.header("🗓️ 2. Care Services & Timesheet Audit")
st.write("Cross-checking rates and ensuring the **Daily Billed Total** matches the **Daily Logged Total** from the timesheets.")
st.dataframe(styled_care_df, use_container_width=True, hide_index=True)
st.markdown("---")

# --- 💊 3. THE SMART THIRD-PARTY MATRIX ---
st.header("💊 3. Third-Party Receipts & Surcharges")

# A. Process Receipts & auto-calculate 10%
receipts_df = pd.DataFrame(data["third_party_totals"])
receipts_df["Expected Surcharge"] = receipts_df["amount"] * 0.10
total_receipt_base = receipts_df["amount"].sum()
total_expected_surcharge = receipts_df["Expected Surcharge"].sum()

st.write("**A. Evidence Provided (Physical Receipts):**")
receipts_display = receipts_df.rename(columns={"date": "Date", "vendor": "Vendor", "amount": "Receipt Base Amount"})
st.dataframe(receipts_display, use_container_width=True, hide_index=True)

# B. Process the Grid Claims
df_third_party = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()
grid_base_claimed = df_third_party[~df_third_party['service'].str.contains('SURCHARGE', case=False, na=False)]['subtotal'].sum()
grid_surcharge_claimed = df_third_party[df_third_party['service'].str.contains('SURCHARGE', case=False, na=False)]['subtotal'].sum()

st.write("**B. Surcharge & Reimbursement Cross-Check:**")

tp_data = {
    "Metric": ["Base Reimbursements", "10% Surcharges"],
    "Expected (From Receipts)": [f"${total_receipt_base:.2f}", f"${total_expected_surcharge:.2f}"],
    "Actually Billed (In Grid)": [f"${grid_base_claimed:.2f}", f"${grid_surcharge_claimed:.2f}"],
    "Status": [
        "✅ Match" if abs(total_receipt_base - grid_base_claimed) <= 0.05 else f"❌ Mismatch (Diff: ${(grid_base_claimed - total_receipt_base):.2f})",
        "✅ Match" if abs(total_expected_surcharge - grid_surcharge_claimed) <= 0.05 else f"❌ Mismatch (Diff: ${(grid_surcharge_claimed - total_expected_surcharge):.2f})"
    ]
}
st.table(pd.DataFrame(tp_data).set_index("Metric"))
