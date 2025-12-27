import streamlit as st
import geopandas as gpd
import folium
import streamlit.components.v1 as components
from fpdf import FPDF
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime
import io
import os

# ==========================================
# 1. PAGE CONFIGURATION & SESSION STATE
# ==========================================
st.set_page_config(page_title="MLI Select Pro", layout="wide", page_icon="🏢")

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "accepted_terms" not in st.session_state: st.session_state["accepted_terms"] = False
if "projects" not in st.session_state: st.session_state["projects"] = {} 
if "current_project" not in st.session_state: st.session_state["current_project"] = "New Deal 1"

# ==========================================
# 2. PROFESSIONAL STYLING (CSS)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* GLOBAL RESET */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; color: #1E293B; }
    .stApp { background-color: #F8FAFC; }
    
    /* CARDS & METRICS */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetricLabel"] { font-size: 13px; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    div[data-testid="stMetricValue"] { font-size: 26px; color: #0F172A; font-weight: 700; }
    
    /* HEADERS */
    .section-header { font-size: 18px; font-weight: 700; color: #1E293B; margin-bottom: 15px; border-bottom: 2px solid #E2E8F0; padding-bottom: 8px; }
    
    /* INPUTS & BUTTONS */
    div.stButton > button {
        background-color: #0F172A; color: white; border-radius: 8px; 
        height: 48px; font-weight: 600; border: none; box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.2);
        transition: all 0.2s;
    }
    div.stButton > button:hover { background-color: #334155; transform: translateY(-1px); }
    
    /* FOOTER */
    .footer { position: fixed; bottom: 0; width: 100%; text-align: center; font-size: 11px; color: #94A3B8; padding: 15px; background: white; border-top: 1px solid #E2E8F0; z-index: 999; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. HELPERS & CALCULATORS
# ==========================================
DISCLAIMER_TEXT = "LEGAL DISCLAIMER: This model is for educational purposes only. Users must verify all CMHC criteria, rent caps, and underwriting assumptions with a qualified lender."

@st.cache_data
def load_canada_geo():
    try: return gpd.read_file("app_data.geojson")
    except: return None

def calculate_cmhc_fee(loan, pts):
    # CMHC Fee Scale
    rate = 1.25 if pts >= 100 else (2.25 if pts >= 70 else (3.00 if pts >= 50 else 4.00))
    return loan * (rate/100), rate

def calculate_pmt(principal, annual_rate, years):
    r = annual_rate / 100 / 12; n = years * 12
    if r == 0: return principal / n
    return principal * (r * (1 + r)**n) / ((1 + r)**n - 1)

def parse_score_selection(selection_string):
    # Helper to extract points from string like "Level 1: (50 Points)"
    if "100 Points" in selection_string: return 100
    if "70 Points" in selection_string: return 70
    if "50 Points" in selection_string: return 50
    if "30 Points" in selection_string: return 30
    if "20 Points" in selection_string: return 20
    return 0

def create_excel_download(data, rent_roll_df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        
        # TAB 1: EXECUTIVE SUMMARY
        summary_data = {
            "Metric": ["Project Name", "Market", "Underwritten Date", "", "Total Project Cost", "Approved Loan Amount", "Equity Required", "Loan-to-Cost (LTC)", "", "Net Operating Income (NOI)", "Debt Coverage Ratio (DCR)", "Going-In Cap Rate", "Cash-on-Cash Return", "", "MLI Select Total Score", "Amortization Period", "Underwritten Interest Rate"],
            "Value": [data['project_name'], data['market'], datetime.now().strftime('%Y-%m-%d'), "", f"${data['cost_base']:,.0f}", f"${data['approved_loan']:,.0f}", f"${data['equity']:,.0f}", f"{data['ltc']:.1f}%", "", f"${data['noi']:,.0f}", f"{data['dcr_actual']:.2f}x", f"{data['cap_rate']:.2f}%", f"{data['coc_return']:.2f}%", "", data['score'], f"{data['amort']} Years", f"{data['interest_rate']}%"]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Executive Summary', index=False)
        
        # TAB 2: INPUTS
        inputs_data = {"Category": ["Scoring", "Scoring", "Scoring", "Scoring", "Market", "Market", "Market", "Expenses", "Expenses", "Expenses", "Expenses", "Expenses", "Expenses", "Expenses"], "Item": ["Affordability Points", "Energy Efficiency Points", "Accessibility Points", "Total Score", "CMHC Rent Cap Used", "Residential Units", "Affordable Units %", "Vacancy Rate Used", "Mgmt Fee %", "Property Taxes", "Insurance", "Utilities", "Maintenance (R&M)", "Replacement Reserves"], "Value": [data['pts_aff'], data['pts_nrg'], data['pts_acc'], data['score'], f"${data['rent_cap']:,.0f}", len(rent_roll_df), f"{data['aff_pct']:.1f}%", f"{data['vacancy']}%", "4.25%", f"${data['ex_tax']:,.0f}", f"${data['ex_ins']:,.0f}", f"${data['ex_util']:,.0f}", f"${data['ex_rm']:,.0f}", f"${data['ex_res']:,.0f}"]}
        pd.DataFrame(inputs_data).to_excel(writer, sheet_name='Inputs & Assumptions', index=False)
        
        # TAB 3: RENT ROLL
        rent_roll_df.to_excel(writer, sheet_name='Rent Roll', index=False)
        
        # TAB 4: PRO FORMA
        pro_forma = []
        curr_noi = data['noi']; debt = data['annual_debt_svc']
        for i in range(1, 11):
            pro_forma.append({"Year": i, "Net Operating Income (NOI)": curr_noi, "Annual Debt Service": debt, "Cash Flow": curr_noi - debt, "DCR": curr_noi / debt if debt > 0 else 0}); curr_noi *= 1.02
        pd.DataFrame(pro_forma).to_excel(writer, sheet_name='10-Year Pro Forma', index=False)
        
        # TAB 5: STRESS TEST
        stress_data = []
        base = data['interest_rate']; loan = data['approved_loan']; amort = data['amort']
        for r in [base-0.5, base, base+0.5, base+1.0, base+1.5]:
            pmt = calculate_pmt(loan, r, amort)*12; dcr = data['noi']/pmt if pmt>0 else 0
            stress_data.append({"Rate": f"{r:.2f}%", "Payment": pmt, "DCR": dcr, "Status": "PASS" if dcr>=1.10 else "FAIL"})
        pd.DataFrame(stress_data).to_excel(writer, sheet_name='Stress Test', index=False)
    return output.getvalue()

# --- PDF ENGINE ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 10); self.set_text_color(150, 150, 150); self.cell(0, 10, 'MLI Select Pro Analysis', 0, 1, 'R'); self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.set_text_color(150, 150, 150); self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
    def watermark(self, text="DRAFT / UNAUDITED"):
        self.set_font('Arial', 'B', 40); self.set_text_color(240, 240, 240); self.text(30, 150, text)

def create_advanced_pdf(data, is_white_label, prepared_for, rent_roll_df, deal_notes):
    pdf = PDF()
    
    # Page 1: Executive Summary
    pdf.add_page()
    if not is_white_label: pdf.watermark()
    pdf.set_font('Arial', 'B', 24); pdf.set_text_color(33, 33, 33); pdf.cell(0, 15, data['project_name'], ln=1)
    pdf.set_font('Arial', '', 11); pdf.cell(0, 8, f"Market: {data['market']} | Date: {datetime.now().strftime('%Y-%m-%d')}", ln=1)
    if is_white_label: pdf.cell(0, 8, f"Prepared For: {prepared_for}", ln=1)
    pdf.ln(10); pdf.set_fill_color(240, 244, 248); pdf.rect(10, 50, 190, 45, 'F'); pdf.set_xy(15, 55); pdf.set_font('Arial', 'B', 14); pdf.cell(60, 10, "Approved Loan"); pdf.cell(60, 10, "Total Score"); pdf.cell(60, 10, "Equity Required", ln=1)
    pdf.set_xy(15, 65); pdf.set_font('Arial', 'B', 18); pdf.cell(60, 15, f"${data['approved_loan']:,.0f}"); pdf.cell(60, 15, f"{data['score']} Pts"); pdf.cell(60, 15, f"${data['equity']:,.0f}", ln=1)
    pdf.ln(25); pdf.set_text_color(0, 0, 0); pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "Financial Snapshot", ln=1); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5); metrics = [("NOI", f"${data['noi']:,.0f}"), ("Cap Rate", f"{data['cap_rate']:.2f}%"), ("DCR", f"{data['dcr_actual']:.2f}x"), ("Cash-on-Cash", f"{data['coc_return']:.2f}%"), ("LTC", f"{data['ltc']:.1f}%")]; pdf.set_font('Arial', '', 12)
    for l, v in metrics: pdf.cell(120, 8, l, 0); pdf.cell(60, 8, v, 0, 1, 'R')
    if deal_notes: pdf.ln(10); pdf.set_font('Arial', 'B', 12); pdf.cell(0, 10, "Underwriter Notes", ln=1); pdf.set_font('Arial', '', 10); pdf.multi_cell(0, 6, deal_notes)
    
    # Page 2: Pro Forma & Sensitivity
    pdf.add_page()
    if not is_white_label: pdf.watermark()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "10-Year Pro Forma", ln=1); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5); pdf.set_fill_color(220, 220, 220); pdf.set_font('Arial', 'B', 9); pdf.cell(20, 8, "Year", 1, 0, 'C', 1); pdf.cell(40, 8, "NOI", 1, 0, 'R', 1); pdf.cell(40, 8, "Debt", 1, 0, 'R', 1); pdf.cell(40, 8, "Cash Flow", 1, 0, 'R', 1); pdf.cell(30, 8, "DCR", 1, 1, 'C', 1)
    pdf.set_font('Arial', '', 9); noi = data['noi']; debt = data['annual_debt_svc']
    for i in range(1, 11):
        pdf.cell(20, 8, str(i), 1, 0, 'C'); pdf.cell(40, 8, f"{noi:,.0f}", 1, 0, 'R'); pdf.cell(40, 8, f"{debt:,.0f}", 1, 0, 'R'); pdf.cell(40, 8, f"{noi-debt:,.0f}", 1, 0, 'R'); pdf.cell(30, 8, f"{noi/debt:.2f}x", 1, 1, 'C'); noi *= 1.02
    pdf.ln(10); pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "Interest Rate Sensitivity", ln=1); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5); pdf.set_fill_color(220, 220, 220); pdf.set_font('Arial', 'B', 9); pdf.cell(40, 8, "Rate", 1, 0, 'C', 1); pdf.cell(50, 8, "Payment", 1, 0, 'C', 1); pdf.cell(40, 8, "DCR", 1, 1, 'C', 1); pdf.set_font('Arial', '', 9); base = data['interest_rate']
    for r in [base-0.5, base, base+0.5, base+1.0, base+1.5]:
        pmt = calculate_pmt(data['approved_loan'], r, data['amort'])*12; dcr = data['noi']/pmt if pmt>0 else 0
        pdf.cell(40, 8, f"{r:.2f}%", 1, 0, 'C'); pdf.cell(50, 8, f"${pmt:,.0f}", 1, 0, 'C'); pdf.set_text_color(220, 53, 69) if dcr < 1.10 else pdf.set_text_color(0, 0, 0); pdf.cell(40, 8, f"{dcr:.2f}x", 1, 1, 'C'); pdf.set_text_color(0, 0, 0)
    
    # Page 3: Rent Roll
    pdf.add_page()
    if not is_white_label: pdf.watermark()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "Appendix A: Rent Roll", ln=1); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(5); pdf.set_fill_color(220, 220, 220); pdf.set_font('Arial', 'B', 10); pdf.cell(80, 10, "Unit", 1, 0, 'L', 1); pdf.cell(30, 10, "Count", 1, 0, 'C', 1); pdf.cell(40, 10, "Rent", 1, 0, 'R', 1); pdf.cell(40, 10, "Total", 1, 1, 'R', 1); pdf.set_font('Arial', '', 10)
    if 'Total' not in rent_roll_df.columns: rent_roll_df['Total'] = rent_roll_df['Count'] * rent_roll_df['Rent ($)']
    for i, r in rent_roll_df.iterrows():
        pdf.cell(80, 10, str(r['Unit Type']), 1); pdf.cell(30, 10, str(r['Count']), 1, 0, 'C'); pdf.cell(40, 10, f"${r['Rent ($)']:,.0f}", 1, 0, 'R'); pdf.cell(40, 10, f"${r['Total']:,.0f}", 1, 1, 'R')
    pdf.set_y(-40); pdf.set_font('Arial', 'I', 8); pdf.multi_cell(0, 5, DISCLAIMER_TEXT)
    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 4. MAIN APP LOGIC
# ==========================================
def login_screen():
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        if os.path.exists("logo.png"): st.image("logo.png", width=200)
        else: st.markdown("<h1 style='text-align: center;'>MLI Select Pro</h1>", unsafe_allow_html=True)
        with st.form("login"):
            st.text_input("Username"); st.text_input("Password", type="password")
            if st.form_submit_button("Sign In"): st.session_state["logged_in"] = True; st.rerun()

def disclaimer_screen():
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.error("⚠️ Terms of Use"); st.markdown(DISCLAIMER_TEXT)
        if st.checkbox("I accept"): 
            if st.button("Enter Dashboard"): st.session_state["accepted_terms"] = True; st.rerun()

def main_app():
    with st.sidebar:
        if os.path.exists("logo.png"): st.image("logo.png", use_container_width=True)
        st.header("📂 Projects")
        p_name = st.text_input("Current Deal", st.session_state["current_project"])
        st.session_state["current_project"] = p_name
        if st.button("💾 Save Project"): st.session_state["projects"][p_name] = datetime.now(); st.toast("Saved!")
        st.divider(); st.button("Logout", on_click=lambda: st.session_state.update({"logged_in": False}))

    st.title(f"{st.session_state['current_project']}")
    gdf = load_canada_geo()
    alias_map = {"Pickering": "Toronto", "Ajax": "Toronto", "Mississauga": "Toronto", "Brampton": "Toronto"}
    
    t1, t2, t3, t4 = st.tabs(["📍 Market", "⚙️ Financials", "🏦 Underwriting", "📚 Knowledge Base"])
    
    # TAB 1: MARKET
    with t1:
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown('<div class="section-header">Location Intelligence</div>', unsafe_allow_html=True)
            if gdf is not None:
                opts = sorted(list(set(list(gdf['CMANAME'].unique()) + list(alias_map.keys()))))
                search = st.selectbox("Search Market", opts, index=opts.index("Toronto") if "Toronto" in opts else 0)
                real_cma = alias_map.get(search, search)
                d = gdf[gdf['CMANAME'] == real_cma].iloc[0] if not gdf[gdf['CMANAME'] == real_cma].empty else None
                rent_cap = d.get('max_rent', 1550) if d is not None else 1550
                if d is not None:
                    m = folium.Map([d.geometry.centroid.y, d.geometry.centroid.x], zoom_start=9, tiles="CartoDB positron")
                    folium.GeoJson(d.geometry).add_to(m)
                    components.html(m._repr_html_(), height=350)
            else: rent_cap = 1500
        with c2: 
            st.markdown('<div class="section-header">Metrics</div>', unsafe_allow_html=True)
            st.metric("CMHC Rent Cap", f"${rent_cap:,.0f}", help="Maximum rent per unit to qualify for Affordability Points in this specific zone.")
            st.info(f"**Zone:** {real_cma}\n\nUnits renting below **${rent_cap:,.0f}** contribute to your scoring.")

    # TAB 2: FINANCIALS
    with t2:
        c_inc, c_exp = st.columns(2)
        with c_inc:
            st.markdown('<div class="section-header">Income Strategy</div>', unsafe_allow_html=True)
            st.caption("Enter unit mix. Affordability is calculated automatically based on the Rent Cap.")
            df_temp = pd.DataFrame([{"Unit Type": "1-Bed", "Count": 10, "Rent ($)": 1500}, {"Unit Type": "2-Bed", "Count": 5, "Rent ($)": 2200}])
            edited_df = st.data_editor(df_temp, num_rows="dynamic", use_container_width=True)
            res_mask = ~edited_df['Unit Type'].str.contains('Parking|Retail', case=False)
            aff_count = edited_df[res_mask & (edited_df['Rent ($)'] <= rent_cap)]['Count'].sum()
            total_res = edited_df[res_mask]['Count'].sum()
            aff_pct = (aff_count/total_res*100) if total_res > 0 else 0
            if aff_pct >= 25: pts_auto = 100
            elif aff_pct >= 15: pts_auto = 70
            elif aff_pct >= 10: pts_auto = 50
            else: pts_auto = 0
            gross = (edited_df['Count'] * edited_df['Rent ($)']).sum(); potential_inc = gross * 12

        with c_exp:
            st.markdown('<div class="section-header">Operating Expenses</div>', unsafe_allow_html=True)
            c_e1, c_e2 = st.columns(2)
            vac = c_e1.number_input("Vacancy Rate %", 3.0, help="CMHC uses the HIGHER of market vacancy or actuals. Residential minimum is typically 1.0% - 3.0%.")
            mgmt = c_e2.number_input("Management Fee %", 4.25, help="Standard CMHC underwriting floor is 3.25% - 4.25% of EGI, even if self-managed.")
            tax = st.number_input("Property Taxes ($/Year)", 35000, help="Annual Municipal Property Taxes.")
            ins = st.number_input("Insurance Premium ($/Year)", 15000, help="Annual Building Insurance.")
            util = st.number_input("Utilities ($/Year)", 25000, help="Landlord-paid portions (Gas, Water, Common Hydro).")
            rm = st.number_input("Maintenance (R&M) ($/Year)", 10000, help="Day-to-day repairs. Standard is $850/unit/year.")
            reserves = st.number_input("Replacement Reserves ($/Year)", total_res * 500, help="Mandatory Capital Reserve Fund contribution. Typically $500 - $900 per door per year.")
            egi = potential_inc * (1 - vac/100); mgmt_amt = egi * (mgmt/100)
            total_opex = tax + ins + util + rm + reserves + mgmt_amt; noi = egi - total_opex
            chart = alt.Chart(pd.DataFrame({'Cat': ['Tax', 'Ins', 'Util', 'R&M', 'Rsrv', 'Mgmt'], 'Val': [tax, ins, util, rm, reserves, mgmt_amt]})).mark_arc(innerRadius=60).encode(theta='Val', color='Cat', tooltip=['Cat', 'Val']); st.altair_chart(chart, use_container_width=True)

        st.markdown("---")
        c_cost, c_score = st.columns(2)
        with c_cost: 
            st.markdown('<div class="section-header">Project Costs</div>', unsafe_allow_html=True)
            cost_base = st.number_input("Total Project Cost", 12000000, help="Purchase Price + Renovations + Soft Costs + Closing Costs.")
        with c_score:
            st.markdown('<div class="section-header">MLI Select Scoring</div>', unsafe_allow_html=True)
            s1, s2, s3 = st.columns(3)
            with s1: 
                # Expanded Labels
                aff_options = [
                    "None: 0 Points (0%)",
                    "Level 1: 50 Points (10% Units)",
                    "Level 2: 70 Points (15% Units)",
                    "Level 3: 100 Points (25% Units)"
                ]
                if st.checkbox("Manual Override", help="Manually select points instead of auto-calculation"): 
                    pts_aff_sel = st.selectbox("Affordability", aff_options, help="Units must be below the Rent Cap.")
                    pts_aff = parse_score_selection(pts_aff_sel)
                else: 
                    st.metric("Affordability", f"{pts_auto} Points", help=f"Auto-calculated: {aff_pct:.1f}% of units qualify.")
                    pts_aff = pts_auto
            
            with s2: 
                nrg_options = [
                    "None: 0 Points",
                    "Level 1: 30 Points (20% > NECB)",
                    "Level 2: 50 Points (25% > NECB)",
                    "Level 3: 100 Points (40% > NECB)"
                ]
                pts_nrg_sel = st.selectbox("Energy Efficiency", nrg_options, help=" Improvement over National Energy Code (NECB 2017).")
                pts_nrg = parse_score_selection(pts_nrg_sel)
                
            with s3: 
                acc_options = [
                    "None: 0 Points",
                    "Level 1: 20 Points (15% Units)",
                    "Level 2: 30 Points (20% Units)",
                    "Level 3: 100 Points (100% Units)"
                ]
                pts_acc_sel = st.selectbox("Accessibility", acc_options, help="Percent of units meeting CSA B651-18 Universal Design standards.")
                pts_acc = parse_score_selection(pts_acc_sel)
            
            score = pts_aff + pts_nrg + pts_acc
            if score >= 100: rewards = {"ltv": 0.95, "amort": 50}; st.success(f"🌟 **Total Score: {score}** (95% LTV | 50yr)")
            elif score >= 50: rewards = {"ltv": 0.95, "amort": 40}; st.info(f"✅ **Total Score: {score}** (95% LTV | 40yr)")
            else: rewards = {"ltv": 0.75, "amort": 25}; st.warning(f"⚠️ **Total Score: {score}** (Standard 75% LTV | 25yr)")

    # TAB 3: UNDERWRITING
    with t3:
        st.markdown('<div class="section-header">Underwriting Analysis</div>', unsafe_allow_html=True)
        stress_rate = st.slider("Stress Test Interest Rate (%)", 3.0, 8.0, 4.5, 0.25, help="Test the loan feasibility at higher rates.")
        
        loan_ltv = cost_base * rewards['ltv']
        r_mo = stress_rate/100/12; n_mo = rewards['amort']*12
        max_pmt = noi / 1.10
        loan_dcr = max_pmt * ((1 - (1+r_mo)**(-n_mo)) / r_mo)
        approved = min(loan_ltv, loan_dcr)
        
        c_chart = alt.Chart(pd.DataFrame({'Limit': ['Max LTV', 'Max DCR', 'Final Loan'], 'Value': [loan_ltv, loan_dcr, approved], 'Color': ['#CBD5E1', '#CBD5E1', '#10B981']})).mark_bar().encode(x='Limit', y='Value', color=alt.Color('Color', scale=None), tooltip=['Limit', 'Value']).properties(height=200); st.altair_chart(c_chart, use_container_width=True)

        fee, _ = calculate_cmhc_fee(approved, score); final_loan = approved + fee; equity = cost_base - approved
        actual_pmt = calculate_pmt(approved, stress_rate, rewards['amort']) * 12
        dcr_final = noi / actual_pmt if actual_pmt > 0 else 0
        coc = ((noi - actual_pmt) / equity * 100) if equity > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Net Operating Income", f"${noi:,.0f}", help="Total Revenue - Total Expenses"); m2.metric("Cap Rate", f"{(noi/cost_base*100):.2f}%", help="NOI / Total Cost")
        m3.metric("Approved Loan (Base)", f"${approved:,.0f}", help="Lesser of LTV or DCR"); m4.metric("Cash-on-Cash Return", f"{coc:.2f}%", help="Annual Cash Flow / Equity")
        
        st.divider(); c_d1, c_d2 = st.columns(2)
        pdf_data = {
            'project_name': st.session_state["current_project"], 'market': real_cma, 'rent_cap': rent_cap,
            'score': score, 'approved_loan': final_loan, 'equity': equity, 'noi': noi, 'cap_rate': (noi/cost_base)*100,
            'ltc': (approved/cost_base)*100, 'coc_return': coc, 'dcr_actual': dcr_final,
            'pts_aff': pts_aff, 'aff_pct': aff_pct, 'pts_nrg': pts_nrg, 'pts_acc': pts_acc, 'vacancy': vac,
            'annual_debt_svc': actual_pmt, 'cost_base': cost_base, 'interest_rate': stress_rate,
            'ex_tax': tax, 'ex_ins': ins, 'ex_util': util, 'ex_rm': rm, 'ex_res': reserves, 'amort': rewards['amort']
        }
        with c_d1:
            st.markdown("**PDF Report**"); notes = st.text_area("Deal Notes", help="Add custom notes to the report."); is_wl = st.checkbox("Remove Watermark"); client = st.text_input("Client Name") if is_wl else ""
            if st.button("📄 Generate Investor PDF"):
                b = create_advanced_pdf(pdf_data, is_wl, client, edited_df, notes)
                st.download_button("Download PDF", b, file_name="Report.pdf")
        with c_d2:
            st.markdown("**Excel Model**"); st.caption("Download full unlocked spreadsheet.")
            if st.button("📊 Download Excel Model"):
                x = create_excel_download(pdf_data, edited_df)
                st.download_button("Download .xlsx", x, file_name="Model.xlsx")

    # TAB 4: KNOWLEDGE BASE (BEEFED UP)
    with t4:
        st.markdown('<div class="section-header">MLI Select Reference Manual</div>', unsafe_allow_html=True)
        st.markdown("""
        ### 🏗️ Pillar 1: Affordability
        To qualify, units must have rents below the specific **CMHC Median Market Rent** for the area.
        * **Level 1 (50 Points):** Min. **10%** of units at affordable levels.
        * **Level 2 (70 Points):** Min. **15%** of units at affordable levels.
        * **Level 3 (100 Points):** Min. **25%** of units at affordable levels.
        *(Note: Affordable units must be maintained for at least 10 years.)*
        
        ### ⚡ Pillar 2: Energy Efficiency
        Performance is measured against the **NECB 2017** (National Energy Code for Buildings).
        * **Level 1 (30 Points):** **20%** decrease in energy consumption & GHGs over NECB 2017.
        * **Level 2 (50 Points):** **25%** decrease in energy consumption & GHGs.
        * **Level 3 (100 Points):** **40%** decrease in energy consumption & GHGs.
        
        ### ♿ Pillar 3: Accessibility
        Units must meet **CSA B651-18** Universal Design standards.
        * **Level 1 (20 Points):** **15%** of units are accessible.
        * **Level 2 (30 Points):** **20%** of units are accessible.
        * **Level 3 (100 Points):** **100%** of units are accessible (Full Universal Design).
        
        ---
        ### 📖 Financial Definitions
        * **Net Operating Income (NOI):** The annual income generated by an income-producing property after taking into account all income collected from operations, and deducting all expenses incurred from operations. **NOI = EGI - OpEx**.
        * **Effective Gross Income (EGI):** The potential gross income minus vacancy and credit loss.
        * **Debt Coverage Ratio (DCR):** The ratio of cash available for debt servicing to interest, principal and lease payments. CMHC requires a minimum **1.10x** DCR for residential.
        * **Replacement Reserves:** Funds set aside that provide for the periodic replacement of building components that wear out more rapidly than the building itself (e.g., Roof, HVAC, Windows).
        """)

if not st.session_state["logged_in"]: login_screen()
elif not st.session_state["accepted_terms"]: disclaimer_screen()
else: main_app()
st.markdown(f'<div class="footer">MLI Select Pro © 2025 | {st.session_state["current_project"]}</div>', unsafe_allow_html=True)