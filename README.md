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

Install the Python requirements and run:

```bash
pip install -r requirements-aws.txt
python app.py
```

The Dockerfile installs the face-recognition/dlib runtime and runs the Flask app with Gunicorn.

## Security notes

- Firebase ID tokens are verified server-side; the browser does not get to choose its own Firebase UID.
- Firebase service-account credentials must never be committed to GitHub.
- Guest face images are not persisted in the server's permanent known-face directory.
- HTTPS should be used in production.
