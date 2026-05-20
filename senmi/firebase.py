# senmi/firebase.py

import os
import firebase_admin

from firebase_admin import credentials
from django.conf import settings

if not firebase_admin._apps:

    firebase_path = os.path.join(
        settings.BASE_DIR,
        "firebase-service-account.json"
    )

    cred = credentials.Certificate(firebase_path)

    firebase_admin.initialize_app(cred)