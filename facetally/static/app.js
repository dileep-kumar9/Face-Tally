(function () {
  const dropzone = document.getElementById("dropzone");
  const mediaInput = document.getElementById("media-input");
  const filenameEl = document.getElementById("dropzone-filename");
  const urlInput = document.getElementById("media-url");
  const form = document.getElementById("analyze-form");
  const analyzeBtn = document.getElementById("analyze-btn");

  if (mediaInput) {
    mediaInput.addEventListener("change", () => {
      if (mediaInput.files && mediaInput.files[0]) {
        filenameEl.textContent = mediaInput.files[0].name;
        if (urlInput) urlInput.value = "";
      }
    });
  }

  // Typing a link clears any chosen file, so only one source is submitted.
  if (urlInput) {
    urlInput.addEventListener("input", () => {
      if (urlInput.value.trim() && mediaInput) {
        mediaInput.value = "";
        filenameEl.textContent = "";
      }
    });
  }

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone && dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dropzone && dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    });
  });
  dropzone && dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) {
      mediaInput.files = e.dataTransfer.files;
      filenameEl.textContent = file.name;
      if (urlInput) urlInput.value = "";
    }
  });

  if (form) {
    form.addEventListener("submit", () => {
      analyzeBtn.textContent = "Analyzing…";
      analyzeBtn.disabled = true;
    });
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/static/sw.js").catch(() => {});
    });
  }
})();
