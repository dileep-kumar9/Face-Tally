"""
FaceTally — detect, recognize, and count people in photos and videos.

One upload box accepts a photo, a video, or a pasted link. Videos are sampled
frame-by-frame; every face seen is matched against known people or clustered
against other unknown faces already seen in this same photo/video, so the
result is a per-person appearance count rather than a raw per-frame dump.
"""

import io
import os
import re
import base64
import mimetypes
from collections import OrderedDict
from urllib.parse import urlparse

import numpy as np
import requests
import cv2
from flask import Flask, render_template, request, redirect, url_for, flash
from PIL import Image, ImageDraw
import face_recognition

APP_NAME = "FaceTally"

app = Flask(__name__)
app.secret_key = os.environ.get("FACETALLY_SECRET_KEY", "dev-secret-key-change-this")
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # 150 MB upload cap

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# In Docker/Render these point at a mounted disk (/data/known_faces) and a
# scratch dir (/tmp/uploads) via env vars set in the Dockerfile. Locally,
# with no env vars set, they just fall back to folders next to app.py.
KNOWN_FACES_DIR = os.environ.get("KNOWN_FACES_DIR", os.path.join(BASE_DIR, "known_faces"))
UPLOADS_DIR = os.environ.get("UPLOADS_DIR", os.path.join(BASE_DIR, "uploads"))

os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "bmp"}
VIDEO_EXT = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}
ALLOWED_EXT = IMAGE_EXT | VIDEO_EXT

# Matching / clustering thresholds
KNOWN_TOLERANCE = 0.5       # lower = stricter match against known_faces/
UNKNOWN_CLUSTER_TOLERANCE = 0.5  # lower = stricter "same unknown person" grouping

# Video sampling
TARGET_SAMPLE_FPS = 1.0     # analyze ~1 frame per second of video
MAX_SAMPLED_FRAMES = 60     # hard cap so long videos stay fast

KNOWN_COLOR = (0, 200, 150)
UNKNOWN_COLOR = (255, 180, 70)

MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def ext_of(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def is_video_file(filename):
    return ext_of(filename) in VIDEO_EXT


def safe_name(name):
    return "".join(c for c in name if c.isalnum() or c in (" ", "_", "-")).strip()


# ----------------------------------------------------------------------------
# Known-face management
# ----------------------------------------------------------------------------

def load_known_faces():
    """Load reference photos from known_faces/. Filename (no extension) = name."""
    known_encodings, known_names = [], []
    for filename in os.listdir(KNOWN_FACES_DIR):
        if not allowed_file(filename) or is_video_file(filename):
            continue
        path = os.path.join(KNOWN_FACES_DIR, filename)
        try:
            image = face_recognition.load_image_file(path)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                known_encodings.append(encodings[0])
                known_names.append(os.path.splitext(filename)[0])
        except Exception as e:
            print(f"Could not process {filename}: {e}")
    return known_encodings, known_names


def list_known_people():
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(KNOWN_FACES_DIR)
        if allowed_file(f) and not is_video_file(f)
    )


# ----------------------------------------------------------------------------
# Image helpers
# ----------------------------------------------------------------------------

def image_to_base64(pil_image, fmt="PNG"):
    buf = io.BytesIO()
    pil_image.save(buf, format=fmt, quality=85 if fmt == "JPEG" else None)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def crop_thumbnail(rgb_frame, location, pad_ratio=0.35, size=160):
    top, right, bottom, left = location
    h, w = bottom - top, right - left
    pad_h, pad_w = int(h * pad_ratio), int(w * pad_ratio)
    t = max(top - pad_h, 0)
    b = min(bottom + pad_h, rgb_frame.shape[0])
    l = max(left - pad_w, 0)
    r = min(right + pad_w, rgb_frame.shape[1])
    crop = rgb_frame[t:b, l:r]
    if crop.size == 0:
        crop = rgb_frame
    img = Image.fromarray(crop)
    img.thumbnail((size, size))
    return image_to_base64(img, fmt="JPEG")


def annotate_frame(rgb_frame, locations, labels):
    pil_image = Image.fromarray(rgb_frame)
    draw = ImageDraw.Draw(pil_image)
    for (top, right, bottom, left), label in zip(locations, labels):
        color = UNKNOWN_COLOR if label.startswith("Unknown") else KNOWN_COLOR
        draw.rectangle(((left, top), (right, bottom)), outline=color, width=3)
        bbox = draw.textbbox((left, bottom), label)
        draw.rectangle(((left, bottom), (bbox[2] + 8, bbox[3] + 6)), fill=color)
        draw.text((left + 4, bottom + 2), label, fill=(15, 15, 20))
    del draw
    return pil_image


# ----------------------------------------------------------------------------
# Video sampling
# ----------------------------------------------------------------------------

def sample_video_frames(path, target_fps=TARGET_SAMPLE_FPS, max_samples=MAX_SAMPLED_FRAMES):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = (total_frames / fps) if fps else 0.0
    step = max(int(round(fps / target_fps)), 1)

    frames = []
    idx = 0
    while True:
        ret, frame_bgr = cap.read()
        if not ret:
            break
        if idx % step == 0:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frames.append((idx / fps, rgb))
            if len(frames) >= max_samples:
                break
        idx += 1
    cap.release()
    return frames, duration, fps, total_frames


# ----------------------------------------------------------------------------
# Core analysis: works identically for a single-frame image or many video frames
# ----------------------------------------------------------------------------

def analyze_frames(frames, known_encodings, known_names):
    """
    frames: list of (timestamp_seconds, rgb_ndarray)
    Returns (persons: OrderedDict[label -> entry], total_detections, preview_pil_image_or_None)
    """
    persons = OrderedDict()
    total_detections = 0
    best_frame = None  # (face_count, rgb, locations, labels)

    for ts, rgb in frames:
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        frame_labels = []

        for loc, enc in zip(locations, encodings):
            total_detections += 1
            label = None

            if known_encodings:
                matches = face_recognition.compare_faces(known_encodings, enc, tolerance=KNOWN_TOLERANCE)
                distances = face_recognition.face_distance(known_encodings, enc)
                if len(distances):
                    best = int(distances.argmin())
                    if matches[best]:
                        label = known_names[best]

            if label is not None:
                if label not in persons:
                    persons[label] = {
                        "label": label, "count": 0, "is_known": True,
                        "thumb": crop_thumbnail(rgb, loc), "first_ts": ts,
                    }
            else:
                label = _match_or_create_unknown(enc, rgb, loc, ts, persons)

            persons[label]["count"] += 1
            persons[label]["last_ts"] = ts
            frame_labels.append(label)

        if locations and (best_frame is None or len(locations) > best_frame[0]):
            best_frame = (len(locations), rgb, locations, frame_labels)

    preview = None
    if best_frame is not None:
        preview = annotate_frame(best_frame[1], best_frame[2], best_frame[3])
    elif frames:
        preview = Image.fromarray(frames[0][1])

    return persons, total_detections, preview


def _match_or_create_unknown(enc, rgb, loc, ts, persons):
    best_label, best_dist = None, None
    for label, p in persons.items():
        if p["is_known"]:
            continue
        d = float(np.linalg.norm(p["_encoding"] - enc))
        if best_dist is None or d < best_dist:
            best_dist, best_label = d, label

    if best_label is not None and best_dist < UNKNOWN_CLUSTER_TOLERANCE:
        p = persons[best_label]
        p["_encoding"] = (p["_encoding"] * p["_n"] + enc) / (p["_n"] + 1)
        p["_n"] += 1
        return best_label

    idx = sum(1 for p in persons.values() if not p["is_known"]) + 1
    label = f"Unknown Person {idx}"
    persons[label] = {
        "label": label, "count": 0, "is_known": False,
        "thumb": crop_thumbnail(rgb, loc), "first_ts": ts,
        "_encoding": enc.copy(), "_n": 1,
    }
    return label


def finalize_persons(persons):
    out = []
    for p in persons.values():
        out.append({
            "label": p["label"],
            "count": p["count"],
            "is_known": p["is_known"],
            "thumb": p["thumb"],
        })
    out.sort(key=lambda x: (-x["count"], x["label"]))
    return out


# ----------------------------------------------------------------------------
# Fetching media from a pasted link (incl. public Google Drive share links)
# ----------------------------------------------------------------------------

def _resolve_drive_link(url):
    m = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if "drive.google.com" in url and m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def download_from_url(url, dest_dir):
    url = _resolve_drive_link(url.strip())
    resp = requests.get(url, stream=True, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    ext = mimetypes.guess_extension(content_type) if content_type else None
    if not ext or ext.lstrip(".").lower() not in ALLOWED_EXT:
        path_ext = os.path.splitext(urlparse(url).path)[1]
        ext = path_ext if path_ext.lstrip(".").lower() in ALLOWED_EXT else ext

    if not ext:
        raise ValueError("couldn't tell what kind of file that link points to")

    filename = f"link_download{ext}"
    path = os.path.join(dest_dir, filename)
    size = 0
    with open(path, "wb") as f:
        for chunk in resp.iter_content(8192):
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                f.close()
                os.remove(path)
                raise ValueError("file is too large (150MB max)")
            f.write(chunk)
    return path


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", app_name=APP_NAME, known_people=list_known_people())


@app.route("/add_known", methods=["POST"])
def add_known():
    name = request.form.get("name", "").strip()
    file = request.files.get("photo")

    if not name:
        flash("Please provide a name.", "error")
        return redirect(url_for("index"))
    if not file or file.filename == "":
        flash("Please choose a photo.", "error")
        return redirect(url_for("index"))
    if not allowed_file(file.filename) or is_video_file(file.filename):
        flash("Use a photo (PNG/JPG/WebP) for known people, not a video.", "error")
        return redirect(url_for("index"))

    ext = ext_of(file.filename)
    save_path = os.path.join(KNOWN_FACES_DIR, f"{safe_name(name)}.{ext}")
    file.save(save_path)

    image = face_recognition.load_image_file(save_path)
    if not face_recognition.face_encodings(image):
        os.remove(save_path)
        flash(f"No face detected in that photo for '{name}'. Try another photo.", "error")
        return redirect(url_for("index"))

    flash(f"Added '{name}' to known people.", "success")
    return redirect(url_for("index"))


@app.route("/remove_known/<name>", methods=["POST"])
def remove_known(name):
    for f in os.listdir(KNOWN_FACES_DIR):
        if os.path.splitext(f)[0] == name and allowed_file(f):
            os.remove(os.path.join(KNOWN_FACES_DIR, f))
            flash(f"Removed '{name}'.", "success")
            break
    return redirect(url_for("index"))


@app.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("media")
    url = request.form.get("media_url", "").strip()
    upload_path = None

    try:
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Unsupported file. Use a photo (JPG/PNG/WebP) or video (MP4/MOV/WebM/MKV).", "error")
                return redirect(url_for("index"))
            filename = safe_name(os.path.splitext(file.filename)[0]) + "." + ext_of(file.filename)
            upload_path = os.path.join(UPLOADS_DIR, filename or f"upload.{ext_of(file.filename)}")
            file.save(upload_path)
        elif url:
            try:
                upload_path = download_from_url(url, UPLOADS_DIR)
            except Exception as e:
                flash(f"Couldn't fetch that link: {e}", "error")
                return redirect(url_for("index"))
            if not allowed_file(os.path.basename(upload_path)):
                os.remove(upload_path)
                flash("That link didn't point to a supported photo or video.", "error")
                return redirect(url_for("index"))
        else:
            flash("Choose a photo/video, or paste a link.", "error")
            return redirect(url_for("index"))

        known_encodings, known_names = load_known_faces()
        media_type = "video" if is_video_file(os.path.basename(upload_path)) else "image"

        if media_type == "image":
            rgb = face_recognition.load_image_file(upload_path)
            frames = [(0.0, rgb)]
            duration = None
            sampled_frames = 1
        else:
            frames, duration, fps, total_frames = sample_video_frames(upload_path)
            if not frames:
                flash("Couldn't read that video file.", "error")
                return redirect(url_for("index"))
            sampled_frames = len(frames)

        persons_raw, total_detections, preview = analyze_frames(frames, known_encodings, known_names)
        persons = finalize_persons(persons_raw)

        result = {
            "media_type": media_type,
            "preview_image": image_to_base64(preview) if preview is not None else None,
            "persons": persons,
            "total_unique": len(persons),
            "known_count": sum(1 for p in persons if p["is_known"]),
            "unknown_count": sum(1 for p in persons if not p["is_known"]),
            "total_detections": total_detections,
            "duration": round(duration) if duration else None,
            "sampled_frames": sampled_frames if media_type == "video" else None,
        }

        return render_template(
            "index.html", app_name=APP_NAME, known_people=list_known_people(), result=result
        )
    finally:
        if upload_path and os.path.exists(upload_path):
            os.remove(upload_path)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))