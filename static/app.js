(function () {
    "use strict";

    // ============================================================
    // ELEMENTS
    // ============================================================

    const dropzone =
        document.getElementById("dropzone");

    const mediaInput =
        document.getElementById("media-input");

    const filenameEl =
        document.getElementById(
            "dropzone-filename"
        );

    const urlInput =
        document.getElementById("media-url");

    const form =
        document.getElementById("analyze-form");

    const analyzeBtn =
        document.getElementById("analyze-btn");


    // ============================================================
    // FILE DISPLAY
    // ============================================================

    function showSelectedFile(file) {

        if (!filenameEl || !file) {
            return;
        }

        const sizeMB =
            file.size /
            (1024 * 1024);

        filenameEl.textContent =
            `✓ ${file.name} · ${sizeMB.toFixed(2)} MB`;
    }


    function clearSelectedFile() {

        if (filenameEl) {
            filenameEl.textContent = "";
        }
    }


    // ============================================================
    // NORMAL FILE SELECTION
    // ============================================================

    if (mediaInput) {

        mediaInput.addEventListener(
            "change",
            () => {

                const file =
                    mediaInput.files &&
                    mediaInput.files[0];

                if (!file) {

                    clearSelectedFile();

                    return;
                }

                showSelectedFile(file);


                // Local file is the selected source,
                // therefore clear URL.

                if (urlInput) {
                    urlInput.value = "";
                }

            }
        );

    }


    // ============================================================
    // URL INPUT
    // ============================================================

    if (urlInput) {

        urlInput.addEventListener(
            "input",
            () => {

                if (
                    urlInput.value.trim()
                ) {

                    if (mediaInput) {
                        mediaInput.value = "";
                    }

                    clearSelectedFile();

                }

            }
        );

    }


    // ============================================================
    // DRAG ENTER / DRAG OVER
    // ============================================================

    [
        "dragenter",
        "dragover"
    ].forEach(
        (eventName) => {

            if (!dropzone) {
                return;
            }

            dropzone.addEventListener(
                eventName,
                (event) => {

                    event.preventDefault();
                    event.stopPropagation();

                    dropzone.classList.add(
                        "drag-over"
                    );

                }
            );

        }
    );


    // ============================================================
    // DRAG LEAVE / DROP
    // ============================================================

    [
        "dragleave",
        "drop"
    ].forEach(
        (eventName) => {

            if (!dropzone) {
                return;
            }

            dropzone.addEventListener(
                eventName,
                (event) => {

                    event.preventDefault();
                    event.stopPropagation();

                    dropzone.classList.remove(
                        "drag-over"
                    );

                }
            );

        }
    );


    // ============================================================
    // DROP FILE
    // ============================================================

    if (dropzone) {

        dropzone.addEventListener(
            "drop",
            (event) => {

                const files =
                    event.dataTransfer &&
                    event.dataTransfer.files;

                const file =
                    files &&
                    files[0];

                if (
                    !file ||
                    !mediaInput
                ) {
                    return;
                }


                try {

                    mediaInput.files =
                        files;

                } catch (error) {

                    console.warn(
                        "Could not assign dropped files:",
                        error
                    );

                }


                showSelectedFile(file);


                if (urlInput) {
                    urlInput.value = "";
                }

            }
        );

    }


    // ============================================================
    // KNOWN PERSON PHOTO
    // ============================================================

    const knownPhotoInput =
        document.querySelector(
            '.add-known-form input[name="photo"]'
        );


    if (knownPhotoInput) {

        const fileButton =
            knownPhotoInput.closest(
                ".file-btn"
            );


        knownPhotoInput.addEventListener(
            "change",
            () => {

                const file =
                    knownPhotoInput.files &&
                    knownPhotoInput.files[0];

                if (!file) {
                    return;
                }


                if (fileButton) {

                    fileButton.classList.add(
                        "file-selected"
                    );


                    const textNode =
                        Array.from(
                            fileButton.childNodes
                        ).find(
                            (node) =>
                                node.nodeType ===
                                    Node.TEXT_NODE &&
                                node.textContent.trim()
                        );


                    if (textNode) {

                        textNode.textContent =
                            `✓ ${file.name} `;

                    }

                }

            }
        );

    }


    // ============================================================
    // IN-PAGE CAMERA (for Known People)
    // ============================================================
    // The HTML `capture` attribute on a file input is only a hint, and
    // is documented as inconsistent across Android versions/browsers -
    // sometimes it opens the camera app directly, sometimes it silently
    // falls back to the plain file picker with no way to tell which will
    // happen ahead of time. Using getUserMedia() instead gives a camera
    // view fully under this page's own control, which doesn't depend on
    // the OS file-picker/camera-app handoff working correctly at all.

    const cameraBtn = document.getElementById("known-camera-btn");
    const cameraModal = document.getElementById("camera-modal");
    const cameraPreview = document.getElementById("camera-preview");
    const cameraCanvas = document.getElementById("camera-canvas");
    const cameraShootBtn = document.getElementById("camera-shoot-btn");
    const cameraCancelBtn = document.getElementById("camera-cancel-btn");
    const cameraStatus = document.getElementById("camera-modal-status");

    let cameraStream = null;

    function stopCameraStream() {
        if (cameraStream) {
            cameraStream.getTracks().forEach((track) => track.stop());
            cameraStream = null;
        }
        if (cameraPreview) cameraPreview.srcObject = null;
    }

    function closeCameraModal() {
        stopCameraStream();
        if (cameraModal) cameraModal.hidden = true;
        if (cameraStatus) cameraStatus.textContent = "";
    }

    async function openCameraModal() {

        if (!cameraModal || !cameraPreview) return;

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            if (cameraStatus) {
                cameraStatus.textContent =
                    "Camera access isn't available in this browser. " +
                    "Use \u201cChoose reference photo\u201d instead.";
            }
            cameraModal.hidden = false;
            return;
        }

        cameraModal.hidden = false;
        if (cameraStatus) cameraStatus.textContent = "Requesting camera access\u2026";

        try {
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "user" },
                audio: false,
            });
            cameraPreview.srcObject = cameraStream;
            if (cameraStatus) cameraStatus.textContent = "";
        } catch (error) {
            if (cameraStatus) {
                cameraStatus.textContent =
                    "Couldn't access the camera (permission denied, or " +
                    "none available). Use \u201cChoose reference photo\u201d instead.";
            }
        }
    }

    function takePhotoFromCamera() {

        if (!cameraPreview || !cameraPreview.videoWidth || !knownPhotoInput) return;

        cameraCanvas.width = cameraPreview.videoWidth;
        cameraCanvas.height = cameraPreview.videoHeight;

        const context = cameraCanvas.getContext("2d");
        context.drawImage(cameraPreview, 0, 0);

        cameraCanvas.toBlob((blob) => {

            if (!blob) return;

            const file = new File(
                [blob],
                "camera-photo.jpg",
                { type: "image/jpeg" }
            );

            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            knownPhotoInput.files = dataTransfer.files;

            knownPhotoInput.dispatchEvent(
                new Event("change", { bubbles: true })
            );

            closeCameraModal();

        }, "image/jpeg", 0.9);
    }

    if (cameraBtn) {
        cameraBtn.addEventListener("click", openCameraModal);
    }

    if (cameraShootBtn) {
        cameraShootBtn.addEventListener("click", takePhotoFromCamera);
    }

    if (cameraCancelBtn) {
        cameraCancelBtn.addEventListener("click", closeCameraModal);
    }

    // Never leave the camera light on if the user navigates away mid-capture.
    window.addEventListener("beforeunload", stopCameraStream);


    // ============================================================
    // FORM SUBMISSION
    // ============================================================

    if (form) {

        form.addEventListener(
            "submit",
            (event) => {

                const hasFile =
                    mediaInput &&
                    mediaInput.files &&
                    mediaInput.files.length > 0;


                const hasUrl =
                    urlInput &&
                    urlInput.value.trim().length > 0;


                if (
                    !hasFile &&
                    !hasUrl
                ) {

                    event.preventDefault();

                    return;

                }


                if (analyzeBtn) {

                    analyzeBtn.textContent =
                        "⏳ Analyzing…";

                    analyzeBtn.disabled = true;

                }

            }
        );

    }


    // ============================================================
    // SERVICE WORKER
    // ============================================================

    if (
        "serviceWorker" in navigator
    ) {

        window.addEventListener(
            "load",
            () => {

                navigator.serviceWorker
                    .register(
                        "/static/sw.js"
                    )
                    .catch(
                        (error) => {

                            console.warn(
                                "Service worker registration failed:",
                                error
                            );

                        }
                    );

            }
        );

    }

    // ========================================================
    // TIMELINE CLICK-TO-SEEK
    // ========================================================
    // Clicking (or Enter/Space-ing) a timeline entry jumps the result
    // video to that timestamp and plays from there. Delegated on
    // document since the result card is re-rendered on every analysis.

    function seekToTimelineItem(item) {

        const video = document.getElementById("result-video");
        if (!video) return;

        const start = parseFloat(item.dataset.start);
        if (Number.isNaN(start)) return;

        video.pause();
        video.currentTime = start;

        video.scrollIntoView({
            behavior: "smooth",
            block: "center",
        });
    }

    document.addEventListener("click", (event) => {
        const item = event.target.closest(".timeline-item.clickable");
        if (item) seekToTimelineItem(item);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const item = event.target.closest &&
            event.target.closest(".timeline-item.clickable");
        if (!item) return;
        event.preventDefault();
        seekToTimelineItem(item);
    });


    // ========================================================
    // SAVE AN UNKNOWN PERSON AS KNOWN
    // ========================================================
    // Each unknown person's card has its own reveal-a-name-field flow.
    // Saving posts the thumbnail already generated during analysis (no
    // new photo needed) and, on success, updates that card in place -
    // the current result stays on screen instead of being lost to a
    // redirect.

    document.querySelectorAll(".save-unknown").forEach((container) => {

        const openBtn = container.querySelector(".save-unknown-btn");
        const cancelBtn = container.querySelector(".save-unknown-cancel");
        const confirmBtn = container.querySelector(".save-unknown-confirm");
        const nameInput = container.querySelector(".save-unknown-name");
        const thumbInput = container.querySelector(".save-unknown-thumb");
        const status = container.querySelector(".save-unknown-status");
        const card = container.closest(".person-card");

        if (!openBtn || !confirmBtn || !nameInput || !thumbInput) return;

        openBtn.addEventListener("click", () => {
            container.classList.add("open");
            nameInput.focus();
        });

        if (cancelBtn) {
            cancelBtn.addEventListener("click", () => {
                container.classList.remove("open");
                nameInput.value = "";
                if (status) status.textContent = "";
            });
        }

        nameInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                confirmBtn.click();
            }
        });

        confirmBtn.addEventListener("click", async () => {

            const name = nameInput.value.trim();

            if (!name) {
                if (status) status.textContent = "Enter a name first.";
                return;
            }

            confirmBtn.disabled = true;
            if (status) status.textContent = "Saving\u2026";

            try {

                const body = new URLSearchParams();
                body.set("name", name);
                body.set("thumb", thumbInput.value);

                const response = await fetch("/save_unknown", {
                    method: "POST",
                    body,
                });

                const data = await response.json();

                if (data.ok) {

                    if (card) {

                        card.classList.remove("unknown");

                        const label = card.querySelector(".person-name");

                        if (label) {

                            label.classList.remove("unknown-label");

                            const nameNode = Array.from(label.childNodes).find(
                                (node) => node.nodeType === Node.TEXT_NODE &&
                                    node.textContent.trim()
                            );
                            if (nameNode) nameNode.textContent = `${data.name} `;

                            const tag = label.querySelector(".tag-unknown, .tag-known");
                            if (tag) {
                                tag.textContent = "Known";
                                tag.classList.remove("tag-unknown");
                                tag.classList.add("tag-known");
                            }
                        }
                    }

                    container.remove();

                } else {

                    if (status) status.textContent = data.error || "Couldn't save that.";
                    confirmBtn.disabled = false;

                }

            } catch (error) {

                if (status) status.textContent = "Network error - try again.";
                confirmBtn.disabled = false;

            }

        });

    });

})();