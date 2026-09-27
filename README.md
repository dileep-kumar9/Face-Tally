# FaceTally

FaceTally detects, recognizes, and counts faces in photos and videos.

## Authentication and saved faces

FaceTally now uses **Firebase Authentication** for persistent accounts while keeping the main app usable without login.

### Guest mode

- The home page, camera, uploads, and analysis work without an account.
- Saved face references are kept in the browser's IndexedDB only.
- Guest references are never copied into `known_faces/`.
- When a guest runs an analysis, the browser sends the local reference images with that single request. The server uses them only for that analysis and deletes the temporary files afterward.
- Guest saved faces are removed when the site's browser data is cleared.

### Logged-in mode

- Email/password sign-up and sign-in are handled by Firebase Authentication.
- Google Sign-In is supported.
- Forgot password sends Firebase's password-reset email.
- Persistent known faces are stored under a folder named for the verified Firebase UID.
- Users cannot access another user's saved-face directory.
- If temporary guest faces exist when the user signs in, FaceTally offers **Import & Save**. Only successfully imported faces are removed from the guest IndexedDB store.

Firebase's client SDK handles the sign-in flows, while the Flask backend verifies Firebase ID tokens with the Firebase Admin SDK before creating its server session.

## Required Firebase setup

In the Firebase console:

1. Create/select a Firebase project.
2. Open **Authentication → Sign-in method**.
3. Enable **Email/Password**.
4. Enable **Google**.
5. Add your production domain (and local development domain if needed) to Authentication's authorized domains.
6. Open Project settings → Your apps → Web app and copy the Firebase web configuration.
7. Create a Firebase service account and keep its private key secret.

### Web configuration environment variables

Set these on the server:

```text
FIREBASE_API_KEY=...
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_STORAGE_BUCKET=...
FIREBASE_MESSAGING_SENDER_ID=...
FIREBASE_APP_ID=...
```

### Firebase Admin credentials

Use either one service-account JSON environment variable:

```text
FIREBASE_SERVICE_ACCOUNT_JSON={...}
```

or the individual service-account variables:

```text
FIREBASE_PROJECT_ID=...
FIREBASE_PRIVATE_KEY_ID=...
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
FIREBASE_CLIENT_EMAIL=firebase-adminsdk-...@your-project.iam.gserviceaccount.com
FIREBASE_CLIENT_ID=...
FIREBASE_CLIENT_CERT_URL=...
```

`FIREBASE_PROJECT_ID` is shared by the web configuration and Admin configuration.

Also set a stable secret for Flask sessions:

```text
FACETALLY_SECRET_KEY=<long-random-secret>
```

## Persistent storage

The existing `KNOWN_FACES_DIR` directory is still used for persistent reference photos. For Render, mount a persistent disk and point it at that directory, for example:

```text
KNOWN_FACES_DIR=/data/known_faces
UPLOADS_DIR=/tmp/uploads
```

The app uses one directory per Firebase UID, so persistent face data remains separated between accounts.

## Local run

**Use Python 3.11.** Newer versions (e.g. 3.14) have no wheels for `dlib-bin` or `numpy<2`, so installation fails.

Put your local settings in `.env.local` (or `.env`) next to `app.py`; see `.env.example`.

### Option A: Python 3.11 virtualenv (fastest for development)

Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip wheel "setuptools<81"
.venv\Scripts\python -m pip install dlib-bin
.venv\Scripts\python -m pip install -r requirements-aws.txt
.venv\Scripts\python -m pip install --no-deps face_recognition==1.3.0 face_recognition_models==0.3.0
.venv\Scripts\python app.py
```

The app runs at http://localhost:5000. `--no-deps` stops pip from trying to build `dlib` from source; `setuptools<81` keeps `pkg_resources`, which `face_recognition_models` needs.

### Option B: Docker (identical to the Render deployment)

```bash
docker build -t facetally .
docker run --rm -p 10000:10000 --env-file .env.local \
  -v facetally-data:/data \
  -v "$(pwd)/firebase-service-account.json:/app/firebase-service-account.json:ro" \
  facetally
```

(Drop the service-account mount if you configure Firebase Admin through `FIREBASE_SERVICE_ACCOUNT_JSON` or the individual `FIREBASE_*` variables instead.)

The app runs at http://localhost:10000. The Dockerfile installs the face-recognition/dlib runtime and runs the Flask app with Gunicorn. Secrets are excluded from the image by `.dockerignore`, so pass them with `--env-file` locally and as environment variables on Render.

## Security notes

- Firebase ID tokens are verified server-side; the browser does not get to choose its own Firebase UID.
- Firebase service-account credentials must never be committed to GitHub.
- Guest face images are not persisted in the server's permanent known-face directory.
- HTTPS should be used in production.
