import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI
import json
import random
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Family OS", page_icon="🏡", layout="centered", initial_sidebar_state="collapsed")

# --- DATABASE CONNECTION (Fail-Safe Version) ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        # 1. Try to load from Streamlit Secrets
        if "firebase" in st.secrets:
            try:
                # Convert the AttrDict to a normal Python dict
                key_dict = dict(st.secrets["firebase"])
                
                # Double-check the private key has real newlines
                # (The script fixed this, but this is a safety net)
                if "\\n" in key_dict["private_key"]:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            except Exception as e:
                st.error(f"❌ Secret Error: {e}")
                return None
        
        # 2. Local Fallback
        else:
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                st.warning("⚠️ No database connection found.")
                return None

    return firestore.client()

db = get_db()

# --- OPENAI SETUP ---
if "OPENAI_API_KEY" in st.secrets:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    client = OpenAI(api_key="sk-placeholder")

# --- DATA FETCHING ---
if 'family_data' not in st.session_state:
    st.session_state['family_data'] = {}

def refresh_data():
    if db:
        doc = db.collection("families").document("fam_8829_xyz").get()
        if doc.exists:
            st.session_state['family_data'] = doc.to_dict()
        else:
            # Create default if missing
            default = {
                "members": [{"name": "Dad", "role": "parent"}],
                "current_week_plan": {}
            }
            db.collection("families").document("fam_8829_xyz").set(default)
            st.session_state['family_data'] = default

# Load data on start
if not st.session_state['family_data']:
    refresh_data()

data = st.session_state['family_data']

# --- MAIN APP UI ---
st.title("🏡 Family OS")

# Debug Status
if db:
    st.caption("✅ Database Connected")
else:
    st.error("❌ Database Disconnected")

# Login / Main View
if 'user' not in st.session_state or not st.session_state['user']:
    st.subheader("Who is this?")
    if 'members' in data:
        cols = st.columns(len(data['members']))
        for i, m in enumerate(data['members']):
            if cols[i].button(m['name'], use_container_width=True):
                st.session_state['user'] = m
                st.rerun()
    elif db:
        st.info("Loading members...")
        if st.button("Refresh"):
            refresh_data()
            st.rerun()
else:
    # LOGGED IN VIEW
    user = st.session_state['user']
    c1, c2 = st.columns([3,1])
    c1.write(f"**Hi, {user['name']}!**")
    if c2.button("Logout"):
        st.session_state['user'] = None
        st.rerun()
    
    st.divider()
    
    # Simple Planner View (Proof of Concept)
    st.subheader("📅 This Week")
    if st.button("Generate New Plan"):
        st.info("Chef is thinking...")
        # (AI Logic would go here)
        st.success("Done! (Reload to see)")
    
    if 'current_week_plan' in data:
        st.json(data['current_week_plan'])