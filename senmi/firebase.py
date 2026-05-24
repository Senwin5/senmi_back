import os
import json
import firebase_admin
from firebase_admin import credentials

if not firebase_admin._apps:

    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if firebase_json:

        # Railway / production
        cred_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cred_dict)

    else:

        # Local development
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        cred_path = os.path.join(
            BASE_DIR,
            "firebase-service-account.json"
        )

        cred = credentials.Certificate(cred_path)

    firebase_admin.initialize_app(cred)

    print("🔥 FIREBASE INITIALIZED")