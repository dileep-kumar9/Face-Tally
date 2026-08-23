import base64
import io
import mimetypes
import os
import re
import shutil
import sqlite3
import uuid
from collections import OrderedDict
from functools import wraps
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import requests
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from PIL import Image, ImageDraw
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)
import face_recognition

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

APP_NAME = "FaceTally"

app = Flask(__name__)

_secret_key = os.environ.get("FACETALLY_SECRET_KEY")

if not _secret_key:
    # A hardcoded fallback secret would be visible in this public repo,
    # which would let anyone forge valid session cookies once real
    # accounts/passwords depend on session integrity - not acceptable
    # once login exists. Generating a random one per process is safe,
    # but means sessions (i.e. being logged in) won't survive a restart
    # unless FACETALLY_SECRET_KEY is actually set as a real env var -
    # set one in Render's dashboard for stable logins across deploys.
    _secret_key = os.urandom(32).hex()
    print(
        "WARNING: FACETALLY_SECRET_KEY is not set - using a random "
        "key for this process. Everyone will be logged out on the "
        "next restart. Set FACETALLY_SECRET_KEY as a real environment "
        "variable to avoid this."
    )

app.secret_key = _secret_key

app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Holds one subfolder per user (named by user id), each containing that
# user's own known-face reference photos. KNOWN_FACES_DIR is kept as the
# env var name for continuity with existing Render configs; it's now a
# root directory rather than a flat folder of images.
KNOWN_FACES_ROOT = os.environ.get(
    "KNOWN_FACES_DIR",
    os.path.join(BASE_DIR, "known_faces"),
)

UPLOADS_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(BASE_DIR, "uploads"),
)

# Holds, at most, one video per browser session: the most recently analyzed
# one, kept around just long enough for its timeline to be clickable/seekable
# in the <video> player. Not for long-term storage - see _cleanup_session_playback().
PLAYBACK_DIR = os.environ.get(
    "PLAYBACK_DIR",
    os.path.join(UPLOADS_DIR, "playback"),
)

# Lives on the same persistent disk as known_faces so accounts survive a
# redeploy - see the README note about attaching a Render Disk at /data.
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(KNOWN_FACES_ROOT.rstrip("/")) or BASE_DIR, "facetally.db"),
)

os.makedirs(KNOWN_FACES_ROOT, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(PLAYBACK_DIR, exist_ok=True)

# Best-effort cleanup of anything left over from a previous run (e.g. after
# a crash mid-analysis). Safe because PLAYBACK_DIR holds nothing but these
# transient copies.
for _leftover in os.listdir(PLAYBACK_DIR):
    try:
        os.remove(os.path.join(PLAYBACK_DIR, _leftover))
    except OSError:
        pass


# ============================================================
# ACCOUNTS
# ============================================================

def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


init_db()


USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-@]{2,62}$")


def create_user(username, password):
    """Returns the new user's id, or raises ValueError with a user-facing message."""

    username = username.strip()

    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 3-64 characters: letters, numbers, "
            "underscore, period, hyphen, or @ (so an email address works too)."
        )

    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")

    password_hash = generate_password_hash(password)

    with get_db() as db:

        existing = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if existing:
            raise ValueError("That username is already taken.")

        cursor = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )

        user_id = cursor.lastrowid

    _migrate_legacy_known_faces_if_first_user(user_id)

    return user_id


def get_user_by_username(username):
    with get_db() as db:
        return db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()


def get_user_by_id(user_id):
    with get_db() as db:
        return db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def login_required_json(view):
    """For fetch()-based JSON endpoints - a redirect response would just
    break response.json() on the frontend, so this returns a proper 401
    JSON body instead."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify(
                {
                    "ok": False,
                    "error": "Please log in again.",
                }
            ), 401
        return view(*args, **kwargs)
    return wrapped


def user_known_faces_dir(user_id):
    path = os.path.join(KNOWN_FACES_ROOT, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _migrate_legacy_known_faces_if_first_user(new_user_id):
    """
    Before accounts existed, known_faces/ was a flat folder shared by
    everyone. If that folder still has loose image files sitting directly
    in it (not yet claimed by any user), the very first account created
    claims them, so existing saved people aren't silently lost.
    """
    try:
        entries = os.listdir(KNOWN_FACES_ROOT)
    except OSError:
        return

    loose_files = [
        f for f in entries
        if os.path.isfile(os.path.join(KNOWN_FACES_ROOT, f))
        and allowed_file(f)
        and not is_video_file(f)
    ]

    if not loose_files:
        return

    dest = user_known_faces_dir(new_user_id)

    for filename in loose_files:
        try:
            shutil.move(
                os.path.join(KNOWN_FACES_ROOT, filename),
                os.path.join(dest, filename),
            )
        except OSError:
            pass

VIDEO_MIME_TYPES = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "m4v": "video/x-m4v",
}


def guess_video_mimetype(filename):
    ext = ext_of(filename)
    return VIDEO_MIME_TYPES.get(ext, "video/mp4")


def cleanup_session_playback():
    """Delete the previous video kept for this browser session, if any."""
    info = session.get("playback")
    if info and info.get("path") and os.path.exists(info["path"]):
        try:
            os.remove(info["path"])
        except OSError:
            pass
    session.pop("playback", None)


# ============================================================
# FILE TYPES
# ============================================================

IMAGE_EXT = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "bmp",
}

VIDEO_EXT = {
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "m4v",
}

ALLOWED_EXT = IMAGE_EXT | VIDEO_EXT


# ============================================================
# FACE MATCHING
# ============================================================

KNOWN_TOLERANCE = 0.5
UNKNOWN_CLUSTER_TOLERANCE = 0.5


# ============================================================
# VIDEO SETTINGS
# ============================================================

# Two samples per second gives better timeline accuracy
# than the previous 1 FPS configuration.
TARGET_SAMPLE_FPS = 2.0

# Maximum number of frames analyzed.
MAX_SAMPLED_FRAMES = 120


# ============================================================
# COLORS
# ============================================================

KNOWN_COLOR = (0, 200, 150)
UNKNOWN_COLOR = (255, 180, 70)


# ============================================================
# DOWNLOAD LIMIT
# ============================================================

MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024


# ============================================================
# GENERAL HELPERS
# ============================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT
    )


def ext_of(filename):
    return (
        filename.rsplit(".", 1)[1].lower()
        if "." in filename
        else ""
    )


def is_video_file(filename):
    return ext_of(filename) in VIDEO_EXT


def safe_name(name):
    cleaned = "".join(
        c for c in name
        if c.isalnum() or c in (" ", "_", "-")
    )

    return cleaned.strip()


# ============================================================
# URL DETECTION
# ============================================================

def is_youtube_url(url):
    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower().split(":")[0]

        return (
            host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "youtu.be"
        )

    except Exception:
        return False


def is_google_drive_url(url):
    try:
        host = urlparse(url).netloc.lower()

        return (
            "drive.google.com" in host
            or "docs.google.com" in host
        )

    except Exception:
        return False


def is_direct_media_url(url):
    path = urlparse(url).path.lower()

    return any(
        path.endswith("." + extension)
        for extension in ALLOWED_EXT
    )


# ============================================================
# KNOWN FACE MANAGEMENT
# ============================================================

def load_known_faces(known_faces_dir):
    known_encodings = []
    known_names = []

    for filename in os.listdir(known_faces_dir):

        if not allowed_file(filename):
            continue

        if is_video_file(filename):
            continue

        path = os.path.join(
            known_faces_dir,
            filename,
        )

        try:
            image = face_recognition.load_image_file(path)

            encodings = face_recognition.face_encodings(
                image
            )

            if encodings:
                known_encodings.append(encodings[0])

                known_names.append(
                    os.path.splitext(filename)[0]
                )

        except Exception as exc:
            print(
                f"Could not process known face "
                f"{filename}: {exc}"
            )

    return known_encodings, known_names


def list_known_people(known_faces_dir):
    people = [
        {
            "name": os.path.splitext(filename)[0],
            "filename": filename,
        }
        for filename in os.listdir(known_faces_dir)
        if allowed_file(filename)
        and not is_video_file(filename)
    ]

    people.sort(key=lambda p: p["name"].lower())

    return people


# ============================================================
# IMAGE HELPERS
# ============================================================

def image_to_base64(
    pil_image,
    fmt="PNG",
):
    buffer = io.BytesIO()

    if fmt == "JPEG":
        pil_image.save(
            buffer,
            format="JPEG",
            quality=85,
        )

    else:
        pil_image.save(
            buffer,
            format=fmt,
        )

    return base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")


def _crop_face_region(
    rgb_frame,
    location,
    pad_ratio=0.35,
):
    top, right, bottom, left = location

    height = bottom - top
    width = right - left

    pad_h = int(height * pad_ratio)
    pad_w = int(width * pad_ratio)

    top = max(top - pad_h, 0)

    bottom = min(
        bottom + pad_h,
        rgb_frame.shape[0],
    )

    left = max(left - pad_w, 0)

    right = min(
        right + pad_w,
        rgb_frame.shape[1],
    )

    crop = rgb_frame[
        top:bottom,
        left:right,
    ]

    if crop.size == 0:
        crop = rgb_frame

    return Image.fromarray(crop)


def crop_thumbnail(
    rgb_frame,
    location,
    pad_ratio=0.35,
    size=160,
):
    image = _crop_face_region(
        rgb_frame,
        location,
        pad_ratio,
    )

    image.thumbnail(
        (size, size)
    )

    return image_to_base64(
        image,
        fmt="JPEG",
    )


def annotate_frame(
    rgb_frame,
    locations,
    labels,
):
    pil_image = Image.fromarray(rgb_frame)

    draw = ImageDraw.Draw(
        pil_image
    )

    for location, label in zip(
        locations,
        labels,
    ):
        top, right, bottom, left = location

        if label.startswith("Unknown"):
            color = UNKNOWN_COLOR

        else:
            color = KNOWN_COLOR

        draw.rectangle(
            (
                (left, top),
                (right, bottom),
            ),
            outline=color,
            width=3,
        )

        bbox = draw.textbbox(
            (left, bottom),
            label,
        )

        draw.rectangle(
            (
                (left, bottom),
                (
                    bbox[2] + 8,
                    bbox[3] + 6,
                ),
            ),
            fill=color,
        )

        draw.text(
            (
                left + 4,
                bottom + 2,
            ),
            label,
            fill=(15, 15, 20),
        )

    del draw

    return pil_image


# ============================================================
# VIDEO SAMPLING
# ============================================================

def sample_video_frames(
    path,
    target_fps=TARGET_SAMPLE_FPS,
    max_samples=MAX_SAMPLED_FRAMES,
):
    cap = cv2.VideoCapture(path)

    if not cap.isOpened():
        return [], 0.0, 0.0, 0

    fps = cap.get(
        cv2.CAP_PROP_FPS
    ) or 25.0

    total_frames = int(
        cap.get(
            cv2.CAP_PROP_FRAME_COUNT
        )
    )

    duration = (
        total_frames / fps
        if fps
        else 0.0
    )

    step = max(
        int(round(fps / target_fps)),
        1,
    )

    frames = []
    index = 0

    while True:

        ret, frame_bgr = cap.read()

        if not ret:
            break

        if index % step == 0:

            rgb = cv2.cvtColor(
                frame_bgr,
                cv2.COLOR_BGR2RGB,
            )

            frames.append(
                (
                    index / fps,
                    rgb,
                )
            )

            if len(frames) >= max_samples:
                break

        index += 1

    cap.release()

    return (
        frames,
        duration,
        fps,
        total_frames,
    )


# ============================================================
# TIMELINE HELPERS
# ============================================================

def _add_timeline_event(
    person,
    timestamp,
):
    """
    Store every timestamp at which a person
    was detected.
    """

    person.setdefault(
        "timestamps",
        [],
    )

    person["timestamps"].append(
        float(timestamp)
    )


def _build_timeline(
    timestamps,
    gap=1.6,
):
    """
    Convert individual detection timestamps
    into readable appearance intervals.

    Example:

        0, 0.5, 1, 1.5, 8, 8.5, 9

    becomes:

        00:00 – 00:02
        00:08 – 00:09
    """

    if not timestamps:
        return []

    timestamps = sorted(
        set(
            float(ts)
            for ts in timestamps
        )
    )

    ranges = []

    start = timestamps[0]
    previous = timestamps[0]

    for timestamp in timestamps[1:]:

        if timestamp - previous <= gap:
            previous = timestamp
            continue

        ranges.append(
            {
                "start": round(
                    start,
                    1,
                ),
                "end": round(
                    previous,
                    1,
                ),
            }
        )

        start = timestamp
        previous = timestamp

    ranges.append(
        {
            "start": round(
                start,
                1,
            ),
            "end": round(
                previous,
                1,
            ),
        }
    )

    return ranges


def format_timestamp(seconds):
    """
    Convert seconds into:

    MM:SS

    or

    HH:MM:SS
    """

    seconds = max(
        0,
        int(round(seconds)),
    )

    hours = seconds // 3600

    minutes = (
        seconds % 3600
    ) // 60

    secs = seconds % 60

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


# ============================================================
# FACE ANALYSIS
# ============================================================

# Face *detection* cost scales with pixel count, but phone video/photos are
# often 1080p+ while a detectable face rarely needs more than a few hundred
# pixels across. Detecting on a downscaled copy and scaling the resulting
# boxes back up (the same technique used in face_recognition's own example
# scripts) cuts detection time substantially with negligible accuracy loss
# for normally-framed faces. Encodings and thumbnails still use the
# full-resolution frame, since those benefit from the extra detail.
DETECTION_MAX_WIDTH = 640


def _locate_faces_fast(rgb):

    height, width = rgb.shape[:2]

    if width <= DETECTION_MAX_WIDTH:
        return face_recognition.face_locations(rgb)

    scale = DETECTION_MAX_WIDTH / width

    small = cv2.resize(
        rgb,
        (0, 0),
        fx=scale,
        fy=scale,
    )

    small_locations = face_recognition.face_locations(
        small
    )

    inverse_scale = 1.0 / scale

    return [
        (
            int(top * inverse_scale),
            int(right * inverse_scale),
            int(bottom * inverse_scale),
            int(left * inverse_scale),
        )
        for (top, right, bottom, left) in small_locations
    ]


def _best_reference_frame(frames):
    """
    Given sampled video frames, finds the largest single detected face
    across all of them (a reasonable proxy for 'most clearly facing the
    camera, closest to it') and returns a padded crop around it plus its
    encoding. Returns None if no frame had a detectable face. Used for
    turning a short recorded clip into one clean reference photo.
    """

    best = None

    for _, rgb in frames:

        for location in _locate_faces_fast(rgb):

            top, right, bottom, left = location

            area = (bottom - top) * (right - left)

            if best is None or area > best[0]:
                best = (area, rgb, location)

    if best is None:
        return None

    _, rgb, location = best

    encodings = face_recognition.face_encodings(
        rgb,
        [location],
    )

    if not encodings:
        return None

    image = _crop_face_region(
        rgb,
        location,
        pad_ratio=0.6,
    )

    return image, encodings[0]


def analyze_frames(
    frames,
    known_encodings,
    known_names,
):
    persons = OrderedDict()

    total_detections = 0

    best_frame = None

    for timestamp, rgb in frames:

        locations = _locate_faces_fast(
            rgb
        )

        encodings = face_recognition.face_encodings(
            rgb,
            locations,
        )

        frame_labels = []

        for location, encoding in zip(
            locations,
            encodings,
        ):

            total_detections += 1

            label = None

            # ====================================================
            # MATCH KNOWN PEOPLE
            # ====================================================

            if known_encodings:

                matches = face_recognition.compare_faces(
                    known_encodings,
                    encoding,
                    tolerance=KNOWN_TOLERANCE,
                )

                distances = face_recognition.face_distance(
                    known_encodings,
                    encoding,
                )

                if len(distances):

                    best_index = int(
                        distances.argmin()
                    )

                    if matches[best_index]:

                        label = known_names[
                            best_index
                        ]

            # ====================================================
            # KNOWN PERSON
            # ====================================================

            if label is not None:

                if label not in persons:

                    persons[label] = {
                        "label": label,
                        "count": 0,
                        "is_known": True,
                        "thumb": crop_thumbnail(
                            rgb,
                            location,
                        ),
                        "first_ts": timestamp,
                        "last_ts": timestamp,
                        "timestamps": [],
                    }

            # ====================================================
            # UNKNOWN PERSON
            # ====================================================

            else:

                label = _match_or_create_unknown(
                    encoding,
                    rgb,
                    location,
                    timestamp,
                    persons,
                )

            # ====================================================
            # RECORD DETECTION
            # ====================================================

            persons[label]["count"] += 1

            persons[label]["last_ts"] = timestamp

            _add_timeline_event(
                persons[label],
                timestamp,
            )

            frame_labels.append(label)

        # ========================================================
        # BEST PREVIEW FRAME
        # ========================================================

        if locations:

            if (
                best_frame is None
                or len(locations) > best_frame[0]
            ):
                best_frame = (
                    len(locations),
                    rgb,
                    locations,
                    frame_labels,
                )

    # ============================================================
    # CREATE PREVIEW
    # ============================================================

    preview = None

    if best_frame is not None:

        preview = annotate_frame(
            best_frame[1],
            best_frame[2],
            best_frame[3],
        )

    elif frames:

        preview = Image.fromarray(
            frames[0][1]
        )

    return (
        persons,
        total_detections,
        preview,
    )


# ============================================================
# UNKNOWN FACE CLUSTERING
# ============================================================

def _match_or_create_unknown(
    encoding,
    rgb,
    location,
    timestamp,
    persons,
):
    best_label = None
    best_distance = None

    for label, person in persons.items():

        if person["is_known"]:
            continue

        distance = float(
            np.linalg.norm(
                person["_encoding"]
                - encoding
            )
        )

        if (
            best_distance is None
            or distance < best_distance
        ):
            best_distance = distance
            best_label = label

    if (
        best_label is not None
        and best_distance < UNKNOWN_CLUSTER_TOLERANCE
    ):

        person = persons[best_label]

        person["_encoding"] = (
            person["_encoding"] * person["_n"]
            + encoding
        ) / (
            person["_n"] + 1
        )

        person["_n"] += 1

        return best_label

    unknown_count = sum(
        1
        for person in persons.values()
        if not person["is_known"]
    )

    label = (
        f"Unknown Person "
        f"{unknown_count + 1}"
    )

    persons[label] = {
        "label": label,
        "count": 0,
        "is_known": False,
        "thumb": crop_thumbnail(
            rgb,
            location,
        ),
        "first_ts": timestamp,
        "last_ts": timestamp,
        "timestamps": [],
        "_encoding": encoding.copy(),
        "_n": 1,
    }

    return label


# ============================================================
# FINALIZE PEOPLE
# ============================================================

def finalize_persons(persons):
    result = []

    for person in persons.values():

        timeline = _build_timeline(
            person.get(
                "timestamps",
                [],
            )
        )

        for item in timeline:

            start_display = format_timestamp(
                item["start"]
            )

            end_display = format_timestamp(
                item["end"]
            )

            item["display"] = (
                start_display
                if start_display == end_display
                else f"{start_display} – {end_display}"
            )

        result.append(
            {
                "label": person["label"],
                "count": person["count"],
                "is_known": person["is_known"],
                "thumb": person["thumb"],
                "first_ts": round(
                    person.get(
                        "first_ts",
                        0,
                    ),
                    1,
                ),
                "last_ts": round(
                    person.get(
                        "last_ts",
                        0,
                    ),
                    1,
                ),
                "timeline": timeline,
            }
        )

    result.sort(
        key=lambda item: (
            -item["count"],
            item["label"],
        )
    )

    return result


# ============================================================
# GOOGLE DRIVE
# ============================================================

def resolve_drive_link(url):
    url = url.strip()

    parsed = urlparse(url)

    # /file/d/FILE_ID/view
    match = re.search(
        r"/file/d/([^/]+)",
        parsed.path,
    )

    if match:

        file_id = match.group(1)

        return (
            "https://drive.google.com/"
            "uc?export=download&id="
            + file_id
        )

    # ?id=FILE_ID
    query = parse_qs(
        parsed.query
    )

    file_ids = query.get("id")

    if (
        "drive.google.com"
        in parsed.netloc.lower()
        and file_ids
    ):

        return (
            "https://drive.google.com/"
            "uc?export=download&id="
            + file_ids[0]
        )

    return url


# ============================================================
# DOWNLOAD HELPERS
# ============================================================

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _write_response_to_file(
    response,
    path,
):
    size = 0

    with open(path, "wb") as file:

        for chunk in response.iter_content(
            8192
        ):

            if not chunk:
                continue

            size += len(chunk)

            if size > MAX_DOWNLOAD_BYTES:

                file.close()

                if os.path.exists(path):
                    os.remove(path)

                raise ValueError(
                    "File is too large. "
                    "Maximum size is 150 MB."
                )

            file.write(chunk)

    return path


def _extension_from_response(
    response,
    url,
):
    content_type = (
        response.headers
        .get(
            "Content-Type",
            "",
        )
        .split(";")[0]
        .strip()
        .lower()
    )

    extension = mimetypes.guess_extension(
        content_type
    )

    if extension:

        extension = (
            extension
            .lstrip(".")
            .lower()
        )

        if extension in ALLOWED_EXT:
            return "." + extension

    path_extension = os.path.splitext(
        urlparse(url).path
    )[1].lower()

    if (
        path_extension
        and path_extension.lstrip(".")
        in ALLOWED_EXT
    ):
        return path_extension

    return None


# ============================================================
# GOOGLE DRIVE DOWNLOAD
# ============================================================

def _drive_download(
    url,
    dest_dir,
):
    direct_url = resolve_drive_link(url)

    session = requests.Session()

    response = session.get(
        direct_url,
        stream=True,
        timeout=30,
        allow_redirects=True,
        headers=DOWNLOAD_HEADERS,
    )

    response.raise_for_status()

    content_type = (
        response.headers
        .get(
            "Content-Type",
            "",
        )
        .lower()
    )

    # Google may return an HTML confirmation page.
    if "text/html" in content_type:

        html = response.text

        confirm_match = re.search(
            r"confirm=([^&\"']+)",
            html,
        )

        if confirm_match:

            token = confirm_match.group(1)

            parsed = urlparse(
                direct_url
            )

            query = parse_qs(
                parsed.query
            )

            file_ids = query.get("id")

            if file_ids:

                direct_url = (
                    "https://drive.usercontent.google.com/"
                    "download?id="
                    + file_ids[0]
                    + "&confirm="
                    + token
                )

                response = session.get(
                    direct_url,
                    stream=True,
                    timeout=30,
                    allow_redirects=True,
                    headers=DOWNLOAD_HEADERS,
                )

                response.raise_for_status()

                content_type = (
                    response.headers
                    .get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

        if "text/html" in content_type:

            raise ValueError(
                "Google Drive did not return "
                "the media file. Make sure the "
                "file is publicly accessible."
            )

    extension = _extension_from_response(
        response,
        url,
    )

    if not extension:

        raise ValueError(
            "Couldn't determine whether the "
            "Google Drive file is a supported "
            "photo or video."
        )

    path = os.path.join(
        dest_dir,
        "drive_download" + extension,
    )

    return _write_response_to_file(
        response,
        path,
    )


# ============================================================
# DIRECT URL DOWNLOAD
# ============================================================

def download_from_url(
    url,
    dest_dir,
):
    url = url.strip()

    if is_google_drive_url(url):

        return _drive_download(
            url,
            dest_dir,
        )

    response = requests.get(
        url,
        stream=True,
        timeout=30,
        allow_redirects=True,
        headers=DOWNLOAD_HEADERS,
    )

    response.raise_for_status()

    extension = _extension_from_response(
        response,
        url,
    )

    if not extension:

        raise ValueError(
            "Couldn't determine whether "
            "that link is a supported "
            "photo or video."
        )

    path = os.path.join(
        dest_dir,
        "link_download" + extension,
    )

    return _write_response_to_file(
        response,
        path,
    )


# ============================================================
# YOUTUBE DOWNLOAD
# ============================================================

def download_youtube_video(
    url,
    dest_dir,
):
    if yt_dlp is None:

        raise RuntimeError(
            "yt-dlp is not installed on the server."
        )

    output_template = os.path.join(
        dest_dir,
        "youtube_%(id)s.%(ext)s",
    )

    ffmpeg_path = (
        shutil.which("ffmpeg")
        or "/usr/bin/ffmpeg"
    )

    ydl_options = {
        "format": (
            "bestvideo[ext=mp4][height<=720]"
            "+bestaudio[ext=m4a]/"
            "best[ext=mp4][height<=720]/"
            "best"
        ),

        "outtmpl": output_template,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "retries": 3,

        "fragment_retries": 3,

        "socket_timeout": 30,

        "max_filesize": MAX_DOWNLOAD_BYTES,

        "http_headers": DOWNLOAD_HEADERS,

        "ffmpeg_location": ffmpeg_path,

        # Cloud/datacenter IPs (Render, AWS, etc.) get hit with YouTube's
        # "Sign in to confirm you're not a bot" challenge far more than
        # residential IPs, regardless of the video. Identifying as the tv
        # or mobile player clients instead of the default web client avoids
        # that challenge in most cases, with no account/cookies needed.
        "extractor_args": {
            "youtube": {
                "player_client": ["tv", "web_safari", "android"],
            }
        },
    }

    try:

        with yt_dlp.YoutubeDL(
            ydl_options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True,
            )

            requested_downloads = (
                info.get(
                    "requested_downloads"
                )
                or []
            )

            candidate_paths = []

            for item in requested_downloads:

                filepath = item.get(
                    "filepath"
                )

                if filepath:
                    candidate_paths.append(
                        filepath
                    )

            prepared_filename = (
                ydl.prepare_filename(info)
            )

            candidate_paths.append(
                prepared_filename
            )

            base_path = os.path.splitext(
                prepared_filename
            )[0]

            for extension in (
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
            ):

                candidate_paths.append(
                    base_path + extension
                )

            for candidate in candidate_paths:

                if (
                    candidate
                    and os.path.exists(candidate)
                    and os.path.getsize(candidate) > 0
                ):
                    return candidate

            videos = []

            for filename in os.listdir(
                dest_dir
            ):

                if filename.lower().endswith(
                    tuple(
                        "."
                        + ext
                        for ext in VIDEO_EXT
                    )
                ):

                    path = os.path.join(
                        dest_dir,
                        filename,
                    )

                    if os.path.isfile(path):
                        videos.append(path)

            if videos:

                videos.sort(
                    key=os.path.getmtime,
                    reverse=True,
                )

                return videos[0]

            raise RuntimeError(
                "yt-dlp completed but no "
                "video file was produced."
            )

    except Exception as exc:

        message = str(exc)
        message_lower = message.lower()

        if "429" in message:

            raise RuntimeError(
                "YouTube temporarily rate-limited "
                "the download. Please try again later."
            ) from exc

        # YouTube's automated-traffic challenge. This is about the
        # server's IP reputation, not the specific video - it fires on
        # cloud/datacenter IPs (Render, AWS, etc.) far more than on
        # residential ones. Checked before the generic "Sign in" branch
        # below, since this message also contains the words "Sign in".
        if "not a bot" in message_lower:

            raise RuntimeError(
                "YouTube blocked this download as automated traffic "
                "(a known issue for server-hosted downloads, unrelated "
                "to this specific video). Please try again in a bit, "
                "or try a different video."
            ) from exc

        # Checked before the generic "Sign in" branch below, since this
        # message also contains the words "Sign in if you've been
        # granted access to this video".
        if "private video" in message_lower:

            raise RuntimeError(
                "This is a private YouTube video."
            ) from exc

        if "confirm your age" in message_lower:

            raise RuntimeError(
                "This YouTube video is age-restricted and "
                "cannot be downloaded by the server."
            ) from exc

        if "sign in" in message_lower:

            raise RuntimeError(
                "This YouTube video requires sign-in "
                "and cannot be downloaded by the server."
            ) from exc

        if "not available" in message_lower:

            raise RuntimeError(
                "This YouTube video is unavailable "
                "or restricted."
            ) from exc

        raise RuntimeError(
            f"Unable to download the YouTube video: "
            f"{message}"
        ) from exc


# ============================================================
# MEDIA DOWNLOAD ROUTER
# ============================================================

def download_media_from_link(
    url,
    dest_dir,
):
    url = url.strip()

    if not url:

        raise ValueError(
            "Please provide a link."
        )

    if is_youtube_url(url):

        return download_youtube_video(
            url,
            dest_dir,
        )

    return download_from_url(
        url,
        dest_dir,
    )


# ============================================================
# ACCOUNTS: SIGNUP / LOGIN / LOGOUT
# ============================================================

@app.route(
    "/signup",
    methods=["GET", "POST"],
)
def signup():

    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template(
            "signup.html",
            app_name=APP_NAME,
        )

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if password != confirm:
        flash("Passwords don't match.", "error")
        return render_template(
            "signup.html",
            app_name=APP_NAME,
            username=username,
        )

    try:
        user_id = create_user(username, password)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template(
            "signup.html",
            app_name=APP_NAME,
            username=username,
        )

    session.clear()
    session["user_id"] = user_id

    flash("Welcome to FaceTally!", "success")
    return redirect(url_for("index"))


@app.route(
    "/login",
    methods=["GET", "POST"],
)
def login():

    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "GET":
        return render_template(
            "login.html",
            app_name=APP_NAME,
        )

    username = request.form.get("username", "")
    password = request.form.get("password", "")

    user = get_user_by_username(username)

    if not user or not check_password_hash(user["password_hash"], password):
        flash("Incorrect username or password.", "error")
        return render_template(
            "login.html",
            app_name=APP_NAME,
            username=username,
        )

    session.clear()
    session["user_id"] = user["id"]

    next_path = request.form.get("next") or request.args.get("next")

    # Only ever redirect to a path within this app - an unchecked "next"
    # value would be an open-redirect vector.
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return redirect(next_path)

    return redirect(url_for("index"))


@app.route(
    "/logout",
    methods=["POST"],
)
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


# ============================================================
# KNOWN-PERSON AVATAR IMAGE
# ============================================================

@app.route("/known_face_image/<name>")
@login_required
def known_face_image(name):
    """Serves a known person's own saved reference photo, scoped to the
    logged-in user - never any other user's."""

    known_dir = user_known_faces_dir(current_user()["id"])

    for filename in os.listdir(known_dir):
        if (
            os.path.splitext(filename)[0] == name
            and allowed_file(filename)
            and not is_video_file(filename)
        ):
            return send_file(
                os.path.join(known_dir, filename),
                conditional=True,
            )

    abort(404)


# ============================================================
# HOME
# ============================================================

@app.route(
    "/",
    methods=["GET"],
)
@login_required
def index():

    user = current_user()

    return render_template(
        "index.html",
        app_name=APP_NAME,
        user=user,
        known_people=list_known_people(
            user_known_faces_dir(user["id"])
        ),
    )


# ============================================================
# ADD KNOWN PERSON
# ============================================================

@app.route(
    "/add_known",
    methods=["POST"],
)
@login_required
def add_known():

    user = current_user()
    known_dir = user_known_faces_dir(user["id"])

    name = request.form.get(
        "name",
        "",
    ).strip()

    file = request.files.get(
        "photo"
    )

    if not file or file.filename == "":

        flash(
            "Please choose a photo, record a "
            "video, or use the camera.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    if not allowed_file(file.filename):

        flash(
            "Use a photo (JPG/PNG/WebP) or a "
            "short video clip.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    is_video = is_video_file(
        file.filename
    )

    extension = ext_of(
        file.filename
    )

    temp_path = os.path.join(
        UPLOADS_DIR,
        f"known_temp_{uuid.uuid4().hex}.{extension}",
    )

    file.save(
        temp_path
    )

    try:

        known_encodings, known_names = load_known_faces(
            known_dir
        )

        if is_video:

            frames, duration, _fps, _total = sample_video_frames(
                temp_path
            )

            media_type = "video"
            sampled_frames = len(frames)

        else:

            rgb = face_recognition.load_image_file(
                temp_path
            )

            frames = [(0.0, rgb)]
            media_type = "image"
            duration = None
            sampled_frames = None

        if not frames:

            flash(
                "Couldn't read that video.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        # Detect everyone in the shot before deciding what to do - a
        # solo photo/clip saves directly under the typed name (the
        # common case, no extra taps), but a shot with several people
        # in it (e.g. a group photo) shows all of them so each unknown
        # face can be named and saved individually, same as an
        # Unknown Person card from a regular analysis.
        persons_raw, total_detections, preview = analyze_frames(
            frames,
            known_encodings,
            known_names,
        )

        if len(persons_raw) == 0:

            flash(
                f"No face detected in that "
                f"{'recording' if is_video else 'photo'}. Try "
                f"again with better lighting, or facing the "
                f"camera directly.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        if len(persons_raw) > 1:

            # ------------------------------------------------
            # GROUP SHOT: hand off to the same results view
            # Unknown Person cards already use for saving faces
            # ------------------------------------------------

            result = finalize_analysis_result(
                persons_raw,
                total_detections,
                preview,
                media_type,
                temp_path,
                sampled_frames=sampled_frames,
                duration=duration,
                enable_playback=False,
            )

            flash(
                f"Detected {len(result['persons'])} people in "
                f"that shot. Save whichever ones you'd like below.",
                "success",
            )

            return render_template(
                "index.html",
                app_name=APP_NAME,
                user=user,
                known_people=list_known_people(
                    known_dir
                ),
                result=result,
            )

        # ------------------------------------------------------
        # EXACTLY ONE PERSON: the simple, common case
        # ------------------------------------------------------

        only_label, only_person = next(
            iter(persons_raw.items())
        )

        if only_person["is_known"]:

            flash(
                f"That looks like '{only_label}', who's "
                f"already saved.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        if not name:

            flash(
                "Please provide a name.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        cleaned_name = safe_name(
            name
        )

        if not cleaned_name:

            flash(
                "Please provide a valid name.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        # Replacing an existing person shouldn't leave a stale
        # duplicate around under a different extension.
        for existing in os.listdir(known_dir):
            if (
                os.path.splitext(existing)[0] == cleaned_name
                and allowed_file(existing)
                and not is_video_file(existing)
            ):
                try:
                    os.remove(os.path.join(known_dir, existing))
                except OSError:
                    pass

        if is_video:

            best = _best_reference_frame(
                frames
            )

            if not best:

                flash(
                    f"No face detected in that recording for "
                    f"'{name}'. Try again with better lighting "
                    f"or hold still facing the camera.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            cropped_image, _encoding = best

        else:

            location = _locate_faces_fast(
                frames[0][1]
            )[0]

            cropped_image = _crop_face_region(
                frames[0][1],
                location,
                pad_ratio=0.6,
            )

        save_path = os.path.join(
            known_dir,
            f"{cleaned_name}.jpg",
        )

        cropped_image.save(
            save_path,
            format="JPEG",
            quality=90,
        )

        flash(
            f"Added '{name}' to known people.",
            "success",
        )

        return redirect(
            url_for("index")
        )

    finally:

        if os.path.exists(temp_path):
            os.remove(temp_path)


# ============================================================
# SAVE AN UNKNOWN PERSON FROM ANALYZE RESULTS
# ============================================================

@app.route(
    "/save_unknown",
    methods=["POST"],
)
@login_required_json
def save_unknown():
    """
    Promotes an 'Unknown Person N' from a just-viewed analyze result into
    a saved known person, using the face thumbnail already generated
    during analysis (passed back as base64) rather than asking for a
    fresh photo. JSON in, JSON out - called via fetch() so the result
    page can update in place instead of losing the current analysis.
    """

    name = request.form.get(
        "name",
        "",
    ).strip()

    thumb_b64 = request.form.get(
        "thumb",
        "",
    ).strip()

    if not name:

        return jsonify(
            {
                "ok": False,
                "error": "Please enter a name.",
            }
        ), 400

    cleaned_name = safe_name(
        name
    )

    if not cleaned_name:

        return jsonify(
            {
                "ok": False,
                "error": "Please enter a valid name.",
            }
        ), 400

    if not thumb_b64:

        return jsonify(
            {
                "ok": False,
                "error": "Missing photo data.",
            }
        ), 400

    try:

        image_bytes = base64.b64decode(
            thumb_b64,
            validate=True,
        )

    except Exception:

        return jsonify(
            {
                "ok": False,
                "error": "Invalid photo data.",
            }
        ), 400

    save_path = os.path.join(
        user_known_faces_dir(current_user()["id"]),
        f"{cleaned_name}.jpg",
    )

    with open(save_path, "wb") as f:
        f.write(image_bytes)

    try:

        image = face_recognition.load_image_file(
            save_path
        )

        encodings = face_recognition.face_encodings(
            image
        )

    except Exception:

        encodings = []

    if not encodings:

        if os.path.exists(save_path):
            os.remove(save_path)

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Couldn't detect a clear face in that "
                    "thumbnail. Try saving a different appearance."
                ),
            }
        ), 400

    return jsonify(
        {
            "ok": True,
            "name": cleaned_name,
        }
    )


# ============================================================
# REMOVE KNOWN PERSON
# ============================================================

@app.route(
    "/remove_known/<name>",
    methods=["POST"],
)
@login_required
def remove_known(name):

    known_dir = user_known_faces_dir(
        current_user()["id"]
    )

    for filename in os.listdir(
        known_dir
    ):

        if (
            os.path.splitext(filename)[0]
            == name
            and allowed_file(filename)
        ):

            os.remove(
                os.path.join(
                    known_dir,
                    filename,
                )
            )

            flash(
                f"Removed '{name}'.",
                "success",
            )

            break

    return redirect(
        url_for("index")
    )


def finalize_analysis_result(
    persons_raw,
    total_detections,
    preview,
    media_type,
    upload_path,
    sampled_frames=None,
    duration=None,
    enable_playback=True,
):
    """
    Builds the same result dict shape the analyze results template expects,
    from an already-computed analyze_frames() output. Kept separate from
    running analyze_frames itself so callers that need to inspect the raw
    detections first (add_known's single-vs-group-photo check) don't have
    to run face detection twice.

    If enable_playback and media_type == "video", upload_path is MOVED
    (not copied) into PLAYBACK_DIR as a side effect - the caller's own
    cleanup of upload_path should account for it possibly no longer
    existing at that path afterward.
    """

    persons = finalize_persons(
        persons_raw
    )

    video_url = None

    if media_type == "video" and enable_playback:

        media_filename = os.path.basename(
            upload_path
        )

        token = uuid.uuid4().hex

        playback_path = os.path.join(
            PLAYBACK_DIR,
            f"{token}.{ext_of(media_filename)}",
        )

        try:
            shutil.move(upload_path, playback_path)

            session["playback"] = {
                "token": token,
                "path": playback_path,
                "mimetype": guess_video_mimetype(media_filename),
            }

            video_url = url_for(
                "serve_playback",
                token=token,
            )

        except OSError:
            video_url = None

    return {
        "media_type": media_type,

        "video_url": video_url,

        "preview_image": (
            image_to_base64(
                preview
            )
            if preview is not None
            else None
        ),

        "persons": persons,

        "total_unique": len(
            persons
        ),

        "known_count": sum(
            1
            for person in persons
            if person["is_known"]
        ),

        "unknown_count": sum(
            1
            for person in persons
            if not person["is_known"]
        ),

        "total_detections": (
            total_detections
        ),

        "duration": (
            round(duration)
            if duration
            else None
        ),

        "sampled_frames": (
            sampled_frames
            if media_type == "video"
            else None
        ),
    }


# ============================================================
# ANALYZE MEDIA
# ============================================================

@app.route(
    "/analyze",
    methods=["POST"],
)
@login_required
def analyze():

    cleanup_session_playback()

    file = request.files.get(
        "media"
    )

    url = request.form.get(
        "media_url",
        "",
    ).strip()

    upload_path = None

    try:

        # ====================================================
        # DEVICE UPLOAD
        # ====================================================

        if file and file.filename:

            if not allowed_file(
                file.filename
            ):

                flash(
                    "Unsupported file. "
                    "Use JPG, PNG, WebP, MP4, MOV, "
                    "WebM, MKV, AVI, or M4V.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            original_extension = ext_of(
                file.filename
            )

            original_name = os.path.splitext(
                file.filename
            )[0]

            filename = (
                safe_name(
                    original_name
                )
                or "upload"
            )

            filename += (
                "."
                + original_extension
            )

            upload_path = os.path.join(
                UPLOADS_DIR,
                filename,
            )

            file.save(
                upload_path
            )

        # ====================================================
        # LINK
        # ====================================================

        elif url:

            try:

                upload_path = (
                    download_media_from_link(
                        url,
                        UPLOADS_DIR,
                    )
                )

            except Exception as exc:

                flash(
                    f"Couldn't fetch that link: {exc}",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            if not allowed_file(
                os.path.basename(
                    upload_path
                )
            ):

                if os.path.exists(
                    upload_path
                ):
                    os.remove(
                        upload_path
                    )

                flash(
                    "That link did not produce "
                    "a supported photo or video.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

        # ====================================================
        # NOTHING PROVIDED
        # ====================================================

        else:

            flash(
                "Choose a photo/video or paste a link.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        # ====================================================
        # LOAD KNOWN PEOPLE
        # ====================================================

        known_encodings, known_names = (
            load_known_faces(
                user_known_faces_dir(current_user()["id"])
            )
        )

        media_filename = os.path.basename(
            upload_path
        )

        media_type = (
            "video"
            if is_video_file(
                media_filename
            )
            else "image"
        )

        # ====================================================
        # IMAGE
        # ====================================================

        if media_type == "image":

            rgb = face_recognition.load_image_file(
                upload_path
            )

            frames = [
                (
                    0.0,
                    rgb,
                )
            ]

            duration = None

            sampled_frames = 1

        # ====================================================
        # VIDEO
        # ====================================================

        else:

            (
                frames,
                duration,
                fps,
                total_frames,
            ) = sample_video_frames(
                upload_path
            )

            if not frames:

                flash(
                    "Couldn't read that video.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            sampled_frames = len(
                frames
            )

        # ====================================================
        # FACE ANALYSIS + RESULT
        # ====================================================

        persons_raw, total_detections, preview = analyze_frames(
            frames,
            known_encodings,
            known_names,
        )

        result = finalize_analysis_result(
            persons_raw,
            total_detections,
            preview,
            media_type,
            upload_path,
            sampled_frames=sampled_frames if media_type == "video" else None,
            duration=duration if media_type == "video" else None,
        )

        if media_type == "video" and result["video_url"]:
            # Moved into PLAYBACK_DIR by finalize_analysis_result - the
            # `finally` block below should not try to delete it again.
            upload_path = None

        return render_template(
            "index.html",
            app_name=APP_NAME,
            user=current_user(),
            known_people=list_known_people(
                user_known_faces_dir(current_user()["id"])
            ),
            result=result,
        )

    except Exception as exc:

        flash(
            f"Analysis failed: {exc}",
            "error",
        )

        return redirect(
            url_for("index")
        )

    finally:

        if (
            upload_path
            and os.path.exists(
                upload_path
            )
        ):

            try:
                os.remove(
                    upload_path
                )

            except Exception:
                pass


# ============================================================
# SERVE ANALYZED VIDEO (FOR TIMELINE PLAYBACK)
# ============================================================

@app.route("/media/<token>")
@login_required
def serve_playback(token):
    """
    Streams the most recently analyzed video back to this same browser
    session, so the timeline can seek/play it. Not a general file server -
    only ever serves the one path this session itself just produced.
    """

    info = session.get("playback")

    if not info or info.get("token") != token:
        abort(404)

    path = info.get("path")

    if not path or not os.path.exists(path):
        abort(404)

    return send_file(
        path,
        mimetype=info.get("mimetype", "video/mp4"),
        conditional=True,
    )


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000,
            )
        ),
    )