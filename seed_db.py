import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime

# 1. Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# 2. Define the "Source of Truth" (Our Schema)
family_data = {
    "family_id": "fam_8829_xyz",
    "created_at": datetime.datetime.now(),
    "members": [
        {
            "name": "Sarah",
            "role": "parent",
            "dislikes": ["cilantro", "lamb"]
        },
        {
            "name": "Leo",
            "dob": "2020-05-15",  # He is 5 years old
            "dietary_flags": ["peanut_allergy"], 
            "sensory_profile": {
                "texture_aversion": ["mushy"], 
                "spiciness_tolerance": "low"
            }
        }
    ],
    "kitchen_profile": {
        "equipment": ["air_fryer", "microwave"],
        "pantry_staples": ["pasta", "rice", "canned tomatoes"],
        "current_inventory": ["spinach (needs using)", "chicken breast"]
    }
}

# 3. Push to Firestore
# We use .set() to overwrite if it exists, ensuring a clean state
db.collection("families").document("fam_8829_xyz").set(family_data)

print("✅ Database seeded! Family profile is live in the cloud.")