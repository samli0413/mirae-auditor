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

# 1. THE V3 MOCK JSON DATA (Simulating edge cases and errors)
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
    if val == 'Public Hol': return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
    elif val == 'Sunday': return 'background-color: #ffe6cc; color: #cc6600; font-weight: bold;'
    elif val == 'Saturday': return 'background-color: #ffffcc; color: #999900; font-weight: bold;'
    return ''

# --- ⚙️ PROCESSING DATA ---
df_third_party = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()
df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT|UBER', case=False, na=False)].copy()

df_care["Day Type"] = df_care["date"].apply(get_day_type)
df_care["Expected Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)
df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if abs(row["price"] - row["Expected Rate"]) <= 0.05 else "❌ No", axis=1)

display_care_df = df_care[["date", "service", "Day Type", "Expected Rate", "price", "Rate Match", "qty", "subtotal"]]
display_care_df = display_care_df.rename(columns={"date": "Service Date", "service": "Service", "price": "Extracted Rate", "qty": "Qty", "subtotal": "Subtotal"})
styled_care_df = display_care_df.style.map(style_day_type, subset=['Day Type'])


# --- 🖥️ UI LAYOUT ---
st.header("📊 1. Main Invoice Totals Check")
calc_item_total = df["subtotal"].sum()
calc_gst = 32.20 # Mocked for this example
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

st.header("🗓️ 2. Care Services & Rate Audit")
st.dataframe(styled_care_df, use_container_width=True, hide_index=True)
st.markdown("---")

# --- ⏱️ THE NEW TIMESHEET MATRIX ---
st.header("⏱️ 3. Timesheet Reconciliation")
st.write("Cross-checking the billed quantities from the grid against the physical timesheet logs.")

# 1. Aggregate Billed Hours
billed_grouped = df_care.groupby("date")["qty"].sum().reset_index().rename(columns={"date": "Service Date", "qty": "Billed Qty"})

# 2. Aggregate Logged Hours (from the new List format)
timesheet_df = pd.DataFrame(data["timesheet_hours"])
logged_grouped = timesheet_df.groupby("date")["hours"].sum().reset_index().rename(columns={"date": "Service Date", "hours": "Logged Hours"})

# 3. Merge & Compare
recon_df = pd.merge(billed_grouped, logged_grouped, on="Service Date", how="outer").fillna(0)
recon_df["Variance"] = recon_df["Billed Qty"] - recon_df["Logged Hours"]

def get_timesheet_status(variance):
    if variance > 0: return "🚨 Overbilled"
    elif variance < 0: return "⚠️ Underbilled"
    return "✅ Match"

recon_df["Status"] = recon_df["Variance"].apply(get_timesheet_status)

def style_variance(val):
    if val > 0: return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
    elif val < 0: return 'background-color: #ffffcc; color: #999900; font-weight: bold;'
    return 'color: green;'

styled_recon = recon_df.style.map(style_variance, subset=['Variance'])
st.dataframe(styled_recon, use_container_width=True, hide_index=True)
st.markdown("---")

# --- 💊 THE NEW THIRD-PARTY MATRIX ---
st.header("💊 4. Third-Party & Reimbursements")
col1, col2 = st.columns(2)

with col1:
    st.write("**A. Claimed in Main Grid (Excl. Surcharge):**")
    base_grid_df = df_third_party[~df_third_party['service'].str.contains('SURCHARGE', case=False, na=False)]
    base_grid_df = base_grid_df.rename(columns={"date": "Date", "service": "Service", "subtotal": "Amount claimed"})
    st.dataframe(base_grid_df[["Date", "Service", "Amount claimed"]], use_container_width=True, hide_index=True)

with col2:
    st.write("**B. Physical Receipts Found:**")
    receipts_df = pd.DataFrame(data["third_party_totals"])
    receipts_df = receipts_df.rename(columns={"date": "Date", "vendor": "Vendor", "amount": "Receipt Total"})
    st.dataframe(receipts_df, use_container_width=True, hide_index=True)

st.write("**Reimbursement Match:**")
grid_total = base_grid_df["Amount claimed"].sum()
receipts_total = receipts_df["Receipt Total"].sum()
tp_match_status = "✅ Match" if abs(grid_total - receipts_total) <= 0.05 else "❌ Mismatch"

tp_data = {
    "Metric": ["Totals"],
    "Grid Claims": [f"${grid_total:.2f}"],
    "Receipt Proof": [f"${receipts_total:.2f}"],
    "Status": [tp_match_status]
}
st.table(pd.DataFrame(tp_data).set_index("Metric"))
if abs(grid_total - receipts_total) > 0.05:
    st.error(f"⚠️ **Variance Detected:** The vendor claimed **${grid_total:.2f}** in the grid, but the physical receipts only add up to **${receipts_total:.2f}**. Please check the Uber line item.")
