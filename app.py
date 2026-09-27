import base64
import io
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import tempfile
import time
import uuid
from collections import OrderedDict
from functools import wraps
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

# ============================================================
# LOAD LOCAL ENVIRONMENT VARIABLES
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env.local, then .env, for local development. Values already
# set win, so .env.local overrides .env and real environment variables
# (e.g. on Render) override both.
load_dotenv(os.path.join(BASE_DIR, ".env.local"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

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

from PIL import Image, ImageDraw, ImageOps
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

# Keep the session cookie across browser restarts, so a guest's
# analysis folder (and a signed-in user's sign-in) survive them.
app.config["PERMANENT_SESSION_LIFETIME"] = 365 * 24 * 60 * 60


@app.before_request
def _make_session_permanent():
    session.permanent = True


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

# Per-browser-session history of analyses ("This session" folder).
HISTORY_DIR = os.environ.get(
    "HISTORY_DIR",
    os.path.join(UPLOADS_DIR, "history"),
)

os.makedirs(KNOWN_FACES_ROOT, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)


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
# PERMANENT STORAGE (Firestore)
# ============================================================
#
# Render's disk is wiped on every deploy/restart unless a paid disk is
# attached, so signed-in users' saved faces and analysis folder are
# kept in Firestore. The local folders act as a fast cache:
#
#   owners/{owner}/faces/{name}          name, version, image (JPEG)
#   owners/{owner}/history/{entry_id}    meta, version, thumb, chunks
#     .../chunks/{i}                     gzip(result JSON), split to
#                                        stay under Firestore's 1 MiB
#
# Each local cache folder has a .cloud.json manifest mapping item ->
# version, so a sync can tell new, changed, deleted and not-yet-
# uploaded items apart. Without Firestore everything still works from
# local disk only.

import gzip
import threading
from collections import defaultdict

try:
    from firebase_admin import firestore as firebase_firestore
except ImportError:
    firebase_firestore = None


CLOUD_RETRY_SECONDS = 300
CLOUD_SYNC_SECONDS = 30
CLOUD_CHUNK_BYTES = 900 * 1024
MANIFEST_NAME = ".cloud.json"

_cloud_db = None
_cloud_checked_at = 0.0
_cloud_lock = threading.Lock()
_owner_locks = defaultdict(threading.Lock)
_last_sync = {}


def cloud_db():
    """
    Return a Firestore client, or None if Firestore isn't usable.
    Re-checks every few minutes, so enabling Firestore in the console
    takes effect without a restart.
    """

    global _cloud_db, _cloud_checked_at

    if _cloud_db is not None:
        return _cloud_db

    if FIREBASE_ADMIN_APP is None or firebase_firestore is None:
        return None

    with _cloud_lock:

        if _cloud_db is not None:
            return _cloud_db

        if time.time() - _cloud_checked_at < CLOUD_RETRY_SECONDS:
            return None

        _cloud_checked_at = time.time()

        try:
            client = firebase_firestore.client(FIREBASE_ADMIN_APP)
            client.collection("owners").limit(1).get()
            _cloud_db = client
            print("Firestore connected: saved faces and analyses are permanent.")
        except Exception as exc:
            print(
                "WARNING: Firestore is not available, so saved faces and "
                f"analyses are stored on local disk only: {exc}"
            )

    return _cloud_db


def _owner_ref(db, owner):
    return db.collection("owners").document(owner)


def _read_manifest(local_dir):
    try:
        with open(os.path.join(local_dir, MANIFEST_NAME), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(local_dir, manifest):
    path = os.path.join(local_dir, MANIFEST_NAME)
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    os.replace(temp_path, path)


def _manifest_set(local_dir, key, version):
    manifest = _read_manifest(local_dir)

    if version is None:
        manifest.pop(key, None)
    else:
        manifest[key] = version

    _write_manifest(local_dir, manifest)


def _sync_due(kind, owner, force=False):
    key = (kind, owner)
    now = time.time()

    if not force and now - _last_sync.get(key, 0) < CLOUD_SYNC_SECONDS:
        return False

    _last_sync[key] = now
    return True


# ---------------------------------------------------------------
# Saved faces
# ---------------------------------------------------------------

def cloud_put_face(owner, name, path):
    db = cloud_db()

    if db is None:
        return

    version = uuid.uuid4().hex

    try:
        with open(path, "rb") as f:
            image = f.read()

        _owner_ref(db, owner).collection("faces").document(name).set(
            {
                "name": name,
                "version": version,
                "image": image,
                "updated": time.time(),
            }
        )

        _manifest_set(os.path.dirname(path), name, version)

    except Exception as exc:
        print(f"WARNING: couldn't save face '{name}' to Firestore: {exc}")


def cloud_delete_face(owner, name, local_dir):
    db = cloud_db()

    if db is None:
        return

    try:
        _owner_ref(db, owner).collection("faces").document(name).delete()
        _manifest_set(local_dir, name, None)
    except Exception as exc:
        print(f"WARNING: couldn't delete face '{name}' from Firestore: {exc}")


def _local_face_files(local_dir):
    faces = {}

    for filename in os.listdir(local_dir):
        name, extension = os.path.splitext(filename)

        if (
            extension.lstrip(".").lower() in IMAGE_EXT
            and not filename.startswith(".")
        ):
            faces[name] = os.path.join(local_dir, filename)

    return faces


def sync_faces(owner, local_dir, force=False):
    """
    Bring the local face cache in line with Firestore: download new or
    changed faces, drop ones deleted elsewhere, and upload faces that
    only exist locally (e.g. saved before Firestore was enabled).
    """

    db = cloud_db()

    if db is None or not _sync_due("faces", owner, force):
        return

    with _owner_locks[owner]:

        try:
            faces_ref = _owner_ref(db, owner).collection("faces")

            remote = {
                doc.id: doc.to_dict().get("version")
                for doc in faces_ref.select(["version"]).stream()
            }

            manifest = _read_manifest(local_dir)
            local = _local_face_files(local_dir)

            for name, version in remote.items():
                if manifest.get(name) == version and name in local:
                    continue

                data = faces_ref.document(name).get().to_dict() or {}

                if not data.get("image"):
                    continue

                if name in local:
                    os.remove(local[name])

                with open(os.path.join(local_dir, f"{name}.jpg"), "wb") as f:
                    f.write(data["image"])

                manifest[name] = version

            for name in list(manifest):
                if name not in remote:
                    # Deleted in Firestore (e.g. from another device).
                    if name in local:
                        os.remove(local[name])
                    manifest.pop(name)

            _write_manifest(local_dir, manifest)

            for name, path in _local_face_files(local_dir).items():
                if name not in remote and name not in manifest:
                    cloud_put_face(owner, name, path)

        except Exception as exc:
            print(f"WARNING: saved-face sync with Firestore failed: {exc}")


# ---------------------------------------------------------------
# Analysis folder
# ---------------------------------------------------------------

def _entry_ref(db, owner, entry_id):
    return _owner_ref(db, owner).collection("history").document(entry_id)


def cloud_put_entry(owner, local_dir, entry_id):
    db = cloud_db()

    if db is None:
        return

    try:
        meta = _read_json(os.path.join(local_dir, entry_id + ".meta.json"))

        with open(os.path.join(local_dir, entry_id + ".json"), "rb") as f:
            packed = gzip.compress(f.read())

        thumb = b""
        thumb_path = os.path.join(local_dir, entry_id + ".jpg")

        if os.path.isfile(thumb_path):
            with open(thumb_path, "rb") as f:
                thumb = f.read()

        chunks = [
            packed[i:i + CLOUD_CHUNK_BYTES]
            for i in range(0, len(packed), CLOUD_CHUNK_BYTES)
        ] or [b""]

        ref = _entry_ref(db, owner, entry_id)
        batch = db.batch()

        for index, chunk in enumerate(chunks):
            batch.set(
                ref.collection("chunks").document(str(index)),
                {"data": chunk},
            )

        version = uuid.uuid4().hex

        batch.set(
            ref,
            {
                "meta": meta,
                "version": version,
                "thumb": thumb,
                "chunks": len(chunks),
                "created": meta.get("created", time.time()),
            },
        )

        batch.commit()

        _manifest_set(local_dir, entry_id, version)

    except Exception as exc:
        print(f"WARNING: couldn't save analysis to Firestore: {exc}")


def cloud_delete_entry(owner, local_dir, entry_id):
    db = cloud_db()

    if db is None:
        return

    try:
        ref = _entry_ref(db, owner, entry_id)

        for chunk in ref.collection("chunks").stream():
            chunk.reference.delete()

        ref.delete()

        _manifest_set(local_dir, entry_id, None)

    except Exception as exc:
        print(f"WARNING: couldn't delete analysis from Firestore: {exc}")


def cloud_fetch_result(owner, local_dir, entry_id):
    """
    Download an analysis result that isn't in the local cache yet.
    """

    db = cloud_db()

    if db is None:
        return None

    try:
        ref = _entry_ref(db, owner, entry_id)
        doc = ref.get()

        if not doc.exists:
            return None

        count = int(doc.to_dict().get("chunks") or 0)

        packed = b"".join(
            (ref.collection("chunks").document(str(i)).get().to_dict() or {}).get("data", b"")
            for i in range(count)
        )

        result = json.loads(gzip.decompress(packed))

        _write_json(os.path.join(local_dir, entry_id + ".json"), result)

        return result

    except Exception as exc:
        print(f"WARNING: couldn't load analysis from Firestore: {exc}")
        return None


def sync_history(owner, local_dir, force=False):
    """
    Bring the local analysis folder in line with Firestore. Results are
    fetched lazily when an analysis is opened; only summaries and
    thumbnails are downloaded here.
    """

    db = cloud_db()

    if db is None or not _sync_due("history", owner, force):
        return

    with _owner_locks[owner]:

        try:
            history_ref = _owner_ref(db, owner).collection("history")

            remote = {}

            for doc in history_ref.select(["meta", "version"]).stream():
                data = doc.to_dict()
                remote[doc.id] = data

            manifest = _read_manifest(local_dir)

            for entry_id, data in remote.items():
                if not _HEX_ID.fullmatch(entry_id):
                    continue

                meta_path = os.path.join(local_dir, entry_id + ".meta.json")

                if manifest.get(entry_id) == data.get("version") and os.path.isfile(meta_path):
                    continue

                # New or changed elsewhere: refresh the summary and
                # thumbnail, and drop any stale cached result.
                _write_json(meta_path, data.get("meta") or {})

                thumb = (history_ref.document(entry_id).get(["thumb"]).to_dict() or {}).get("thumb")

                if thumb:
                    with open(os.path.join(local_dir, entry_id + ".jpg"), "wb") as f:
                        f.write(thumb)

                try:
                    os.remove(os.path.join(local_dir, entry_id + ".json"))
                except OSError:
                    pass

                manifest[entry_id] = data.get("version")

            for entry_id in list(manifest):
                if entry_id not in remote:
                    history_delete_entry(local_dir, entry_id, cloud=False)
                    manifest.pop(entry_id)

            _write_manifest(local_dir, manifest)

            # Upload analyses that only exist locally (made before
            # Firestore was enabled, or brought over from guest mode).
            for meta in history_list(local_dir):
                entry_id = meta.get("id", "")

                if (
                    entry_id not in remote
                    and entry_id not in manifest
                    and os.path.isfile(os.path.join(local_dir, entry_id + ".json"))
                ):
                    cloud_put_entry(owner, local_dir, entry_id)

        except Exception as exc:
            print(f"WARNING: analysis folder sync with Firestore failed: {exc}")


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

    # Restore faces from Firestore (e.g. after a Render restart wiped
    # the disk) and upload any that only exist here.
    sync_faces(
        face_owner(path),
        path,
    )

    return path


def face_owner(known_dir):
    return "u_" + os.path.basename(known_dir)


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


# ============================================================
# ANALYSIS FOLDER ("Your analyses")
# ============================================================
#
# Every analysis is saved so it can be reopened later without
# re-analysing. Signed-in users' folders are permanent (Firestore, see
# PERMANENT STORAGE); guests' folders are tied to a long-lived browser
# cookie and move into the account when the guest signs in.
#
# Local layout, one folder per owner under HISTORY_DIR:
#
#   <entry>.meta.json   summary shown on the folder card
#   <entry>.json        full result (faces, timeline, preview)
#   <entry>.jpg         preview thumbnail
#   <entry>.<ext>       uploaded video, for playback (links are never
#                       downloaded; they play from their source)

HISTORY_MAX_ENTRIES = 50
GUEST_HISTORY_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
USER_CACHE_MAX_AGE_SECONDS = 2 * 24 * 60 * 60

_HEX_ID = re.compile(r"[0-9a-f]{32}")


def current_owner(create_guest=True):
    """
    "u_<uid>" for a signed-in user, "g_<id>" for a guest browser.
    """

    uid = session.get("firebase_uid")

    if uid:
        return "u_" + _safe_uid(uid)

    guest_id = session.get("guest_id")

    if not (isinstance(guest_id, str) and _HEX_ID.fullmatch(guest_id)):
        if not create_guest:
            return None

        guest_id = uuid.uuid4().hex
        session["guest_id"] = guest_id

    return "g_" + guest_id


def owner_is_user(owner):
    return bool(owner) and owner.startswith("u_")


def owner_history_dir(create=False):
    owner = current_owner(create_guest=create)

    if not owner:
        return None

    path = os.path.join(HISTORY_DIR, owner)

    if create or owner_is_user(owner):
        os.makedirs(path, exist_ok=True)
    elif not os.path.isdir(path):
        return None

    if owner_is_user(owner):
        sync_history(owner, path)

    # Mark the folder as in use so it isn't purged.
    try:
        os.utime(path)
    except OSError:
        pass

    return path


def purge_old_history():
    """
    Drop guest folders unused for 30 days, and user cache folders
    (which Firestore can restore) unused for 2 days.
    """

    now = time.time()
    cloud = cloud_db() is not None

    try:
        names = os.listdir(HISTORY_DIR)
    except OSError:
        return

    for name in names:
        path = os.path.join(HISTORY_DIR, name)

        if name.startswith("g_"):
            max_age = GUEST_HISTORY_MAX_AGE_SECONDS
        elif name.startswith("u_") and cloud:
            max_age = USER_CACHE_MAX_AGE_SECONDS
        else:
            continue

        try:
            if os.path.isdir(path) and os.path.getmtime(path) < now - max_age:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _write_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    os.replace(temp_path, path)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def history_list(history_dir):
    if not history_dir or not os.path.isdir(history_dir):
        return []

    entries = []

    for filename in os.listdir(history_dir):
        if filename.endswith(".meta.json"):
            meta = _read_json(
                os.path.join(history_dir, filename)
            )

            if meta and meta.get("id"):
                entries.append(meta)

    entries.sort(
        key=lambda meta: meta.get("created", 0),
        reverse=True,
    )

    return entries


def history_delete_entry(history_dir, entry_id, cloud=True):
    for filename in os.listdir(history_dir):
        if filename.split(".", 1)[0] == entry_id:
            try:
                os.remove(os.path.join(history_dir, filename))
            except OSError:
                pass

    owner = os.path.basename(history_dir)

    if cloud and owner_is_user(owner):
        cloud_delete_entry(owner, history_dir, entry_id)


def history_add(
    meta,
    result,
    thumb_image,
    video_path=None,
):
    """
    Save an analysis to the current owner's folder and return its id.
    """

    history_dir = owner_history_dir(create=True)
    owner = os.path.basename(history_dir)

    entry_id = uuid.uuid4().hex

    meta = dict(
        meta,
        id=entry_id,
        created=time.time(),
        total_unique=result["total_unique"],
        known_count=result["known_count"],
        unknown_count=result["unknown_count"],
        known_names=[
            person["label"]
            for person in result["persons"]
            if person["is_known"]
        ][:5],
        duration=result["duration"],
    )

    if video_path:
        extension = os.path.splitext(video_path)[1].lower()
        filename = entry_id + extension

        shutil.move(
            video_path,
            os.path.join(history_dir, filename),
        )

        meta["playback"] = {
            "type": "file",
            "file": filename,
        }

    if thumb_image is not None:
        thumb = thumb_image.convert("RGB")
        thumb.thumbnail((360, 360))
        thumb.save(
            os.path.join(history_dir, entry_id + ".jpg"),
            format="JPEG",
            quality=80,
        )

    _write_json(
        os.path.join(history_dir, entry_id + ".json"),
        result,
    )

    _write_json(
        os.path.join(history_dir, entry_id + ".meta.json"),
        meta,
    )

    if owner_is_user(owner):
        cloud_put_entry(owner, history_dir, entry_id)

    for old in history_list(history_dir)[HISTORY_MAX_ENTRIES:]:
        history_delete_entry(history_dir, old["id"])

    return entry_id


def history_load(entry_id):
    if not _HEX_ID.fullmatch(entry_id or ""):
        return None, None, None

    history_dir = owner_history_dir()

    if not history_dir:
        return None, None, None

    meta = _read_json(
        os.path.join(history_dir, entry_id + ".meta.json")
    )

    if not meta:
        return None, None, None

    result = _read_json(
        os.path.join(history_dir, entry_id + ".json")
    )

    owner = os.path.basename(history_dir)

    if result is None and owner_is_user(owner):
        result = cloud_fetch_result(owner, history_dir, entry_id)

    if result is None:
        return None, None, None

    return meta, result, history_dir


def clear_history():
    history_dir = owner_history_dir()

    if not history_dir:
        return

    for meta in history_list(history_dir):
        history_delete_entry(history_dir, meta["id"])


def merge_guest_history(guest_id, user_owner):
    """
    Move a guest's analyses into the account they just signed in to,
    so they become permanent.
    """

    if not (isinstance(guest_id, str) and _HEX_ID.fullmatch(guest_id)):
        return

    guest_dir = os.path.join(HISTORY_DIR, "g_" + guest_id)

    if not os.path.isdir(guest_dir):
        return

    user_dir = os.path.join(HISTORY_DIR, user_owner)
    os.makedirs(user_dir, exist_ok=True)

    for filename in os.listdir(guest_dir):
        if filename == MANIFEST_NAME:
            continue

        try:
            shutil.move(
                os.path.join(guest_dir, filename),
                os.path.join(user_dir, filename),
            )
        except OSError:
            pass

    shutil.rmtree(guest_dir, ignore_errors=True)

    # Uploads the moved analyses to Firestore.
    sync_history(user_owner, user_dir, force=True)


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
    )

    if not isinstance(id_token, str) or not id_token.strip():
        return jsonify(
            {
                "ok": False,
                "error": "Missing Firebase ID token.",
            }
        ), 400

    try:
        # A small clock skew allowance avoids "Token used too early"
        # failures when the local PC clock is a few seconds off.
        decoded = firebase_auth.verify_id_token(
            id_token.strip(),
            clock_skew_seconds=10,
        )

    except Exception as exc:
        print(
            f"WARNING: Firebase ID token verification failed: {exc}"
        )

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

    guest_id = session.get("guest_id")

    session.clear()

    session["firebase_uid"] = decoded["uid"]

    # Analyses made as a guest in this browser become part of the
    # account, and so permanent.
    if guest_id:
        merge_guest_history(
            guest_id,
            current_owner(),
        )

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

    # Saved faces and analyses stay in the account; only the browser's
    # sign-in is cleared.
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

            encoding = encode_reference(
                load_rgb_image(path)
            )

            if encoding is not None:

                known_encodings.append(
                    encoding
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

REFERENCE_FACE_MIN_SIZE = 160
REFERENCE_MAX_SIZE = 480
PREVIEW_MAX_SIZE = 1280


def load_rgb_image(source):
    """
    Load an image file (path or file-like) as an RGB numpy array,
    applying the EXIF orientation so phone photos aren't sideways.
    """

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)

        return np.array(
            image.convert("RGB")
        )


def encode_reference(rgb):
    """
    Return the first face encoding in a reference image, or None.

    Falls back to upsampled detection so small saved faces still work.
    """

    encodings = face_recognition.face_encodings(rgb)

    if encodings:
        return encodings[0]

    locations = face_recognition.face_locations(
        rgb,
        number_of_times_to_upsample=2,
    )

    if not locations:
        return None

    encodings = face_recognition.face_encodings(
        rgb,
        locations[:1],
    )

    return encodings[0] if encodings else None


def make_reference_image(
    rgb_frame,
    location,
):
    """
    Crop a face for saving as a known-person reference. Small faces
    are upscaled so the detector can find them again later.
    """

    image = _crop_face_region(
        rgb_frame,
        location,
        pad_ratio=0.6,
    )

    top, right, bottom, left = location

    face_size = max(
        right - left,
        bottom - top,
        1,
    )

    if face_size < REFERENCE_FACE_MIN_SIZE:
        scale = REFERENCE_FACE_MIN_SIZE / face_size

        image = image.resize(
            (
                max(int(image.width * scale), 1),
                max(int(image.height * scale), 1),
            ),
            Image.LANCZOS,
        )

    image.thumbnail(
        (
            REFERENCE_MAX_SIZE,
            REFERENCE_MAX_SIZE,
        )
    )

    return image


def remove_existing_reference(
    known_dir,
    name,
):
    """
    Delete any saved reference photo for this name, whatever its
    extension, so a person never has two photos.
    """

    for existing in os.listdir(known_dir):
        if (
            os.path.splitext(existing)[0] == name
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


def save_reference_image(
    known_dir,
    name,
    pil_image,
):
    """
    Atomically replace the saved reference photo for this name.
    """

    save_path = os.path.join(
        known_dir,
        f"{name}.jpg",
    )

    temp_path = os.path.join(
        known_dir,
        f".{uuid.uuid4().hex}.tmp",
    )

    pil_image.convert("RGB").save(
        temp_path,
        format="JPEG",
        quality=92,
    )

    remove_existing_reference(
        known_dir,
        name,
    )

    os.replace(
        temp_path,
        save_path,
    )

    # Every way of saving a face (photo, camera, recording, "Save as
    # known", guest import) ends here, so this makes them all permanent.
    cloud_put_face(
        face_owner(known_dir),
        name,
        save_path,
    )

    return save_path


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

VIDEO_FRAME_MAX_WIDTH = 960
STREAM_TIMEOUT_MS = 30000


def _open_video(source):
    """
    Open a local file or an http(s) stream URL. Streams are read
    directly by FFmpeg; nothing is downloaded to disk.
    """

    if re.match(r"https?://", source or ""):
        return cv2.VideoCapture(
            source,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                STREAM_TIMEOUT_MS,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                STREAM_TIMEOUT_MS,
            ],
        )

    return cv2.VideoCapture(source)


def _frame_to_rgb(frame_bgr):
    height, width = frame_bgr.shape[:2]

    # Detection runs at 640px anyway; capping the size keeps memory
    # low on small servers.
    if width > VIDEO_FRAME_MAX_WIDTH:
        scale = VIDEO_FRAME_MAX_WIDTH / width
        frame_bgr = cv2.resize(
            frame_bgr,
            (VIDEO_FRAME_MAX_WIDTH, max(int(height * scale), 1)),
            interpolation=cv2.INTER_AREA,
        )

    return cv2.cvtColor(
        frame_bgr,
        cv2.COLOR_BGR2RGB,
    )


def iter_video_frames(
    source,
    stats,
    target_fps=TARGET_SAMPLE_FPS,
    max_samples=MAX_SAMPLED_FRAMES,
    duration_hint=None,
):
    """
    Yield (timestamp, rgb) samples from a video file or stream URL.

    Short videos are sampled at target_fps. Longer ones get
    max_samples frames spread evenly over the whole video (by seeking),
    so faces late in a long video are still found.

    `stats` is filled in with duration, sampled and interval.
    """

    stats.update(duration=0.0, sampled=0, interval=1.0 / target_fps)

    cap = _open_video(source)

    if not cap.isOpened():
        cap.release()
        return

    try:
        reported_fps = cap.get(cv2.CAP_PROP_FPS)

        # Browser (MediaRecorder) WebM files often report 0 or 1000 fps.
        # Treat anything implausible as unknown and fall back to 30.
        fps_known = (
            reported_fps == reported_fps  # not NaN
            and 1.0 <= reported_fps <= 240.0
        )

        fps = reported_fps if fps_known else 30.0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if duration_hint and duration_hint > 0:
            duration = float(duration_hint)
        elif fps_known and total_frames > 0:
            duration = total_frames / fps
        else:
            duration = 0.0

        if duration * target_fps > max_samples:

            # Long video: seek to evenly spaced points.
            interval = duration / max_samples
            stats["interval"] = interval
            stats["duration"] = duration

            for i in range(max_samples):
                timestamp = (i + 0.5) * interval

                cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)

                ret, frame_bgr = cap.read()

                if not ret:
                    continue

                stats["sampled"] += 1

                yield timestamp, _frame_to_rgb(frame_bgr)

            return

        # Short (or unknown-length) video: read sequentially.
        interval = 1.0 / target_fps
        index = 0
        next_sample = 0.0
        last_timestamp = 0.0

        while stats["sampled"] < max_samples:

            ret, frame_bgr = cap.read()

            if not ret:
                break

            # Prefer the container's own timestamp; it stays correct
            # even when the reported frame rate is wrong.
            position_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

            timestamp = (
                position_ms / 1000.0
                if position_ms and position_ms > 0
                else index / fps
            )

            last_timestamp = max(last_timestamp, timestamp)
            stats["duration"] = max(duration, last_timestamp)

            if timestamp >= next_sample:

                while next_sample <= timestamp:
                    next_sample += interval

                stats["sampled"] += 1

                yield timestamp, _frame_to_rgb(frame_bgr)

            index += 1

    finally:
        cap.release()


def sample_video_frames(
    path,
    target_fps=TARGET_SAMPLE_FPS,
    max_samples=MAX_SAMPLED_FRAMES,
):
    """
    List version of iter_video_frames, for short clips.
    Returns (frames, duration, interval, sampled).
    """

    stats = {}

    frames = list(
        iter_video_frames(
            path,
            stats,
            target_fps=target_fps,
            max_samples=max_samples,
        )
    )

    return (
        frames,
        stats["duration"],
        stats["interval"],
        stats["sampled"],
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
        "ref": image_to_base64(
            make_reference_image(
                rgb,
                location,
            ),
            fmt="JPEG",
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

class FrameAnalyzer:
    """
    Detects, recognises and clusters faces one frame at a time.

    Used for whole files/streams (analyze_frames) and for "analyse
    while watching", where frames arrive from the browser as the video
    plays.
    """

    def __init__(self, known_encodings, known_names):
        self.known_encodings = known_encodings
        self.known_names = known_names
        self.persons = OrderedDict()
        self.total_detections = 0
        self.frames_seen = 0
        self.best_frame = None
        self.first_rgb = None

    def add_frame(self, timestamp, rgb):
        """
        Analyse one frame; returns the labels of the faces found in it.
        """

        self.frames_seen += 1

        if self.first_rgb is None:
            self.first_rgb = rgb

        persons = self.persons

        locations = _locate_faces_fast(rgb)

        encodings = face_recognition.face_encodings(
            rgb,
            locations,
        )

        frame_labels = []

        for location, encoding in zip(locations, encodings):

            self.total_detections += 1

            label = None

            if self.known_encodings:

                matches = face_recognition.compare_faces(
                    self.known_encodings,
                    encoding,
                    tolerance=KNOWN_TOLERANCE,
                )

                distances = face_recognition.face_distance(
                    self.known_encodings,
                    encoding,
                )

                if len(distances):

                    best_index = int(distances.argmin())

                    if matches[best_index]:
                        label = self.known_names[best_index]

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

            frame_labels.append(label)

        if locations and (
            self.best_frame is None
            or len(locations) > self.best_frame[0]
        ):

            self.best_frame = (
                len(locations),
                rgb,
                locations,
                frame_labels,
            )

        return frame_labels

    def preview(self):

        if self.best_frame is not None:

            return annotate_frame(
                self.best_frame[1],
                self.best_frame[2],
                self.best_frame[3],
            )

        if self.first_rgb is not None:
            return Image.fromarray(self.first_rgb)

        return None


def analyze_frames(
    frames,
    known_encodings,
    known_names,
):

    # `frames` may be a generator (streamed video); each frame is
    # analysed as it arrives and never kept.
    analyzer = FrameAnalyzer(
        known_encodings,
        known_names,
    )

    for timestamp, rgb in frames:
        analyzer.add_frame(timestamp, rgb)

    return (
        analyzer.persons,
        analyzer.total_detections,
        analyzer.preview(),
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

    image = make_reference_image(
        rgb,
        location,
    )

    return (
        image,
        encodings[0],
    )


# ============================================================
# FINALIZE PERSONS
# ============================================================

def finalize_persons(
    persons,
    sample_interval=1.0 / TARGET_SAMPLE_FPS,
):

    # Samples closer than this belong to one continuous appearance.
    # Long videos are sampled more sparsely, so the gap scales with it.
    gap = max(1.6, sample_interval * 2.2)

    result = []

    for person in persons.values():

        timeline = _build_timeline(
            person.get(
                "timestamps",
                [],
            ),
            gap=gap,
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
                "ref": person.get(
                    "ref",
                    person["thumb"],
                ),
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

def drive_file_id(url):
    """
    Extract the file id from a Google Drive share link, or None.
    """

    parsed = urlparse(url.strip())

    match = re.search(
        r"/file/d/([A-Za-z0-9_-]+)",
        parsed.path,
    )

    if match:
        return match.group(1)

    file_ids = parse_qs(parsed.query).get("id")

    if file_ids and re.fullmatch(r"[A-Za-z0-9_-]+", file_ids[0]):
        return file_ids[0]

    return None


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


MAX_REDIRECTS = 5


def _assert_public_url(url):
    """
    Refuse URLs that aren't http(s) or that resolve to a private,
    loopback, link-local or otherwise internal address, so the server
    can't be used to reach its own network (SSRF).
    """

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            "Only public http(s) links are supported."
        )

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise ValueError(
            "Couldn't resolve that link's host."
        ) from exc

    for *_, sockaddr in addresses:
        ip = ipaddress.ip_address(
            sockaddr[0].split("%")[0]
        )

        if not ip.is_global:
            raise ValueError(
                "That link points to a private or internal address."
            )


def _safe_get(client, url):
    """
    GET a URL with streaming, re-checking every redirect hop
    against _assert_public_url.
    """

    for _ in range(MAX_REDIRECTS + 1):
        _assert_public_url(url)

        response = client.get(
            url,
            stream=True,
            timeout=30,
            allow_redirects=False,
            headers=DOWNLOAD_HEADERS,
        )

        if response.is_redirect:
            location = response.headers.get("Location", "")
            response.close()
            url = requests.compat.urljoin(url, location)
            continue

        response.raise_for_status()

        return response

    raise ValueError(
        "That link redirected too many times."
    )


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
# LINKS: STREAM VIDEOS, FETCH PHOTOS
# ============================================================
#
# Videos from links are never downloaded. The server reads the stream
# directly while analysing, and the browser plays the original source
# (YouTube's own player, or the original URL). Only photos are fetched,
# into the request's temp folder, and deleted after analysis.

def _filename_from_response(response):
    disposition = response.headers.get("Content-Disposition", "")

    match = re.search(
        r"filename\*?=(?:UTF-8'')?\"?([^\";]+)",
        disposition,
    )

    return match.group(1).strip() if match else ""


def _link_title(url, response=None):
    name = _filename_from_response(response) if response is not None else ""

    if not name:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path) or parsed.hostname or url

    return name[:120]


def _media_from_response(response, url, dest_dir, kind, playback_url, title):
    """
    Turn a successful GET into a link result: videos become a stream
    (the body is not read), photos are saved to dest_dir.
    """

    extension = _extension_from_response(response, response.url or url)

    if not extension:
        filename = _filename_from_response(response)
        candidate = os.path.splitext(filename)[1].lower()

        if candidate.lstrip(".") in ALLOWED_EXT:
            extension = candidate

    if not extension:
        response.close()

        raise ValueError(
            "Couldn't determine whether that link is a supported "
            "photo or video."
        )

    if extension.lstrip(".") in VIDEO_EXT:
        response.close()

        return {
            "media_type": "video",
            "stream_url": response.url or url,
            "duration_hint": None,
            "kind": kind,
            "title": title,
            "playback": {
                "type": "remote",
                "url": playback_url,
            },
        }

    path = os.path.join(
        dest_dir,
        "link_photo" + extension,
    )

    _write_response_to_file(response, path)

    return {
        "media_type": "image",
        "path": path,
        "kind": kind,
        "title": title,
        "playback": None,
    }


def resolve_drive_link(url, dest_dir):
    file_id = drive_file_id(url)

    if not file_id:
        raise ValueError(
            "Couldn't find the file in that Google Drive link."
        )

    # confirm=t skips Drive's "can't scan for viruses" page for large files.
    direct_url = (
        "https://drive.usercontent.google.com/download"
        f"?id={file_id}&export=download&confirm=t"
    )

    response = _safe_get(requests.Session(), direct_url)

    if "text/html" in response.headers.get("Content-Type", "").lower():
        response.close()

        raise ValueError(
            "Google Drive did not return the media file. Make sure "
            "the file is shared as 'Anyone with the link'."
        )

    result = _media_from_response(
        response,
        url,
        dest_dir,
        kind="drive",
        playback_url=direct_url,
        title=_filename_from_response(response) or "Google Drive file",
    )

    if result["playback"]:
        # If the browser can't play Drive's file directly, the page
        # falls back to Drive's own player.
        result["playback"]["embed_url"] = (
            f"https://drive.google.com/file/d/{file_id}/preview"
        )

    return result


def resolve_direct_link(url, dest_dir):
    response = _safe_get(requests.Session(), url)

    return _media_from_response(
        response,
        url,
        dest_dir,
        kind="link",
        playback_url=url,
        title=_link_title(url, response),
    )


# ============================================================
# YOUTUBE
# ============================================================

# Video-only, <=480p is plenty for face detection and fast to stream.
# H.264 (avc1) first because OpenCV's FFmpeg decodes it everywhere.
YOUTUBE_ANALYSIS_FORMAT = (
    "bestvideo[height<=480][vcodec^=avc1]/"
    "best[height<=480][vcodec^=avc1]/"
    "bestvideo[height<=480]/"
    "best[height<=480]/"
    "best"
)


def _youtube_options(work_dir):
    options = {
        "format": YOUTUBE_ANALYSIS_FORMAT,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
        "http_headers": DOWNLOAD_HEADERS,
    }

    # YouTube blocks most datacenter IPs (Render included) with a
    # "confirm you're not a bot" check. Optional workarounds:
    #   YTDLP_COOKIES_FILE  - Netscape cookies.txt from a signed-in
    #                         account (on Render: a Secret File, found
    #                         automatically at /etc/secrets/youtube_cookies.txt)
    #   YTDLP_PROXY         - e.g. http://user:pass@host:port
    cookies_source = os.environ.get(
        "YTDLP_COOKIES_FILE",
        "/etc/secrets/youtube_cookies.txt",
    )

    if cookies_source and os.path.isfile(cookies_source):
        # yt-dlp rewrites the cookie file when it finishes, and Render
        # secret files are read-only, so work on a private copy.
        cookies_copy = os.path.join(
            work_dir,
            "youtube_cookies.txt",
        )

        shutil.copyfile(cookies_source, cookies_copy)

        options["cookiefile"] = cookies_copy

    proxy = os.environ.get("YTDLP_PROXY", "").strip()

    if proxy:
        options["proxy"] = proxy

    return options


class YouTubeBlockedError(RuntimeError):
    """
    YouTube refused the server (bot check / rate limit). The video can
    still be analysed in the browser with "analyse while watching".
    """


def youtube_video_id(url):
    """
    Extract the video id from any common YouTube URL form, or None.
    """

    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    candidate = None

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        candidate = (parse_qs(parsed.query).get("v") or [None])[0]

        match = re.match(r"/(?:shorts|embed|live|v)/([^/?#]+)", parsed.path)

        if not candidate and match:
            candidate = match.group(1)

    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate

    return None


def _youtube_error(exc):
    message = str(exc)
    message_lower = message.lower()

    print("YouTube lookup failed:", message)

    if "429" in message:
        return YouTubeBlockedError(
            "YouTube temporarily rate-limited the server."
        )

    if (
        "not a bot" in message_lower
        or "not a bot" in message_lower.replace("’", "'")
        or "automated traffic" in message_lower
        or "sign in to confirm" in message_lower
    ):
        return YouTubeBlockedError(
            "YouTube is blocking this server from reading videos."
        )

    if "private video" in message_lower:
        return RuntimeError("This is a private YouTube video.")

    if (
        "video unavailable" in message_lower
        or "this video is unavailable" in message_lower
    ):
        return RuntimeError("This YouTube video is unavailable.")

    return RuntimeError(f"Couldn't read the YouTube video: {message}")


def resolve_youtube_link(url, work_dir):
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed on the server.")

    try:
        with yt_dlp.YoutubeDL(_youtube_options(work_dir)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise _youtube_error(exc) from exc

    if info.get("_type") == "playlist" or info.get("entries"):
        raise ValueError(
            "Paste a link to a single YouTube video, not a playlist."
        )

    if info.get("is_live"):
        raise ValueError("Live streams aren't supported.")

    stream_url = info.get("url")

    if not stream_url:
        for item in info.get("requested_formats") or []:
            if item.get("vcodec") not in (None, "none") and item.get("url"):
                stream_url = item["url"]
                break

    video_id = info.get("id", "")

    if not stream_url or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        raise RuntimeError(
            "Couldn't find a playable stream for that YouTube video."
        )

    return {
        "media_type": "video",
        "stream_url": stream_url,
        "duration_hint": info.get("duration"),
        "kind": "youtube",
        "title": (info.get("title") or "YouTube video")[:120],
        "playback": {
            "type": "youtube",
            "video_id": video_id,
        },
    }


def resolve_link(url, work_dir):
    """
    Work out what a pasted link is. Returns a dict with media_type
    ("video" with a stream_url, or "image" with a local path), a title,
    a kind (youtube/drive/link) and how the browser should play it.
    """

    url = url.strip()

    if not url:
        raise ValueError("Please provide a link.")

    if is_youtube_url(url):
        return resolve_youtube_link(url, work_dir)

    if is_google_drive_url(url):
        return resolve_drive_link(url, work_dir)

    return resolve_direct_link(url, work_dir)


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

app.jinja_env.filters["timestamp"] = format_timestamp


def render_home(
    result=None,
    entry=None,
):
    """
    Render the main page, with the session folder and optionally one
    result (and its player) open.
    """

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
        history=history_list(
            owner_history_dir()
        ),
        entry=entry,
        result=result,
    )


@app.route("/")
def index():

    return render_home()


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
                sample_interval,
                sampled_frames,
            ) = sample_video_frames(
                temp_path
            )

            media_type = "video"

        else:

            rgb = load_rgb_image(
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
            sample_interval = None

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
                sampled_frames=sampled_frames,
                duration=duration,
                sample_interval=sample_interval,
            )

            flash(
                f"Detected {len(result['persons'])} people "
                "in that shot. Save whichever ones you'd "
                "like below.",
                "success",
            )

            return render_home(
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

            cropped_image = make_reference_image(
                frames[0][1],
                locations[0],
            )

        # Only replace an existing photo for this name once the new
        # one is known to be good.
        save_reference_image(
            known_dir,
            cleaned_name,
            cropped_image,
        )

        flash(
            f"Added '{cleaned_name}' to known people.",
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

    # Validate in memory first so a bad image never overwrites an
    # existing saved photo with the same name.
    try:

        with Image.open(
            io.BytesIO(image_bytes)
        ) as opened:
            pil_image = ImageOps.exif_transpose(
                opened
            ).convert("RGB")

        encoding = encode_reference(
            np.array(pil_image)
        )

    except Exception:

        encoding = None

    if encoding is None:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Couldn't detect a clear face "
                    "in that photo."
                ),
            }
        ), 400

    save_reference_image(
        user_known_faces_dir(
            current_user()["uid"]
        ),
        cleaned_name,
        pil_image,
    )

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

            cloud_delete_face(
                face_owner(known_dir),
                name,
                known_dir,
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

def _shrink_preview(pil_image):
    """
    Downscale large previews; a full-resolution phone photo embedded
    as base64 would make the result page tens of MB.
    """

    pil_image = pil_image.convert("RGB")

    pil_image.thumbnail(
        (
            PREVIEW_MAX_SIZE,
            PREVIEW_MAX_SIZE,
        )
    )

    return pil_image


def finalize_analysis_result(
    persons_raw,
    total_detections,
    preview,
    media_type,
    sampled_frames=None,
    duration=None,
    sample_interval=None,
):

    persons = finalize_persons(
        persons_raw,
        sample_interval or 1.0 / TARGET_SAMPLE_FPS,
    )

    return {
        "media_type": media_type,
        "preview_image": (
            image_to_base64(
                _shrink_preview(preview),
                fmt="JPEG",
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
        # Spacing between analysed frames; the player uses it to decide
        # how close to a detection still counts as "on screen".
        "sample_interval": (
            round(sample_interval, 3)
            if media_type == "video" and sample_interval
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

    encodings = []
    known_names = []

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
            f"{index}.{extension}",
        )

        file.save(
            path
        )

        # Encode here rather than via load_known_faces so the label
        # is the person's name, not the temporary filename.
        try:
            encoding = encode_reference(
                load_rgb_image(path)
            )
        except Exception as exc:
            print(f"Could not process guest face {name}: {exc}")
            encoding = None

        if encoding is not None:
            encodings.append(encoding)
            known_names.append(name)

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

        try:

            file.save(
                temp_path
            )

            with Image.open(
                temp_path
            ) as opened:
                pil = ImageOps.exif_transpose(
                    opened
                ).convert("RGB")

            if encode_reference(np.array(pil)) is None:

                skipped.append(name)

                continue

            save_reference_image(
                known_dir,
                name,
                pil,
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

    purge_old_history()

    guest_known_dir = None

    file = request.files.get(
        "media"
    )

    url = request.form.get(
        "media_url",
        "",
    ).strip()

    # Every request works in its own folder, so concurrent uploads
    # with the same name (e.g. camera-photo.jpg) can't collide.
    request_dir = tempfile.mkdtemp(
        prefix="analyze_",
        dir=UPLOADS_DIR,
    )

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

            filename = (
                safe_name(
                    os.path.splitext(file.filename)[0]
                )
                or "upload"
            ) + "." + ext_of(file.filename)

            upload_path = os.path.join(
                request_dir,
                filename,
            )

            file.save(
                upload_path
            )

            media = {
                "media_type": (
                    "video"
                    if is_video_file(filename)
                    else "image"
                ),
                "path": upload_path,
                "stream_url": upload_path,
                "duration_hint": None,
                "kind": "upload",
                "title": file.filename[:120],
                "playback": None,
            }

            source_url = None

        # ----------------------------------------------------
        # LINK (videos are streamed, never downloaded)
        # ----------------------------------------------------

        elif url:

            try:

                media = resolve_link(
                    url,
                    request_dir,
                )

            except YouTubeBlockedError:

                # The server can't read it, but the viewer's browser
                # can: analyse it while it plays instead.
                flash(
                    "YouTube won't let the server read this video, so "
                    "FaceTally will analyse it while you watch it here.",
                    "success",
                )

                return redirect(
                    url_for(
                        "watch",
                        url=url,
                    )
                )

            except Exception as exc:

                flash(
                    f"Couldn't open that link: {exc}",
                    "error",
                )

                return redirect(
                    url_for("index")
                )

            source_url = url

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

        media_type = media["media_type"]

        # ----------------------------------------------------
        # ANALYSIS
        # ----------------------------------------------------

        stats = {}

        if media_type == "image":

            frames = [
                (
                    0.0,
                    load_rgb_image(
                        media["path"]
                    ),
                )
            ]

        else:

            # A generator: frames are analysed as they are read, so
            # a streamed video is never held in memory or on disk.
            frames = iter_video_frames(
                media["stream_url"],
                stats,
                duration_hint=media.get("duration_hint"),
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

        if media_type == "video" and not stats.get("sampled"):

            flash(
                "Couldn't read that video.",
                "error",
            )

            return redirect(
                url_for("index")
            )

        result = finalize_analysis_result(
            persons_raw,
            total_detections,
            preview,
            media_type,
            sampled_frames=stats.get("sampled"),
            duration=stats.get("duration"),
            sample_interval=stats.get("interval"),
        )

        # ----------------------------------------------------
        # SAVE TO THE SESSION FOLDER
        # ----------------------------------------------------

        entry_id = history_add(
            {
                "title": media["title"],
                "kind": media["kind"],
                "source_url": source_url,
                "media_type": media_type,
                "playback": media["playback"],
            },
            result,
            preview,
            # Uploaded videos are kept (in the session folder only) so
            # they can be played back; links play from their source.
            video_path=(
                media["path"]
                if media["kind"] == "upload"
                and media_type == "video"
                else None
            ),
        )

        # Redirect so refreshing the page doesn't re-submit the form.
        return redirect(
            url_for(
                "history_entry",
                entry_id=entry_id,
            )
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

        shutil.rmtree(
            request_dir,
            ignore_errors=True,
        )

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
# ANALYSIS FOLDER ROUTES
# ============================================================

@app.route("/history/<entry_id>")
def history_entry(entry_id):

    meta, result, history_dir = history_load(entry_id)

    if meta is None:

        flash(
            "That analysis is no longer available.",
            "error",
        )

        return redirect(
            url_for("index")
        )

    playback = meta.get("playback") or {}

    # Uploaded videos live on the server's disk, which Render clears
    # on restart; the results and faces are still kept.
    meta["video_missing"] = (
        playback.get("type") == "file"
        and not os.path.isfile(
            os.path.join(
                history_dir,
                os.path.basename(playback.get("file", "")),
            )
        )
    )

    return render_home(
        result=result,
        entry=meta,
    )


@app.route("/history/<entry_id>/thumb.jpg")
def history_thumb(entry_id):

    history_dir = owner_history_dir()

    path = (
        os.path.join(history_dir, entry_id + ".jpg")
        if history_dir and _HEX_ID.fullmatch(entry_id)
        else None
    )

    if not path or not os.path.isfile(path):
        abort(404)

    return send_file(
        path,
        mimetype="image/jpeg",
        max_age=3600,
    )


@app.route(
    "/history/<entry_id>/delete",
    methods=["POST"],
)
def history_delete(entry_id):

    history_dir = owner_history_dir()

    if history_dir and _HEX_ID.fullmatch(entry_id):
        history_delete_entry(
            history_dir,
            entry_id,
        )

    return redirect(
        url_for("index")
    )


@app.route(
    "/history/clear",
    methods=["POST"],
)
def history_clear():

    clear_history()

    return redirect(
        url_for("index")
    )


# ============================================================
# ANALYSE WHILE WATCHING (YouTube)
# ============================================================
#
# When YouTube blocks the server, the video is analysed in the
# viewer's own browser session instead: the page plays it in YouTube's
# player, the viewer shares that tab, and the page sends a frame of the
# player (with the exact video time) every half second of video. The
# server analyses each frame as it arrives and saves the result like
# any other analysis. YouTube only ever sees a normal viewer.
#
# Live sessions are kept in memory (gunicorn runs a single worker).

LIVE_SESSIONS = {}
LIVE_LOCK = threading.Lock()
LIVE_MAX_AGE_SECONDS = 3 * 60 * 60
LIVE_MAX_FRAMES = 4000
LIVE_FRAME_MAX_BYTES = 3 * 1024 * 1024


def _purge_live_sessions():
    cutoff = time.time() - LIVE_MAX_AGE_SECONDS

    with LIVE_LOCK:
        for live_id in [
            key
            for key, live in LIVE_SESSIONS.items()
            if live["last_seen"] < cutoff
        ]:
            LIVE_SESSIONS.pop(live_id, None)


def _get_live(live_id):
    with LIVE_LOCK:
        live = LIVE_SESSIONS.get(live_id)

    if not live or live["owner"] != current_owner(create_guest=False):
        return None

    live["last_seen"] = time.time()

    return live


def _live_summary(live, on_screen=()):
    analyzer = live["analyzer"]

    return {
        "ok": True,
        "frames": analyzer.frames_seen,
        "people": [
            {
                "label": person["label"],
                "is_known": person["is_known"],
                "count": person["count"],
            }
            for person in analyzer.persons.values()
        ],
        "on_screen": list(on_screen),
    }


@app.route("/watch")
def watch():

    url = request.args.get("url", "").strip()

    video_id = youtube_video_id(url) if url else None

    if url and not video_id:

        flash(
            "That doesn't look like a YouTube video link.",
            "error",
        )

        return redirect(url_for("index"))

    return render_template(
        "watch.html",
        app_name=APP_NAME,
        user=current_user(),
        url=url,
        video_id=video_id,
    )


@app.route(
    "/live/start",
    methods=["POST"],
)
def live_start():

    _purge_live_sessions()

    url = request.form.get("url", "").strip()

    video_id = youtube_video_id(url)

    if not video_id:
        return jsonify({"ok": False, "error": "Not a YouTube video link."}), 400

    guest_known_dir = None

    try:

        if current_user():

            known_encodings, known_names = load_known_faces(
                user_known_faces_dir(current_user()["uid"])
            )

        else:

            (
                known_encodings,
                known_names,
                guest_known_dir,
            ) = load_guest_known_faces_from_request()

    finally:

        if guest_known_dir:
            shutil.rmtree(guest_known_dir, ignore_errors=True)

    try:
        duration = max(float(request.form.get("duration") or 0), 0.0)
    except ValueError:
        duration = 0.0

    live_id = uuid.uuid4().hex

    live = {
        "owner": current_owner(create_guest=True),
        "analyzer": FrameAnalyzer(known_encodings, known_names),
        "lock": threading.Lock(),
        "url": url,
        "video_id": video_id,
        "title": (request.form.get("title") or "YouTube video").strip()[:120],
        "duration": duration,
        "timestamps": [],
        "last_seen": time.time(),
    }

    with LIVE_LOCK:
        LIVE_SESSIONS[live_id] = live

    return jsonify({"ok": True, "id": live_id})


@app.route(
    "/live/<live_id>/frame",
    methods=["POST"],
)
def live_frame(live_id):

    live = _get_live(live_id)

    if live is None:
        return jsonify({"ok": False, "error": "This analysis has expired. Start again."}), 404

    frame = request.files.get("frame")

    try:
        timestamp = float(request.form.get("t", ""))
    except ValueError:
        timestamp = -1.0

    if not frame or timestamp < 0 or timestamp != timestamp:
        return jsonify({"ok": False, "error": "Bad frame."}), 400

    data = frame.read(LIVE_FRAME_MAX_BYTES + 1)

    if len(data) > LIVE_FRAME_MAX_BYTES:
        return jsonify({"ok": False, "error": "Frame too large."}), 413

    if live["analyzer"].frames_seen >= LIVE_MAX_FRAMES:
        return jsonify(_live_summary(live))

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((VIDEO_FRAME_MAX_WIDTH, VIDEO_FRAME_MAX_WIDTH))
            rgb = np.array(image)
    except Exception:
        return jsonify({"ok": False, "error": "Couldn't read that frame."}), 400

    with live["lock"]:
        labels = live["analyzer"].add_frame(timestamp, rgb)
        live["timestamps"].append(timestamp)

    return jsonify(_live_summary(live, on_screen=labels))


@app.route(
    "/live/<live_id>/finish",
    methods=["POST"],
)
def live_finish(live_id):

    live = _get_live(live_id)

    if live is None:
        return jsonify({"ok": False, "error": "This analysis has expired. Start again."}), 404

    with live["lock"]:

        analyzer = live["analyzer"]

        if analyzer.frames_seen == 0:
            return jsonify({"ok": False, "error": "No frames were captured yet."}), 400

        timestamps = sorted(set(live["timestamps"]))

        gaps = sorted(
            later - earlier
            for earlier, later in zip(timestamps, timestamps[1:])
            if later > earlier
        )

        # Frames arrive as fast as the server keeps up, so use the
        # typical spacing actually achieved for grouping appearances.
        sample_interval = max(
            1.0 / TARGET_SAMPLE_FPS,
            gaps[len(gaps) // 2] if gaps else 0.0,
        )

        preview = analyzer.preview()

        result = finalize_analysis_result(
            analyzer.persons,
            analyzer.total_detections,
            preview,
            "video",
            sampled_frames=analyzer.frames_seen,
            duration=live["duration"] or (timestamps[-1] if timestamps else 0),
            sample_interval=sample_interval,
        )

        entry_id = history_add(
            {
                "title": live["title"],
                "kind": "youtube",
                "source_url": live["url"],
                "media_type": "video",
                "method": "watch",
                "playback": {
                    "type": "youtube",
                    "video_id": live["video_id"],
                },
            },
            result,
            preview,
        )

    with LIVE_LOCK:
        LIVE_SESSIONS.pop(live_id, None)

    return jsonify(
        {
            "ok": True,
            "redirect": url_for(
                "history_entry",
                entry_id=entry_id,
            ) + "#result",
        }
    )


# ============================================================
# SERVICE WORKER
# ============================================================

@app.route("/sw.js")
def service_worker():
    """
    Serve the service worker from the site root so its scope covers
    the whole app, not just /static/.
    """

    response = send_file(
        os.path.join(
            BASE_DIR,
            "static",
            "sw.js",
        ),
        mimetype="application/javascript",
        max_age=0,
    )

    response.headers["Cache-Control"] = "no-cache"

    return response


# ============================================================
# SERVE UPLOADED VIDEOS FOR PLAYBACK
# ============================================================

@app.route("/media/<entry_id>")
def serve_playback(entry_id):
    """
    Stream an uploaded video back for playback. Only its owner (the
    signed-in account, or the guest browser) can open it.
    """

    meta, _result, history_dir = history_load(entry_id)

    playback = (meta or {}).get("playback") or {}

    if playback.get("type") != "file":
        abort(404)

    path = os.path.join(
        history_dir,
        os.path.basename(playback["file"]),
    )

    if not os.path.isfile(path):
        abort(404)

    return send_file(
        path,
        mimetype=guess_video_mimetype(path),
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