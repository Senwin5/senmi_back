import os
import json
import firebase_admin
from firebase_admin import credentials

if not firebase_admin._apps:

    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if not firebase_json:
        raise Exception("FIREBASE_CREDENTIALS_JSON not set")

    cred_dict = json.loads(firebase_json)

    cred = credentials.Certificate(cred_dict)

    firebase_admin.initialize_app(cred)