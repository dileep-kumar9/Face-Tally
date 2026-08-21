document.addEventListener("DOMContentLoaded", () => {

    const mediaInput =
        document.getElementById("media");

    const selectedFile =
        document.getElementById("selectedFile");

    const analyzeForm =
        document.getElementById("analyzeForm");

    const analyzeButton =
        document.getElementById("analyzeButton");

    const mediaUrl =
        document.getElementById("media_url");


    // ========================================================
    // FILE SELECTION
    // ========================================================

    if (mediaInput) {

        mediaInput.addEventListener(
            "change",
            () => {

                if (!mediaInput.files.length) {

                    selectedFile.textContent = "";

                    return;
                }

                const file =
                    mediaInput.files[0];

                const sizeMB =
                    file.size /
                    (1024 * 1024);

                selectedFile.textContent =
                    `${file.name} · ${sizeMB.toFixed(2)} MB`;

                // Clear URL when local file selected
                if (mediaUrl) {
                    mediaUrl.value = "";
                }

            }
        );

    }


    // ========================================================
    // URL INPUT
    // ========================================================

    if (mediaUrl) {

        mediaUrl.addEventListener(
            "input",
            () => {

                if (
                    mediaUrl.value.trim()
                    && mediaInput
                ) {

                    mediaInput.value = "";

                    if (selectedFile) {
                        selectedFile.textContent = "";
                    }

                }

            }
        );

    }


    // ========================================================
    // ANALYSIS LOADING STATE
    // ========================================================

    if (analyzeForm) {

        analyzeForm.addEventListener(
            "submit",
            () => {

                if (analyzeButton) {

                    analyzeButton.disabled = true;

                    analyzeButton.textContent =
                        "⏳ Analyzing...";

                }

            }
        );

    }


    // ========================================================
    // AUTO-HIDE ALERTS
    // ========================================================

    const alerts =
        document.querySelectorAll(".alert");

    alerts.forEach(
        (alert) => {

            setTimeout(
                () => {

                    alert.style.transition =
                        "opacity 0.4s ease";

                    alert.style.opacity = "0";

                    setTimeout(
                        () => {
                            alert.remove();
                        },
                        450
                    );

                },
                6000
            );

        }
    );

});