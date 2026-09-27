# FaceTally

FaceTally detects, recognizes, and counts faces in photos and videos.

## Videos, links and saved analyses

- **Links are never downloaded.** For a pasted video link (YouTube, Google Drive or a direct video URL) the server reads the video stream directly while analysing it; nothing is saved to disk. Photos from links are fetched temporarily and deleted after analysis.
- **"Your analyses" folder.** Every analysis is saved as a card (preview, source URL, people/known/unknown counts, known names, date). Clicking a card reopens its results and faces instantly without re-analysing; **Open video** then loads the player. Cards can be deleted individually or all at once. Signed-in users keep up to 50 analyses permanently; guests' analyses are kept in their browser for 30 days and move into their account when they sign in.
- **Playback uses the original source.** YouTube videos play in YouTube's embedded player, other links from their original URL (Drive falls back to Drive's own player if needed). Uploaded videos play from the server copy; on Render without a persistent disk that file is lost on restart, but the analysis itself is kept.
- **Timeline tracing.** Each person has a bar over the whole video showing when they appear. While the video plays, a playhead moves along every bar, the current appearance lights up, people on screen are highlighted, and an "On screen at …" line names them. Clicking a time or a bar segment jumps there and plays.
- **Long videos** are sampled with 120 frames spread across the whole video, so late appearances are found too.

## Permanent storage (Firestore)

Render's disk is wiped on every deploy and restart unless a paid disk is attached, so signed-in users' **saved faces** (however they were saved: photo, camera, recording, "Save as known", guest import) and **analyses** are stored in **Cloud Firestore**, which is free on the Spark plan. The server's disk is only a cache that is refilled from Firestore after a restart; faces that existed on disk before Firestore was enabled are uploaded automatically.

To enable it: Firebase console → your project → **Build → Firestore Database → Create database** → Production mode → choose a location. Nothing else is needed; the server uses the same Firebase Admin credentials and picks the database up within 5 minutes (or on restart). Production-mode security rules are fine because only the server (Admin SDK) accesses it.

Without Firestore, everything still works but is stored on local disk only.

`FACETALLY_SECRET_KEY` must be set in production: the sign-in and guest cookies are signed with it and last a year, so a changing key would log everyone out and detach guests from their saved analyses.

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

## Analyse while watching (YouTube)

When YouTube won't let the server read a video, FaceTally doesn't fail: it opens the **Analyse while watching** page (also reachable from the link under the upload box, or `/watch?url=<YouTube link>`).

1. The video plays in YouTube's own player on the page.
2. The viewer clicks **Start analysing** and, when the browser asks, shares **this tab**.
3. Every half second of video the page cuts the player out of the tab capture and sends that frame, with the exact video time, to the server, which analyses it immediately (live people count and "on screen now").
4. When the video ends, or on **Finish & save**, the result is saved to "Your analyses" with the YouTube player and timeline tracing, like any other analysis.

YouTube only ever sees a normal viewer, so this can't be blocked and needs no cookies or proxy. It runs in real time (skipping ahead and YouTube's speed setting both work) and needs a desktop browser (Chrome or Edge recommended; phones can't share a tab). Frames are analysed and discarded, never stored. Saved faces (the account's, or a guest's browser faces) are recognised.

## YouTube links on Render

YouTube blocks most cloud-server IPs (Render included) with a "confirm you're not a bot" check. This applies even though FaceTally only *reads* the stream for analysis and never downloads it, so YouTube links fail on Render by default (playback in the browser is unaffected). On a home connection, e.g. running locally, they work without setup. Uploading the video file always works. To enable YouTube analysis on Render, configure one of:

- **Cookies:** export `cookies.txt` (Netscape format) from a browser signed in to YouTube and add it on Render as a **Secret File** named `youtube_cookies.txt`; it is used automatically. Elsewhere, set `YTDLP_COOKIES_FILE` to its path. Use a spare Google account, since YouTube may restrict accounts used for automated downloads, and re-export the cookies when they expire.
- **Proxy:** set `YTDLP_PROXY=http://user:pass@host:port`, ideally a residential proxy.

## Security notes

- Firebase ID tokens are verified server-side; the browser does not get to choose its own Firebase UID.
- Firebase service-account credentials must never be committed to GitHub.
- Guest face images are not persisted in the server's permanent known-face directory.
- HTTPS should be used in production.
