/**
 * SpotDown — Frontend Logic
 * Handles URL input, track fetching, download management, and job polling.
 */

const API = "/api";

// ── State ─────────────────────────────────────────────────────────────────────
let currentInfo = null;       // fetched track/playlist info
let selectedTracks = new Set(); // indices of selected tracks
let activeJobs = {};           // jobId -> intervalId (polling)
let settings = {
  outputDir: "",
  format: "mp3",
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const urlInput         = document.getElementById("url-input");
const btnFetch         = document.getElementById("btn-fetch");
const btnPaste         = document.getElementById("btn-paste");
const loadingCard      = document.getElementById("loading-card");
const errorBanner      = document.getElementById("error-banner");
const errorText        = document.getElementById("error-text");
const trackInfoCard    = document.getElementById("track-info-card");
const coverImg         = document.getElementById("cover-img");
const trackTypeBadge   = document.getElementById("track-type-chip");
const trackTitle       = document.getElementById("track-title");
const trackCount       = document.getElementById("track-count");
const trackList        = document.getElementById("track-list");
const btnDownloadAll   = document.getElementById("btn-download-all");
const btnSelectAll     = document.getElementById("btn-select-all");
const btnDlSelected    = document.getElementById("btn-download-selected");
const selectedCountEl  = document.getElementById("selected-count");
const jobsPanel        = document.getElementById("jobs-panel");
const jobsList         = document.getElementById("jobs-list");
const settingsModal    = document.getElementById("settings-modal");
const btnSettings      = document.getElementById("btn-settings");
const closeSettings    = document.getElementById("close-settings");
const outputDirInput   = document.getElementById("output-dir-input");
const formatSelect     = document.getElementById("format-select");
const saveSettingsBtn  = document.getElementById("save-settings");
const btnHistory       = document.getElementById("btn-history");

// ── Init ──────────────────────────────────────────────────────────────────────
(async function init() {
  loadSettings();

  // Load default output dir from backend
  try {
    const res = await fetch(`${API}/default-dir`);
    const data = await res.json();
    if (!settings.outputDir) {
      settings.outputDir = data.dir;
      outputDirInput.value = data.dir;
    }
  } catch (e) {}

  // Auto-paste if clipboard has a spotify link
  autoDetectClipboard();
})();

// ── Event Listeners ───────────────────────────────────────────────────────────
btnFetch.addEventListener("click", handleFetch);
urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") handleFetch(); });
urlInput.addEventListener("input", () => { hideError(); });

btnPaste.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    urlInput.value = text.trim();
    handleFetch();
  } catch (e) {
    urlInput.focus();
  }
});

btnDownloadAll.addEventListener("click", () => {
  if (!currentInfo) return;
  const urls = currentInfo.tracks.map((t) => t.url);
  startDownload(urls, currentInfo.title);
});

btnSelectAll.addEventListener("click", () => {
  const checkboxes = trackList.querySelectorAll(".track-check");
  const allChecked = checkboxes.length > 0 && [...checkboxes].every((c) => c.checked);
  checkboxes.forEach((cb, i) => {
    cb.checked = !allChecked;
    cb.closest(".track-row").classList.toggle("selected", !allChecked);
    if (!allChecked) selectedTracks.add(i);
    else selectedTracks.delete(i);
  });
  updateSelectionUI();
  btnSelectAll.textContent = allChecked ? "Select All" : "Deselect All";
});

btnDlSelected.addEventListener("click", () => {
  if (!currentInfo || selectedTracks.size === 0) return;
  const urls = [...selectedTracks].map((i) => currentInfo.tracks[i].url);
  startDownload(urls, `${selectedTracks.size} selected tracks`);
});

// Settings
btnSettings.addEventListener("click", () => { settingsModal.style.display = "flex"; });
closeSettings.addEventListener("click", () => { settingsModal.style.display = "none"; });
settingsModal.addEventListener("click", (e) => { if (e.target === settingsModal) settingsModal.style.display = "none"; });
saveSettingsBtn.addEventListener("click", () => {
  settings.outputDir = outputDirInput.value.trim() || settings.outputDir;
  settings.format = formatSelect.value;
  saveSettings();
  settingsModal.style.display = "none";
  showToast("Settings saved");
});

// History
btnHistory.addEventListener("click", () => {
  jobsPanel.style.display = "block";
  loadJobHistory();
  jobsPanel.scrollIntoView({ behavior: "smooth" });
});

// ── Core: Fetch Info ──────────────────────────────────────────────────────────
async function handleFetch() {
  const url = urlInput.value.trim();
  if (!url) { showError("Please paste a Spotify URL."); return; }

  showLoading(true);
  hideError();
  trackInfoCard.style.display = "none";

  try {
    const res = await fetch(`${API}/fetch-info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (data.error) { showError(data.error); return; }

    currentInfo = data;
    selectedTracks.clear();
    renderTrackInfo(data);
  } catch (e) {
    showError("Could not reach the backend. Make sure the server is running.");
  } finally {
    showLoading(false);
  }
}

// ── Render Track Info ─────────────────────────────────────────────────────────
function renderTrackInfo(info) {
  const typeLabels = { track: "Song", playlist: "Playlist", album: "Album" };

  coverImg.src = info.cover || "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140' viewBox='0 0 140 140'%3E%3Crect width='140' height='140' fill='%23111'/%3E%3Ccircle cx='70' cy='70' r='30' fill='%231DB954' opacity='.3'/%3E%3C/svg%3E";
  coverImg.onerror = () => { coverImg.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140' viewBox='0 0 140 140'%3E%3Crect width='140' height='140' fill='%23111'/%3E%3Ccircle cx='70' cy='70' r='30' fill='%231DB954' opacity='.3'/%3E%3C/svg%3E"; };

  trackTypeBadge.textContent = typeLabels[info.type] || info.type;
  trackTitle.textContent = info.title;
  trackCount.textContent = info.track_count === 1
    ? "1 track"
    : `${info.track_count} tracks`;

  // Render track rows
  trackList.innerHTML = "";
  info.tracks.forEach((track, i) => {
    const row = document.createElement("div");
    row.className = "track-row";
    row.dataset.index = i;

    row.innerHTML = `
      <div class="track-num">
        <input type="checkbox" class="track-check" id="check-${i}" />
        <span class="num-label">${i + 1}</span>
      </div>
      <div class="track-name-wrap">
        <span class="track-name">
          ${escHtml(track.name)}
          ${track.explicit ? '<span class="track-explicit-tag">E</span>' : ""}
        </span>
        <span class="track-artist">${escHtml(track.artists)}</span>
      </div>
      <span class="track-album">${escHtml(track.album)}</span>
      <span class="track-duration">${formatDuration(track.duration)}</span>
      <button class="btn-dl-single" id="btn-dl-${i}" data-url="${escHtml(track.url)}" data-name="${escHtml(track.name)}">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        Download
      </button>
    `;

    // Checkbox handler
    const cb = row.querySelector(".track-check");
    cb.addEventListener("change", () => {
      if (cb.checked) selectedTracks.add(i);
      else selectedTracks.delete(i);
      row.classList.toggle("selected", cb.checked);
      updateSelectionUI();
    });

    // Single download button
    const dlBtn = row.querySelector(".btn-dl-single");
    dlBtn.addEventListener("click", () => {
      startSingleTrackDownload(track.url, track.name, dlBtn);
    });

    trackList.appendChild(row);
  });

  trackInfoCard.style.display = "block";

  // Show download all if multiple tracks
  btnDownloadAll.style.display = info.track_count > 1 ? "inline-flex" : "none";
  if (info.track_count === 1) {
    // Single track: just show download
    btnDownloadAll.style.display = "inline-flex";
    btnDownloadAll.textContent = "";
    btnDownloadAll.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd"/></svg> Download`;
    btnSelectAll.style.display = "none";
  } else {
    btnSelectAll.style.display = "inline-flex";
  }
}

// ── Download Triggers ─────────────────────────────────────────────────────────
async function startSingleTrackDownload(url, name, btn) {
  btn.classList.add("downloading");
  btn.innerHTML = `<div class="spinner" style="width:14px;height:14px;border-width:2px"></div> Downloading`;

  try {
    const res = await fetch(`${API}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls: [url],
        output_dir: settings.outputDir,
        track_name: name,
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    pollJobForButton(data.job_id, btn, name);
    showJobsPanel();
    addJobCard(data.job_id, name, 1);
  } catch (e) {
    btn.classList.remove("downloading");
    btn.classList.add("error");
    btn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg> Error`;
  }
}

async function startDownload(urls, name) {
  try {
    const res = await fetch(`${API}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls,
        output_dir: settings.outputDir,
        track_name: name,
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    showJobsPanel();
    addJobCard(data.job_id, name, urls.length);
    pollJob(data.job_id);
  } catch (e) {
    showError("Failed to start download: " + e.message);
  }
}

// ── Job Polling ───────────────────────────────────────────────────────────────
function pollJobForButton(jobId, btn, name) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/job/${jobId}`);
      const job = await res.json();
      if (job.status === "done" || job.status === "done_with_errors") {
        clearInterval(interval);
        btn.classList.remove("downloading");
        btn.classList.add("done");
        btn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Done`;
        updateJobCard(job);
      } else if (job.status === "cancelled") {
        clearInterval(interval);
        btn.classList.remove("downloading");
        btn.innerHTML = `Download`;
        updateJobCard(job);
      } else {
        updateJobCard(job);
      }
    } catch (e) {
      clearInterval(interval);
    }
  }, 1500);
  activeJobs[jobId] = interval;
}

function pollJob(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/job/${jobId}`);
      const job = await res.json();
      updateJobCard(job);
      if (["done", "done_with_errors", "cancelled", "error"].includes(job.status)) {
        clearInterval(interval);
        delete activeJobs[jobId];
      }
    } catch (e) {
      clearInterval(interval);
      delete activeJobs[jobId];
    }
  }, 1500);
  activeJobs[jobId] = interval;
}

async function loadJobHistory() {
  try {
    const res = await fetch(`${API}/jobs`);
    const jobs = await res.json();
    jobs.forEach((job) => {
      if (!document.getElementById(`job-${job.id}`)) {
        addJobCard(job.id, job.track_name || "Download", job.total);
      }
      updateJobCard(job);
    });
  } catch (e) {}
}

// ── Job Card Rendering ────────────────────────────────────────────────────────
function showJobsPanel() {
  jobsPanel.style.display = "block";
}

function addJobCard(jobId, name, total) {
  if (document.getElementById(`job-${jobId}`)) return;

  const card = document.createElement("div");
  card.className = "job-card";
  card.id = `job-${jobId}`;
  card.innerHTML = `
    <div class="job-top">
      <span class="job-name">${escHtml(name)}</span>
      <span class="job-status-chip queued" id="jstatus-${jobId}">Queued</span>
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar" id="jprogress-${jobId}" style="width:0%"></div>
    </div>
    <div class="job-meta">
      <span id="jmeta-${jobId}">0 / ${total} tracks</span>
      <button class="btn-cancel-job" onclick="cancelJob('${jobId}')">Cancel</button>
    </div>
  `;
  jobsList.prepend(card);
}

function updateJobCard(job) {
  const statusEl = document.getElementById(`jstatus-${job.id}`);
  const progressEl = document.getElementById(`jprogress-${job.id}`);
  const metaEl = document.getElementById(`jmeta-${job.id}`);

  if (!statusEl) return;

  const statusLabels = {
    queued: "Queued", running: "Downloading",
    done: "Done ✓", done_with_errors: "Done (errors)",
    cancelled: "Cancelled", error: "Error",
  };

  statusEl.textContent = statusLabels[job.status] || job.status;
  statusEl.className = `job-status-chip ${job.status}`;
  progressEl.style.width = (job.progress || 0) + "%";
  metaEl.innerHTML = `${job.done || 0} / ${job.total} tracks — saved to <em>${job.output_dir || ""}</em>`;

  // Hide cancel button when finished
  if (["done", "done_with_errors", "cancelled", "error"].includes(job.status)) {
    const btn = metaEl.parentElement.querySelector(".btn-cancel-job");
    if (btn) btn.style.display = "none";
  }
}

async function cancelJob(jobId) {
  try {
    await fetch(`${API}/cancel/${jobId}`, { method: "POST" });
  } catch (e) {}
}

// ── Selection UI ──────────────────────────────────────────────────────────────
function updateSelectionUI() {
  const count = selectedTracks.size;
  if (count > 0) {
    btnDlSelected.style.display = "inline-flex";
    selectedCountEl.textContent = count;
  } else {
    btnDlSelected.style.display = "none";
  }
}

// ── Settings Persistence ──────────────────────────────────────────────────────
function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem("spotdown-settings") || "{}");
    settings = { ...settings, ...saved };
    outputDirInput.value = settings.outputDir || "";
    formatSelect.value = settings.format || "mp3";
  } catch (e) {}
}

function saveSettings() {
  localStorage.setItem("spotdown-settings", JSON.stringify(settings));
}

// ── Auto-detect clipboard ─────────────────────────────────────────────────────
async function autoDetectClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text && text.includes("open.spotify.com")) {
      urlInput.value = text.trim();
    }
  } catch (e) {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function showLoading(visible) {
  loadingCard.style.display = visible ? "flex" : "none";
}

function showError(msg) {
  errorText.textContent = msg;
  errorBanner.style.display = "flex";
}

function hideError() {
  errorBanner.style.display = "none";
}

function formatDuration(ms) {
  if (!ms) return "—";
  const secs = Math.round(ms / 1000);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function escHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showToast(msg) {
  const toast = document.createElement("div");
  toast.style.cssText = `
    position:fixed; bottom:1.5rem; left:50%; transform:translateX(-50%);
    background:#1DB954; color:#000; font-family:var(--font);
    font-size:0.85rem; font-weight:600; padding:0.6rem 1.2rem;
    border-radius:100px; z-index:200; box-shadow:0 8px 24px rgba(29,185,84,0.4);
    animation: fadeIn 0.2s ease;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}
