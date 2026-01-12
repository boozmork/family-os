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

# --- 5. AGENT LOGIC ---
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
    prefs = family_data.get('style_preferences', {})
    favorites = [s for s in ALL_STYLES if prefs.get(s, 0) > 2]
    disliked = [s for s in ALL_STYLES if prefs.get(s, 0) < -1]
    return favorites, disliked

# --- CORE GENERATOR (Used for Week & Day) ---
def generate_week_plan():
    data = get_data_cached()
    # 1. Capture Lock State
    current_plan = data.get('current_week_plan', {})
    locked_meals = {} # Store locked meal objects to restore later
    
    if current_plan:
        for day in current_plan.get('days', []):
            for m_type, m_data in day.get('meals', {}).items():
                if m_data.get('locked', False):
                    # Save the whole meal object (including recipe details if they exist)
                    locked_meals[f"{day['day']}_{m_type}"] = m_data

    # 2. Prepare Prompt
    favorites, disliked = get_style_preferences(data)
    family_count = len(data.get('members', []))
    
    prompt = f"""
    Plan a 7-day menu (Mon-Sun) for {family_count} PEOPLE.
    
    CRITICAL RULES:
    1. INGREDIENTS: You MUST include specific quantities scaled for {family_count} people. 
       (e.g., "500g Beef Mince", "4 Burger Buns", "1 tbsp Oil"). DO NOT just say "Beef".
    2. VARIETY: Do not repeat dinner cuisines.
    3. BREAKFAST: Western/UK Standard.
    4. LUNCH: Light/Packed.
    
    PREFERENCES:
    - LOVES: {", ".join(favorites) if favorites else "Any"}
    - HATES: {", ".join(disliked) if disliked else "None"}
    - STYLES: {", ".join(ALL_STYLES)}
    
    OUTPUT JSON:
    {{
      "days": [
        {{
          "day": "Monday",
          "meals": {{
            "breakfast": {{ "name": "...", "ingredients": ["2 slices Toast", "2 Eggs"], "method": "...", "style_tag": "Western" }},
            "lunch": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "Packed" }},
            "dinner": {{ "name": "...", "ingredients": ["500g Pasta", "400g Sauce"], "method": "...", "style_tag": "Italian" }}
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
        new_plan = json.loads(res.choices[0].message.content)
        
        # 3. Restore Locked Meals (The Merge)
        for day in new_plan.get('days', []):
            for m_type in ['breakfast', 'lunch', 'dinner']:
                key = f"{day['day']}_{m_type}"
                if key in locked_meals:
                    # Overwrite the AI's new suggestion with the old locked meal
                    day['meals'][m_type] = locked_meals[key]
        
        db.collection("families").document("fam_8829_xyz").update({"current_week_plan": new_plan})
    except Exception as e:
        st.error(f"AI Error: {e}")

# --- SINGLE MEAL REGENERATOR ---
def regenerate_single_meal(day_name, meal_type):
    data = get_data_cached()
    family_count = len(data.get('members', []))
    
    # Check if locked
    current_plan = data.get('current_week_plan', {})
    for day in current_plan.get('days', []):
        if day['day'] == day_name:
            if day['meals'][meal_type].get('locked', False):
                st.toast("🔒 Cannot regenerate a locked meal!")
                return # Abort

    prompt = f"""
    Generate ONE single meal idea.
    Type: {meal_type.upper()}
    Day: {day_name}
    Family Size: {family_count} people.
    
    RULES:
    1. Ingredients MUST have quantities (e.g. "500g Chicken").
    2. If Dinner, pick a fun style from: {", ".join(ALL_STYLES)}.
    
    OUTPUT JSON:
    {{
      "name": "...", 
      "ingredients": ["Qty Item", "Qty Item"], 
      "method": "...", 
      "style_tag": "..." 
    }}
    """
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        new_meal = json.loads(res.choices[0].message.content)
        
        # Save to specific slot
        for day in current_plan.get('days', []):
            if day['day'] == day_name:
                day['meals'][meal_type] = new_meal
                break
        
        db.collection("families").document("fam_8829_xyz").update({"current_week_plan": current_plan})
        
    except Exception as e:
        st.error(f"Error: {e}")

# --- SINGLE DAY REGENERATOR ---
def regenerate_day(day_name):
    data = get_data_cached()
    family_count = len(data.get('members', []))
    current_plan = data.get('current_week_plan', {})
    
    # Find the specific day object
    target_day_idx = next((i for i, d in enumerate(current_plan.get('days', [])) if d['day'] == day_name), None)
    if target_day_idx is None: return

    # Preserve locks for this day
    day_data = current_plan['days'][target_day_idx]
    locked_meals = {}
    for m_type, m_data in day_data.get('meals', {}).items():
        if m_data.get('locked', False):
            locked_meals[m_type] = m_data
            
    prompt = f"""
    Generate 3 meals (Breakfast, Lunch, Dinner) for {day_name}.
    Family Size: {family_count}.
    Ingredients MUST have specific quantities.
    
    OUTPUT JSON:
    {{
       "breakfast": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "..." }},
       "lunch": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "..." }},
       "dinner": {{ "name": "...", "ingredients": ["..."], "method": "...", "style_tag": "..." }}
    }}
    """
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        new_meals = json.loads(res.choices[0].message.content)
        
        # Merge logic (restore locks)
        for m_type, m_data in new_meals.items():
            if m_type in locked_meals:
                new_meals[m_type] = locked_meals[m_type]
        
        # Save
        current_plan['days'][target_day_idx]['meals'] = new_meals
        db.collection("families").document("fam_8829_xyz").update({"current_week_plan": current_plan})
        
    except Exception as e:
        st.error(f"Error: {e}")

# --- RECIPE GENERATOR ---
def generate_recipe_instructions(meal_name, ingredients, style):
    prompt = f"""
    Write a cooking guide for "{meal_name}".
    Style: {style}
    Ingredients available: {", ".join(ingredients)}
    
    OUTPUT JSON:
    {{
        "steps": ["Step 1...", "Step 2..."],
        "tips": "Chef's secret tip..."
    }}
    Provide 5-8 concise steps.
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return json.loads(res.choices[0].message.content)
    except:
        return {"steps": ["Could not generate recipe."], "tips": ""}

def save_recipe_to_db(day_name, meal_type, recipe_data):
    data = get_data_cached()
    plan = data.get('current_week_plan', {})
    for day in plan.get('days', []):
        if day['day'] == day_name:
            day['meals'][meal_type]['recipe_details'] = recipe_data
            break
    db.collection("families").document("fam_8829_xyz").update({"current_week_plan": plan})

# --- SHOPPING ---
def generate_shopping_list(plan):
    all_ing = []
    for day in plan.get('days', []):
        if 'meals' in day:
            for m in day['meals'].values():
                all_ing.extend(m.get('ingredients', []))
                
    prompt = f"""
    1. Consolidate these ingredients: {", ".join(all_ing)}
    2. Sum up quantities (e.g. 500g + 500g = 1kg Beef).
    3. Estimate UK Price (GBP).
    
    JSON: {{ "items": [ {{ "item": "Beef Mince", "quantity": "1kg", "est_price": 5.50 }} ] }}
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
        if st.button("Retry"): force_refresh(); st.rerun()
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
        if st.button("⚡ Generate Week (Respects Locks)", type="primary"):
            with st.spinner("Chef is cooking..."):
                generate_week_plan()
                force_refresh()
                st.rerun()
        
        if 'current_week_plan' in data:
            for day in data['current_week_plan'].get('days', []):
                if 'meals' not in day: continue
                
                with st.expander(f"**{day['day']}**"):
                    # REGENERATE DAY BUTTON
                    if st.button(f"🔄 Regenerate {day['day']}", key=f"regen_day_{day['day']}"):
                         with st.spinner("Rethinking today..."):
                             regenerate_day(day['day'])
                             force_refresh()
                             st.rerun()

                    tb, tl, td = st.tabs(["Breakfast", "Lunch", "Dinner"])
                    
                    def render(m_type, m_data, d_name):
                        # Header Row: Name + Controls
                        r1_c1, r1_c2, r1_c3 = st.columns([6, 1, 1])
                        r1_c1.write(f"**{m_data['name']}**")
                        
                        is_locked = m_data.get('locked', False)
                        
                        # Lock Button
                        if r1_c2.button("🔒" if is_locked else "🔓", key=f"l_{d_name}_{m_type}"):
                             toggle_lock(d_name, m_type)
                             force_refresh()
                             st.rerun()
                             
                        # Regenerate Single Meal Button (Only if not locked)
                        if not is_locked:
                            if r1_c3.button("🎲", help="Reroll this meal", key=f"rr_{d_name}_{m_type}"):
                                with st.spinner("Rerolling dish..."):
                                    regenerate_single_meal(d_name, m_type)
                                    force_refresh()
                                    st.rerun()
                        
                        st.caption(m_data.get('method', ''))
                        st.text(f"Ing: {', '.join(m_data.get('ingredients', []))}")
                        
                        # Recipe
                        if 'recipe_details' in m_data:
                            with st.expander("👨‍🍳 Method (Step-by-Step)", expanded=False):
                                details = m_data['recipe_details']
                                for idx, step in enumerate(details.get('steps', [])):
                                    st.write(f"**{idx+1}.** {step}")
                                if details.get('tips'):
                                    st.info(f"💡 **Tip:** {details['tips']}")
                        else:
                            if st.button("👨‍🍳 Get Recipe", key=f"rec_{d_name}_{m_type}"):
                                with st.spinner("Writing recipe..."):
                                    details = generate_recipe_instructions(
                                        m_data['name'], 
                                        m_data.get('ingredients', []), 
                                        m_data.get('style_tag', 'General')
                                    )
                                    save_recipe_to_db(d_name, m_type, details)
                                    force_refresh()
                                    st.rerun()

                        # Ratings
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