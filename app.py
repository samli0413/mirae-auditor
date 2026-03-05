import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="Invoice Auditor V2", layout="wide")
st.title("🧾 Automated Invoice Discrepancy Engine")

# 1. THE DATA (This is the exact output from your Gemini test!)
raw_json = """
{
  "summary_rows": [
    {"date": "26/01/2026", "service": "PERSONAL CARE", "price": 182.6, "qty": 2.0, "subtotal": 365.2},
    {"date": "26/01/2026", "service": "MEALS/ Meal preparation", "price": 171.6, "qty": 1.0, "subtotal": 171.6},
    {"date": "01/02/2026", "service": "PHARMACY REIMBURSEMENT", "price": 486.95, "qty": 1.0, "subtotal": 486.95},
    {"date": "01/02/2026", "service": "INVOICE SURCHARGE 10%", "price": 48.69, "qty": 1.0, "subtotal": 48.69}
  ],
  "timesheet_hours": {
    "26/01/2026": 3.0
  },
  "third_party_totals": [486.95],
  "invoice_totals": {
    "item_total": 4716.04,
    "gst": 418.04,
    "total_due": 5134.08
  }
}
"""
# (I shortened the JSON slightly above just to keep the code clean, but you can paste the full 34-item list in!)

data = json.loads(raw_json)

# 2. BUILD THE DATAFRAMES
df = pd.DataFrame(data["summary_rows"])
timesheet = data["timesheet_hours"]
totals = data["invoice_totals"]

# 3. THE DISCREPANCY ENGINE
st.header("🔍 Audit Results")
errors = []

# Check A: The Bottom Line Math
calculated_subtotal = df["subtotal"].sum()
if abs(calculated_subtotal - totals["item_total"]) > 0.05: # Using 0.05 to safely ignore tiny 1-cent rounding errors
    errors.append(f"🚨 **Vendor Subtotal Mismatch:** The line items add up to **${calculated_subtotal:.2f}**, but the vendor's total claims **${totals['item_total']:.2f}**.")

# Check B: Timesheet Matching (Groups billed hours by day and compares to timesheet)
daily_billed = df.groupby("date")["qty"].sum().to_dict()
for date, billed_units in daily_billed.items():
    logged_hours = timesheet.get(date, 0)
    # We only flag it if it's a standard care day, ignoring the 01/02 pharmacy date for this test
    if billed_units != logged_hours and logged_hours > 0: 
        errors.append(f"⏱️ **Timesheet Mismatch on {date}:** Vendor billed for {billed_units} units, but timesheet shows {logged_hours} hours.")

# Check C: Line-by-Line Math
df["Status"] = "✅ OK"
for index, row in df.iterrows():
    expected_sub = row["qty"] * row["price"]
    if abs(expected_sub - row["subtotal"]) > 0.05:
        df.at[index, "Status"] = f"❌ Math Error (Should be ${expected_sub:.2f})"
        errors.append(f"🧮 **Line Item Math Error on {row['date']}:** {row['service']} was calculated incorrectly.")

# 4. THE USER INTERFACE
if errors:
    st.error("### ⚠️ Discrepancies Found! Please review the errors below before approving.")
    for error in errors:
        st.write(error)
else:
    st.success("### 🎉 All checks passed! The math and timesheets match perfectly.")

st.markdown("---")
st.subheader("📋 Invoice Line Items")
st.dataframe(df, use_container_width=True)

# 5. EXPORT FOR VENDOR
st.subheader("📤 Export Discrepancy Report")
st.write("Generate a quick spreadsheet of these errors to send back to the vendor.")

# Filter to only show rows with errors
error_df = df[df["Status"] != "✅ OK"]

# Create a CSV download button
csv = error_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="Download Error Report (CSV)",
    data=csv,
    file_name="vendor_discrepancy_report.csv",
    mime="text/csv",
)
