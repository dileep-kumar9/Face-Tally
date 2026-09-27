// Analyse while watching: play a YouTube video in YouTube's player,
// capture this tab (cropped to the player) while it plays, and send a
// frame with the exact video time every half second of video. The
// server analyses each frame and saves the result like any other
// analysis. Used when YouTube blocks the server from reading a video.

(function () {
    "use strict";

    const app = document.getElementById("watch-app");

    if (!app || !app.dataset.videoId) {
        return;
    }

    const videoId = app.dataset.videoId;
    const sourceUrl = app.dataset.url;

    const stage = document.getElementById("watch-stage");
    const startBtn = document.getElementById("watch-start");
    const finishBtn = document.getElementById("watch-finish");
    const statusEl = document.getElementById("watch-status");
    const nowEl = document.getElementById("watch-now");
    const peopleEl = document.getElementById("watch-people");
    const titleEl = document.getElementById("watch-title");

    // Seconds of video between analysed frames (~2 frames/sec).
    const SAMPLE_SECONDS = 0.5;
    const MAX_FRAME_WIDTH = 960;

    const canvas = document.createElement("canvas");

    let player = null;
    let stream = null;
    let captureVideo = null;
    let manualCrop = true;
    let liveId = null;
    let framesDone = 0;
    let busy = false;
    let finishing = false;
    let nextSample = 0;
    let lastTime = -1;
    let timer = null;


    function setStatus(text, isError) {
        statusEl.textContent = text;
        statusEl.classList.toggle("error", Boolean(isError));
    }


    function formatClock(totalSeconds) {
        const seconds = Math.max(0, Math.floor(totalSeconds));
        const minutes = Math.floor(seconds / 60);
        return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    }


    // ------------------------------------------------------------
    // YouTube player
    // ------------------------------------------------------------

    const playerReady = new Promise(function (resolve) {

        window.onYouTubeIframeAPIReady = function () {

            player = new YT.Player("watch-player", {
                // Fill the box from the start; a player created at the
                // default 640x360 and shrunk by CSS draws the video
                // zoomed and cut off.
                width: "100%",
                height: "100%",
                videoId: videoId,
                playerVars: {
                    playsinline: 1,
                    rel: 0
                },
                events: {
                    onReady: function () {
                        const data = player.getVideoData() || {};
                        if (data.title) {
                            titleEl.textContent = data.title;
                        }
                        resolve();
                    },
                    onStateChange: function (event) {
                        if (
                            event.data === YT.PlayerState.ENDED &&
                            liveId &&
                            framesDone > 0
                        ) {
                            finish();
                        }
                    }
                }
            });
        };

        const script = document.createElement("script");
        script.src = "https://www.youtube.com/iframe_api";
        document.head.appendChild(script);
    });


    // ------------------------------------------------------------
    // Server session
    // ------------------------------------------------------------

    async function startLive() {

        const body = new FormData();

        const data = player.getVideoData() || {};

        body.append("url", sourceUrl);
        body.append("title", data.title || "");
        body.append("duration", String(player.getDuration() || 0));

        // Guests' saved faces live in this browser; send them along so
        // they're recognised (used for this analysis only).
        if (
            !window.FACETALLY_AUTHENTICATED &&
            window.FaceTallyGuest
        ) {
            try {
                const faces = await window.FaceTallyGuest.getGuestFaces();

                for (const face of faces) {
                    body.append("guest_known", face.blob, face.filename || `${face.name}.jpg`);
                    body.append("guest_name", face.name);
                }
            } catch (error) {
                console.warn("Couldn't read guest faces:", error);
            }
        }

        const response = await fetch("/live/start", {
            method: "POST",
            body: body,
            credentials: "same-origin"
        });

        const result = await response.json().catch(function () {
            return {};
        });

        if (!response.ok || !result.ok) {
            throw new Error(result.error || "Couldn't start the analysis.");
        }

        liveId = result.id;
    }


    // ------------------------------------------------------------
    // Tab capture
    // ------------------------------------------------------------

    function stopSharing() {

        clearInterval(timer);
        timer = null;

        if (stream) {
            stream.getTracks().forEach(function (track) {
                track.stop();
            });
        }

        stream = null;
        captureVideo = null;
    }


    function onSharingStopped() {

        stopSharing();

        if (finishing) {
            return;
        }

        startBtn.hidden = false;
        startBtn.disabled = false;
        startBtn.textContent = "● Resume analysing";

        setStatus(
            "Tab sharing stopped. Click Resume to continue, or Finish & save.",
            false
        );
    }


    async function startCapture() {

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getDisplayMedia
        ) {
            setStatus(
                "This browser can't share a tab. Use Chrome, Edge or Firefox on a computer.",
                true
            );
            return;
        }

        startBtn.disabled = true;

        await playerReady;

        try {

            stream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    displaySurface: "browser",
                    frameRate: { ideal: 10 }
                },
                audio: false,
                preferCurrentTab: true,
                selfBrowserSurface: "include",
                surfaceSwitching: "exclude",
                monitorTypeSurfaces: "exclude"
            });

        } catch (error) {

            startBtn.disabled = false;

            setStatus(
                "Sharing was cancelled. Click Start and choose this tab.",
                true
            );

            return;
        }

        const track = stream.getVideoTracks()[0];
        const surface = (track.getSettings() || {}).displaySurface;

        if (surface && surface !== "browser") {

            stopSharing();
            startBtn.disabled = false;

            setStatus(
                "Please share this browser tab, not a window or the whole screen.",
                true
            );

            return;
        }

        // The whole tab is captured and the player is cut out of each
        // frame (see captureFrame). Chrome's Region Capture (cropTo) is
        // deliberately not used: it makes Chrome lay out YouTube's
        // cross-origin player at double size, so the video shows zoomed
        // in and cut off, for the viewer as well as the analysis.
        manualCrop = true;

        track.addEventListener("ended", onSharingStopped);

        captureVideo = document.createElement("video");
        captureVideo.muted = true;
        captureVideo.playsInline = true;
        captureVideo.srcObject = stream;

        await captureVideo.play();

        try {
            if (!liveId) {
                setStatus("Starting…", false);
                await startLive();
            }
        } catch (error) {
            stopSharing();
            startBtn.disabled = false;
            setStatus(error.message, true);
            return;
        }

        startBtn.hidden = true;

        nextSample = player.getCurrentTime() || 0;
        lastTime = -1;

        stage.scrollIntoView({ behavior: "smooth", block: "center" });

        player.playVideo();

        setStatus("Analysing… keep the video visible.", false);

        timer = setInterval(tick, 100);
    }


    function tick() {

        if (!captureVideo || busy || finishing || !player) {
            return;
        }

        if (document.hidden) {
            setStatus("Paused: keep this tab visible while it analyses.", false);
            return;
        }

        if (player.getPlayerState() !== YT.PlayerState.PLAYING) {
            return;
        }

        const time = player.getCurrentTime();

        // Skipped backwards: sample again from the new position.
        if (lastTime >= 0 && time + SAMPLE_SECONDS < lastTime) {
            nextSample = time;
        }

        if (time < nextSample) {
            return;
        }

        lastTime = time;
        nextSample = time + SAMPLE_SECONDS;

        captureFrame(time);
    }


    async function captureFrame(time) {

        busy = true;

        try {

            const width = captureVideo.videoWidth;
            const height = captureVideo.videoHeight;

            if (!width || !height) {
                return;
            }

            let sx = 0;
            let sy = 0;
            let sw = width;
            let sh = height;

            if (manualCrop) {

                // The capture is the whole tab: cut out the player.
                const rect = stage.getBoundingClientRect();
                const scale = width / window.innerWidth;

                sx = Math.max(0, rect.left * scale);
                sy = Math.max(0, rect.top * scale);
                sw = Math.min(width - sx, rect.width * scale);
                sh = Math.min(height - sy, rect.height * scale);

                if (sw < 50 || sh < 50) {
                    setStatus("Scroll so the whole video is visible.", false);
                    return;
                }
            }

            // Recorded for troubleshooting capture problems.
            app.dataset.capture =
                `${manualCrop ? "manual" : "region"} ${width}x${height} ` +
                `crop ${Math.round(sx)},${Math.round(sy)} ${Math.round(sw)}x${Math.round(sh)} ` +
                `viewport ${window.innerWidth}x${window.innerHeight} dpr ${window.devicePixelRatio}`;

            const shrink = Math.min(1, MAX_FRAME_WIDTH / sw);

            canvas.width = Math.round(sw * shrink);
            canvas.height = Math.round(sh * shrink);

            canvas
                .getContext("2d")
                .drawImage(captureVideo, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

            const blob = await new Promise(function (resolve) {
                canvas.toBlob(resolve, "image/jpeg", 0.85);
            });

            if (!blob || !liveId) {
                return;
            }

            const body = new FormData();
            body.append("frame", blob, "frame.jpg");
            body.append("t", time.toFixed(3));

            const response = await fetch(`/live/${liveId}/frame`, {
                method: "POST",
                body: body,
                credentials: "same-origin"
            });

            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.ok) {

                if (response.status === 404) {
                    liveId = null;
                    framesDone = 0;
                    stopSharing();
                    startBtn.hidden = false;
                    startBtn.disabled = false;
                    startBtn.textContent = "● Start again";
                }

                setStatus(data.error || "A frame couldn't be analysed.", true);
                return;
            }

            render(data, time);

        } catch (error) {

            console.warn("Frame capture failed:", error);

        } finally {

            busy = false;
        }
    }


    function render(data, time) {

        framesDone = data.frames;
        finishBtn.disabled = framesDone === 0;

        const people = data.people || [];

        setStatus(
            `Analysing… ${framesDone} frame${framesDone === 1 ? "" : "s"} · ` +
            `at ${formatClock(time)} · ` +
            `${people.length} ${people.length === 1 ? "person" : "people"} so far`,
            false
        );

        nowEl.textContent = (data.on_screen || []).length
            ? `On screen at ${formatClock(time)}: ${data.on_screen.join(", ")}`
            : `At ${formatClock(time)}: no faces detected`;

        peopleEl.innerHTML = "";

        people.forEach(function (person) {

            const chip = document.createElement("div");
            chip.className = "chip" + (person.is_known ? " chip-known" : "");
            chip.textContent = `${person.label} · ${person.count}`;

            if ((data.on_screen || []).includes(person.label)) {
                chip.classList.add("chip-now");
            }

            peopleEl.appendChild(chip);
        });
    }


    // ------------------------------------------------------------
    // Finish and save
    // ------------------------------------------------------------

    async function finish() {

        if (finishing || !liveId) {
            return;
        }

        finishing = true;

        finishBtn.disabled = true;
        startBtn.disabled = true;

        clearInterval(timer);

        // Let an in-flight frame finish first.
        while (busy) {
            await new Promise(function (resolve) {
                setTimeout(resolve, 100);
            });
        }

        stopSharing();

        if (player && typeof player.pauseVideo === "function") {
            player.pauseVideo();
        }

        setStatus("Saving…", false);

        try {

            const response = await fetch(`/live/${liveId}/finish`, {
                method: "POST",
                credentials: "same-origin"
            });

            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.ok) {
                throw new Error(data.error || "Couldn't save the analysis.");
            }

            liveId = null;
            window.location.href = data.redirect;

        } catch (error) {

            finishing = false;
            finishBtn.disabled = framesDone === 0;
            startBtn.hidden = false;
            startBtn.disabled = false;
            startBtn.textContent = "● Resume analysing";

            setStatus(error.message, true);
        }
    }


    startBtn.addEventListener("click", startCapture);
    finishBtn.addEventListener("click", finish);


    // Warn before leaving with unsaved progress.
    window.addEventListener("beforeunload", function (event) {
        if (liveId && framesDone > 0 && !finishing) {
            event.preventDefault();
            event.returnValue = "";
        }
    });
})();
