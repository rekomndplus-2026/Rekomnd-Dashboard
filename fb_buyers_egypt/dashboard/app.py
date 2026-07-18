"""
Streamlit Dashboard — Team Lead Management
===========================================
Run with:  streamlit run dashboard/app.py
"""

import os
import sys
import subprocess
from datetime import datetime
import json
import time

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import DatabaseManager
from config.settings import Config

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Egypt RE Leads",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS (Premium Dark Theme) ─────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

    .stApp {
        font-family: 'Outfit', sans-serif;
        background-color: #0f172a;
        color: #f8fafc;
    }
    
    /* Headers */
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    /* Main Gradient Title */
    .main-title {
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
    }

    /* Metric Cards */
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 20px;
        padding: 24px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        margin-bottom: 1rem;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    .metric-card h2 {
        font-size: 42px;
        font-weight: 800;
        margin: 0;
        background: linear-gradient(to right, #fff, #cbd5e1);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .metric-card p {
        font-size: 15px;
        font-weight: 500;
        color: #94a3b8;
        margin: 8px 0 0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    /* Specialized Cards */
    .hot-lead { background: linear-gradient(135deg, rgba(244, 63, 94, 0.1) 0%, rgba(225, 29, 72, 0.2) 100%); border-color: rgba(244, 63, 94, 0.3); }
    .hot-lead h2 { background: linear-gradient(to right, #fda4af, #f43f5e); -webkit-background-clip: text; }
    
    .phone-lead { background: linear-gradient(135deg, rgba(56, 189, 248, 0.1) 0%, rgba(14, 165, 233, 0.2) 100%); border-color: rgba(56, 189, 248, 0.3); }
    .phone-lead h2 { background: linear-gradient(to right, #bae6fd, #38bdf8); -webkit-background-clip: text; }
    
    .contacted-lead { background: linear-gradient(135deg, rgba(52, 211, 153, 0.1) 0%, rgba(16, 185, 129, 0.2) 100%); border-color: rgba(52, 211, 153, 0.3); }
    .contacted-lead h2 { background: linear-gradient(to right, #a7f3d0, #34d399); -webkit-background-clip: text; }

    /* Session Status */
    .session-box {
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 1rem;
        font-weight: 500;
    }
    .session-ok { background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; }
    .session-warn { background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24; }
    .session-bad { background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; }

    /* Dataframes */
    div[data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.1);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
    }
    
    /* Streamlit overrides for dark mode */
    .stSelectbox label, .stSlider label {
        color: #e2e8f0 !important;
        font-weight: 500;
    }
    
    /* Custom button styling */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }
    
    /* Terminal output */
    .terminal-box {
        background-color: #020617;
        color: #38bdf8;
        font-family: monospace;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #1e293b;
        height: 300px;
        overflow-y: auto;
    }
</style>
""", unsafe_allow_html=True)


# ── Initialize ────────────────────────────────────────────────────────────
@st.cache_resource
def get_db():
    return DatabaseManager(Config.DB_URL)

db = get_db()

def stream_command(cmd_list):
    """Run a command and stream output to a Streamlit element."""
    st.markdown("### 📡 Terminal Output")
    log_container = st.empty()
    logs = []
    
    process = subprocess.Popen(
        cmd_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    
    for line in iter(process.stdout.readline, ''):
        logs.append(line.strip())
        # Keep only last 20 lines for clean display
        display_logs = logs[-20:]
        html = f'<div class="terminal-box">{"<br>".join(display_logs)}</div>'
        log_container.markdown(html, unsafe_allow_html=True)
        
    process.stdout.close()
    process.wait()
    return process.returncode

def add_group_to_config(url, name, region):
    """Safely append a group to config/groups.py"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "groups.py")
    
    new_group = f"""    {{
        "name":    "{name}",
        "url":     "{url}",
        "region":  "{region}",
        "enabled": True,
    }},
"""
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # insert before the closing bracket of EGYPT_REALESTATE_GROUPS
    content = content.replace("]\n\nACTIVE_GROUPS", new_group + "]\n\nACTIVE_GROUPS")
    
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)

# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ Controls")
    st.markdown("---")

    # Session Status
    session_file = Config.SESSION_FILE
    if os.path.exists(session_file):
        meta_path = session_file + ".meta"
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            saved_at = meta.get("saved_at", "unknown")
            st.markdown(f'<div class="session-box session-ok">'
                       f'✅ Session Active<br>'
                       f'<small style="color:rgba(255,255,255,0.7);">Saved: {saved_at[:19]}</small></div>',
                       unsafe_allow_html=True)
        else:
            st.markdown('<div class="session-box session-warn">'
                       '⚠️ Session exists (no metadata)</div>',
                       unsafe_allow_html=True)
    else:
        st.markdown('<div class="session-box session-bad">'
                   '❌ No session found</div>',
                   unsafe_allow_html=True)

    # Action Buttons
    if st.button("🚀 Start Scraping Groups", use_container_width=True, type="primary"):
        st.session_state.run_scrape = True
        
    st.markdown("### 📌 Scrape with a Post")
    with st.form("scrape_post_form"):
        post_url_input = st.text_input("Post URL", placeholder="https://www.facebook.com/...")
        if st.form_submit_button("Scrape Post", use_container_width=True):
            if post_url_input:
                st.session_state.run_scrape_post = True
                st.session_state.post_url_to_scrape = post_url_input
            else:
                st.error("Please enter a Post URL")
        
    if st.button("🔄 Refresh Session", use_container_width=True):
        st.session_state.run_refresh = True

    st.markdown("---")
    
    # Group Management
    st.markdown("### ➕ Add Group")
    with st.form("add_group_form"):
        new_url = st.text_input("Group URL")
        new_name = st.text_input("Group Name")
        new_region = st.selectbox("Region", ["general", "cairo", "new_cairo", "new_capital", "west_cairo", "alexandria", "north_coast", "red_sea", "custom"])
        if st.form_submit_button("Add to Config", use_container_width=True):
            if new_url and new_name:
                add_group_to_config(new_url, new_name, new_region)
                st.success(f"Added {new_name}!")
            else:
                st.error("Please fill URL and Name")

    st.markdown("---")

    # Filters
    st.markdown("### 🔍 Filters")
    min_score = st.slider("Min Lead Score", 0, 100, 0, 5)

    df_all = db.get_all_leads()

    regions = ["All"] + sorted(df_all["group_region"].unique().tolist()) if len(df_all) > 0 else ["All"]
    selected_region = st.selectbox("Region", regions)

    prop_types = ["All"] + sorted(df_all["property_type"].unique().tolist()) if len(df_all) > 0 else ["All"]
    selected_type = st.selectbox("Property Type", prop_types)

    intents = ["All", "buy", "rent"]
    selected_intent = st.selectbox("Intent", intents)

    phone_only = st.checkbox("📱 With phone number only", value=False)
    email_only = st.checkbox("📧 With email only", value=False)
    not_contacted = st.checkbox("🆕 Not contacted only", value=False)
    hide_brokers = st.checkbox("🚫 Hide brokers", value=False)

    st.markdown("---")

    # Export
    if st.button("📥 Export to Excel", use_container_width=True):
        os.makedirs(Config.EXPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        path = os.path.join(Config.EXPORT_DIR, f"leads_{ts}.xlsx")
        db.export_to_excel(path, min_score=min_score)
        st.success(f"✅ Exported to {path}")


# ── Main Content ──────────────────────────────────────────────────────────

st.markdown('<div class="main-title">Real Estate AI Lead Engine</div>', unsafe_allow_html=True)
st.markdown("<p style='color: #94a3b8; font-size: 1.1rem; margin-bottom: 2rem;'>Aggregating, scoring, and delivering Facebook buyer signals directly to your team.</p>", unsafe_allow_html=True)

# Handle Actions
if st.session_state.get("run_scrape", False):
    st.session_state.run_scrape = False
    with st.spinner("Scraping groups in progress..."):
        # We need to run the main.py script
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        stream_command([sys.executable, script_path, "--scrape"])
        st.success("Scrape Complete! Reloading data...")
        time.sleep(2)
        st.rerun()

if st.session_state.get("run_scrape_post", False):
    st.session_state.run_scrape_post = False
    post_url = st.session_state.get("post_url_to_scrape", "")
    if post_url:
        with st.spinner(f"Scraping post: {post_url[:30]}..."):
            script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
            stream_command([sys.executable, script_path, "--scrape-post", post_url])
            st.success("Post Scrape Complete! Reloading data...")
            time.sleep(2)
            st.rerun()

if st.session_state.get("run_refresh", False):
    st.session_state.run_refresh = False
    with st.spinner("Opening browser to refresh session... Please interact with the Chrome window if needed."):
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        stream_command([sys.executable, script_path, "--refresh-session"])
        st.success("Session Refresh Task Completed!")
        time.sleep(2)
        st.rerun()


# Stats cards
stats = db.get_stats()

col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    st.markdown(f'<div class="metric-card">'
               f'<h2>{stats["total_leads"]}</h2>'
               f'<p>Total Leads</p></div>',
               unsafe_allow_html=True)
with col2:
    st.markdown(f'<div class="metric-card hot-lead">'
               f'<h2>{stats["hot_leads"]}</h2>'
               f'<p>Hot Leads (60+)</p></div>',
               unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="metric-card phone-lead">'
               f'<h2>{stats["with_phone"]}</h2>'
               f'<p>With Phone</p></div>',
               unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="metric-card" style="background: linear-gradient(135deg, rgba(168, 85, 247, 0.1) 0%, rgba(139, 92, 246, 0.2) 100%); border-color: rgba(168, 85, 247, 0.3);">'
               f'<h2 style="background: linear-gradient(to right, #d8b4fe, #a855f7); -webkit-background-clip: text;">{stats.get("with_email", 0)}</h2>'
               f'<p>With Email</p></div>',
               unsafe_allow_html=True)
with col5:
    st.markdown(f'<div class="metric-card contacted-lead">'
               f'<h2>{stats["contacted"]}</h2>'
               f'<p>Contacted</p></div>',
               unsafe_allow_html=True)
with col6:
    st.markdown(f'<div class="metric-card">'
               f'<h2>{stats["avg_lead_score"]}</h2>'
               f'<p>Avg Score</p></div>',
               unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Apply filters
if len(df_all) > 0:
    df = df_all.copy()
    if min_score > 0:
        df = df[df["lead_score"] >= min_score]
    if selected_region != "All":
        df = df[df["group_region"] == selected_region]
    if selected_type != "All":
        df = df[df["property_type"] == selected_type]
    if selected_intent != "All":
        df = df[df["intent"] == selected_intent]
    if phone_only:
        df = df[df["phone_numbers"].str.len() > 0]
    if email_only:
        df = df[df["emails"].str.len() > 0]
    if not_contacted:
        df = df[df["is_contacted"] == False]
    if hide_brokers:
        df = df[df["is_broker"] != True]

    # Charts row
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("<h3 style='color: #e2e8f0;'>📊 Lead Score Distribution</h3>", unsafe_allow_html=True)
        if len(df) > 0:
            fig = px.histogram(
                df, x="lead_score", nbins=20,
                color_discrete_sequence=["#38bdf8"],
                labels={"lead_score": "Lead Score", "count": "Count"},
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Outfit", color="#94a3b8"),
                margin=dict(l=20, r=20, t=20, b=20),
                height=300,
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
            st.plotly_chart(fig, use_container_width=True)

    with chart_col2:
        st.markdown("<h3 style='color: #e2e8f0;'>🗺️ Leads by Region</h3>", unsafe_allow_html=True)
        if len(df) > 0:
            region_counts = df["group_region"].value_counts().reset_index()
            region_counts.columns = ["region", "count"]
            fig2 = px.pie(
                region_counts, values="count", names="region",
                color_discrete_sequence=px.colors.qualitative.Pastel,
                hole=0.5,
            )
            fig2.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Outfit", color="#94a3b8"),
                margin=dict(l=20, r=20, t=20, b=20),
                height=300,
            )
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # Leads table
    st.markdown(f"<h3 style='color: #e2e8f0;'>👥 Leads ({len(df)} results)</h3>", unsafe_allow_html=True)

    display_cols = [
        "buyer_name", "phone_numbers", "emails", "lead_score", "intent",
        "property_type", "locations", "budget_max", "bedrooms",
        "area_max", "lives_in", "work_title", "is_broker",
        "raw_text", "group_region", "notes", "is_contacted",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(
        df[available_cols].sort_values("lead_score", ascending=False),
        use_container_width=True,
        height=600,
        column_config={
            "lead_score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%d",
            ),
            "budget_max": st.column_config.NumberColumn(
                "Budget (EGP)", format="%,.0f",
            ),
            "area_max": st.column_config.NumberColumn(
                "Area (m²)", format="%,.0f",
            ),
            "is_contacted": st.column_config.CheckboxColumn("Contacted"),
            "is_broker": st.column_config.CheckboxColumn("Broker?"),
            "raw_text": st.column_config.TextColumn("Comment / Post Text"),
            "emails": st.column_config.TextColumn("Emails"),
            "lives_in": st.column_config.TextColumn("Lives In"),
            "work_title": st.column_config.TextColumn("Job Title"),
        },
    )

else:
    st.info("🔍 No leads yet. Click 'Start Scraping' in the sidebar to start collecting.")

# ── Footer ────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.9rem;'>Egypt Real Estate Lead Generator | Built for your team</p>", unsafe_allow_html=True)
