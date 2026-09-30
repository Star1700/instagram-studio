const DEFAULT_IMAGE_CUSTOM = { background: "ivory", accent: "terracotta", layout: "editorial" };
const state = { draftId: null, accountId: "", models: [], presets: {}, oauthTimer: null, hasImage: false, hasLogo: false, useLogo: true, logoPosition: "bottom_right", saveTimer: null, creating: null, saving: Promise.resolve(), mediaType: "image", media: {}, slide: 0, mediaBusy: false, templates: [], styles: [], customOptions: {}, imageStyle: "warm", customStyle: { ...DEFAULT_IMAGE_CUSTOM }, savedCustomStyle: { ...DEFAULT_IMAGE_CUSTOM }, imageInputs: {}, writingProfiles: [], writingProfileId: "", profileTimer: null, profileDirty: false, profileSaving: Promise.resolve(true), profileRevision: 0 };
const fields = {
  headline: document.querySelector("#headline"), caption: document.querySelector("#caption"),
  hashtags: document.querySelector("#hashtags"), alt_text: document.querySelector("#altText"),
  image_prompt: document.querySelector("#imagePrompt")
};
const idea = document.querySelector("#idea");
const errorBanner = document.querySelector("#errorBanner");
const successBanner = document.querySelector("#successBanner");
const preview = document.querySelector("#preview");
const emptyPreview = document.querySelector("#emptyPreview");
const sendNowButton = document.querySelector("#sendNow");
const scheduleButton = document.querySelector("#schedulePost");
const scheduleTime = document.querySelector("#scheduleTime");
const replaceImageButton = document.querySelector("#replaceImage");
const studioTabId = crypto.randomUUID().replaceAll("-", "");
const presenceAbort = new AbortController();
let presenceClosed = false;

function reportPresence(action) {
  fetch("/api/presence", { method: "POST", keepalive: true, cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
    body: JSON.stringify({ tab_id: studioTabId, action }) }).catch(() => {});
}
reportPresence("touch");
const presenceTimer = setInterval(() => reportPresence("touch"), 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) reportPresence("touch"); });
async function holdPresenceConnection() {
  while (!presenceClosed) {
    try {
      const response = await fetch("/api/presence/stream", { method: "POST", cache: "no-store", signal: presenceAbort.signal,
        headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
        body: JSON.stringify({ tab_id: studioTabId }) });
      if (response.ok && response.body) {
        const reader = response.body.getReader();
        while (!presenceClosed && !(await reader.read()).done) { /* Keep the connection open. */ }
      }
    } catch { /* A dropped connection is retried while this tab is open. */ }
    if (!presenceClosed) await new Promise(resolve => setTimeout(resolve, 1000));
  }
}
holdPresenceConnection();
window.addEventListener("pagehide", () => { presenceClosed = true; presenceAbort.abort(); clearInterval(presenceTimer); reportPresence("leave"); });

async function request(path, options = {}) {
  let response;
  try { response = await fetch(path, { ...options, headers: { ...options.headers, "X-Studio-Request": "1", "X-Studio-Local-Account": state.accountId } }); }
  catch { throw new Error("Studio ist gerade nicht erreichbar. Deine Eingaben sind noch da. Bitte starte Studio erneut."); }
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json") ? await response.json() : null;
  if (!response.ok) throw new Error(data?.error || "Die Anfrage konnte nicht verarbeitet werden.");
  return data;
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
  successBanner.hidden = true;
  errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showSuccess(message) {
  successBanner.textContent = message;
  successBanner.hidden = false;
  errorBanner.hidden = true;
  setTimeout(() => { successBanner.hidden = true; }, 2800);
}

function draftKey() { return "studioDraftId:" + (state.accountId || "pending"); }

function canvasValue() { return document.querySelector('input[name="canvas"]:checked').value; }

function updateVisualControls() {
  const video = state.mediaType === "video", carousel = state.mediaType === "carousel";
  replaceImageButton.textContent = video ? (state.hasImage ? "Video ersetzen" : "Video hinzufügen") : carousel ? "Bilder hinzufügen" : state.hasImage ? "Bild ersetzen" : "Bild hinzufügen";
  document.querySelector("#removeMedia").hidden = !state.hasImage;
  document.querySelector("#removeMedia").textContent = carousel ? "🗑 Alle Bilder entfernen" : video ? "🗑 Video entfernen" : "🗑 Bild entfernen";
  ["#logoPicker", "#logoControls", "#canvasControls", "#headlineField", "#imageIdeaPanel"].forEach(id => { document.querySelector(id).hidden = video; });
  document.querySelector("#altTextField").hidden = video || carousel;
  document.querySelector("#headlineHelp").textContent = carousel ? "Wird nur auf das erste Bild gesetzt. Leer lassen, wenn dieses schon eine Überschrift enthält." : "Leer lassen, wenn dein Bild bereits Text enthält. Sonst wird sie oben ins Bild gesetzt.";
  document.querySelector("#dropTitle").textContent = video ? "Video hier ablegen" : carousel ? "Bilder hier ablegen" : "Bild hier ablegen";
  document.querySelector("#mediaHelp").textContent = video ? "Fertiges MP4 · H.264 · bis 100 MB · 3 Sekunden bis 15 Minuten. Caption und Ton bleiben erhalten; Studio setzt keine Überschrift und kein Logo ins Video." : carousel ? "2 bis 10 Bilder · je bis 8 MB · Reihenfolge unten ändern. Alle Bilder werden auf das gewählte Format zugeschnitten." : "JPG, PNG oder WebP · bis 8 MB · passend zum gewählten Format zugeschnitten.";
  imageInput.accept = video ? "video/mp4,.mp4" : "image/jpeg,image/png,image/webp";
  imageInput.multiple = carousel;
  document.querySelector("#logoPickerText").textContent = state.hasLogo ? "Logo ändern" : "Logo auswählen";
  const logoToggle = document.querySelector("#useLogo");
  logoToggle.disabled = !state.hasLogo;
  logoToggle.checked = state.hasLogo && state.useLogo;
  document.querySelector("#logoPosition").disabled = !state.hasLogo || !state.useLogo;
  document.querySelector("#logoPosition").value = state.logoPosition;
  document.querySelector("#logoState").textContent = !state.hasLogo
    ? "Noch kein Logo für dieses Instagram-Konto gespeichert."
    : state.useLogo
      ? "Logo ist für dieses Konto gespeichert und wird auf diesem Beitrag verwendet. Neue Beiträge verwenden es ebenfalls automatisch."
      : "Logo ist für dieses Konto gespeichert, auf diesem Beitrag aber ausgeschaltet. Neue Beiträge verwenden es automatisch.";
  updateOverlay();
}

function fillDraft(draft) {
  state.draftId = draft.id;
  localStorage.setItem(draftKey(), draft.id);
  idea.value = draft.idea || "";
  Object.entries(fields).forEach(([name, element]) => { element.value = draft[name] || ""; });
  const canvas = document.querySelector(`input[name="canvas"][value="${draft.canvas || "portrait"}"]`);
  if (canvas) canvas.checked = true;
  state.hasImage = Boolean(draft.preview_url);
  state.useLogo = draft.use_logo !== false;
  state.logoPosition = draft.logo_position || "bottom_right";
  state.mediaType = draft.media_type || "image";
  document.querySelector(`input[name="mediaType"][value="${state.mediaType}"]`).checked = true;
  document.querySelector("#imageTemplate").value = draft.image_template || "";
  state.imageStyle = draft.image_style || "warm";
  state.customStyle = { ...state.savedCustomStyle, ...(draft.image_custom || {}) };
  state.imageInputs = draft.image_inputs || {};
  invalidateCodexPrompt();
  updateTemplateExample();
  applyMedia(draft);
}

async function ensureDraft() {
  if (state.draftId) return state.draftId;
  if (!state.creating) state.creating = (async () => {
    const data = await request("/api/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ idea: idea.value }) });
    state.draftId = data.draft.id;
    localStorage.setItem(draftKey(), state.draftId);
    return state.draftId;
  })().finally(() => { state.creating = null; });
  return state.creating;
}

function currentFields() {
  return { idea: idea.value, headline: fields.headline.value, caption: fields.caption.value, hashtags: fields.hashtags.value,
    alt_text: fields.alt_text.value, image_prompt: fields.image_prompt.value, canvas: canvasValue(), use_logo: state.useLogo,
    logo_position: state.logoPosition,
    media_type: state.mediaType, image_template: document.querySelector("#imageTemplate").value,
    image_style: state.imageStyle, image_custom: state.customStyle, image_inputs: state.imageInputs,
    carousel_alts: state.mediaType === "carousel" ? Object.fromEntries((state.media.carousel || []).map(item => [item.id, item.alt_text || ""])) : undefined };
}

async function saveDraft() {
  const values = currentFields();
  if (!state.draftId && !idea.value.trim() && !Object.values(fields).some(field => field.value.trim())) return true;
  const id = await ensureDraft();
  const pending = state.saving.then(() => persistDraft(id, values));
  state.saving = pending.catch(() => false);
  return pending;
}

async function persistDraft(id, values) {
  document.querySelector("#saveState").textContent = "Wird gespeichert …";
  document.querySelector("#saveState").classList.add("saving");
  try {
    await request(`/api/drafts/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
    document.querySelector("#saveState").textContent = "Lokal gespeichert";
  } catch (error) { showError(error.message); document.querySelector("#saveState").classList.remove("saving"); return false; }
  document.querySelector("#saveState").classList.remove("saving");
  return true;
}

function queueSave() { invalidateCodexPrompt(); clearTimeout(state.saveTimer); state.saveTimer = setTimeout(() => saveDraft().catch(error => showError(error.message)), 450); }

async function generateText(part = null) {
  if (state.taskBusy || state.mediaBusy) return;
  if (!idea.value.trim() && !["headline", "caption", "hashtags"].some(key => fields[key].value.trim())) { showError("Schreibe zuerst eine Idee oder einen Textentwurf."); return; }
  const button = part ? document.querySelector(`[data-part="${part}"]`) : document.querySelector("#generateAll");
  const old = button.textContent; setComposerBusy(true); button.textContent = "Codex arbeitet …";
  try {
    if (!await flushProfile()) return;
    const id = await ensureDraft();
    if (!await saveDraft()) return;
    const data = await request(`/api/drafts/${id}/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ part }) });
    fillDraft(data.draft); showSuccess(part ? "Feld neu erzeugt." : "Textentwurf ist bereit."); await loadPosts();
  } catch (error) { showError(error.message); }
  finally { setComposerBusy(false); button.textContent = old; }
}

function setComposerBusy(busy) {
  state.taskBusy = busy;
  document.querySelectorAll("#accountSelect, main input, main textarea, main select, main button").forEach(element => {
    if (busy) { element.dataset.wasDisabled = String(element.disabled); element.disabled = true; }
    else if (element.dataset.wasDisabled !== undefined) { element.disabled = element.dataset.wasDisabled === "true"; delete element.dataset.wasDisabled; }
  });
}

async function uploadImage(file) {
  if (!file) return;
  const id = await ensureDraft();
  if (!await saveDraft()) return;
  const form = new FormData(); form.append("image", file);
  try {
    const data = await request(`/api/drafts/${id}/image`, { method: "POST", body: form });
    applyMedia({ ...state.media, preview_url: data.preview_url });
    showSuccess("Bild wurde lokal gestaltet."); await loadPosts();
  } catch (error) { showError(error.message); }
}

async function restamp() {
  if (!state.draftId || !state.hasImage) { queueSave(); return; }
  try {
    if (!await saveDraft()) return;
    const data = await request(`/api/drafts/${state.draftId}/stamp`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ headline: fields.headline.value, canvas: canvasValue() }) });
    applyMedia(data.draft || { ...state.media, preview_url: data.preview_url });
  } catch (error) { showError(error.message); }
}

async function loadPosts() {
  try {
    const data = await request("/api/posts");
    if (data.warning) showError(data.warning);
    const list = document.querySelector("#postList"); list.textContent = "";
    if (!data.posts.length) { list.innerHTML = '<p class="empty-list">Noch keine Entwürfe.</p>'; return; }
    data.posts.forEach(post => {
      const row = document.createElement("article"); row.className = `post-row ${post.source}`;
      const copy = document.createElement("div");
      const heading = document.createElement("h3"); heading.textContent = post.headline || post.caption?.slice(0, 70) || "Unbenannter Beitrag";
      const detail = document.createElement("p"); detail.textContent = postDetail(post);
      const actions = document.createElement("div"); actions.className = "post-actions";
      const status = document.createElement("span"); status.className = `status ${post.status || "draft"}`; status.textContent = postStatus(post);
      actions.append(status);
      if (post.source === "local" || (post.source === "server" && post.status !== "sent")) {
        const local = post.source === "local";
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "delete-button";
        remove.textContent = "🗑"; remove.setAttribute("aria-label", local ? "Entwurf löschen" : "Geplanten Beitrag löschen"); remove.title = local ? "Entwurf löschen" : "Beitrag löschen";
        remove.addEventListener("click", async event => {
          event.stopPropagation();
          if (state.taskBusy || state.mediaBusy) return;
          if (remove.dataset.confirmed !== "true") {
            remove.dataset.confirmed = "true";
            remove.textContent = "Löschen?";
            remove.classList.add("confirm");
            remove.setAttribute("aria-label", "Löschen bestätigen");
            remove.title = local ? "Noch einmal klicken, um den Entwurf zu löschen" : "Noch einmal klicken, um den Beitrag zu löschen";
            setTimeout(() => {
              if (!remove.isConnected || remove.dataset.confirmed !== "true") return;
              remove.dataset.confirmed = "false";
              remove.textContent = "🗑";
              remove.classList.remove("confirm");
              remove.setAttribute("aria-label", local ? "Entwurf löschen" : "Geplanten Beitrag löschen");
              remove.title = local ? "Entwurf löschen" : "Beitrag löschen";
            }, 5000);
            return;
          }
          remove.disabled = true;
          try {
            if (local && state.draftId === post.id) {
              clearTimeout(state.saveTimer);
              await state.saving;
            }
            await request(local ? `/api/drafts/${post.id}/delete` : `/api/posts/${post.id}/delete`, { method: "POST" });
            if (local && state.draftId === post.id) resetComposer();
            showSuccess(local ? "Entwurf wurde gelöscht." : "Beitrag wurde gelöscht.");
            await loadPosts();
          }
          catch (error) { remove.disabled = false; showError(error.message); }
        });
        actions.append(remove);
      }
      copy.append(heading, detail); row.append(copy, actions);
      if (post.source === "local") row.addEventListener("click", async () => { if (state.taskBusy || state.mediaBusy) return; try { clearTimeout(state.saveTimer); if (!await saveDraft()) return; const loaded = await request(`/api/drafts/${post.id}`); fillDraft(loaded.draft); window.scrollTo({ top: 0, behavior: "smooth" }); } catch (error) { showError(error.message); } });
      list.append(row);
    });
    if (data.warning) showError(data.warning);
  } catch (error) { showError(error.message); }
}

function publishDate(post) {
  const value = Date.parse(post.publish_at || "");
  return Number.isFinite(value) ? value : null;
}

function postStatus(post) {
  const when = publishDate(post);
  if (post.status === "scheduled" && when !== null && when <= Date.now() + 90_000) return "Sobald wie möglich";
  return post.status_label;
}

function postDetail(post) {
  if (post.source !== "server") return "Lokaler Entwurf";
  const when = publishDate(post);
  if (post.status === "sent") return "Auf Instagram veröffentlicht";
  if (post.status === "container_pending") return "Instagram verarbeitet den Beitrag";
  if (post.status === "failed") return "Beim Online-Dienst · Verarbeitung fehlgeschlagen";
  if (post.status === "scheduled" && when !== null) {
    if (when <= Date.now() + 90_000) return "Versand beim nächsten Serverlauf";
    const formatted = new Intl.DateTimeFormat("de-AT", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Vienna" }).format(new Date(when));
    return `Veröffentlichung am ${formatted}`;
  }
  return "Beim Online-Dienst";
}

async function loadProfile() {
  try {
    const data = await request("/api/profile");
    const dot = document.querySelector("#connectionDot");
    state.accountId = data.active_account_id || "";
    state.models = data.models; state.presets = data.presets;
    dot.classList.toggle("connected", data.connected);
    document.querySelector("#connectionText").textContent = data.connected ? `@${data.profile.handle || "Instagram"} ausgewählt` : "Noch kein Instagram-Konto";
    document.querySelector("#connectButton").textContent = data.connected ? "Konten verwalten" : "Instagram einrichten";
    const accounts = document.querySelector("#accountSelect"); accounts.textContent = "";
    data.accounts.forEach(account => accounts.add(new Option("@" + (account.username || account.id), account.id)));
    accounts.value = state.accountId; accounts.hidden = !data.accounts.length;
    document.querySelector("#addAccount").textContent = data.connected ? "Weiteres Konto verbinden" : "Instagram verbinden";
    document.querySelector("#checkConnection").disabled = !data.connected;
    document.querySelector("#settingsTitle").textContent = "Dein Schreibstil";
    if (!data.connected) document.querySelector("#accountsPanel").open = true;
    document.querySelector("#accountSetupNote").hidden = data.connected;
    document.querySelector("#accountReadyNote").hidden = !data.connected;
    document.querySelector("#showAccountSetup").hidden = !data.connected;
    document.querySelector("#welcomeNote").hidden = Boolean(data.profile.setup_complete);
    Object.entries(profileFields).forEach(([key, id]) => {
      const element = document.querySelector(id);
      const raw = data.profile[key] || "";
      if (key === "language") element.value = raw || "Deutsch";
      else if (key === "emoji") element.value = [...element.options].some(option => option.value === raw) ? raw : "Wenige Emojis";
      else element.value = raw;
    });
    state.writingProfiles = data.writing_profiles || [];
    state.writingProfileId = data.profile.writing_profile_id || "";
    populateProfiles();
    const tones = document.querySelector("#tonePreset"); tones.length = 1;
    data.tones.forEach(tone => tones.add(new Option(tone, tone)));
    tones.value = data.tones.includes(data.profile.tone) ? data.profile.tone : "";
    document.querySelector("#customToneLabel").hidden = Boolean(tones.value);
    const models = document.querySelector("#modelSelect"); models.length = 1;
    data.models.forEach(model => models.add(new Option(model.name, model.id)));
    models.value = data.codex.model !== "Codex-Standard" ? data.codex.model : "";
    updateEfforts(data.codex.effort || "high");
    document.querySelector("#referenceFolder").value = data.reference_folder || "";
    state.hasLogo = Boolean(data.profile.logo_path);
    state.codex = data.codex;
    invalidateCodexPrompt();
    updateProfileSummary();
    document.querySelectorAll(".mock-handle").forEach(element => { element.textContent = data.profile.handle || "dein_konto"; });
    updateVisualControls();
  } catch (error) { showError(error.message); }
}

function resetComposer() {
  localStorage.removeItem(draftKey());
  state.draftId = null;
  state.hasImage = false;
  state.useLogo = true;
  state.logoPosition = "bottom_right";
  state.mediaType = "image"; state.media = {}; state.slide = 0;
  state.imageStyle = "warm"; state.customStyle = { ...state.savedCustomStyle }; state.imageInputs = {};
  document.querySelector('input[name="mediaType"][value="image"]').checked = true;
  document.querySelector("#imageTemplate").value = "";
  document.querySelector("#newDraftChoice").hidden = true;
  idea.value = "";
  Object.values(fields).forEach(element => { element.value = ""; });
  scheduleTime.value = "";
  preview.hidden = true;
  preview.removeAttribute("src");
  emptyPreview.hidden = false;
  invalidateCodexPrompt();
  updateTemplateExample(); applyMedia({});
}

async function sendPost(when) {
  if (state.taskBusy || state.mediaBusy) { showError("Warte bitte, bis die aktuelle Verarbeitung fertig ist."); return; }
  const localTime = when === "schedule" ? scheduleTime.value : null;
  if (when === "schedule" && !localTime) { showError("Bitte wähle ein Datum und eine Uhrzeit."); return; }
  const oldNow = sendNowButton.textContent;
  const oldSchedule = scheduleButton.textContent;
  setComposerBusy(true);
  (when === "now" ? sendNowButton : scheduleButton).textContent = "Wird übertragen …";
  try {
    const id = await ensureDraft();
    clearTimeout(state.saveTimer);
    if (!await saveDraft()) return;
    await request(`/api/drafts/${id}/send`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ when, local_time: localTime })
    });
    resetComposer();
    showSuccess(when === "now" ? "Beitrag wurde zum Veröffentlichen übergeben." : "Dein Beitrag ist für den gewählten Zeitpunkt eingeplant.");
    await loadPosts();
  } catch (error) { showError(error.message); }
  finally {
    setComposerBusy(false);
    sendNowButton.textContent = oldNow;
    scheduleButton.textContent = oldSchedule;
  }
}

document.querySelector("#generateAll").addEventListener("click", () => generateText(null));
document.querySelectorAll(".regenerate").forEach(button => button.addEventListener("click", () => generateText(button.dataset.part)));
Object.values(fields).forEach(element => element.addEventListener("input", queueSave));
idea.addEventListener("input", queueSave);
fields.headline.addEventListener("change", restamp);
document.querySelectorAll('input[name="canvas"]').forEach(input => input.addEventListener("change", restamp));
document.querySelectorAll(".new-draft-trigger").forEach(button => button.addEventListener("click", async () => {
  if (state.taskBusy || state.mediaBusy) return;
  if (!state.draftId && !idea.value.trim() && !Object.values(fields).some(field => field.value.trim()) && !state.hasImage) { resetComposer(); window.scrollTo({ top: 0, behavior: "smooth" }); return; }
  const choice = document.querySelector("#newDraftChoice"); choice.hidden = false;
  choice.scrollIntoView({ behavior: "smooth", block: "center" });
}));
document.querySelector("#cancelNewDraft").addEventListener("click", () => { document.querySelector("#newDraftChoice").hidden = true; });
document.querySelector("#keepDraft").addEventListener("click", async () => {
  try { clearTimeout(state.saveTimer); if (!await saveDraft()) return; resetComposer(); await loadPosts(); window.scrollTo({ top: 0, behavior: "smooth" }); showSuccess("Entwurf behalten. Du kannst einen neuen Beitrag beginnen."); }
  catch (error) { showError(error.message); }
});
document.querySelector("#discardDraft").addEventListener("click", async () => {
  try {
    clearTimeout(state.saveTimer); await state.saving;
    if (state.draftId) await request(`/api/drafts/${state.draftId}/delete`, { method: "POST" });
    resetComposer(); await loadPosts(); window.scrollTo({ top: 0, behavior: "smooth" }); showSuccess("Entwurf gelöscht. Du kannst einen neuen Beitrag beginnen.");
  } catch (error) { showError(error.message); }
});
const imageInput = document.querySelector("#imageInput");
document.querySelector("#dropzone").addEventListener("click", event => { if (!event.target.closest("video, button")) imageInput.click(); });
document.querySelector("#dropzone").addEventListener("keydown", event => { if (event.target === event.currentTarget && ["Enter", " "].includes(event.key)) { event.preventDefault(); imageInput.click(); } });
document.querySelector("#replaceImage").addEventListener("click", () => imageInput.click());
document.querySelector("#removeMedia").addEventListener("click", async () => {
  if (!state.draftId || state.mediaBusy) return;
  state.mediaBusy = true;
  try {
    clearTimeout(state.saveTimer); if (!await saveDraft()) return;
    const result = await request(`/api/drafts/${state.draftId}/clear-media`, { method: "POST" });
    state.slide = 0; fields.alt_text.value = result.draft.alt_text || ""; applyMedia(result.draft); await loadPosts(); showSuccess("Medium aus dem Entwurf entfernt.");
  } catch (error) { showError(error.message); }
  finally { state.mediaBusy = false; }
});
imageInput.addEventListener("change", () => uploadFiles([...imageInput.files]));
const dropzone = document.querySelector("#dropzone");
dropzone.addEventListener("dragover", event => { event.preventDefault(); dropzone.classList.add("dragging"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
dropzone.addEventListener("drop", event => { event.preventDefault(); dropzone.classList.remove("dragging"); uploadFiles([...event.dataTransfer.files]); });
document.querySelector("#openChatGPT").addEventListener("click", async () => {
  const template = selectedTemplate();
  if (template) {
    const missing = incompleteTemplateFields(template);
    if (missing.length) { showError("Bitte fülle zuerst diese Vorlagenfelder aus: " + missing.join(", ") + "."); return; }
  }
  const prompt = fields.image_prompt.value.trim();
  if (!prompt) { showError("Schreibe zuerst eine Bildidee für ChatGPT."); return; }
  let copied = Promise.resolve(false);
  try {
    if (navigator.clipboard?.writeText) copied = navigator.clipboard.writeText(prompt).then(() => true, () => false);
  } catch { /* Opening ChatGPT must not depend on clipboard access. */ }
  const popup = window.open("about:blank", "_blank");
  try {
    const id = await ensureDraft();
    if (!await saveDraft()) { popup?.close(); return; }
    const data = await request(`/api/drafts/${id}/chatgpt`, { method: "POST" });
    if (popup) { popup.opener = null; popup.location = data.url; }
    else { window.location.assign(data.url); return; }
    if (await copied) showSuccess("ChatGPT wurde geöffnet. Die Bildidee wurde kopiert.");
    else showSuccess("ChatGPT wurde geöffnet. Falls der Prompt dort fehlt, kopiere ihn aus dem sichtbaren Feld „Dein Bild-Prompt“.");
  }
  catch (error) { if (popup) popup.close(); showError(error.message); }
});
document.querySelector("#openReferences").addEventListener("click", () => referenceAction("open"));
document.querySelector("#logoInput").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    await ensureDraft();
    const form = new FormData(); form.append("logo", file);
    await request("/api/profile/logo", { method: "POST", body: form });
    state.hasLogo = true;
    state.useLogo = true;
    if (!await saveDraft()) return;
    if (state.hasImage) await restamp();
    updateVisualControls();
    showSuccess("Logo ist für dieses Konto gespeichert und auf diesem Beitrag eingeschaltet.");
  } catch (error) { showError(error.message); }
});
document.querySelector("#useLogo").addEventListener("change", async event => {
  const previous = state.useLogo;
  try {
    await ensureDraft();
    state.useLogo = event.target.checked;
    updateVisualControls();
    if (!await saveDraft()) { state.useLogo = previous; updateVisualControls(); return; }
    if (state.hasImage) await restamp();
    showSuccess(state.useLogo ? "Logo ist für diesen Beitrag eingeschaltet." : "Logo ist für diesen Beitrag ausgeschaltet.");
  } catch (error) { state.useLogo = previous; updateVisualControls(); showError(error.message); }
});
document.querySelector("#logoPosition").addEventListener("change", async event => {
  const previous = state.logoPosition;
  state.logoPosition = event.target.value;
  try {
    if (!await saveDraft()) { state.logoPosition = previous; updateVisualControls(); return; }
    if (state.hasImage && state.useLogo) await restamp();
  } catch (error) { state.logoPosition = previous; updateVisualControls(); showError(error.message); }
});
document.querySelector("#connectButton").addEventListener("click", () => { const panel = document.querySelector("#accountsPanel"); panel.open = !panel.open; if (panel.open) panel.scrollIntoView({ behavior: "smooth" }); });
document.querySelector("#addAccount").addEventListener("click", startConnection);
document.querySelector("#refreshPosts").addEventListener("click", loadPosts);
sendNowButton.addEventListener("click", () => sendPost("now"));
scheduleButton.addEventListener("click", () => sendPost("schedule"));

const profileFields = { name: "#profileName", niche: "#profileNiche", language: "#profileLanguage", tone: "#profileTone", avoid: "#profileAvoid", hashtags: "#profileHashtags", emoji: "#profileEmoji" };
const effortNames = { low: "Niedrig", medium: "Mittel", high: "Hoch", xhigh: "Sehr hoch", max: "Maximal", ultra: "Ultra", none: "Ohne", minimal: "Minimal" };
function updateEfforts(selected = "high") {
  const model = state.models.find(item => item.id === document.querySelector("#modelSelect").value);
  const select = document.querySelector("#effortSelect"); select.textContent = "";
  select.add(new Option("Codex-Standard", ""));
  (model?.efforts || ["low", "medium", "high"]).forEach(value => select.add(new Option(effortNames[value] || value, value)));
  select.value = [...select.options].some(option => option.value === selected) ? selected : ([...select.options].some(option => option.value === "high") ? "high" : (model?.efforts || ["medium"])[0]);
}
function profileValues() {
  if (!document.querySelector("#profileEmoji").value) document.querySelector("#profileEmoji").value = "Wenige Emojis";
  const values = Object.fromEntries(Object.entries(profileFields).map(([key, id]) => [key, document.querySelector(id).value]));
  return { ...values, model: document.querySelector("#modelSelect").value, effort: document.querySelector("#effortSelect").value };
}
function updateProfileSummary() {
  const p = profileValues();
  document.querySelector("#profileSummary").textContent = [p.niche ? "Konto: " + p.niche : "", p.language, p.tone,
    p.hashtags ? "Hashtags: " + p.hashtags : "", p.emoji ? "Emojis: " + p.emoji : ""].filter(Boolean).join(" · ") + (p.avoid ? ". Vermeidet: " + p.avoid : "");
  document.querySelector("#codexSettings").textContent = `Modell: ${p.model || state.codex?.model || "Codex-Standard"} · Denkaufwand: ${effortNames[p.effort || state.codex?.effort] || "Codex-Standard"}.`;
}
function populateProfiles() {
  const select = document.querySelector("#preset"); select.replaceChildren(new Option("Eigene Einstellungen", ""));
  const mine = document.createElement("optgroup"); mine.label = "Deine Schreibprofile";
  state.writingProfiles.forEach(item => mine.append(new Option(item.name, "saved:" + item.id)));
  if (mine.children.length) select.append(mine);
  const starters = document.createElement("optgroup"); starters.label = "Vorlagen für deinen Schreibstil";
  Object.entries(state.presets).forEach(([key, item]) => starters.append(new Option(item.label, "preset:" + key)));
  select.append(starters); select.value = state.writingProfileId ? "saved:" + state.writingProfileId : "";
  document.querySelector("#saveProfileCopy").hidden = !state.writingProfileId;
  document.querySelector("#saveProfile").textContent = state.writingProfileId ? "Profil aktualisieren" : "Profil speichern";
}
function queueProfileSave() {
  invalidateCodexPrompt(); updateProfileSummary(); state.profileDirty = true; state.profileRevision++;
  document.querySelector("#profileSaveState").textContent = "Wird für dieses Konto gespeichert …";
  clearTimeout(state.profileTimer); state.profileTimer = setTimeout(flushProfile, 500);
}
async function flushProfile() {
  clearTimeout(state.profileTimer);
  if (!state.profileDirty) return state.profileSaving;
  const values = profileValues(), revision = state.profileRevision;
  state.profileDirty = false;
  const save = state.profileSaving.then(async () => {
    try {
      const result = await request("/api/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      if (revision === state.profileRevision) {
        state.codex = result.codex;
        document.querySelector("#profileSaveState").textContent = "Für dieses Konto übernommen. Mit Profil speichern sicherst du den Stil für alle Konten.";
        updateProfileSummary();
      }
      return true;
    } catch (error) { state.profileDirty = true; showError(error.message); document.querySelector("#profileSaveState").textContent = "Noch nicht gespeichert. Deine Eingaben bleiben hier erhalten."; return false; }
  });
  state.profileSaving = save;
  return save;
}
Object.values(profileFields).forEach(id => document.querySelector(id).addEventListener("input", queueProfileSave));
document.querySelector("#effortSelect").addEventListener("change", queueProfileSave);
document.querySelector("#modelSelect").addEventListener("change", () => { updateEfforts(); queueProfileSave(); });
document.querySelector("#tonePreset").addEventListener("change", event => {
  if (event.target.value) document.querySelector("#profileTone").value = event.target.value;
  document.querySelector("#customToneLabel").hidden = Boolean(event.target.value); queueProfileSave();
});
document.querySelector("#preset").addEventListener("change", async event => {
  const chosen = event.target.value;
  if (!await flushProfile()) { populateProfiles(); return; }
  try {
    const savedId = chosen.startsWith("saved:") ? chosen.slice(6) : "";
    await request("/api/writing-profiles/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: savedId }) });
    if (savedId) { await loadProfile(); showSuccess("Schreibprofil übernommen."); return; }
    state.writingProfileId = "";
    document.querySelector("#saveProfileCopy").hidden = true;
    document.querySelector("#saveProfile").textContent = "Profil speichern";
    const preset = state.presets[chosen.replace("preset:", "")];
    if (preset) {
      ["niche", "avoid"].forEach(key => { document.querySelector(profileFields[key]).value = preset[key]; });
      document.querySelector("#profileName").value = preset.label;
      queueProfileSave();
    }
  } catch (error) { showError(error.message); }
});
async function saveNamedProfile(asNew, button) {
  button.disabled = true;
  try {
    if (!await flushProfile()) return;
    await request("/api/writing-profiles", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: asNew ? null : state.writingProfileId || null, values: profileValues() }) });
    await loadProfile(); showSuccess("Schreibprofil gespeichert – bei allen Konten auswählbar.");
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
}
document.querySelector("#saveProfile").addEventListener("click", event => saveNamedProfile(false, event.currentTarget));
document.querySelector("#saveProfileCopy").addEventListener("click", event => saveNamedProfile(true, event.currentTarget));
document.querySelector("#editSettings").addEventListener("click", () => { const panel = document.querySelector("#settingsPanel"); panel.open = true; panel.scrollIntoView({ behavior: "smooth" }); });
function invalidateCodexPrompt() {
  const output = document.querySelector("#codexPromptText");
  if (output) output.textContent = "Eingaben geändert. Klicke auf „Aktuellen Prompt anzeigen“, um den neuesten Stand zu sehen.";
  const settings = document.querySelector("#codexPromptSettings");
  if (settings) settings.textContent = "";
}
document.querySelector("#showCodexPrompt").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true;
  try {
    if (!await flushProfile()) return;
    const id = await ensureDraft();
    if (!await saveDraft()) return;
    const data = await request(`/api/drafts/${id}/text-prompt`, { method: "POST" });
    document.querySelector("#codexPromptSettings").textContent = `Modell: ${data.codex.model} · Denkaufwand: ${effortNames[data.codex.effort] || data.codex.effort}`;
    document.querySelector("#codexPromptText").textContent = data.prompt;
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
});
document.querySelector("#showAccountSetup").addEventListener("click", () => { document.querySelector("#accountSetupNote").hidden = !document.querySelector("#accountSetupNote").hidden; });
async function reloadAccount() {
  state.draftId = null;
  await loadProfile();
  state.draftId = localStorage.getItem(draftKey());
  if (state.draftId) {
    try { fillDraft((await request(`/api/drafts/${state.draftId}`)).draft); }
    catch { resetComposer(); }
  } else { resetComposer(); }
  await loadPosts();
}
document.querySelector("#accountSelect").addEventListener("change", async event => {
  try {
    if (state.taskBusy || state.mediaBusy) { event.target.value = state.accountId; showError("Warte bitte, bis die aktuelle Verarbeitung fertig ist."); return; }
    clearTimeout(state.saveTimer); if (!await saveDraft() || !await flushProfile()) { event.target.value = state.accountId; return; }
    await request("/api/accounts/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: event.target.value }) });
    await reloadAccount();
  } catch (error) { event.target.value = state.accountId; showError(error.message); }
});
async function startConnection() {
  const popup = window.open("about:blank", "_blank");
  try {
    clearTimeout(state.saveTimer); if (!await saveDraft()) { popup?.close(); return; }
    if (!await flushProfile()) { popup?.close(); return; }
    const result = await request("/api/oauth/start", { method: "POST" });
    const link = document.querySelector("#oauthLink"); link.href = result.url; link.hidden = false;
    if (popup) { popup.opener = null; popup.location = result.url; }
    const progress = document.querySelector("#oauthProgress"); progress.hidden = false;
    progress.textContent = "Warte auf deine Freigabe bei Instagram. Falls die Anmeldung scheitert: Prüfe beide Berechtigungen und dein Creator- oder Business-Konto. Solange Meta die Rechte nur zum Testen freigibt, brauchst du auch eine angenommene Tester-Einladung.";
    clearTimeout(state.oauthTimer); state.oauthTimer = setTimeout(pollConnection, 3000);
  } catch (error) { popup?.close(); showError(error.message); }
}
async function pollConnection() {
  try {
    clearTimeout(state.saveTimer);
    if (!await saveDraft()) return;
    const result = await request("/api/oauth/poll", { method: "POST" });
    if (result.state === "waiting") { state.oauthTimer = setTimeout(pollConnection, 4000); return; }
    if (result.state === "connected") {
      clearTimeout(state.saveTimer); await reloadAccount();
      document.querySelector("#oauthProgress").hidden = true; document.querySelector("#oauthLink").hidden = true;
      showSuccess(`@${result.account.username} ist verbunden und geprüft.`);
    }
  } catch (error) { showError(error.message); }
}
document.querySelector("#checkConnection").addEventListener("click", async () => {
  try { const data = await request("/api/accounts/check", { method: "POST" }); await loadProfile(); showSuccess(`Verbindung zu @${data.account.username} funktioniert.`); }
  catch (error) { showError(error.message); }
});

(async () => {
  await loadProfile();
  await loadTemplates();
  state.draftId = localStorage.getItem(draftKey());
  if (state.draftId) { try { fillDraft((await request(`/api/drafts/${state.draftId}`)).draft); } catch { localStorage.removeItem(draftKey()); state.draftId = null; } }
  await loadPosts();
  try { const health = await request("/api/setup"); document.querySelector("#systemCheck").textContent =
    [health.python ? "Python bereit" : "Python prüfen", health.packages ? "Pakete bereit" : "Pakete prüfen",
     health.chatgpt_login ? "Codex mit ChatGPT angemeldet" : "Bitte Codex mit ChatGPT anmelden",
     health.shortcut ? "Desktop-Verknüpfung vorhanden" : "Desktop-Verknüpfung: Installer ausführen"].join(" · ");
  } catch { document.querySelector("#systemCheck").textContent = "Die Systemprüfung ist gerade nicht verfügbar. Starte Studio bei Bedarf neu."; }
  pollConnection();
})();
function applyMedia(draft) {
  state.media = draft;
  const carousel = state.mediaType === "carousel", video = state.mediaType === "video";
  const items = draft.carousel || [];
  state.slide = Math.min(state.slide, Math.max(0, items.length - 1));
  const source = carousel ? items[state.slide]?.preview_url : draft.preview_url;
  state.hasImage = Boolean(video ? draft.video_url : source);
  preview.hidden = video || !source;
  if (source && !video) preview.src = source + "?v=" + Date.now();
  const player = document.querySelector("#videoPreview");
  player.hidden = !video || !draft.video_url;
  if (video && draft.video_url) {
    if (player.dataset.source !== draft.video_url) { player.src = draft.video_url + "?v=" + Date.now(); player.dataset.source = draft.video_url; }
  } else { player.pause(); player.removeAttribute("src"); delete player.dataset.source; }
  document.querySelector("#mediaStage").hidden = !state.hasImage;
  emptyPreview.hidden = state.hasImage;
  document.querySelector("#carouselBadge").hidden = !carousel || !items.length;
  document.querySelector("#carouselBadge").textContent = `${state.slide + 1}/${items.length}`;
  const previous = document.querySelector("#previousSlide"), next = document.querySelector("#nextSlide");
  previous.hidden = next.hidden = !carousel || items.length < 2;
  previous.disabled = state.slide === 0; next.disabled = state.slide >= items.length - 1;
  renderCarousel(); updateVisualControls();
}
for (const [selector, direction] of [["#previousSlide", -1], ["#nextSlide", 1]]) {
  document.querySelector(selector).addEventListener("click", event => {
    event.stopPropagation(); state.slide += direction; applyMedia(state.media);
  });
}
function renderCarousel() {
  const list = document.querySelector("#carouselItems"); list.textContent = ""; list.hidden = state.mediaType !== "carousel";
  (state.media.carousel || []).forEach((item, index, items) => {
    const row = document.createElement("div"); row.className = "carousel-item" + (index === state.slide ? " selected" : "");
    const thumb = document.createElement("button"); thumb.className = "carousel-thumb"; thumb.title = `Bild ${index + 1} in der Vorschau anzeigen`;
    const img = document.createElement("img"); img.src = item.preview_url + "?v=" + Date.now(); img.alt = `Bild ${index + 1}`; thumb.append(img);
    thumb.addEventListener("click", () => { state.slide = index; applyMedia(state.media); });
    const label = document.createElement("label"); label.textContent = `Bild ${index + 1} · Alternativtext (optional)`;
    const input = document.createElement("input"); input.maxLength = 1000; input.value = item.alt_text || ""; input.placeholder = "Was ist auf diesem Bild zu sehen?";
    input.addEventListener("input", () => { item.alt_text = input.value; queueSave(); }); label.append(input);
    const actions = document.createElement("div"); actions.className = "item-actions";
    [["left", "←", "Bild nach vorne", index === 0], ["right", "→", "Bild nach hinten", index === items.length - 1], ["remove", "×", "Bild entfernen", false]].forEach(([action, text, title, disabled]) => {
      const button = document.createElement("button"); button.className = "carousel-action"; button.textContent = text; button.title = title; button.setAttribute("aria-label", title); button.disabled = disabled;
      button.addEventListener("click", () => carouselAction(item.id, action)); actions.append(button);
    });
    row.append(thumb, label, actions); list.append(row);
  });
}
async function carouselAction(id, action, alt = "") {
  if (state.taskBusy || state.mediaBusy) return;
  state.mediaBusy = true;
  try {
    if (!await saveDraft()) return;
    const data = await request(`/api/drafts/${state.draftId}/media`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, action, alt_text: alt }) });
    applyMedia(data.draft);
  } catch (error) { showError(error.message); }
  finally { state.mediaBusy = false; }
}
async function uploadFiles(files) {
  if (!files.length || state.taskBusy || state.mediaBusy) return;
  const carousel = state.mediaType === "carousel", video = state.mediaType === "video";
  if (!carousel && files.length > 1) { showError("Wähle eine Datei oder wechsle für mehrere Bilder zum Karussell."); return; }
  if (carousel && (state.media.carousel?.length || 0) + files.length > 10) { showError("Ein Karussell kann höchstens zehn Bilder enthalten."); return; }
  if (files.some(file => file.size > (video ? 100_000_000 : 8_000_000))) { showError(video ? "Das Video darf höchstens 100 MB groß sein." : "Jedes Bild darf höchstens 8 MB groß sein."); return; }
  state.mediaBusy = true; replaceImageButton.disabled = true;
  document.querySelectorAll('input[name="mediaType"]').forEach(input => { input.disabled = true; });
  sendNowButton.disabled = scheduleButton.disabled = true;
  try {
    if (state.mediaType === "image") { await uploadImage(files[0]); return; }
    const id = await ensureDraft(); if (!await saveDraft()) return;
    for (const [index, file] of files.entries()) {
      replaceImageButton.textContent = video ? "Video wird geprüft …" : `Bild ${index + 1} von ${files.length} …`;
      const form = new FormData(); form.append("file", file);
      const result = await request(`/api/drafts/${id}/media`, { method: "POST", body: form });
      if (video) delete document.querySelector("#videoPreview").dataset.source;
      applyMedia(result.draft);
    }
    showSuccess(video ? "Video ist bereit. Caption ergänzen und senden oder planen." : "Bilder hinzugefügt. Reihenfolge und Ausschnitte kannst du unten prüfen.");
    await loadPosts();
  } catch (error) { showError(error.message); }
  finally {
    state.mediaBusy = false; imageInput.value = ""; replaceImageButton.disabled = false;
    document.querySelectorAll('input[name="mediaType"]').forEach(input => { input.disabled = false; });
    sendNowButton.disabled = scheduleButton.disabled = false; updateVisualControls();
  }
}
document.querySelectorAll('input[name="mediaType"]').forEach(input => input.addEventListener("change", async () => {
  if (state.mediaBusy) return;
  state.mediaType = input.value;
  document.querySelector("#previewMode").value = input.value === "video" ? "reel" : "feed";
  applyMedia(state.media);
  if (state.draftId) await saveDraft();
}));
function updateOverlay() {
  const enabled = document.querySelector("#showOverlay").checked;
  const reel = document.querySelector("#previewMode").value === "reel";
  const mockup = document.querySelector("#mockup");
  mockup.classList.toggle("enabled", enabled); mockup.classList.toggle("reel", enabled && reel);
  document.querySelector("#previewModeLabel").hidden = !enabled;
  document.querySelector("#reelOverlay").hidden = !enabled || !reel || !state.hasImage;
  document.querySelector("#feedHeader").hidden = document.querySelector("#feedFooter").hidden = !enabled || reel;
  document.querySelector("#overlayNote").hidden = !enabled;
  const caption = fields.caption.value || "Hier steht später deine Caption …";
  document.querySelector("#feedCaption").textContent = caption.slice(0, 120) + (caption.length > 120 ? " … mehr" : "");
  document.querySelector("#reelCaption").textContent = caption.slice(0, 70) + (caption.length > 70 ? " … mehr" : "");
}
document.querySelector("#showOverlay").addEventListener("change", updateOverlay);
document.querySelector("#previewMode").addEventListener("change", updateOverlay);
fields.caption.addEventListener("input", updateOverlay);
async function loadTemplates() {
  try {
    const data = await request("/api/image-templates"); state.templates = data.templates; state.styles = data.styles; state.customOptions = data.custom_options;
    const saved = await request("/api/image-style"); state.savedCustomStyle = saved.custom; state.customStyle = { ...saved.custom };
    const select = document.querySelector("#imageTemplate");
    state.templates.forEach(item => select.add(new Option(item.label, item.id)));
    for (const [key, selector] of [["background", "#customBackground"], ["accent", "#customAccent"], ["layout", "#customLayout"]]) {
      const control = document.querySelector(selector);
      (state.customOptions[key] || []).forEach(option => control.add(new Option(option.label, option.id)));
      control.value = state.customStyle[key];
    }
  } catch (error) { showError(error.message); }
}
function selectedTemplate() { return state.templates.find(item => item.id === document.querySelector("#imageTemplate").value); }
function updateTemplatePreview() {
  const template = selectedTemplate(); if (!template) return;
  document.querySelector("#templatePreview").src = template.style_previews?.[state.imageStyle] || template.preview;
}
function customOption(key) { return (state.customOptions[key] || []).find(item => item.id === state.customStyle[key]); }
function styleInstruction(style, visualOnly = false) {
  if (style?.id !== "custom") return (visualOnly ? style?.visual_instruction : style?.instruction) || "";
  const background = customOption("background"), accent = customOption("accent"), layout = customOption("layout");
  if (!background || !accent || !layout) return "";
  if (visualOnly) return `Stimme Licht, Umgebung und kleine Details auf ${background.label} (${background.color}) und wenige Akzente in ${accent.label} (${accent.color}) ab. Die Farben sollen zum Motiv passen und nicht wie ein künstlicher Filter wirken. ${layout.visual_instruction} Der beschriebene Bildaufbau bleibt erhalten.`;
  return `Gestalte die Farbwelt mit ${background.label} (${background.color}) als überwiegender Grundfarbe. Setze ${accent.label} (${accent.color}) gezielt für kleine Blickfänge ein. Wenn Text im Motiv vorkommt, verwende ${background.text} für die Schrift und achte auf klaren Kontrast. ${layout.instruction} Erhalte den zuvor beschriebenen Bildaufbau.`;
}
function updateCustomStyleUi() {
  document.querySelector("#imageCustomControls").hidden = state.imageStyle !== "custom";
  const background = customOption("background"), accent = customOption("accent"), layout = customOption("layout");
  if (!background || !accent || !layout) return;
  for (const [key, selector] of [["background", "#customBackground"], ["accent", "#customAccent"], ["layout", "#customLayout"]]) document.querySelector(selector).value = state.customStyle[key];
  const sample = document.querySelector("#customStyleSample");
  sample.style.setProperty("--sample-bg", background.color);
  sample.style.setProperty("--sample-text", background.text);
  sample.style.setProperty("--sample-accent", accent.color);
  sample.dataset.layout = layout.id;
  const swatches = document.querySelector('#imageStyles input[value="custom"]')?.closest("label")?.querySelector(".swatches");
  if (swatches) {
    swatches.replaceChildren();
    [background.color, accent.color, background.text].forEach(color => { const dot = document.createElement("i"); dot.style.backgroundColor = color; swatches.append(dot); });
  }
  const remembered = Object.keys(DEFAULT_IMAGE_CUSTOM).every(key => state.customStyle[key] === state.savedCustomStyle[key]);
  document.querySelector("#customStyleSaveState").textContent = remembered ? "Für neue Beiträge gemerkt." : "Bisher nur in diesem Entwurf gespeichert.";
}
for (const [key, selector] of [["background", "#customBackground"], ["accent", "#customAccent"], ["layout", "#customLayout"]]) {
  document.querySelector(selector).addEventListener("change", event => {
    state.customStyle[key] = event.target.value;
    updateCustomStyleUi();
    if (selectedTemplate()) composeTemplatePrompt(); else queueSave();
  });
}
document.querySelector("#saveCustomStyle").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true;
  try {
    const data = await request("/api/image-style", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ custom: state.customStyle }) });
    state.savedCustomStyle = { ...data.custom };
    updateCustomStyleUi();
    showSuccess("Deine Farbmischung steht jetzt auch für neue Beiträge bereit.");
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
});
function incompleteTemplateFields(template) {
  return template.fields.filter(field => !field.optional && !(state.imageInputs[field.id] || "").trim()).map(field => field.label);
}
function templateGuidance(template) {
  const missing = incompleteTemplateFields(template);
  if (missing.length) return "Für ChatGPT fehlen noch: " + missing.join(", ") + ".";
  const short = template.fields.filter(field => !field.optional && (state.imageInputs[field.id] || "").trim().length < 4).map(field => field.label);
  if (short.length) return "Sehr kurze Angaben bei " + short.join(", ") + ": ChatGPT könnte nachfragen. Du kannst trotzdem fortfahren.";
  return "Bereit für ChatGPT. Dein Prompt wird automatisch aktualisiert.";
}
function composeTemplatePrompt() {
  const template = selectedTemplate(); if (!template) return;
  const style = state.styles.find(item => item.id === state.imageStyle) || state.styles[0];
  let prompt = template.prompt.replaceAll("{format}", canvasValue() === "square" ? "1:1 (Quadrat)" : "4:5 (Porträt)")
    .replaceAll("{style}", styleInstruction(style, template.kind === "visual"));
  template.fields.forEach(field => {
    const value = (state.imageInputs[field.id] || "").trim();
    if (field.id === "row3") prompt = prompt.replaceAll("{row3}", value ? `Füge als dritte Zeile exakt „${value}“ hinzu.` : "Füge keine dritte Zeile hinzu.");
    else if (field.id === "subtitle") prompt = prompt.replaceAll("{subtitle}", value ? `Setze als kleine Unterzeile exakt „${value}“.` : "Lass die Unterzeile weg.");
    else prompt = prompt.replaceAll(`{${field.id}}`, value || (field.optional ? "ein schlichtes, zum Inhalt passendes Motiv" : `〔${field.label} fehlt〕`));
  });
  fields.image_prompt.value = prompt;
  const missing = incompleteTemplateFields(template);
  document.querySelector("#templateValidation").textContent = templateGuidance(template);
  document.querySelector("#openChatGPT").disabled = missing.length > 0;
  queueSave();
}
function updateTemplateExample() {
  const template = selectedTemplate();
  document.querySelector("#templateExample").hidden = document.querySelector("#templateInputs").hidden = !template;
  if (!template) { document.querySelector("#openChatGPT").disabled = false; return; }
  updateTemplatePreview();
  document.querySelector("#templatePreview").alt = "Stilbeispiel: " + template.label;
  document.querySelector("#templateTitle").textContent = template.label;
  document.querySelector("#templateDescription").textContent = template.description;
  document.querySelector("#templateTextNote").hidden = !template.fields.some(field => ["title", "statement", "point1", "row1"].includes(field.id));
  const container = document.querySelector("#templateFields"); container.replaceChildren();
  template.fields.forEach(field => {
    const label = document.createElement("label"); label.textContent = field.label;
    const input = document.createElement("input"); input.type = "text"; input.maxLength = 500; input.placeholder = field.placeholder; input.value = state.imageInputs[field.id] || "";
    input.addEventListener("input", () => { state.imageInputs[field.id] = input.value; composeTemplatePrompt(); });
    label.append(input); container.append(label);
  });
  const styles = document.querySelector("#imageStyles"); styles.replaceChildren();
  state.styles.forEach(style => {
    const label = document.createElement("label"); label.className = "style-option";
    const input = document.createElement("input"); input.type = "radio"; input.name = "imageStyle"; input.value = style.id; input.checked = state.imageStyle === style.id;
    input.addEventListener("change", () => { state.imageStyle = style.id; updateCustomStyleUi(); updateTemplatePreview(); composeTemplatePrompt(); });
    const swatches = document.createElement("span"); swatches.className = "swatches";
    if (style.colors.length) style.colors.forEach(color => { const dot = document.createElement("i"); dot.style.backgroundColor = color; swatches.append(dot); });
    else { const free = document.createElement("span"); free.className = "free-colors"; free.textContent = "✦"; free.setAttribute("aria-hidden", "true"); swatches.append(free); }
    label.append(input, swatches, document.createTextNode(style.label)); styles.append(label);
  });
  updateCustomStyleUi();
  const missing = incompleteTemplateFields(template);
  document.querySelector("#templateValidation").textContent = templateGuidance(template);
  document.querySelector("#openChatGPT").disabled = missing.length > 0;
}
document.querySelector("#imageTemplate").addEventListener("change", () => { state.imageInputs = {}; updateTemplateExample(); if (selectedTemplate()) composeTemplatePrompt(); else queueSave(); });
document.querySelectorAll('input[name="canvas"]').forEach(input => input.addEventListener("change", () => { if (selectedTemplate()) composeTemplatePrompt(); }));
async function referenceAction(action) {
  const button = document.querySelector(action === "choose" ? "#chooseReferences" : action === "open" ? "#openReferences" : "#saveReferences");
  button.disabled = true;
  try {
    const data = await request("/api/references", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, path: document.querySelector("#referenceFolder").value }) });
    document.querySelector("#referenceFolder").value = data.path;
    if (action === "open") showSuccess("Referenzordner geöffnet. Bilder bei Bedarf selbst an ChatGPT anhängen.");
    else showSuccess("Referenzordner übernommen.");
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
}
document.querySelector("#chooseReferences").addEventListener("click", () => referenceAction("choose"));
document.querySelector("#saveReferences").addEventListener("click", () => referenceAction("save"));
