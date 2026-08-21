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
   surfaces Google Drive, Photos, iCloud, Files, etc. on most phones) or a
   pasted link (including public Google Drive share links).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` (or `http://<your-computer's-LAN-IP>:5000` from
your phone, if it's on the same Wi-Fi).

> `face_recognition` depends on `dlib`, which needs a C++ compiler and CMake
> to build. On macOS: `brew install cmake`. On Ubuntu/Debian:
> `sudo apt install cmake build-essential`. On Windows, installing dlib is
> easiest via `pip install dlib-binary` or using a prebuilt wheel — if
> `pip install -r requirements.txt` fails on dlib specifically, that's the
> library to look into first.

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
- **Videos:** the same matching runs per sampled frame; a person's count is
  how many sampled frames they appeared in, which is a reasonable proxy for
  how much screen time they got. Sampling (rather than every frame) keeps
  a multi-minute clip from taking forever to process.
- **Unknown people** are still counted and shown (as "Unknown Person 1",
  "Unknown Person 2", ...) with a cropped thumbnail, even without a name.

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
