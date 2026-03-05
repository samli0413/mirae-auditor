import streamlit as st
import pandas as pd
import json
import holidays

st.set_page_config(page_title="Invoice Auditor V2", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine")

# --- 📍 UI: STATE SELECTION ---
st.subheader("⚙️ Audit Settings")
client_state = st.radio("Select Client State (for Public Holiday logic):", ["NSW", "VIC"], horizontal=True)
st.markdown("---")

# 1. THE FULL JSON DATA
raw_json = """
{
"summary_rows": [
{"date": "26/01/2026", "service": "PERSONAL CARE", "price": 182.6, "qty": 2.0, "subtotal": 365.2},
{"date": "26/01/2026", "service": "MEALS", "price": 171.6, "qty": 1.0, "subtotal": 171.6},
{"date": "27/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "27/01/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "27/01/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "28/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "28/01/2026", "service": "MEALS", "price": 78.0, "qty": 2.0, "subtotal": 156.0},
{"date": "29/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "29/01/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "30/01/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "30/01/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "30/01/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "31/01/2026", "service": "PERSONAL CARE", "price": 116.2, "qty": 2.0, "subtotal": 232.4},
{"date": "31/01/2026", "service": "MEALS", "price": 109.2, "qty": 1.0, "subtotal": 109.2},
{"date": "31/01/2026", "service": "RESPITE", "price": 109.2, "qty": 1.0, "subtotal": 109.2},
{"date": "02/02/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "02/02/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "03/02/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "03/02/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "03/02/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "04/02/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "04/02/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "04/02/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "05/02/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "05/02/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "05/02/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "06/02/2026", "service": "PERSONAL CARE", "price": 83.0, "qty": 2.0, "subtotal": 166.0},
{"date": "06/02/2026", "service": "MEALS", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "06/02/2026", "service": "RESPITE", "price": 78.0, "qty": 1.0, "subtotal": 78.0},
{"date": "07/02/2026", "service": "PERSONAL CARE", "price": 116.2, "qty": 2.0, "subtotal": 232.4},
{"date": "07/02/2026", "service": "MEALS", "price": 109.2, "qty": 1.0, "subtotal": 109.2},
{"date": "07/02/2026", "service": "RESPITE", "price": 109.2, "qty": 1.0, "subtotal": 109.2},
{"date": "01/02/2026", "service": "PHARMACY REIMBURSEMENT", "price": 486.95, "qty": 1.0, "subtotal": 486.95},
{"date": "01/02/2026", "service": "INVOICE SURCHARGE 10%", "price": 48.69, "qty": 1.0, "subtotal": 48.69}
],
"third_party_totals": [486.95],
"invoice_totals": {
"item_total": 4716.04,
"gst": 418.04,
"total_due": 5134.08
}
}
"""
data = json.loads(raw_json)
df = pd.DataFrame(data["summary_rows"])

# --- 🗓️ DYNAMIC HOLIDAY LOGIC ---
# Load the correct holidays for the selected state and the year 2026
state_holidays = holidays.AU(subdiv=client_state, years=2026)

def get_day_type(date_str):
    dt = pd.to_datetime(date_str, format="%d/%m/%Y")
    
    if dt in state_holidays:
        # e.g., Jan 26 is Australia Day, so it will trigger here
        return "Public Hol"
    if dt.weekday() == 5: 
        return "Saturday"
    if dt.weekday() == 6: 
        return "Sunday"
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

# --- ⚙️ PROCESSING THE DATAFRAME ---
# Split data into Care Services vs Third Party
df_third_party = df[df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT', case=False, na=False)].copy()
df_care = df[~df['service'].str.contains('PHARMACY|SURCHARGE|REIMBURSEMENT', case=False, na=False)].copy()

# Apply Rate Logic
df_care["Day Type"] = df_care["date"].apply(get_day_type)
df_care["Expected Rate"] = df_care.apply(lambda row: get_expected_rate(row["service"], row["Day Type"]), axis=1)

# Check for Matches
df_care["Rate Match"] = df_care.apply(lambda row: "✅ Yes" if abs(row["price"] - row["Expected Rate"]) <= 0.05 else "❌ No", axis=1)
df_care["Math OK"] = df_care.apply(lambda row: "✅" if abs((row["price"] * row["qty"]) - row["subtotal"]) <= 0.05 else "❌", axis=1)

# Format the Display Table (Renamed 'date' to 'Service Date' for clarity)
display_care_df = df_care[["date", "Day Type", "service", "Expected Rate", "price", "Rate Match", "qty", "subtotal", "Math OK"]]
display_care_df = display_care_df.rename(columns={"date": "Service Date", "price": "Extracted Rate"})


# --- 🖥️ UI LAYOUT ---
st.header("📊 1. Main Invoice Totals Check")
calc_item_total = df["subtotal"].sum()
calc_gst = 418.04 
calc_grand = calc_item_total + calc_gst

totals_data = {
    "Metric": ["Item Total", "GST", "Grand Total"],
    "Vendor Claims": [f"${data['invoice_totals']['item_total']:.2f}", f"${data['invoice_totals']['gst']:.2f}", f"${data['invoice_totals']['total_due']:.2f}"],
    "App Calculated": [f"${calc_item_total:.2f}", f"${calc_gst:.2f}", f"${calc_grand:.2f}"],
    "Status": [
        "✅ Match" if abs(data['invoice_totals']['item_total'] - calc_item_total) <= 0.05 else "❌ Mismatch",
        "✅ Match" if abs(data['invoice_totals']['gst'] - calc_gst) <= 0.05 else "❌ Mismatch",
        "✅ Match" if abs(data['invoice_totals']['total_due'] - calc_grand) <= 0.05 else "❌ Mismatch"
    ]
}
st.table(pd.DataFrame(totals_data))
st.markdown("---")

st.header("🗓️ 2. Care Services & Rate Audit")
st.write("Cross-checking dates, states, and weekend/holiday penalty rates.")
# Using st.dataframe allows your wife to sort by any of these columns instantly!
st.dataframe(display_care_df, use_container_width=True, height=500)
st.markdown("---")

st.header("💊 3. Third-Party & Reimbursements")
col1, col2 = st.columns([2, 1])

with col1:
    st.write("**Extracted Third-Party Line Items:**")
    df_third_party = df_third_party.rename(columns={"date": "Service Date", "price": "Rate", "qty": "Qty", "subtotal": "Subtotal"})
    st.dataframe(df_third_party[["Service Date", "service", "Subtotal"]], use_container_width=True)

with col2:
    st.write("**Third-Party Math Check:**")
    ai_raw_receipts = sum(data["third_party_totals"])
    line_items_sum = df_third_party["Subtotal"].sum()
    
    st.info(f"**Base Receipts Found:** ${ai_raw_receipts:.2f}\n\n**Total Billed (with surcharges):** ${line_items_sum:.2f}")
    if line_items_sum > ai_raw_receipts:
        st.warning(f"Note: Vendor billed **${(line_items_sum - ai_raw_receipts):.2f}** more in the grid than the base receipts. Please verify this surcharge is valid.")
