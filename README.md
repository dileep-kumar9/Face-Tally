# FaceTally

Detect, recognize, and **count** people in photos and videos — one upload box,
your own private known-people list behind a real account, installable on your
phone as an app.

Built on top of the `face_recognition` demo, rewritten with:

1. **Accounts** — separate logins, each with their own known-people list.
   Nobody can see, use, or delete another account's saved people.
2. **Video support** — samples ~2 frames/sec (up to 120 frames) and runs face
   detection + recognition across the whole clip, not just a single frame,
   with detection running on a downscaled copy for speed (full resolution is
   still used for encoding/thumbnail quality).
3. **Per-person counting** — every face seen (in a photo, or across all sampled
   video frames) is matched to a known person, or clustered against other
   unknown faces already seen in that same upload, so you get a count of how
   many *distinct* people appeared and how many times each one showed up —
   not a raw per-frame face count.
4. **Mobile-ready** — mobile-first responsive UI, installable as a home-screen
   app (PWA) with an app icon and standalone window. (A true native
   iOS/Android app needs a separate Swift/Kotlin build — this gives you an
   app-like experience today without that.)
5. **One unified upload** — no separate photo vs. video tabs. A single box
   accepts either, via your device's normal file picker, an in-page camera
   (take a photo or record a video directly, no OS camera-app handoff
   required), or a pasted link (direct file URL, public Google Drive link,
   or YouTube video).
6. **Per-person timeline** — for videos, each person's card shows the
   timestamp ranges they appeared in, and clicking one seeks the video
   player there (paused — you press play yourself).
7. **Save an Unknown Person in one tap** — every "Unknown Person" card in a
   result has a "Save as known" button right there, using the thumbnail
   already generated during analysis. No separate photo needed.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install --upgrade pip wheel "setuptools<81"
pip install dlib-bin==19.24.6
pip install -r requirements-aws.txt
pip install --no-deps face_recognition==1.3.0 face_recognition_models==0.3.0

export FACETALLY_SECRET_KEY="$(python3 -c 'import os; print(os.urandom(32).hex())')"
python app.py
```

Open `http://127.0.0.1:5000`, sign up for an account, and you're in.

> This installs the same way the Docker build does: `dlib-bin` is a
> **prebuilt** wheel (covers Windows/macOS/Linux, Python 3.7–3.13), so there's
> no C++ compiler or CMake step needed. `face_recognition` is installed with
> `--no-deps` afterward so pip doesn't try to pull in the *source* `dlib`
> package on top of it and trigger a from-scratch compile.
>
> `FACETALLY_SECRET_KEY` signs login sessions. If it's not set, the app
> generates a random one at startup so it's never running with a known,
> public fallback (that would let anyone forge a valid login) — but it means
> everyone gets logged out on every restart. Set a real one via your host's
> environment variables for stable logins.
>
> YouTube links additionally need `ffmpeg` on your PATH locally (already
> included in the Docker image). macOS: `brew install ffmpeg`. Ubuntu/Debian:
> `sudo apt install ffmpeg`. Windows: install from ffmpeg.org and add it to PATH.

## Deploying somewhere persistent (Render, etc.)

Accounts and known-people photos both live under whatever `KNOWN_FACES_DIR`
points at (the account database sits right alongside it). **If that path
isn't on a persistent disk, every account and every saved known person is
wiped on the next redeploy or restart** — the included `Dockerfile` points
`KNOWN_FACES_DIR` at `/data/known_faces`, which only survives across deploys
if you've attached a Render Disk (or equivalent) mounted at `/data`. Without
one, this is a fresh, empty app every time it restarts.

## Install on your phone (PWA)

From your phone's browser, visit your deployment's URL:

- **Android (Chrome):** menu (⋮) → "Add to Home screen" / "Install app".
- **iPhone (Safari):** Share icon → "Add to Home Screen".

It'll launch full-screen with its own icon, like a native app.

> If you update the app and your phone still shows the old version, close
> the tab/PWA fully and reopen it once — the service worker needs a full
> restart to pick up a new deploy, not just a pull-to-refresh.

## How counting works

- **Photos:** each detected face is matched against your saved known people,
  or grouped with other unmatched faces in the same photo if they look like
  the same person (e.g. someone appearing twice in a group shot).
- **Videos:** the same matching runs per sampled frame; a person's count is
  how many sampled frames they appeared in. Each person's card also shows a
  timeline of the timestamp ranges they were detected in.
- **Unknown people** are still counted and shown (as "Unknown Person 1",
  "Unknown Person 2", ...) with a cropped thumbnail, even without a name —
  and can be saved as known directly from the result.

## Adding a known person

Three ways, all under "Known people":
- **Choose reference photo** — upload an existing photo.
- **Use camera** — opens an in-page live camera, takes one photo.
- **Record video** — opens the camera, records a short (~4s) clip, and the
  server automatically picks the clearest single frame from it as the
  reference photo. Useful if a still photo keeps coming out blurry/at a bad
  angle.

## Links you can paste

- A direct photo/video URL (e.g. `https://example.com/photo.jpg`)
- A public Google Drive share link (`drive.google.com/file/d/...`) — the
  server follows Google's confirmation-page redirect automatically
- A YouTube video link — downloaded server-side via `yt-dlp`, capped at 720p
  and 150MB. **Known limitation:** cloud-hosted servers (Render, AWS, etc.)
  get flagged by YouTube's automated-traffic bot-check far more than
  residential IPs, and this can fail intermittently for reasons unrelated to
  the app. The next step up in reliability is authenticating yt-dlp with
  cookies from a real signed-in account, which isn't set up here (needs a
  throwaway Google account and periodic re-export of the cookies file).

## Renaming the app

Change `APP_NAME` at the top of `app.py`, and `name`/`short_name` in
`static/manifest.json`.

## Suggested next improvements

- **Rate-limit login attempts.** There's currently no lockout/backoff on
  repeated failed logins - fine for personal use, worth adding
  (Flask-Limiter or similar) before exposing this more broadly.
- **Password reset.** There's no "forgot password" flow - losing your
  password currently means losing access to your known-people list.
- **Persistent analysis history.** Results aren't saved anywhere beyond the
  current page view. A history table (SQLite, same DB the accounts already
  use) would make "how many times has this person appeared across *all* my
  uploads" answerable.
- **Background/async processing.** Video analysis currently blocks the
  request; for longer clips a job queue (Celery/RQ) with a progress
  indicator would keep the UI responsive.
- **Face quality guardrails.** Very small, blurry, or side-angle faces can
  produce weak encodings and get miscounted as a "new" unknown person. A
  minimum face-size/confidence threshold would reduce false splits.
- **Tolerance as a setting.** Matching strictness is currently a fixed
  constant (`KNOWN_TOLERANCE` / `UNKNOWN_CLUSTER_TOLERANCE` in `app.py`).
  Exposing this as a per-account slider would let people trade off false
  matches vs. missed matches for their own use case.
- **Two-factor or passkeys.** Password-only accounts are the baseline; worth
  layering on if this ever holds anything sensitive.
- **Privacy note.** Known-people photos and uploaded media are processed
  entirely on the machine running this app - nothing leaves the server
  except when analyzing a pasted link (fetched from wherever it points).
  Each account's data is isolated from every other account's, but there's
  no encryption-at-rest on the stored photos/database - worth knowing if
  you deploy this somewhere the underlying disk isn't fully trusted.
