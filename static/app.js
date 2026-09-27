(function () {
    "use strict";

    // ============================================================
    // AUTHENTICATION STATE
    // ============================================================

    const body = document.body;

    window.FACETALLY_AUTHENTICATED =
        body?.dataset?.authenticated === "true";


    // ============================================================
    // ELEMENTS
    // ============================================================

    const dropzone =
        document.getElementById("dropzone");

    const mediaInput =
        document.getElementById("media-input");

    const filenameEl =
        document.getElementById("dropzone-filename");

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
            file.size / (1024 * 1024);

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
            function () {
                const file =
                    mediaInput.files &&
                    mediaInput.files[0];

                if (!file) {
                    clearSelectedFile();
                    return;
                }

                showSelectedFile(file);

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
            function () {
                if (urlInput.value.trim()) {

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

    ["dragenter", "dragover"].forEach(
        function (eventName) {

            if (!dropzone) {
                return;
            }

            dropzone.addEventListener(
                eventName,
                function (event) {

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

    ["dragleave", "drop"].forEach(
        function (eventName) {

            if (!dropzone) {
                return;
            }

            dropzone.addEventListener(
                eventName,
                function (event) {

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
            function (event) {

                const files =
                    event.dataTransfer &&
                    event.dataTransfer.files;

                const file =
                    files && files[0];

                if (!file || !mediaInput) {
                    return;
                }

                try {
                    mediaInput.files = files;
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
            function () {

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
                            function (node) {
                                return (
                                    node.nodeType ===
                                    Node.TEXT_NODE &&
                                    node.textContent.trim()
                                );
                            }
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
    // CAMERA / RECORDER
    // ============================================================

    const cameraModal =
        document.getElementById("camera-modal");

    const cameraPreview =
        document.getElementById("camera-preview");

    const cameraCanvas =
        document.getElementById("camera-canvas");

    const cameraShootBtn =
        document.getElementById("camera-shoot-btn");

    const cameraRecordBtn =
        document.getElementById("camera-record-btn");

    const cameraCancelBtn =
        document.getElementById("camera-cancel-btn");

    const cameraStatus =
        document.getElementById("camera-modal-status");

    const cameraTimer =
        document.getElementById("camera-modal-timer");


    let cameraStream = null;
    let mediaRecorder = null;
    let recordedChunks = [];

    let recordTimerInterval = null;
    let recordElapsedSeconds = 0;

    let cameraTargetInput = null;
    let cameraMode = "photo";
    let cameraAutoStopSeconds = null;


    function stopCameraStream() {

        if (cameraStream) {

            cameraStream
                .getTracks()
                .forEach(function (track) {
                    track.stop();
                });

            cameraStream = null;
        }

        if (cameraPreview) {
            cameraPreview.srcObject = null;
        }
    }


    function pickSupportedRecordingMimeType() {

        const candidates = [
            "video/mp4",
            "video/webm;codecs=vp9",
            "video/webm;codecs=vp8",
            "video/webm"
        ];

        if (
            !window.MediaRecorder ||
            !MediaRecorder.isTypeSupported
        ) {
            return "";
        }

        for (const type of candidates) {

            if (
                MediaRecorder.isTypeSupported(type)
            ) {
                return type;
            }
        }

        return "";
    }


    function formatElapsed(totalSeconds) {

        const minutes =
            Math.floor(totalSeconds / 60);

        const seconds =
            totalSeconds % 60;

        return (
            `${minutes}:` +
            String(seconds).padStart(2, "0")
        );
    }


    function resetCameraUI() {

        if (cameraShootBtn) {
            cameraShootBtn.hidden =
                cameraMode !== "photo";
        }

        const isAutoRecord =
            cameraMode === "video" &&
            Boolean(cameraAutoStopSeconds);

        if (cameraRecordBtn) {

            cameraRecordBtn.hidden =
                cameraMode !== "video" ||
                isAutoRecord;

            cameraRecordBtn.textContent =
                "Start recording";

            cameraRecordBtn.classList.remove(
                "recording"
            );
        }

        if (cameraTimer) {
            cameraTimer.textContent = "";
        }

        clearInterval(recordTimerInterval);

        recordTimerInterval = null;
        recordElapsedSeconds = 0;
    }


    function closeCameraModal() {

        if (
            mediaRecorder &&
            mediaRecorder.state !== "inactive"
        ) {
            try {
                mediaRecorder.stop();
            } catch (error) {
                console.warn(
                    "Could not stop recorder:",
                    error
                );
            }
        }

        mediaRecorder = null;

        stopCameraStream();

        if (cameraModal) {
            cameraModal.hidden = true;
        }

        if (cameraStatus) {
            cameraStatus.textContent = "";
        }

        resetCameraUI();
    }


    function funnelFileInto(input, file) {

        if (!input || !file) {
            return;
        }

        try {

            const dataTransfer =
                new DataTransfer();

            dataTransfer.items.add(file);

            input.files =
                dataTransfer.files;

            input.dispatchEvent(
                new Event(
                    "change",
                    { bubbles: true }
                )
            );

        } catch (error) {

            console.error(
                "Could not place camera file into input:",
                error
            );
        }
    }


    function takePhoto() {

        if (
            !cameraPreview ||
            !cameraCanvas ||
            !cameraPreview.videoWidth ||
            !cameraTargetInput
        ) {
            return;
        }

        cameraCanvas.width =
            cameraPreview.videoWidth;

        cameraCanvas.height =
            cameraPreview.videoHeight;

        const context =
            cameraCanvas.getContext("2d");

        if (!context) {
            return;
        }

        context.drawImage(
            cameraPreview,
            0,
            0,
            cameraCanvas.width,
            cameraCanvas.height
        );

        cameraCanvas.toBlob(
            function (blob) {

                if (!blob) {
                    return;
                }

                const file =
                    new File(
                        [blob],
                        "camera-photo.jpg",
                        {
                            type: "image/jpeg"
                        }
                    );

                funnelFileInto(
                    cameraTargetInput,
                    file
                );

                closeCameraModal();
            },
            "image/jpeg",
            0.9
        );
    }


    function startRecording() {

        if (
            !cameraStream ||
            !cameraTargetInput
        ) {
            return;
        }

        if (!window.MediaRecorder) {

            if (cameraStatus) {
                cameraStatus.textContent =
                    "Recording isn't supported in this browser.";
            }

            return;
        }

        recordedChunks = [];

        const mimeType =
            pickSupportedRecordingMimeType();

        try {

            mediaRecorder =
                mimeType
                    ? new MediaRecorder(
                        cameraStream,
                        { mimeType: mimeType }
                    )
                    : new MediaRecorder(
                        cameraStream
                    );

        } catch (error) {

            console.error(error);

            if (cameraStatus) {
                cameraStatus.textContent =
                    "Recording isn't supported in this browser.";
            }

            return;
        }


        mediaRecorder.ondataavailable =
            function (event) {

                if (
                    event.data &&
                    event.data.size > 0
                ) {
                    recordedChunks.push(
                        event.data
                    );
                }
            };


        mediaRecorder.onstop =
            function () {

                const type =
                    mediaRecorder.mimeType ||
                    mimeType ||
                    "video/webm";

                const blob =
                    new Blob(
                        recordedChunks,
                        { type: type }
                    );

                const extension =
                    type.includes("mp4")
                        ? "mp4"
                        : "webm";

                const file =
                    new File(
                        [blob],
                        `camera-recording.${extension}`,
                        { type: type }
                    );

                funnelFileInto(
                    cameraTargetInput,
                    file
                );

                mediaRecorder = null;

                closeCameraModal();
            };


        mediaRecorder.start();


        if (cameraRecordBtn) {

            cameraRecordBtn.textContent =
                "Stop recording";

            cameraRecordBtn.classList.add(
                "recording"
            );
        }


        recordElapsedSeconds = 0;

        if (cameraTimer) {
            cameraTimer.textContent =
                formatElapsed(0);
        }


        clearInterval(
            recordTimerInterval
        );

        recordTimerInterval =
            setInterval(
                function () {

                    recordElapsedSeconds += 1;

                    if (cameraTimer) {
                        cameraTimer.textContent =
                            formatElapsed(
                                recordElapsedSeconds
                            );
                    }

                    if (
                        cameraAutoStopSeconds &&
                        recordElapsedSeconds >=
                        cameraAutoStopSeconds
                    ) {
                        stopRecording();
                    }

                },
                1000
            );
    }


    function stopRecording() {

        clearInterval(
            recordTimerInterval
        );

        recordTimerInterval = null;

        if (
            mediaRecorder &&
            mediaRecorder.state !== "inactive"
        ) {
            try {
                mediaRecorder.stop();
            } catch (error) {
                console.warn(
                    "Could not stop recording:",
                    error
                );
            }
        }
    }


    function toggleRecording() {

        if (
            mediaRecorder &&
            mediaRecorder.state === "recording"
        ) {
            stopRecording();
        } else {
            startRecording();
        }
    }


    async function openCamera(
        targetInput,
        mode,
        autoStopSeconds
    ) {

        if (
            !cameraModal ||
            !cameraPreview ||
            !targetInput
        ) {
            return;
        }

        cameraTargetInput =
            targetInput;

        cameraMode =
            mode;

        cameraAutoStopSeconds =
            autoStopSeconds || null;

        resetCameraUI();

        cameraModal.hidden = false;


        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {

            if (cameraStatus) {
                cameraStatus.textContent =
                    "Camera access isn't available in this browser. " +
                    "Use the file picker instead.";
            }

            return;
        }


        if (cameraStatus) {
            cameraStatus.textContent =
                "Requesting camera access…";
        }


        try {

            cameraStream =
                await navigator.mediaDevices.getUserMedia(
                    {
                        video: {
                            facingMode: "user"
                        },
                        audio:
                            mode === "video"
                    }
                );


            cameraPreview.srcObject =
                cameraStream;


            if (cameraStatus) {
                cameraStatus.textContent = "";
            }


            if (
                mode === "video" &&
                cameraAutoStopSeconds
            ) {
                startRecording();
            }

        } catch (error) {

            console.error(
                "Camera error:",
                error
            );

            if (cameraStatus) {
                cameraStatus.textContent =
                    "Couldn't access the camera " +
                    "(permission denied, or none available). " +
                    "Use the file picker instead.";
            }
        }
    }


    if (cameraShootBtn) {
        cameraShootBtn.addEventListener(
            "click",
            takePhoto
        );
    }


    if (cameraRecordBtn) {
        cameraRecordBtn.addEventListener(
            "click",
            toggleRecording
        );
    }


    if (cameraCancelBtn) {
        cameraCancelBtn.addEventListener(
            "click",
            closeCameraModal
        );
    }


    window.addEventListener(
        "beforeunload",
        stopCameraStream
    );


    const knownCameraBtn =
        document.getElementById(
            "known-camera-btn"
        );

    const knownRecordBtn =
        document.getElementById(
            "known-record-btn"
        );

    const mediaCameraBtn =
        document.getElementById(
            "media-camera-btn"
        );

    const mediaRecordBtn =
        document.getElementById(
            "media-record-btn"
        );


    if (
        knownCameraBtn &&
        knownPhotoInput
    ) {

        knownCameraBtn.addEventListener(
            "click",
            function () {
                openCamera(
                    knownPhotoInput,
                    "photo"
                );
            }
        );
    }


    if (
        knownRecordBtn &&
        knownPhotoInput
    ) {

        knownRecordBtn.addEventListener(
            "click",
            function () {

                openCamera(
                    knownPhotoInput,
                    "video",
                    4
                );

            }
        );
    }


    if (
        mediaCameraBtn &&
        mediaInput
    ) {

        mediaCameraBtn.addEventListener(
            "click",
            function () {

                openCamera(
                    mediaInput,
                    "photo"
                );

            }
        );
    }


    if (
        mediaRecordBtn &&
        mediaInput
    ) {

        mediaRecordBtn.addEventListener(
            "click",
            function () {

                openCamera(
                    mediaInput,
                    "video"
                );

            }
        );
    }


    // ============================================================
    // GUEST FACE STORAGE
    // ============================================================

    const GUEST_DB_NAME =
        "facetally_guest_faces";

    const GUEST_STORE =
        "faces";


    function guestDb() {

        return new Promise(
            function (resolve, reject) {

                const request =
                    indexedDB.open(
                        GUEST_DB_NAME,
                        1
                    );


                request.onupgradeneeded =
                    function () {

                        const db =
                            request.result;

                        if (
                            !db.objectStoreNames.contains(
                                GUEST_STORE
                            )
                        ) {

                            db.createObjectStore(
                                GUEST_STORE,
                                {
                                    keyPath: "id",
                                    autoIncrement: true
                                }
                            );
                        }
                    };


                request.onsuccess =
                    function () {
                        resolve(
                            request.result
                        );
                    };


                request.onerror =
                    function () {
                        reject(
                            request.error
                        );
                    };
            }
        );
    }


    async function getGuestFaces() {

        const db =
            await guestDb();

        return new Promise(
            function (resolve, reject) {

                const transaction =
                    db.transaction(
                        GUEST_STORE,
                        "readonly"
                    );

                const request =
                    transaction
                        .objectStore(GUEST_STORE)
                        .getAll();


                request.onsuccess =
                    function () {
                        resolve(
                            request.result || []
                        );
                    };


                request.onerror =
                    function () {
                        reject(
                            request.error
                        );
                    };
            }
        );
    }


    async function putGuestFace(face) {

        const db =
            await guestDb();

        return new Promise(
            function (resolve, reject) {

                const transaction =
                    db.transaction(
                        GUEST_STORE,
                        "readwrite"
                    );

                const request =
                    transaction
                        .objectStore(GUEST_STORE)
                        .put(face);


                request.onsuccess =
                    function () {
                        resolve(
                            request.result
                        );
                    };


                request.onerror =
                    function () {
                        reject(
                            request.error
                        );
                    };
            }
        );
    }


    async function deleteGuestFace(id) {

        const db =
            await guestDb();

        return new Promise(
            function (resolve, reject) {

                const transaction =
                    db.transaction(
                        GUEST_STORE,
                        "readwrite"
                    );

                const request =
                    transaction
                        .objectStore(GUEST_STORE)
                        .delete(id);


                request.onsuccess =
                    function () {
                        resolve();
                    };


                request.onerror =
                    function () {
                        reject(
                            request.error
                        );
                    };
            }
        );
    }


    function guestAvatarUrl(blob) {
        return URL.createObjectURL(blob);
    }


    async function renderGuestKnownPeople() {

        const list =
            document.getElementById(
                "guest-known-list"
            );

        const summary =
            document.getElementById(
                "known-people-summary"
            );


        if (
            !list ||
            window.FACETALLY_AUTHENTICATED
        ) {
            return;
        }


        let faces = [];

        try {
            faces =
                await getGuestFaces();
        } catch (error) {
            console.warn(
                "Could not read guest faces:",
                error
            );
            return;
        }


        list.innerHTML = "";

        list.hidden =
            faces.length === 0;


        if (summary) {

            summary.textContent =
                `${faces.length} saved on this device — add or remove`;
        }


        for (const face of faces) {

            const chip =
                document.createElement("div");

            chip.className =
                "chip";


            const img =
                document.createElement("img");

            img.className =
                "chip-avatar";

            img.alt = "";

            img.src =
                guestAvatarUrl(face.blob);


            const name =
                document.createTextNode(
                    face.name
                );


            const remove =
                document.createElement("button");

            remove.type =
                "button";

            remove.title =
                "Remove";

            remove.textContent =
                "×";

            remove.dataset.guestFaceId =
                String(face.id);


            chip.append(
                img,
                name,
                remove
            );


            list.appendChild(chip);
        }
    }


    async function dataUrlToBlob(dataUrl) {

        const response =
            await fetch(dataUrl);

        return response.blob();
    }


    async function importGuestFaces() {

        if (
            !window.FACETALLY_AUTHENTICATED
        ) {
            return;
        }


        const faces =
            await getGuestFaces();


        if (!faces.length) {
            return;
        }


        const modal =
            document.getElementById(
                "guest-import-modal"
            );

        const status =
            document.getElementById(
                "guest-import-status"
            );

        const importButton =
            document.getElementById(
                "guest-import-btn"
            );

        const skipButton =
            document.getElementById(
                "guest-import-skip"
            );

        const countText =
            document.getElementById(
                "guest-import-count"
            );


        if (
            !modal ||
            !importButton ||
            !skipButton
        ) {
            return;
        }


        countText.textContent =
            `You have ${faces.length} temporary saved face` +
            `${faces.length === 1 ? "" : "s"} on this device.`;


        modal.hidden = false;


        skipButton.onclick =
            function () {
                modal.hidden = true;
            };


        importButton.onclick =
            async function () {

                importButton.disabled =
                    true;

                skipButton.disabled =
                    true;


                if (status) {

                    status.hidden =
                        false;

                    status.className =
                        "auth-status info";

                    status.textContent =
                        "Importing…";
                }


                try {

                    const formData =
                        new FormData();


                    for (const face of faces) {

                        formData.append(
                            "photos",
                            face.blob,
                            face.filename ||
                            `${face.name}.jpg`
                        );

                        formData.append(
                            "names",
                            face.name
                        );
                    }


                    const response =
                        await fetch(
                            "/import_known",
                            {
                                method: "POST",
                                body: formData,
                                credentials: "same-origin"
                            }
                        );


                    const data =
                        await response
                            .json()
                            .catch(
                                function () {
                                    return {};
                                }
                            );


                    if (
                        !response.ok ||
                        !data.ok
                    ) {
                        throw new Error(
                            data.error ||
                            "Import failed."
                        );
                    }


                    const imported =
                        new Set(
                            data.imported || []
                        );


                    for (
                        const face of faces
                    ) {

                        if (
                            imported.has(
                                face.name
                            )
                        ) {

                            await deleteGuestFace(
                                face.id
                            );
                        }
                    }


                    modal.hidden =
                        true;

                    window.location.reload();

                } catch (error) {

                    if (status) {

                        status.hidden =
                            false;

                        status.className =
                            "auth-status error";

                        status.textContent =
                            error.message ||
                            "Import failed. Try again.";
                    }


                    importButton.disabled =
                        false;

                    skipButton.disabled =
                        false;
                }
            };
    }


    // ============================================================
    // GUEST ADD
    // ============================================================

    const addKnownForm =
        document.querySelector(
            ".add-known-form"
        );


    if (
        addKnownForm &&
        !window.FACETALLY_AUTHENTICATED
    ) {

        addKnownForm.addEventListener(
            "submit",
            async function (event) {

                event.preventDefault();


                const nameInput =
                    addKnownForm.querySelector(
                        'input[name="name"]'
                    );

                const photoInput =
                    addKnownForm.querySelector(
                        'input[name="photo"]'
                    );


                const name =
                    nameInput?.value.trim() || "";

                const file =
                    photoInput?.files?.[0];


                if (!name || !file) {
                    return;
                }


                if (
                    file.type &&
                    !file.type.startsWith("image/")
                ) {

                    alert(
                        "For guest saved faces, please choose or take a photo."
                    );

                    return;
                }


                try {

                    await putGuestFace(
                        {
                            name: name,
                            filename:
                                file.name ||
                                `${name}.jpg`,
                            type:
                                file.type ||
                                "image/jpeg",
                            blob: file,
                            createdAt:
                                Date.now()
                        }
                    );


                    nameInput.value =
                        "";

                    photoInput.value =
                        "";


                    addKnownForm
                        .querySelectorAll(
                            ".file-selected"
                        )
                        .forEach(
                            function (element) {
                                element.classList.remove(
                                    "file-selected"
                                );
                            }
                        );


                    await renderGuestKnownPeople();

                } catch (error) {

                    console.error(
                        "Could not save guest face:",
                        error
                    );

                    alert(
                        "Could not save this face on the device."
                    );
                }
            }
        );
    }


    // ============================================================
    // GUEST REMOVE
    // ============================================================

    const guestKnownList =
        document.getElementById(
            "guest-known-list"
        );


    if (guestKnownList) {

        guestKnownList.addEventListener(
            "click",
            async function (event) {

                const button =
                    event.target.closest(
                        "button[data-guest-face-id]"
                    );

                if (!button) {
                    return;
                }


                try {

                    await deleteGuestFace(
                        Number(
                            button.dataset.guestFaceId
                        )
                    );

                    await renderGuestKnownPeople();

                } catch (error) {

                    console.error(
                        "Could not delete guest face:",
                        error
                    );
                }
            }
        );
    }


    if (
        !window.FACETALLY_AUTHENTICATED
    ) {

        renderGuestKnownPeople()
            .catch(console.warn);
    }


    // ============================================================
    // AUTH STATE CHANGE
    // ============================================================

    window.addEventListener(
        "facetally-auth-state",
        async function (event) {

            const user =
                event.detail?.user;


            if (
                user &&
                !user.isAnonymous
            ) {

                window.FACETALLY_AUTHENTICATED =
                    true;


                try {

                    await importGuestFaces();

                } catch (error) {

                    console.warn(
                        "Guest face import failed:",
                        error
                    );
                }
            }
        }
    );


    // ============================================================
    // FORM SUBMISSION
    // ============================================================

    if (form) {

        form.addEventListener(
            "submit",
            async function (event) {

                const hasFile =
                    mediaInput &&
                    mediaInput.files &&
                    mediaInput.files.length > 0;


                const hasUrl =
                    urlInput &&
                    urlInput.value.trim().length > 0;


                if (!hasFile && !hasUrl) {

                    event.preventDefault();

                    alert(
                        "Please choose a photo/video or enter a URL."
                    );

                    return;
                }


                if (analyzeBtn) {

                    analyzeBtn.textContent =
                        "⏳ Analyzing…";

                    analyzeBtn.disabled =
                        true;
                }


                // Logged-in users use the normal form submission.
                if (
                    window.FACETALLY_AUTHENTICATED
                ) {
                    return;
                }


                // ====================================================
                // GUEST ANALYSIS
                // ====================================================

                event.preventDefault();


                let faces = [];

                try {

                    faces =
                        await getGuestFaces();

                } catch (error) {

                    console.warn(
                        "Could not read guest faces; analyzing without them:",
                        error
                    );
                }


                // Guest faces are attached only to this request, as
                // hidden file inputs, so the browser does a normal
                // form navigation to the result page.
                form
                    .querySelectorAll(".guest-known-field")
                    .forEach(function (element) {
                        element.remove();
                    });


                if (faces.length) {

                    try {

                        const transfer =
                            new DataTransfer();

                        for (const face of faces) {

                            transfer.items.add(
                                new File(
                                    [face.blob],
                                    face.filename ||
                                    `${face.name}.jpg`,
                                    {
                                        type:
                                            face.type ||
                                            face.blob.type ||
                                            "image/jpeg"
                                    }
                                )
                            );

                            const nameField =
                                document.createElement("input");

                            nameField.type = "hidden";
                            nameField.name = "guest_name";
                            nameField.value = face.name;
                            nameField.className = "guest-known-field";

                            form.appendChild(nameField);
                        }

                        const fileField =
                            document.createElement("input");

                        fileField.type = "file";
                        fileField.name = "guest_known";
                        fileField.multiple = true;
                        fileField.hidden = true;
                        fileField.className = "guest-known-field";
                        fileField.files = transfer.files;

                        form.appendChild(fileField);

                    } catch (error) {

                        console.warn(
                            "This browser can't attach guest faces; analyzing without them:",
                            error
                        );

                        form
                            .querySelectorAll(".guest-known-field")
                            .forEach(function (element) {
                                element.remove();
                            });
                    }
                }


                // form.submit() does not fire the submit event again.
                form.submit();
            }
        );
    }


    // Reset the Analyze button when the page is restored from the
    // back/forward cache, otherwise it stays stuck on "Analyzing…".
    window.addEventListener(
        "pageshow",
        function (event) {

            if (event.persisted && analyzeBtn) {

                analyzeBtn.textContent =
                    "Analyze";

                analyzeBtn.disabled =
                    false;
            }
        }
    );


    // ============================================================
    // SERVICE WORKER
    // ============================================================

    if (
        "serviceWorker" in navigator
    ) {

        window.addEventListener(
            "load",
            function () {

                // Remove the old registration whose scope was only
                // /static/ and therefore never controlled any page.
                navigator.serviceWorker
                    .getRegistrations()
                    .then(function (registrations) {

                        registrations.forEach(
                            function (registration) {

                                if (
                                    new URL(registration.scope)
                                        .pathname
                                        .startsWith("/static/")
                                ) {
                                    registration.unregister();
                                }
                            }
                        );
                    })
                    .catch(function () {});


                navigator.serviceWorker
                    .register(
                        "/sw.js"
                    )
                    .catch(
                        function (error) {

                            console.warn(
                                "Service worker registration failed:",
                                error
                            );
                        }
                    );
            }
        );
    }


    // ============================================================
    // RESULT PLAYER
    // ============================================================
    //
    // The results and faces show first; "Open video" loads the player.
    // YouTube links play in YouTube's own embedded player, other links
    // from their original URL, uploads from the server copy. While it
    // plays, each person's timeline traces the current position.

    const playerPanel =
        document.getElementById("player-panel");

    const openVideoBtn =
        document.getElementById("open-video-btn");

    const youtubeHost =
        document.getElementById("yt-player");

    let resultVideo =
        document.getElementById("result-video");

    let youtubePlayer = null;
    let playerReady = null;
    let traceTimer = null;


    function formatClock(totalSeconds) {

        const seconds =
            Math.max(0, Math.floor(totalSeconds));

        const hours =
            Math.floor(seconds / 3600);

        const minutes =
            Math.floor((seconds % 3600) / 60);

        const rest =
            String(seconds % 60).padStart(2, "0");

        return hours
            ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}`
            : `${String(minutes).padStart(2, "0")}:${rest}`;
    }


    function loadYouTubePlayer() {

        return new Promise(function (resolve) {

            function create() {

                youtubePlayer =
                    new YT.Player(
                        "yt-player",
                        {
                            videoId:
                                youtubeHost.dataset.videoId,
                            playerVars: {
                                playsinline: 1,
                                rel: 0
                            },
                            events: {
                                onReady: function () {
                                    resolve();
                                }
                            }
                        }
                    );
            }

            if (window.YT && window.YT.Player) {
                create();
                return;
            }

            window.onYouTubeIframeAPIReady = create;

            const apiScript =
                document.createElement("script");

            apiScript.src =
                "https://www.youtube.com/iframe_api";

            document.head.appendChild(apiScript);
        });
    }


    function loadVideoElement() {

        return new Promise(function (resolve) {

            resultVideo.addEventListener(
                "loadedmetadata",
                function () {
                    resolve();
                },
                { once: true }
            );

            // If the browser can't play a linked video directly (e.g.
            // the host blocks it), use the provider's own player if
            // there is one, otherwise explain and offer the original.
            resultVideo.addEventListener(
                "error",
                function () {

                    const embedUrl =
                        resultVideo.dataset.fallbackEmbed;

                    if (embedUrl) {

                        const frame =
                            document.createElement("iframe");

                        frame.src = embedUrl;
                        frame.className = "result-embed";
                        frame.allow = "autoplay; fullscreen";
                        frame.allowFullscreen = true;

                        resultVideo.replaceWith(frame);
                        resultVideo = null;

                        // Drive's player can't be controlled from here.
                        document
                            .querySelectorAll(".timeline-item.clickable, .timeline-segment.clickable")
                            .forEach(function (element) {
                                element.classList.remove("clickable");
                                element.removeAttribute("role");
                                element.removeAttribute("tabindex");
                            });

                    } else {

                        const message =
                            document.getElementById("player-error");

                        if (message) {
                            message.hidden = false;
                        }
                    }

                    resolve();
                },
                { once: true }
            );

            resultVideo.src =
                resultVideo.dataset.src;
        });
    }


    function openPlayer() {

        if (!playerPanel) {
            return Promise.resolve(false);
        }

        if (!playerReady) {

            playerPanel.hidden = false;

            if (openVideoBtn) {
                openVideoBtn.textContent = "▶ Video open";
                openVideoBtn.disabled = true;
            }

            playerReady =
                (youtubeHost ? loadYouTubePlayer() : loadVideoElement())
                    .then(function () {
                        startTracing();
                        return true;
                    });
        }

        return playerReady;
    }


    function currentPlayerTime() {

        if (youtubePlayer && typeof youtubePlayer.getCurrentTime === "function") {
            return youtubePlayer.getCurrentTime() || 0;
        }

        if (resultVideo) {
            return resultVideo.currentTime || 0;
        }

        return null;
    }


    function seekTo(start) {

        openPlayer().then(function () {

            if (youtubePlayer && typeof youtubePlayer.seekTo === "function") {

                youtubePlayer.seekTo(start, true);
                youtubePlayer.playVideo();

            } else if (resultVideo) {

                resultVideo.currentTime = start;
                resultVideo.play().catch(function () {});

            } else {
                return;
            }

            traceAt(start);

            playerPanel.scrollIntoView(
                {
                    behavior: "smooth",
                    block: "center"
                }
            );
        });
    }


    // Highlight where the video is now: move each person's playhead,
    // light up the appearance being played, and mark who is on screen.
    function traceAt(time) {

        if (time === null || Number.isNaN(time)) {
            return;
        }

        const tolerance =
            Math.max(
                0.75,
                parseFloat(playerPanel.dataset.interval) || 0.5
            );

        const onScreen = [];

        document
            .querySelectorAll(".person-card")
            .forEach(function (card) {

                let active = false;

                card
                    .querySelectorAll(".timeline-item, .timeline-segment")
                    .forEach(function (element) {

                        const start = parseFloat(element.dataset.start);
                        const end = parseFloat(element.dataset.end);

                        const isNow =
                            time >= start - tolerance &&
                            time <= end + tolerance;

                        element.classList.toggle("now", isNow);

                        active = active || isNow;
                    });

                const track =
                    card.querySelector(".timeline-track");

                if (track) {

                    const duration =
                        parseFloat(track.dataset.duration) || 0;

                    const playhead =
                        track.querySelector(".timeline-playhead");

                    if (playhead && duration > 0) {
                        playhead.hidden = false;
                        playhead.style.left =
                            Math.min(100, (time / duration) * 100) + "%";
                    }
                }

                card.classList.toggle("on-screen", active);

                if (active) {
                    onScreen.push(card.dataset.label);
                }
            });

        const nowShowing =
            document.getElementById("now-showing");

        if (nowShowing) {
            nowShowing.textContent =
                onScreen.length
                    ? `On screen at ${formatClock(time)}: ${onScreen.join(", ")}`
                    : `At ${formatClock(time)}: no detected faces`;
        }
    }


    function startTracing() {

        clearInterval(traceTimer);

        traceTimer =
            setInterval(
                function () {
                    traceAt(currentPlayerTime());
                },
                250
            );
    }


    if (openVideoBtn) {
        openVideoBtn.addEventListener(
            "click",
            function () {

                openPlayer();

                playerPanel.scrollIntoView(
                    {
                        behavior: "smooth",
                        block: "center"
                    }
                );
            }
        );
    }


    // ============================================================
    // TIMELINE CLICK TO SEEK
    // ============================================================

    function seekToTimelineItem(item) {

        const start =
            parseFloat(
                item.dataset.start
            );

        if (!Number.isNaN(start)) {
            seekTo(start);
        }
    }


    document.addEventListener(
        "click",
        function (event) {

            const item =
                event.target.closest(
                    ".timeline-item.clickable, .timeline-segment.clickable"
                );

            if (item) {
                seekToTimelineItem(item);
            }
        }
    );


    document.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key !== "Enter" &&
                event.key !== " "
            ) {
                return;
            }

            const item =
                event.target.closest &&
                event.target.closest(
                    ".timeline-item.clickable"
                );

            if (!item) {
                return;
            }

            event.preventDefault();

            seekToTimelineItem(item);
        }
    );


    // ============================================================
    // SAVED ANALYSES: LOCAL DATES AND DELETE CONFIRMATION
    // ============================================================

    document
        .querySelectorAll("time[data-ts]")
        .forEach(function (element) {

            const date =
                new Date(parseFloat(element.dataset.ts) * 1000);

            if (!Number.isNaN(date.getTime())) {

                element.dateTime = date.toISOString();

                element.textContent =
                    date.toLocaleString(
                        undefined,
                        {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                            hour: "numeric",
                            minute: "2-digit"
                        }
                    );
            }
        });


    document
        .querySelectorAll("form[data-confirm]")
        .forEach(function (confirmForm) {

            confirmForm.addEventListener(
                "submit",
                function (event) {

                    if (!window.confirm(confirmForm.dataset.confirm)) {
                        event.preventDefault();
                    }
                }
            );
        });


    // ============================================================
    // SAVE UNKNOWN PERSON
    // ============================================================

    document
        .querySelectorAll(".save-unknown")
        .forEach(
            function (container) {

                const openBtn =
                    container.querySelector(
                        ".save-unknown-btn"
                    );

                const cancelBtn =
                    container.querySelector(
                        ".save-unknown-cancel"
                    );

                const confirmBtn =
                    container.querySelector(
                        ".save-unknown-confirm"
                    );

                const nameInput =
                    container.querySelector(
                        ".save-unknown-name"
                    );

                const thumbInput =
                    container.querySelector(
                        ".save-unknown-thumb"
                    );

                const status =
                    container.querySelector(
                        ".save-unknown-status"
                    );

                const card =
                    container.closest(
                        ".person-card"
                    );


                if (
                    !openBtn ||
                    !confirmBtn ||
                    !nameInput ||
                    !thumbInput
                ) {
                    return;
                }


                openBtn.addEventListener(
                    "click",
                    function () {

                        container.classList.add(
                            "open"
                        );

                        nameInput.focus();
                    }
                );


                if (cancelBtn) {

                    cancelBtn.addEventListener(
                        "click",
                        function () {

                            container.classList.remove(
                                "open"
                            );

                            nameInput.value =
                                "";

                            if (status) {
                                status.textContent =
                                    "";
                            }
                        }
                    );
                }


                nameInput.addEventListener(
                    "keydown",
                    function (event) {

                        if (
                            event.key === "Enter"
                        ) {

                            event.preventDefault();

                            confirmBtn.click();
                        }
                    }
                );


                confirmBtn.addEventListener(
                    "click",
                    async function () {

                        const name =
                            nameInput.value.trim();


                        if (!name) {

                            if (status) {
                                status.textContent =
                                    "Enter a name first.";
                            }

                            return;
                        }


                        confirmBtn.disabled =
                            true;


                        if (status) {
                            status.textContent =
                                "Saving…";
                        }


                        try {

                            // ========================================
                            // GUEST
                            // ========================================

                            if (
                                !window.FACETALLY_AUTHENTICATED
                            ) {

                                const blob =
                                    await dataUrlToBlob(
                                        "data:image/jpeg;base64," +
                                        thumbInput.value
                                    );


                                await putGuestFace(
                                    {
                                        name: name,
                                        filename:
                                            `${name}.jpg`,
                                        type:
                                            "image/jpeg",
                                        blob: blob,
                                        createdAt:
                                            Date.now()
                                    }
                                );


                                if (card) {

                                    card.classList.remove(
                                        "unknown"
                                    );


                                    const label =
                                        card.querySelector(
                                            ".person-name"
                                        );


                                    if (label) {

                                        label.classList.remove(
                                            "unknown-label"
                                        );


                                        const nameNode =
                                            Array.from(
                                                label.childNodes
                                            ).find(
                                                function (node) {
                                                    return (
                                                        node.nodeType ===
                                                        Node.TEXT_NODE &&
                                                        node.textContent.trim()
                                                    );
                                                }
                                            );


                                        if (nameNode) {
                                            nameNode.textContent =
                                                `${name} `;
                                        }


                                        const tag =
                                            label.querySelector(
                                                ".tag-unknown"
                                            );


                                        if (tag) {

                                            tag.textContent =
                                                "Known";

                                            tag.classList.remove(
                                                "tag-unknown"
                                            );

                                            tag.classList.add(
                                                "tag-known"
                                            );
                                        }
                                    }
                                }


                                container.remove();

                                await renderGuestKnownPeople();

                                return;
                            }


                            // ========================================
                            // AUTHENTICATED USER
                            // ========================================

                            const requestBody =
                                new URLSearchParams();


                            requestBody.set(
                                "name",
                                name
                            );


                            requestBody.set(
                                "thumb",
                                thumbInput.value
                            );


                            const response =
                                await fetch(
                                    "/save_unknown",
                                    {
                                        method: "POST",
                                        body: requestBody,
                                        credentials:
                                            "same-origin"
                                    }
                                );


                            const data =
                                await response
                                    .json();


                            if (data.ok) {

                                if (card) {

                                    card.classList.remove(
                                        "unknown"
                                    );


                                    const label =
                                        card.querySelector(
                                            ".person-name"
                                        );


                                    if (label) {

                                        label.classList.remove(
                                            "unknown-label"
                                        );


                                        const nameNode =
                                            Array.from(
                                                label.childNodes
                                            ).find(
                                                function (node) {
                                                    return (
                                                        node.nodeType ===
                                                        Node.TEXT_NODE &&
                                                        node.textContent.trim()
                                                    );
                                                }
                                            );


                                        if (nameNode) {
                                            nameNode.textContent =
                                                `${data.name} `;
                                        }


                                        const tag =
                                            label.querySelector(
                                                ".tag-unknown, .tag-known"
                                            );


                                        if (tag) {

                                            tag.textContent =
                                                "Known";

                                            tag.classList.remove(
                                                "tag-unknown"
                                            );

                                            tag.classList.add(
                                                "tag-known"
                                            );
                                        }
                                    }
                                }


                                container.remove();

                            } else {

                                if (status) {
                                    status.textContent =
                                        data.error ||
                                        "Couldn't save that.";
                                }

                                confirmBtn.disabled =
                                    false;
                            }

                        } catch (error) {

                            console.error(
                                "Save unknown error:",
                                error
                            );

                            if (status) {
                                status.textContent =
                                    "Network error - try again.";
                            }

                            confirmBtn.disabled =
                                false;
                        }
                    }
                );
            }
        );

})();