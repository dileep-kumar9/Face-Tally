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

})();