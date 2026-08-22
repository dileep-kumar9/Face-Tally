import base64
import io
import mimetypes
import os
import re
import shutil
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import requests
from flask import Flask, flash, redirect, render_template, request, url_for
from PIL import Image, ImageDraw
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

app.secret_key = os.environ.get(
    "FACETALLY_SECRET_KEY",
    "dev-secret-key-change-this",
)

app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

KNOWN_FACES_DIR = os.environ.get(
    "KNOWN_FACES_DIR",
    os.path.join(BASE_DIR, "known_faces"),
)

UPLOADS_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(BASE_DIR, "uploads"),
)

os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)


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

def load_known_faces():
    known_encodings = []
    known_names = []

    for filename in os.listdir(KNOWN_FACES_DIR):

        if not allowed_file(filename):
            continue

        if is_video_file(filename):
            continue

        path = os.path.join(
            KNOWN_FACES_DIR,
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


def list_known_people():
    return sorted(
        os.path.splitext(filename)[0]
        for filename in os.listdir(KNOWN_FACES_DIR)
        if allowed_file(filename)
        and not is_video_file(filename)
    )


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


def crop_thumbnail(
    rgb_frame,
    location,
    pad_ratio=0.35,
    size=160,
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

    image = Image.fromarray(crop)

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

def analyze_frames(
    frames,
    known_encodings,
    known_names,
):
    persons = OrderedDict()

    total_detections = 0

    best_frame = None

    for timestamp, rgb in frames:

        locations = face_recognition.face_locations(
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

        timeline_display = []

        for item in timeline:

            start = format_timestamp(
                item["start"]
            )

            end = format_timestamp(
                item["end"]
            )

            if start == end:
                timeline_display.append(
                    start
                )

            else:
                timeline_display.append(
                    f"{start} – {end}"
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
                "timeline_display": timeline_display,
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
# HOME
# ============================================================

@app.route(
    "/",
    methods=["GET"],
)
def index():

    return render_template(
        "index.html",
        app_name=APP_NAME,
        known_people=list_known_people(),
    )


# ============================================================
# ADD KNOWN PERSON
# ============================================================

@app.route(
    "/add_known",
    methods=["POST"],
)
def add_known():

    name = request.form.get(
        "name",
        "",
    ).strip()

    file = request.files.get(
        "photo"
    )

    if not name:

        flash(
            "Please provide a name.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    if not file or file.filename == "":

        flash(
            "Please choose a photo.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    if (
        not allowed_file(file.filename)
        or is_video_file(file.filename)
    ):

        flash(
            "Use a photo such as JPG, PNG, "
            "or WebP for a known person.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    extension = ext_of(
        file.filename
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

    save_path = os.path.join(
        KNOWN_FACES_DIR,
        f"{cleaned_name}.{extension}",
    )

    file.save(
        save_path
    )

    try:

        image = face_recognition.load_image_file(
            save_path
        )

        encodings = face_recognition.face_encodings(
            image
        )

        if not encodings:

            os.remove(
                save_path
            )

            flash(
                f"No face detected in the photo "
                f"for '{name}'. Try another photo.",
                "error",
            )

            return redirect(
                url_for("index")
            )

    except Exception as exc:

        if os.path.exists(save_path):
            os.remove(save_path)

        flash(
            f"Could not process the photo: {exc}",
            "error",
        )

        return redirect(
            url_for("index")
        )

    flash(
        f"Added '{name}' to known people.",
        "success",
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# REMOVE KNOWN PERSON
# ============================================================

@app.route(
    "/remove_known/<name>",
    methods=["POST"],
)
def remove_known(name):

    for filename in os.listdir(
        KNOWN_FACES_DIR
    ):

        if (
            os.path.splitext(filename)[0]
            == name
            and allowed_file(filename)
        ):

            os.remove(
                os.path.join(
                    KNOWN_FACES_DIR,
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
# ANALYZE MEDIA
# ============================================================

@app.route(
    "/analyze",
    methods=["POST"],
)
def analyze():

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
            load_known_faces()
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
        # FACE ANALYSIS
        # ====================================================

        (
            persons_raw,
            total_detections,
            preview,
        ) = analyze_frames(
            frames,
            known_encodings,
            known_names,
        )

        persons = finalize_persons(
            persons_raw
        )

        # ====================================================
        # RESULT
        # ====================================================

        result = {
            "media_type": media_type,

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

        return render_template(
            "index.html",
            app_name=APP_NAME,
            known_people=list_known_people(),
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