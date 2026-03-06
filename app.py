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
    return 'color:
