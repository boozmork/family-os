import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI
import json
import random
from datetime import datetime

# --- 1. CONFIG ---
st.set_page_config(page_title="Family OS", page_icon="🏡", layout="centered", initial_sidebar_state="collapsed")

# --- 2. DATABASE CONNECTION ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        if "firebase" in st.secrets:
            try:
                key_dict = dict(st.secrets["firebase"])
                if "\\n" in key_dict["private_key"]:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            except Exception as e:
                st.error(f"❌ Secret Error: {e}")
                return None
        else:
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                st.warning("⚠️ No database connection found.")
                return None
    return firestore.client()

db = get_db()

# --- 3. OPENAI SETUP ---
if "OPENAI_API_KEY" in st.secrets:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    client = OpenAI(api_key="sk-placeholder")

# --- 4. DATA LOGIC ---
@st.cache_data(ttl=600)
def get_data_cached():
    if db is None: return {}
    try:
        doc = db.collection("families").document("fam_8829_xyz").get()
        if doc.exists:
            return doc.to_dict()
        else:
            default = {
                "members": [{"name": "Dad", "role": "parent"}, {"name": "Kid", "role": "child"}],
                "kitchen_profile": {"current_inventory": ["Pasta", "Tomato Sauce"]},
                "current_week_plan": {}
            }
            db.collection("families").document("fam_8829_xyz").set(default)
            return default
    except Exception as e:
        st.error(f"Data Fetch Error: {e}")
        return {}

def force_refresh():
    get_data_cached.clear()
    if 'family_data' in st.session_state:
        del st.session_state['family_data']
    st.session_state['family_data'] = get_data_cached()

# --- 5. AGENT LOGIC (UPDATED FOR VARIETY) ---
ALL_STYLES = [
    "Jamie Oliver 15-Minute Meals (Quick, fresh, rustic)",
    "Ottolenghi (Middle Eastern, veg-heavy, complex spices)",
    "Italian Nonna (Classic pasta, slow sauces, comfort)",
    "Mexican Street Food (Tacos, fresh salsas, grilled meats)",
    "Japanese Izakaya (Rice bowls, teriyaki, miso, clean flavors)",
    "Modern British (Roasts, pies, seasonal veg)",
    "Thai Street Food (Pad Thai, curries, zesty salads)",
    "Mediterranean Diet (Grilled fish, olive oil, salads)",
    "American Diner (Burgers, mac n cheese, ribs)",
    "French Bistro (Steak frites, quiches, rich sauces)",
    "Indian Curry House (Rich curries, naan, tandoori)",
    "Greek Taverna (Souvlaki, fresh salads, feta)"
]

def get_style_preferences(family_data):
    """
    Instead of picking ONE style, we now return the data so the AI can mix it up.
    """
    prefs = family_data.get('style_preferences', {})
    favorites = [s for s in ALL_STYLES if prefs.get(s, 0) > 2]
    disliked = [s for s in ALL_STYLES if prefs.get(s, 0) < -1]
    
    return favorites, disliked

def generate_week_plan():
    data = get_data_cached()
    schedule = {"Monday": [], "Tuesday": ["Busy"], "Wednesday": [], "Thursday": [], "Friday": [], "Saturday": [], "Sunday": []}
    
    # Get the lists, don't pick just one
    favorites, disliked = get_style_preferences(data)
    
    prompt = f"""
    You are a professional family meal planner for a UK family.
    Plan a 7-day menu (Mon-Sun).
    
    CRITICAL RULES FOR MEAL TYPES:
    1. **BREAKFAST**: Must be standard UK/Western style (Toast, Cereal, Porridge, Eggs, Yoghurt, Pancakes). NO soups, rice, or dinner leftovers.
    2. **LUNCH**: Must be "Packed Lunch" friendly (Sandwiches, Wraps, Salads, Soup) or simple weekend light meals.
    3. **DINNER**: This is where you show off.
    
    CRITICAL RULES FOR VARIETY:
    1. **DO NOT** use the same cuisine twice in a row.
    2. **DO NOT** make the whole week one theme (e.g. No "Asian Week").
    3. **Mix it up**: Aim for 7 different styles across 7 days.
    
    USER PREFERENCES:
    - LOVES: {", ".join(favorites) if favorites else "Open to anything"}
    - HATES (Avoid these): {", ".join(disliked) if disliked else "None"}
    - AVAILABLE STYLES TO PICK FROM: {", ".join(ALL_STYLES)}
    
    SCHEDULE CONTEXT:
    {json.dumps(schedule)}
    (If day is 'Busy', dinner must be <20 mins).
    
    OUTPUT JSON:
    {{
      "days": [
        {{
          "day": "Monday",
          "meals": {{
            "breakfast": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "Western" }},
            "lunch": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "Packed Lunch" }},
            "dinner": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "Italian" }}
          }}
        }}
      ]
    }}
    """
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        plan = json.loads(res.choices[0].message.content)
        db.collection("families").document("fam_8829_xyz").update({"current_week_plan": plan})
    except Exception as e:
        st.error(f"AI Error: {e}")

def generate_shopping_list(plan):
    all_ing = []
    for day in plan.get('days', []):
        if 'meals' in day:
            for m in day['meals'].values():
                all_ing.extend(m.get('ingredients', []))
                
    prompt = f"""
    1. Consolidate list: {", ".join(all_ing)}
    2. Estimate UK Price (GBP).
    3. JSON Output: {{ "items": [ {{ "item": "Milk", "quantity": "4pts", "est_price": 1.50 }} ] }}
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)['items']
    except:
        return []

def calculate_comparison(items):
    if not items: return []
    total = sum(i['est_price'] for i in items)
    index = { "Waitrose": 1.22, "Sainsbury's": 1.0, "Tesco": 0.96, "Asda": 0.92, "Aldi": 0.83 }
    return sorted([{"store": s, "total": total * m} for s, m in index.items()], key=lambda x: x['total'])

def rate_meal(name, rating, user, style):
    db.collection("families").document("fam_8829_xyz").collection("meal_history").add({
        "meal": name, "rating": rating, "user": user, "style": style, "date": datetime.now().isoformat()
    })
    
    fam_ref = db.collection("families").document("fam_8829_xyz")
    data = get_data_cached() 
    prefs = data.get("style_preferences", {})
    
    # Fuzzy match the style tag to our master list
    matched = next((s for s in ALL_STYLES if style.split(" ")[0] in s), None)
    if matched:
        score = prefs.get(matched, 0)
        if rating == "like": prefs[matched] = score + 1
        if rating == "dislike": prefs[matched] = score - 1
        fam_ref.update({"style_preferences": prefs})

def toggle_lock(day_name, meal_type):
    data = get_data_cached()
    plan = data.get('current_week_plan', {})
    for d in plan.get('days', []):
        if d['day'] == day_name:
            d['meals'][meal_type]['locked'] = not d['meals'][meal_type].get('locked', False)
    db.collection("families").document("fam_8829_xyz").update({"current_week_plan": plan})


# --- 6. INITIALIZE STATE ---
if 'family_data' not in st.session_state:
    st.session_state['family_data'] = get_data_cached()

# --- 7. AUTH SCREEN ---
data = st.session_state['family_data']

if 'user' not in st.session_state or not st.session_state['user']:
    st.title("🏡 Who is this?")
    if data and 'members' in data:
        cols = st.columns(len(data['members']))
        for i, m in enumerate(data['members']):
            if cols[i].button(f"👤\n{m['name']}", use_container_width=True):
                st.session_state['user'] = m
                st.rerun()
    else:
        st.warning("Loading data...")
        if st.button("Retry Connection"): 
            force_refresh()
            st.rerun()
    st.stop()

# --- 8. MAIN APP ---
user = st.session_state['user']
c1, c2 = st.columns([3,1])
with c1: st.title(f"Hi, {user['name']}!")
with c2: 
    if st.button("Logout"): 
        st.session_state['user'] = None
        st.rerun()

# CHILD VIEW
if user.get('role') == 'child':
    st.subheader("🦖 Tonight's Dinner")
    try:
        meal = data['current_week_plan']['days'][0]['meals']['dinner']
        st.success(f"**{meal['name']}**")
        st.caption(meal.get('method', 'Ask Dad!'))
        c1, c2 = st.columns(2)
        if c1.button("😋 Yummy"): 
            rate_meal(meal['name'], "like", user['name'], meal.get('style_tag', 'General'))
            st.balloons()
        if c2.button("🤢 Yuck"): 
            rate_meal(meal['name'], "dislike", user['name'], meal.get('style_tag', 'General'))
            st.toast("Noted!")
    except:
        st.info("No dinner planned yet!")

# PARENT VIEW
else:
    t1, t2, t3 = st.tabs(["📅 Plan", "🛒 Shop", "⚙️ Admin"])
    
    with t1:
        if st.button("⚡ Generate Week", type="primary"):
            with st.spinner("Chef is cooking..."):
                generate_week_plan()
                force_refresh()
                st.rerun()
        
        if 'current_week_plan' in data:
            for day in data['current_week_plan'].get('days', []):
                if 'meals' not in day: continue
                
                with st.expander(f"**{day['day']}**"):
                    tb, tl, td = st.tabs(["Breakfast", "Lunch", "Dinner"])
                    
                    def render(m_type, m_data, d_name):
                        c1, c2 = st.columns([4,1])
                        c1.write(f"**{m_data['name']}**")
                        
                        is_locked = m_data.get('locked', False)
                        if c2.button("🔒" if is_locked else "🔓", key=f"l_{d_name}_{m_type}"):
                             toggle_lock(d_name, m_type)
                             force_refresh()
                             st.rerun()
                        
                        st.caption(m_data.get('method', ''))
                        st.text(f"Ing: {', '.join(m_data.get('ingredients', []))}")
                        
                        b1, b2 = st.columns(2)
                        if b1.button("👍", key=f"u_{d_name}_{m_type}"):
                             rate_meal(m_data['name'], "like", user['name'], m_data.get('style_tag', 'General'))
                             st.toast("Saved!")
                        if b2.button("👎", key=f"d_{d_name}_{m_type}"):
                             rate_meal(m_data['name'], "dislike", user['name'], m_data.get('style_tag', 'General'))
                             st.toast("Noted")
                    
                    with tb: render('breakfast', day['meals']['breakfast'], day['day'])
                    with tl: render('lunch', day['meals']['lunch'], day['day'])
                    with td: render('dinner', day['meals']['dinner'], day['day'])

    with t2:
        if st.button("📝 Calculate List"):
            with st.spinner("Checking prices..."):
                items = generate_shopping_list(data['current_week_plan'])
                comp = calculate_comparison(items)
                db.collection("families").document("fam_8829_xyz").update({"shopping_list": items, "price_comparison": comp})
                force_refresh()
                st.rerun()
        
        comp = data.get('price_comparison', [])
        items = data.get('shopping_list', [])
        
        if comp and items:
            best = comp[0]
            sains = next((x for x in comp if x['store'] == "Sainsbury's"), None)
            if sains and best['store'] != "Sainsbury's":
                st.info(f"💡 Swap Sainsbury's for **{best['store']}** to save **£{sains['total'] - best['total']:.2f}**")
            
            for s in comp:
                st.progress(min(s['total'] / (comp[-1]['total']*1.1), 1.0))
                st.caption(f"{s['store']}: £{s['total']:.2f}")
            
            st.divider()
            st.write(f"**Your Items ({len(items)})**")
            for i in items:
                label = f"{i.get('quantity', '')} {i['item']}"
                st.checkbox(label, key=i['item'])
                
    with t3:
        st.json(data.get('members', []))