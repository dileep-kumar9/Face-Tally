import base64
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from collections import OrderedDict
from functools import wraps
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

# ============================================================
# LOAD LOCAL ENVIRONMENT VARIABLES
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env.local for local development.
# On Render, real environment variables take precedence.
load_dotenv(os.path.join(BASE_DIR, ".env.local"))

# ============================================================
# THIRD-PARTY IMPORTS
# ============================================================

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
import face_recognition

try:
    import firebase_admin
    from firebase_admin import auth as firebase_auth
    from firebase_admin import credentials as firebase_credentials
except ImportError:
    firebase_admin = None
    firebase_auth = None
    firebase_credentials = None

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
    _secret_key = os.urandom(32).hex()

    print(
        "WARNING: FACETALLY_SECRET_KEY is not set. "
        "A temporary random session key is being used. "
        "Users will be logged out after restart. "
        "Set FACETALLY_SECRET_KEY in production."
    )

app.secret_key = _secret_key

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get(
        "SESSION_COOKIE_SECURE",
        "true" if os.environ.get("RENDER") else "false",
    ).lower()
    == "true"
)

app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024


# ============================================================
# DIRECTORIES
# ============================================================

KNOWN_FACES_ROOT = os.environ.get(
    "KNOWN_FACES_DIR",
    os.path.join(BASE_DIR, "known_faces"),
)

UPLOADS_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(BASE_DIR, "uploads"),
)

PLAYBACK_DIR = os.environ.get(
    "PLAYBACK_DIR",
    os.path.join(UPLOADS_DIR, "playback"),
)

os.makedirs(KNOWN_FACES_ROOT, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(PLAYBACK_DIR, exist_ok=True)


# ============================================================
# FIREBASE WEB CONFIG
# ============================================================

FIREBASE_WEB_CONFIG = {
    "apiKey": os.environ.get("FIREBASE_API_KEY", ""),
    "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
    "projectId": os.environ.get("FIREBASE_PROJECT_ID", ""),
    "storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET", ""),
    "messagingSenderId": os.environ.get(
        "FIREBASE_MESSAGING_SENDER_ID",
        "",
    ),
    "appId": os.environ.get("FIREBASE_APP_ID", ""),
}


# ============================================================
# FIREBASE ADMIN
# ============================================================

def _init_firebase_admin():
    if firebase_admin is None:
        print(
            "WARNING: firebase-admin is not installed. "
            "Firebase authentication is unavailable."
        )
        return None

    if firebase_admin._apps:
        return firebase_admin.get_app()

    try:
        # --------------------------------------------------------
        # OPTION 1: Full service-account JSON in environment
        # --------------------------------------------------------
        service_json = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT_JSON",
            "",
        ).strip()

        if service_json:
            info = json.loads(service_json)

        else:
            # ----------------------------------------------------
            # OPTION 2: Local service-account JSON file
            # ----------------------------------------------------
            service_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "firebase-service-account.json",
            )

            if os.path.exists(service_file):
                with open(
                    service_file,
                    "r",
                    encoding="utf-8",
                ) as f:
                    info = json.load(f)

            else:
                # ------------------------------------------------
                # OPTION 3: Individual environment variables
                # ------------------------------------------------
                private_key = os.environ.get(
                    "FIREBASE_PRIVATE_KEY",
                    "",
                )

                if private_key:
                    private_key = private_key.replace(
                        "\\n",
                        "\n",
                    )

                info = {
                    "type": "service_account",
                    "project_id": os.environ.get(
                        "FIREBASE_PROJECT_ID",
                        "",
                    ),
                    "private_key_id": os.environ.get(
                        "FIREBASE_PRIVATE_KEY_ID",
                        "",
                    ),
                    "private_key": private_key,
                    "client_email": os.environ.get(
                        "FIREBASE_CLIENT_EMAIL",
                        "",
                    ),
                    "client_id": os.environ.get(
                        "FIREBASE_CLIENT_ID",
                        "",
                    ),
                    "auth_uri": (
                        "https://accounts.google.com/"
                        "o/oauth2/auth"
                    ),
                    "token_uri": (
                        "https://oauth2.googleapis.com/token"
                    ),
                    "auth_provider_x509_cert_url": (
                        "https://www.googleapis.com/"
                        "oauth2/v1/certs"
                    ),
                    "client_x509_cert_url": os.environ.get(
                        "FIREBASE_CLIENT_CERT_URL",
                        "",
                    ),
                }

        # --------------------------------------------------------
        # Validate credentials
        # --------------------------------------------------------
        if (
            not info.get("project_id")
            or not info.get("private_key")
            or not info.get("client_email")
        ):
            print(
                "WARNING: Firebase Admin credentials are incomplete."
            )
            return None

        # --------------------------------------------------------
        # Initialize Firebase Admin
        # --------------------------------------------------------
        cred = firebase_credentials.Certificate(info)

        app_options = {}

        if info.get("project_id"):
            app_options["projectId"] = info["project_id"]

        firebase_app = firebase_admin.initialize_app(
            cred,
            app_options,
        )

        print(
            "Firebase Admin initialized successfully."
        )

        return firebase_app

    except Exception as exc:
        print(
            f"WARNING: Firebase Admin initialization failed: {exc}"
        )
        return None


FIREBASE_ADMIN_APP = _init_firebase_admin()


# ============================================================
# USER HELPERS
# ============================================================

def _safe_uid(uid):
    return re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        str(uid),
    )


def current_user():
    uid = session.get("firebase_uid")

    if not uid:
        return None

    return {
        "uid": uid,
        "username": (
            session.get("email")
            or session.get("display_name")
            or "Account"
        ),
        "email": session.get(
            "email",
            "",
        ),
        "display_name": session.get(
            "display_name",
            "",
        ),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("firebase_uid"):
            return redirect(
                url_for(
                    "login",
                    next=request.path,
                )
            )

        return view(*args, **kwargs)

    return wrapped


def login_required_json(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("firebase_uid"):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "Please log in to save faces."
                    ),
                }
            ), 401

        return view(*args, **kwargs)

    return wrapped


def user_known_faces_dir(user_id):
    path = os.path.join(
        KNOWN_FACES_ROOT,
        _safe_uid(user_id),
    )

    os.makedirs(
        path,
        exist_ok=True,
    )

    return path


# ============================================================
# PLAYBACK HELPERS
# ============================================================

def guess_video_mimetype(filename):
    """
    Return the correct MIME type for a video file.
    """

    extension = (
        os.path.splitext(filename)[1]
        .lower()
    )

    mapping = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".m4v": "video/mp4",
    }

    return mapping.get(
        extension,
        "video/mp4",
    )


def cleanup_session_playback():
    """
    Delete the previous temporary playback video belonging
    to this browser session.
    """

    info = session.get("playback")

    if not info:
        return

    path = info.get("path")

    if path:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    session.pop(
        "playback",
        None,
    )


# ============================================================
# FIREBASE ROUTES
# ============================================================

@app.route("/firebase-config")
def firebase_config():
    return jsonify(
        FIREBASE_WEB_CONFIG
    )


@app.route(
    "/auth/session",
    methods=["POST"],
)
def firebase_session():

    if FIREBASE_ADMIN_APP is None:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Firebase Admin is not "
                    "configured on the server."
                ),
            }
        ), 503

    data = request.get_json(
        silent=True
    ) or {}

    id_token = data.get(
        "idToken",
        "",
    ).strip()

    if not id_token:
        return jsonify(
            {
                "ok": False,
                "error": "Missing Firebase ID token.",
            }
        ), 400

    try:
        decoded = firebase_auth.verify_id_token(
            id_token
        )

    except Exception:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Firebase authentication "
                    "could not be verified."
                ),
            }
        ), 401

    if (
        decoded.get("firebase", {}).get(
            "sign_in_provider"
        )
        == "anonymous"
    ):
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Anonymous Firebase accounts "
                    "cannot create persistent "
                    "saved faces."
                ),
            }
        ), 403

    session.clear()

    session["firebase_uid"] = decoded["uid"]

    session["email"] = decoded.get(
        "email",
        "",
    )

    session["display_name"] = decoded.get(
        "name",
        "",
    )

    return jsonify(
        {
            "ok": True,
            "user": current_user(),
        }
    )


@app.route("/signup")
def signup():

    if session.get("firebase_uid"):
        return redirect(
            url_for("index")
        )

    return render_template(
        "signup.html",
        app_name=APP_NAME,
    )


@app.route("/login")
def login():

    if session.get("firebase_uid"):
        return redirect(
            url_for("index")
        )

    return render_template(
        "login.html",
        app_name=APP_NAME,
    )


@app.route(
    "/logout",
    methods=["POST"],
)
def logout():

    cleanup_session_playback()

    session.clear()

    return redirect(
        url_for("index")
    )


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


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(
            ".",
            1,
        )[1].lower()
        in ALLOWED_EXT
    )


def ext_of(filename):
    return (
        filename.rsplit(
            ".",
            1,
        )[1].lower()
        if "." in filename
        else ""
    )


def is_video_file(filename):
    return ext_of(filename) in VIDEO_EXT


def safe_name(name):
    cleaned = "".join(
        c
        for c in name
        if c.isalnum()
        or c in (
            " ",
            "_",
            "-",
        )
    )

    return cleaned.strip()


# ============================================================
# FACE SETTINGS
# ============================================================

KNOWN_TOLERANCE = 0.5
UNKNOWN_CLUSTER_TOLERANCE = 0.5

DETECTION_MAX_WIDTH = 640

TARGET_SAMPLE_FPS = 2.0

MAX_SAMPLED_FRAMES = 120

KNOWN_COLOR = (
    0,
    200,
    150,
)

UNKNOWN_COLOR = (
    255,
    180,
    70,
)

MAX_DOWNLOAD_BYTES = (
    150 * 1024 * 1024
)


# ============================================================
# URL DETECTION
# ============================================================

def is_youtube_url(url):

    try:
        parsed = urlparse(url)

        host = (
            parsed.netloc
            .lower()
            .split(":")[0]
        )

        return (
            host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "youtu.be"
        )

    except Exception:
        return False


def is_google_drive_url(url):

    try:
        host = urlparse(
            url
        ).netloc.lower()

        return (
            "drive.google.com" in host
            or "docs.google.com" in host
        )

    except Exception:
        return False


# ============================================================
# KNOWN FACES
# ============================================================

def load_known_faces(known_faces_dir):

    known_encodings = []
    known_names = []

    if not os.path.isdir(
        known_faces_dir
    ):
        return (
            known_encodings,
            known_names,
        )

    for filename in os.listdir(
        known_faces_dir
    ):

        if not allowed_file(filename):
            continue

        if is_video_file(filename):
            continue

        path = os.path.join(
            known_faces_dir,
            filename,
        )

        try:

            image = face_recognition.load_image_file(
                path
            )

            encodings = face_recognition.face_encodings(
                image
            )

            if encodings:

                known_encodings.append(
                    encodings[0]
                )

                known_names.append(
                    os.path.splitext(
                        filename
                    )[0]
                )

        except Exception as exc:

            print(
                f"Could not process known face "
                f"{filename}: {exc}"
            )

    return (
        known_encodings,
        known_names,
    )


def list_known_people(
    known_faces_dir,
):

    if not os.path.isdir(
        known_faces_dir
    ):
        return []

    people = [
        {
            "name": os.path.splitext(
                filename
            )[0],
            "filename": filename,
        }
        for filename in os.listdir(
            known_faces_dir
        )
        if (
            allowed_file(filename)
            and not is_video_file(filename)
        )
    ]

    people.sort(
        key=lambda p: p["name"].lower()
    )

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

    pad_h = int(
        height * pad_ratio
    )

    pad_w = int(
        width * pad_ratio
    )

    top = max(
        top - pad_h,
        0,
    )

    bottom = min(
        bottom + pad_h,
        rgb_frame.shape[0],
    )

    left = max(
        left - pad_w,
        0,
    )

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

    return Image.fromarray(
        crop
    )


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
        (
            size,
            size,
        )
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

    pil_image = Image.fromarray(
        rgb_frame
    )

    draw = ImageDraw.Draw(
        pil_image
    )

    for location, label in zip(
        locations,
        labels,
    ):

        top, right, bottom, left = location

        color = (
            UNKNOWN_COLOR
            if label.startswith("Unknown")
            else KNOWN_COLOR
        )

        draw.rectangle(
            (
                (left, top),
                (right, bottom),
            ),
            outline=color,
            width=3,
        )

        bbox = draw.textbbox(
            (
                left,
                bottom,
            ),
            label,
        )

        draw.rectangle(
            (
                (
                    left,
                    bottom,
                ),
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
            fill=(
                15,
                15,
                20,
            ),
        )

    return pil_image


# ============================================================
# FAST FACE LOCATION
# ============================================================

def _locate_faces_fast(rgb):

    height, width = rgb.shape[:2]

    if width <= DETECTION_MAX_WIDTH:
        return face_recognition.face_locations(
            rgb
        )

    scale = (
        DETECTION_MAX_WIDTH
        / width
    )

    small = cv2.resize(
        rgb,
        (
            0,
            0,
        ),
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
        for (
            top,
            right,
            bottom,
            left,
        ) in small_locations
    ]


# ============================================================
# VIDEO SAMPLING
# ============================================================

def sample_video_frames(
    path,
    target_fps=TARGET_SAMPLE_FPS,
    max_samples=MAX_SAMPLED_FRAMES,
):

    cap = cv2.VideoCapture(
        path
    )

    if not cap.isOpened():
        return [], 0.0, 0.0, 0

    fps = (
        cap.get(
            cv2.CAP_PROP_FPS
        )
        or 25.0
    )

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
        int(
            round(
                fps
                / target_fps
            )
        ),
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
# TIMELINE
# ============================================================

def _add_timeline_event(
    person,
    timestamp,
):

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

        if (
            timestamp - previous
            <= gap
        ):

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

    seconds = max(
        0,
        int(
            round(seconds)
        ),
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
# UNKNOWN PERSON CLUSTERING
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
        and best_distance
        < UNKNOWN_CLUSTER_TOLERANCE
    ):

        person = persons[
            best_label
        ]

        person["_encoding"] = (
            person["_encoding"]
            * person["_n"]
            + encoding
        ) / (
            person["_n"]
            + 1
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
# ANALYZE FRAMES
# ============================================================

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

            else:

                label = _match_or_create_unknown(
                    encoding,
                    rgb,
                    location,
                    timestamp,
                    persons,
                )

            persons[label]["count"] += 1

            persons[label]["last_ts"] = timestamp

            _add_timeline_event(
                persons[label],
                timestamp,
            )

            frame_labels.append(
                label
            )

        if locations:

            if (
                best_frame is None
                or len(locations)
                > best_frame[0]
            ):

                best_frame = (
                    len(locations),
                    rgb,
                    locations,
                    frame_labels,
                )

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
# BEST REFERENCE FRAME
# ============================================================

def _best_reference_frame(frames):

    best = None

    for _, rgb in frames:

        for location in _locate_faces_fast(
            rgb
        ):

            top, right, bottom, left = location

            area = (
                bottom - top
            ) * (
                right - left
            )

            if (
                best is None
                or area > best[0]
            ):

                best = (
                    area,
                    rgb,
                    location,
                )

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

    return (
        image,
        encodings[0],
    )


# ============================================================
# FINALIZE PERSONS
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
                else (
                    f"{start_display} – "
                    f"{end_display}"
                )
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

    query = parse_qs(
        parsed.query
    )

    file_ids = query.get(
        "id"
    )

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
# DOWNLOAD
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

    with open(
        path,
        "wb",
    ) as file:

        for chunk in response.iter_content(
            8192
        ):

            if not chunk:
                continue

            size += len(chunk)

            if (
                size
                > MAX_DOWNLOAD_BYTES
            ):

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

    direct_url = resolve_drive_link(
        url
    )

    client = requests.Session()

    response = client.get(
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

        html = response.text

        confirm_match = re.search(
            r"confirm=([^&\"']+)",
            html,
        )

        if confirm_match:

            token = confirm_match.group(
                1
            )

            parsed = urlparse(
                direct_url
            )

            query = parse_qs(
                parsed.query
            )

            file_ids = query.get(
                "id"
            )

            if file_ids:

                direct_url = (
                    "https://drive.usercontent.google.com/"
                    "download?id="
                    + file_ids[0]
                    + "&confirm="
                    + token
                )

                response = client.get(
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
                "the media file. Make sure "
                "the file is publicly accessible."
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
        "drive_download"
        + extension,
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
        "link_download"
        + extension,
    )

    return _write_response_to_file(
        response,
        path,
    )


# ============================================================
# YOUTUBE
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
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "tv",
                    "web_safari",
                    "android",
                ]
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
                    base_path
                    + extension
                )

            for candidate in candidate_paths:

                if (
                    candidate
                    and os.path.exists(candidate)
                    and os.path.getsize(candidate)
                    > 0
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

        if "not a bot" in message_lower:

            raise RuntimeError(
                "YouTube blocked this download as "
                "automated traffic. Please try again "
                "later or try another video."
            ) from exc

        if "private video" in message_lower:

            raise RuntimeError(
                "This is a private YouTube video."
            ) from exc

        if "confirm your age" in message_lower:

            raise RuntimeError(
                "This YouTube video is age-restricted "
                "and cannot be downloaded by the server."
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
# KNOWN PERSON IMAGE
# ============================================================

@app.route(
    "/known_face_image/<name>"
)
@login_required
def known_face_image(name):

    known_dir = user_known_faces_dir(
        current_user()["uid"]
    )

    for filename in os.listdir(
        known_dir
    ):

        if (
            os.path.splitext(filename)[0]
            == name
            and allowed_file(filename)
            and not is_video_file(filename)
        ):

            return send_file(
                os.path.join(
                    known_dir,
                    filename,
                ),
                conditional=True,
            )

    abort(404)


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    user = current_user()

    return render_template(
        "index.html",
        app_name=APP_NAME,
        user=user,
        known_people=(
            list_known_people(
                user_known_faces_dir(
                    user["uid"]
                )
            )
            if user
            else []
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

    known_dir = user_known_faces_dir(
        user["uid"]
    )

    name = request.form.get(
        "name",
        "",
    ).strip()

    file = request.files.get(
        "photo"
    )

    if not file or not file.filename:

        flash(
            "Please choose a photo, record a video, "
            "or use the camera.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    if not allowed_file(
        file.filename
    ):

        flash(
            "Use a photo (JPG/PNG/WebP) or "
            "a short video clip.",
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

            (
                frames,
                duration,
                _fps,
                _total,
            ) = sample_video_frames(
                temp_path
            )

            media_type = "video"

            sampled_frames = len(
                frames
            )

        else:

            rgb = face_recognition.load_image_file(
                temp_path
            )

            frames = [
                (
                    0.0,
                    rgb,
                )
            ]

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

        (
            persons_raw,
            total_detections,
            preview,
        ) = analyze_frames(
            frames,
            known_encodings,
            known_names,
        )

        if len(persons_raw) == 0:

            flash(
                f"No face detected in that "
                f"{'recording' if is_video else 'photo'}. "
                "Try again with better lighting.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        if len(persons_raw) > 1:

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
                f"Detected {len(result['persons'])} people "
                "in that shot. Save whichever ones you'd "
                "like below.",
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

        only_label, only_person = next(
            iter(persons_raw.items())
        )

        if only_person["is_known"]:

            flash(
                f"That looks like '{only_label}', "
                "who's already saved.",
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

        for existing in os.listdir(
            known_dir
        ):

            if (
                os.path.splitext(existing)[0]
                == cleaned_name
                and allowed_file(existing)
                and not is_video_file(existing)
            ):

                try:
                    os.remove(
                        os.path.join(
                            known_dir,
                            existing,
                        )
                    )
                except OSError:
                    pass

        if is_video:

            best = _best_reference_frame(
                frames
            )

            if not best:

                flash(
                    "No face detected clearly in "
                    "that recording.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            cropped_image, _encoding = best

        else:

            locations = _locate_faces_fast(
                frames[0][1]
            )

            if not locations:

                flash(
                    "No face detected.",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            cropped_image = _crop_face_region(
                frames[0][1],
                locations[0],
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

        if os.path.exists(
            temp_path
        ):

            os.remove(
                temp_path
            )


# ============================================================
# SAVE UNKNOWN PERSON
# ============================================================

@app.route(
    "/save_unknown",
    methods=["POST"],
)
@login_required_json
def save_unknown():

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
        user_known_faces_dir(
            current_user()["uid"]
        ),
        f"{cleaned_name}.jpg",
    )

    try:

        with open(
            save_path,
            "wb",
        ) as f:
            f.write(
                image_bytes
            )

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
                    "Couldn't detect a clear face "
                    "in that thumbnail."
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

    # FIXED:
    # current_user() returns "uid", not "id".
    known_dir = user_known_faces_dir(
        current_user()["uid"]
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


# ============================================================
# FINALIZE ANALYSIS RESULT
# ============================================================

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

    persons = finalize_persons(
        persons_raw
    )

    video_url = None

    if (
        media_type == "video"
        and enable_playback
    ):

        media_filename = os.path.basename(
            upload_path
        )

        token = uuid.uuid4().hex

        playback_path = os.path.join(
            PLAYBACK_DIR,
            f"{token}.{ext_of(media_filename)}",
        )

        try:

            shutil.move(
                upload_path,
                playback_path,
            )

            session["playback"] = {
                "token": token,
                "path": playback_path,
                "mimetype": guess_video_mimetype(
                    media_filename
                ),
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
        "total_detections": total_detections,
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
# GUEST FACE REFERENCES
# ============================================================

def load_guest_known_faces_from_request():

    files = request.files.getlist(
        "guest_known"
    )

    names = request.form.getlist(
        "guest_name"
    )

    if not files:
        return (
            [],
            [],
            None,
        )

    temp_dir = tempfile.mkdtemp(
        prefix="guest_known_",
        dir=UPLOADS_DIR,
    )

    for index, file in enumerate(
        files
    ):

        if (
            not file
            or not file.filename
        ):
            continue

        if (
            not allowed_file(file.filename)
            or is_video_file(file.filename)
        ):
            continue

        name = safe_name(
            names[index]
            if index < len(names)
            else ""
        )

        if not name:
            continue

        extension = (
            ext_of(file.filename)
            or "jpg"
        )

        path = os.path.join(
            temp_dir,
            f"{name}_{index}.{extension}",
        )

        file.save(
            path
        )

    encodings, known_names = load_known_faces(
        temp_dir
    )

    return (
        encodings,
        known_names,
        temp_dir,
    )


# ============================================================
# IMPORT GUEST FACES AFTER LOGIN
# ============================================================

@app.route(
    "/import_known",
    methods=["POST"],
)
@login_required_json
def import_known():

    files = request.files.getlist(
        "photos"
    )

    names = request.form.getlist(
        "names"
    )

    if not files:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "No temporary faces were supplied."
                ),
            }
        ), 400

    known_dir = user_known_faces_dir(
        current_user()["uid"]
    )

    imported = []
    skipped = []

    for index, file in enumerate(
        files
    ):

        name = safe_name(
            names[index]
            if index < len(names)
            else ""
        )

        if (
            not name
            or not file
            or not file.filename
        ):

            skipped.append(
                name or "Unnamed face"
            )

            continue

        if (
            not allowed_file(file.filename)
            or is_video_file(file.filename)
        ):

            skipped.append(name)

            continue

        extension = (
            ext_of(file.filename)
            or "jpg"
        )

        temp_path = os.path.join(
            UPLOADS_DIR,
            f"import_{uuid.uuid4().hex}.{extension}",
        )

        save_path = os.path.join(
            known_dir,
            f"{name}.jpg",
        )

        try:

            file.save(
                temp_path
            )

            image = face_recognition.load_image_file(
                temp_path
            )

            encodings = face_recognition.face_encodings(
                image
            )

            if not encodings:

                skipped.append(name)

                continue

            pil = Image.open(
                temp_path
            ).convert("RGB")

            pil.save(
                save_path,
                format="JPEG",
                quality=92,
            )

            imported.append(name)

        except Exception:

            skipped.append(name)

        finally:

            if os.path.exists(
                temp_path
            ):

                try:
                    os.remove(
                        temp_path
                    )
                except OSError:
                    pass

    return jsonify(
        {
            "ok": True,
            "imported": imported,
            "skipped": skipped,
        }
    )


# ============================================================
# ANALYZE MEDIA
# ============================================================

@app.route(
    "/analyze",
    methods=["POST"],
)
def analyze():

    cleanup_session_playback()

    guest_known_dir = None

    file = request.files.get(
        "media"
    )

    url = request.form.get(
        "media_url",
        "",
    ).strip()

    upload_path = None

    try:

        # ----------------------------------------------------
        # DEVICE UPLOAD
        # ----------------------------------------------------

        if file and file.filename:

            if not allowed_file(
                file.filename
            ):

                flash(
                    "Unsupported file. Use JPG, PNG, WebP, "
                    "MP4, MOV, WebM, MKV, AVI, or M4V.",
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

        # ----------------------------------------------------
        # LINK
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # NOTHING PROVIDED
        # ----------------------------------------------------

        else:

            flash(
                "Choose a photo/video or paste a link.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        # ----------------------------------------------------
        # KNOWN PEOPLE
        # ----------------------------------------------------

        if current_user():

            known_encodings, known_names = load_known_faces(
                user_known_faces_dir(
                    current_user()["uid"]
                )
            )

        else:

            (
                known_encodings,
                known_names,
                guest_known_dir,
            ) = load_guest_known_faces_from_request()

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

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        else:

            (
                frames,
                duration,
                _fps,
                _total_frames,
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

        # ----------------------------------------------------
        # ANALYSIS
        # ----------------------------------------------------

        (
            persons_raw,
            total_detections,
            preview,
        ) = analyze_frames(
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
            sampled_frames=(
                sampled_frames
                if media_type == "video"
                else None
            ),
            duration=(
                duration
                if media_type == "video"
                else None
            ),
        )

        if (
            media_type == "video"
            and result["video_url"]
        ):

            upload_path = None

        user = current_user()

        return render_template(
            "index.html",
            app_name=APP_NAME,
            user=user,
            known_people=(
                list_known_people(
                    user_known_faces_dir(
                        user["uid"]
                    )
                )
                if user
                else []
            ),
            result=result,
        )

    except Exception as exc:

        print(
            f"Analysis failed: {exc}"
        )

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

        if (
            guest_known_dir
            and os.path.isdir(
                guest_known_dir
            )
        ):

            shutil.rmtree(
                guest_known_dir,
                ignore_errors=True,
            )


# ============================================================
# SERVE TEMPORARY VIDEO PLAYBACK
# ============================================================

@app.route("/media/<token>")
def serve_playback(token):
    """
    Serve temporary video playback by token.

    The token maps directly to a file inside PLAYBACK_DIR.
    This does not depend on the Flask session.
    """

    if not token or not re.fullmatch(
        r"[a-fA-F0-9]{32}",
        token,
    ):
        abort(404)

    matching_path = None

    for extension in (
        ".mp4",
        ".webm",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
    ):
        candidate = os.path.join(
            PLAYBACK_DIR,
            f"{token}{extension}",
        )

        if os.path.isfile(candidate):
            matching_path = candidate
            break

    if not matching_path:
        abort(404)

    return send_file(
        matching_path,
        mimetype=guess_video_mimetype(
            matching_path
        ),
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