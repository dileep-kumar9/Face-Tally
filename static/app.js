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


    const knownCameraInput =
        document.getElementById(
            "known-camera-input"
        );

    if (knownCameraInput && knownPhotoInput) {

        knownCameraInput.addEventListener(
            "change",
            () => {

                const file =
                    knownCameraInput.files &&
                    knownCameraInput.files[0];

                if (!file) {
                    return;
                }

                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);
                knownPhotoInput.files = dataTransfer.files;

                knownPhotoInput.dispatchEvent(
                    new Event("change", { bubbles: true })
                );

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