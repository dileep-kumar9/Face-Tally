# FaceTally

Detect, recognize, and **count** people in photos and videos — one upload box,
runs locally, installable on your phone as an app.

Built on top of the `face_recognition` demo, rewritten with:

1. **New name/branding** — FaceTally (change in one place, see below).
2. **Video support** — samples ~1 frame/sec (up to 60 frames) and runs face
   detection + recognition across the whole clip, not just a single frame.
3. **Per-person counting** — every face seen (in a photo, or across all sampled
   video frames) is matched to a known person, or clustered against other
   unknown faces already seen in that same upload, so you get a count of how
   many *distinct* people appeared and how many times each one showed up —
   not a raw per-frame face count.
4. **Mobile-ready** — mobile-first responsive UI, installable as a home-screen
   app (PWA) with an app icon and standalone window. See "Install on your
   phone" below. (A true native iOS/Android app needs a separate Swift/Kotlin
   build — this gives you an app-like experience today without that; the
   Flask backend here can stay as-is if you build a native front end later.)
5. **One unified upload** — no separate photo vs. video tabs. A single box
   accepts either, via your device's normal file picker (which itself already
   surfaces Google Drive, Photos, iCloud, Files, etc. on most phones), a
   pasted link (direct file URL or public Google Drive share link), or a
   YouTube video link.
6. **Per-person timeline** — for videos, each person's card shows the
   timestamp ranges they appeared in, not just a raw count.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install --upgrade pip wheel "setuptools<81"
pip install dlib-bin==19.24.6
pip install -r requirements-aws.txt
pip install --no-deps face_recognition==1.3.0 face_recognition_models==0.3.0

python app.py
```

Open `http://127.0.0.1:5000` (or `http://<your-computer's-LAN-IP>:5000` from
your phone, if it's on the same Wi-Fi).

> This installs the same way the Docker build does: `dlib-bin` is a
> **prebuilt** wheel (covers Windows/macOS/Linux, Python 3.7–3.13), so there's
> no C++ compiler or CMake step needed. `face_recognition` is installed with
> `--no-deps` afterward so pip doesn't try to pull in the *source* `dlib`
> package on top of it and trigger a from-scratch compile.
>
> YouTube links additionally need `ffmpeg` on your PATH locally (already
> included in the Docker image). macOS: `brew install ffmpeg`. Ubuntu/Debian:
> `sudo apt install ffmpeg`. Windows: install from ffmpeg.org and add it to PATH.

## Install on your phone (PWA)

Run the server on a computer, then from your phone's browser (same Wi‑Fi
network) visit `http://<computer-IP>:5000`:

- **Android (Chrome):** menu (⋮) → "Add to Home screen" / "Install app".
- **iPhone (Safari):** Share icon → "Add to Home Screen".

It'll launch full-screen with its own icon, like a native app. For real
public/internet access instead of same-Wi‑Fi-only, deploy the Flask app to
any host (Render, Railway, a VPS, etc.) and use that URL instead.

## How counting works

- **Photos:** each detected face is matched against your saved "known
  people," or grouped with other unmatched faces in the same photo if they
  look like the same person (e.g. someone appearing twice in a group shot).
- **Videos:** the same matching runs per sampled frame (~2 frames/sec, up to
  120 frames); a person's count is how many sampled frames they appeared in.
  Each person's card also shows a timeline of the timestamp ranges they were
  detected in, so you can see *when* they appeared, not just how often.
- **Unknown people** are still counted and shown (as "Unknown Person 1",
  "Unknown Person 2", ...) with a cropped thumbnail, even without a name.

## Links you can paste

- A direct photo/video URL (e.g. `https://example.com/photo.jpg`)
- A public Google Drive share link (`drive.google.com/file/d/...`) — the
  server follows Google's confirmation-page redirect automatically
- A YouTube video link — downloaded server-side via `yt-dlp`, capped at 720p
  and 150MB to keep processing time reasonable

## Renaming the app

Change `APP_NAME` at the top of `app.py`, and `name`/`short_name` in
`static/manifest.json`. Everything else (page title, header, home-screen
label) pulls from those two spots.

## Suggested next improvements

- **Persistent history:** results aren't saved anywhere right now (nothing
  is written to disk beyond a temp upload that's deleted after processing).
  Worth adding a lightweight database (SQLite) to keep a log of past
  analyses, so "how many times has this person appeared across *all* my
  uploads" becomes answerable, not just per-upload.
- **Naming unknown people from results:** right now you can only add known
  people via a separate reference photo. A "name this person" button next
  to an Unknown Person thumbnail in the results (saving that thumbnail into
  `known_faces/`) would close the loop in one tap.
- **Background/async processing:** video analysis currently blocks the
  request; for longer clips a job queue (e.g. Celery/RQ) with a progress
  indicator would keep the UI responsive.
- **Face quality guardrails:** very small, blurry, or side-angle faces can
  produce weak encodings and get miscounted as a "new" unknown person.
  A minimum face-size/confidence threshold would reduce false splits.
- **Tolerance as a setting:** matching strictness is currently a fixed
  constant (`KNOWN_TOLERANCE` / `UNKNOWN_CLUSTER_TOLERANCE` in `app.py`).
  Exposing this as a slider would let you trade off false matches vs.
  missed matches for your specific use case.
- **Privacy note:** this stores reference face photos and processes uploads
  entirely on the machine you run it on — nothing leaves your server except
  when you paste a link (which is fetched from wherever you point it).
  Worth keeping in mind if you deploy this somewhere multi-user.
