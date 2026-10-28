(() => {
  const editor = document.getElementById("editor");
  if (!editor) return;
  const content = JSON.parse(document.getElementById("initial-content").textContent);
  const titleInput = document.getElementById("document-title");
  const templateSelect = document.getElementById("template-select");
  const preview = document.getElementById("document-preview");
  const saveState = document.getElementById("save-state");
  let timer;
  let saveSequence = 0;
  let saveRevision = 0;
  let dirty = false;
  let pending = false;
  let failed = false;

  const capitalizeKeys = new Set(["name", "job_title", "location"]);

  function styleFieldValue(key, value) {
    if (typeof value !== "string") return value;
    const trimmed = value.trim();
    if (!trimmed) return "";
    if (key === "summary" || key === "skills") return trimmed;
    if (key === "email" || key === "phone" || key === "linkedin" || key === "website" || key === "photo") return trimmed;
    return trimmed.replace(/\s+/g, " ").split(/\s+/).map((part) => {
      if (!part) return part;
      if (part.length === 1) return part.toUpperCase();
      if (/^[A-Z0-9&/.-]+$/i.test(part) && !/^[a-z]+$/i.test(part)) return part;
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    }).join(" ");
  }

  function normalizeFieldValue(key, value) {
    if (key === "skills") {
      return typeof value === "string" ? value.split(/\r?\n/).map(s => s.trim()).filter(Boolean) : Array.isArray(value) ? value : [];
    }
    return styleFieldValue(key, value ?? "");
  }

  for (const input of document.querySelectorAll("[data-field]")) {
    const key = input.dataset.field;
    const value = content[key] ?? (key === "skills" ? [] : "");
    input.value = key === "skills" ? (Array.isArray(value) ? value.join("\n") : value) : value;
    if (capitalizeKeys.has(key)) {
      input.classList.add("capitalize-field");
    }
    input.addEventListener("input", () => {
      const nextValue = normalizeFieldValue(key, input.value);
      content[key] = nextValue;
      if (capitalizeKeys.has(key)) {
        const formatted = styleFieldValue(key, input.value);
        input.value = formatted;
        content[key] = formatted;
      }
      updatePreview();
      scheduleSave();
    });
  }

  function appendEntry(list, item = {}) {
    const holder = document.querySelector(`[data-list="${list}"] .entry-list`);
    const node = document.getElementById("entry-template").content.firstElementChild.cloneNode(true);
    for (const input of node.querySelectorAll("[data-entry-field]")) {
      const key = input.dataset.entryField;
      input.value = item[key] || (key === "company" ? item.institution || "" : "");
      if (["title", "company", "institution"].includes(key)) {
        input.classList.add("capitalize-field");
      }
      input.addEventListener("input", () => {
        if (["title", "company", "institution"].includes(key)) {
          input.value = styleFieldValue(key, input.value);
        }
        readEntries(list);
        updatePreview();
        scheduleSave();
      });
    }
    node.querySelector(".remove-entry").addEventListener("click", () => {
      node.remove();
      readEntries(list);
      updatePreview();
      scheduleSave();
    });
    holder.appendChild(node);
  }

  function readEntries(list) {
    content[list] = [...document.querySelectorAll(`[data-list="${list}"] .entry-card`)].map(card => {
      const entry = {};
      for (const field of card.querySelectorAll("[data-entry-field]")) entry[field.dataset.entryField] = field.value;
      return entry;
    });
  }

  for (const list of ["experience", "education", "projects", "certifications"]) {
    const items = Array.isArray(content[list]) ? content[list] : [];
    items.forEach(item => appendEntry(list, item));
    document.querySelector(`[data-list="${list}"] .add-entry`).addEventListener("click", () => {
      appendEntry(list);
      readEntries(list);
      scheduleSave();
    });
  }

  function setText(selector, text) {
    const element = preview.querySelector(selector);
    if (element) element.textContent = text || "";
  }

  function updatePreview() {
    setText('[data-preview="name"]', content.name || "Your Name");
    setText('[data-preview="job_title"]', content.job_title);
    const photo = content.photo || "";
    const photoEl = preview.querySelector('[data-preview="photo"]');
    const photoWrap = preview.querySelector(".resume-photo-wrap");
    if (photoEl) {
      if (photo) {
        photoEl.src = photo;
        photoEl.hidden = false;
        photoWrap.hidden = false;
      } else {
        photoEl.removeAttribute("src");
        photoEl.hidden = true;
        photoWrap.hidden = true;
      }
    }
    setText('[data-preview="contact"]', [content.email, content.phone, content.location, content.linkedin, content.website].filter(Boolean).join("  ·  "));
    setText('[data-preview="summary"]', content.summary);
    setText('[data-preview="skills"]', Array.isArray(content.skills) ? content.skills.join("  ·  ") : content.skills);
    for (const section of preview.querySelectorAll("[data-preview-section]")) {
      const key = section.dataset.previewSection;
      const hasContent = key === "summary" ? Boolean(content.summary) : key === "skills" ? Boolean(content.skills?.length) : Boolean(content[key]?.length);
      section.hidden = !hasContent;
    }
    for (const list of ["experience", "education", "projects", "certifications"]) {
      const holder = preview.querySelector(`[data-preview-list="${list}"]`);
      holder.replaceChildren();
      for (const item of content[list] || []) {
        if (!Object.values(item).some(value => String(value).trim())) continue;
        const block = document.createElement("div");
        block.className = "resume-entry";
        const heading = document.createElement("strong");
        heading.textContent = [item.title, item.company || item.institution, item.dates].filter(Boolean).join(" · ");
        const description = document.createElement("p");
        description.textContent = item.description || "";
        block.append(heading, description);
        holder.appendChild(block);
      }
      preview.querySelector(`[data-preview-section="${list}"]`).hidden = holder.childElementCount === 0;
    }
  }

  async function save() {
    const sequence = ++saveSequence;
    const revision = saveRevision;
    pending = true;
    failed = false;
    saveState.textContent = "Saving…";
    saveState.classList.remove("save-error");
    try {
      const response = await fetch(editor.dataset.saveUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
        },
        body: JSON.stringify({ title: titleInput.value, template: templateSelect.value, content }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || "Could not save changes.");
      }
      if (sequence === saveSequence) {
        dirty = revision !== saveRevision;
        pending = dirty;
        saveState.textContent = dirty ? "Saving…" : "All changes saved";
      }
      return sequence === saveSequence && !dirty;
    } catch (error) {
      if (sequence === saveSequence) {
        pending = false;
        failed = true;
        saveState.textContent = error.message || "Save failed. Your changes are still on this page.";
        saveState.classList.add("save-error");
      }
      return false;
    }
  }

  function scheduleSave() {
    dirty = true;
    saveRevision++;
    clearTimeout(timer);
    timer = setTimeout(save, 700);
  }
  titleInput.addEventListener("input", scheduleSave);
  templateSelect.addEventListener("change", () => {
    preview.className = `resume-page template-${templateSelect.value}`;
    scheduleSave();
  });
  document.querySelector(".download-pdf").addEventListener("click", async event => {
    event.preventDefault();
    const downloadUrl = event.currentTarget.href;
    clearTimeout(timer);
    while (dirty) {
      const saved = await save();
      if (!saved && failed) return;
    }
    if (!failed) window.location.assign(downloadUrl);
  });
  document.getElementById("print-button").addEventListener("click", () => window.print());
  window.addEventListener("beforeunload", event => {
    if (dirty || pending || failed) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  updatePreview();
})();
