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
    // CAMERA CAPTURE (photo / video)
    // ============================================================
    // Each capture button opens its own hidden input with the
    // `capture` attribute, which is what actually launches the
    // device camera on mobile instead of the general file picker.
    // Whatever gets captured is funneled into the same media-input
    // used everywhere else, so the existing change handler above
    // (filename display, clearing the URL field) just runs normally
    // and the backend still only ever sees one "media" field.

    function routeCapturedFileIntoMediaInput(file) {

        if (!file || !mediaInput) {
            return;
        }

        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        mediaInput.files = dataTransfer.files;

        mediaInput.dispatchEvent(
            new Event("change", { bubbles: true })
        );
    }

    function wireCaptureButton(buttonId, inputId) {

        const button = document.getElementById(buttonId);
        const input = document.getElementById(inputId);

        if (!button || !input) {
            return;
        }

        button.addEventListener("click", () => input.click());

        input.addEventListener("change", () => {
            const file = input.files && input.files[0];
            routeCapturedFileIntoMediaInput(file);
        });
    }

    wireCaptureButton("capture-photo-btn", "camera-photo-input");
    wireCaptureButton("capture-video-btn", "camera-video-input");


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

        video.currentTime = start;
        video.play().catch(() => {});

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

})();