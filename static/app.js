#tester

const renderer = new marked.Renderer();

renderer.code = function (token_or_text, language) {
    const text = typeof token_or_text === "object" ? token_or_text.text : token_or_text;
    const lang = typeof token_or_text === "object" ? token_or_text.lang : language;

    if (lang === "mermaid") {
        return `<div class="mermaid">${text}</div>`;
    }

    return `<pre><code class="language-${lang || ""}">${text}</code></pre>`;
};

marked.use({ renderer: renderer });
mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });

let currentTab = "arch";
let globalData = null;
let expandedStates = {};
let selectedFiles = new Set();
let indexToPathMap = [];
let currentRawMd = "";
let currentSessionId = `session_${Date.now()}`;

async function openSettings() {
    try {
        const response = await fetch("/api/settings");
        const data = await response.json();

        document.getElementById("input-provider").value = data.provider || "gemini";
        document.getElementById("input-gemini-api-key").value = data.gemini_api_key || "";
        document.getElementById("input-gemini-model").value = data.gemini_model || "";
        document.getElementById("input-openai-api-key").value = data.openai_api_key || "";
        document.getElementById("input-openai-model").value = data.openai_model || "gpt-5";

        new bootstrap.Modal(document.getElementById("settingsModal")).show();
    } catch (error) {
        showToast("Failed to load settings", "error");
    }
}

async function saveSettings() {
    const payload = {
        provider: document.getElementById("input-provider").value,
        gemini_api_key: document.getElementById("input-gemini-api-key").value.trim(),
        gemini_model: document.getElementById("input-gemini-model").value.trim(),
        openai_api_key: document.getElementById("input-openai-api-key").value.trim(),
        openai_model: document.getElementById("input-openai-model").value.trim(),
    };

    try {
        const response = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (data.status === "success") {
            showToast("Settings saved successfully", "success");
            const modalEl = document.getElementById("settingsModal");
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();
            return;
        }

        showToast("Failed to save settings", "error");
    } catch (error) {
        showToast("Error saving settings", "error");
    }
}

function showToast(msg, type = "primary") {
    const el = document.getElementById("nexusToast");
    document.getElementById("toast-message").innerText = msg;
    el.className = `toast align-items-center border-0 text-white bg-${type === "error" ? "danger" : (type === "success" ? "success" : "primary")}`;
    new bootstrap.Toast(el).show();
}

function setTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".nav-link").forEach((button) => button.classList.toggle("active", false));
    document.getElementById(`tab-${tab}-btn`)?.classList.add("active");

    if (tab === "scripts") {
        renderScripts();
        return;
    }

    if (tab === "map") {
        renderMindmap();
        return;
    }

    if (tab === "chat") {
        renderChat();
        return;
    }

    renderList();
}

async function fetchUpdate() {
    try {
        const response = await fetch("/api/state");
        globalData = await response.json();

        document.getElementById("status").innerText = `SYNC: ${globalData.last_update}`;

        if (currentTab === "arch") {
            renderList();
        }

        if (globalData.recent_changes.length) {
            document.getElementById("recent-container").innerHTML = `
                <div class="recent-box">
                    <small class="text-danger fw-black uppercase">Live Updates</small>
                    <ul class="list-unstyled mb-0 small mt-1">
                        ${globalData.recent_changes.map((file) => `
                            <li class="text-white-50">
                                <i class="bi bi-record-fill text-danger me-1"></i>${file}
                            </li>
                        `).join("")}
                    </ul>
                </div>
            `;
        }
    } catch (error) {
        console.error(error);
    }
}

function renderList() {
    if (!globalData) return;

    const container = document.getElementById("file-list");
    const scrollPos = container.scrollTop;

    container.innerHTML = "";
    indexToPathMap = [];

    let count = 1;
    const groups = { backend: {}, frontend: {}, other: {} };

    Object.entries(globalData.files).sort().forEach(([path, info]) => {
        if (!groups[info.layer][info.role]) {
            groups[info.layer][info.role] = [];
        }

        groups[info.layer][info.role].push([path, info]);
    });

    ["backend", "frontend", "other"].forEach((layer) => {
        if (!Object.keys(groups[layer]).length) return;

        const layerId = `layer-${layer}`;
        if (expandedStates[layerId] === undefined) {
            expandedStates[layerId] = true;
        }

        const header = document.createElement("div");
        header.className = "layer-header text-uppercase px-2";
        header.innerHTML = `<span>${layer}</span> <i class="bi bi-chevron-${expandedStates[layerId] ? "down" : "right"}"></i>`;
        header.onclick = () => {
            expandedStates[layerId] = !expandedStates[layerId];
            renderList();
        };
        container.appendChild(header);

        if (!expandedStates[layerId]) {
            return;
        }

        Object.entries(groups[layer]).sort().forEach(([role, files]) => {
            const roleId = `role-${layer}-${role}`;
            if (expandedStates[roleId] === undefined) {
                expandedStates[roleId] = true;
            }

            const roleHeader = document.createElement("div");
            roleHeader.className = "role-header text-uppercase ps-3";
            roleHeader.innerHTML = `<i class="bi bi-folder2 text-danger"></i> ${role}s`;
            roleHeader.onclick = (event) => {
                event.stopPropagation();
                expandedStates[roleId] = !expandedStates[roleId];
                renderList();
            };
            container.appendChild(roleHeader);

            if (!expandedStates[roleId]) {
                return;
            }

            files.sort().forEach(([path, info]) => {
                const idx = count++;
                indexToPathMap[idx] = path;

                const isSelected = selectedFiles.has(path);
                const row = document.createElement("div");

                row.className = `file-item ms-4 d-flex align-items-center ${isSelected ? "selected" : ""}`;
                row.innerHTML = `
                    <span class="file-index">${idx}</span>
                    <input type="checkbox" class="file-checkbox" ${isSelected ? "checked" : ""} onchange="toggleFile('${escapeSingleQuotes(path)}')">
                    <span class="text-truncate flex-grow-1" onclick="showInspector('${escapeSingleQuotes(path)}')">
                        ${path.split("/").pop()}
                        ${info.has_context ? '<i class="bi bi-stars text-warning ms-1" title="Engineering Context Generated"></i>' : ""}
                    </span>
                `;

                container.appendChild(row);
            });
        });
    });

    container.scrollTop = scrollPos;
}

function escapeSingleQuotes(value) {
    return value.replace(/'/g, "\\'");
}

function toggleFile(path) {
    if (selectedFiles.has(path)) {
        selectedFiles.delete(path);
    } else {
        selectedFiles.add(path);
    }

    renderList();
}

function clearSelections() {
    selectedFiles.clear();
    renderList();
}

function selectByNumbers() {
    const input = document.getElementById("number-input");
    const nums = input.value
        .split(/[,\s]+/)
        .map((value) => parseInt(value.trim(), 10))
        .filter((value) => !Number.isNaN(value));

    nums.forEach((num) => {
        if (indexToPathMap[num]) {
            selectedFiles.add(indexToPathMap[num]);
        }
    });

    input.value = "";
    renderList();
}

function copyAllPathsWithNumbers() {
    if (!globalData) return;

    let text = "PROJECT FILE LIST:\n\n";
    let count = 1;

    Object.keys(globalData.files).sort().forEach((path) => {
        text += `[${count}] ${path}\n`;
        count += 1;
    });

    navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard"));
}

async function bundleSelected() {
    if (selectedFiles.size === 0) {
        showToast("Select files first!", "error");
        return;
    }

    const response = await fetch("/api/bundle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: Array.from(selectedFiles) }),
    });

    const data = await response.json();

    if (data.status === "success") {
        showToast("Bundle generated", "success");
    } else {
        showToast(data.message || "Bundle failed", "error");
    }
}

function toggleRawMd() {
    const ctxDiv = document.getElementById("ai-context-content");
    const btnRaw = document.getElementById("btn-raw-md");

    if (ctxDiv.classList.contains("showing-raw")) {
        ctxDiv.classList.remove("showing-raw");
        renderMarkdownWithMermaid(currentRawMd, "ai-context-content");
        btnRaw.innerHTML = `<i class="bi bi-code-slash me-1"></i>View Raw`;
        return;
    }

    ctxDiv.classList.add("showing-raw");
    const escapedMd = currentRawMd.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    ctxDiv.innerHTML = `<pre><code class="text-warning">${escapedMd}</code></pre>`;
    btnRaw.innerHTML = `<i class="bi bi-eye me-1"></i>Preview`;
}

async function renderMarkdownWithMermaid(mdContent, containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = marked.parse(mdContent);

    try {
        await mermaid.run({ querySelector: ".mermaid" });
    } catch (error) {
        console.warn("Mermaid parsing failed", error);
        document.querySelectorAll(".mermaid").forEach((element) => {
            if (!element.querySelector("svg")) {
                element.innerHTML = `
                    <div class="mermaid-error">
                        <strong><i class="bi bi-exclamation-triangle me-2"></i>Mermaid Render Error</strong><br>
                        AI generated invalid syntax.<br>
                        ${error.message.split("\n")[0]}
                    </div>
                `;
            }
        });
    }
}

async function fetchAIContext(path) {
    const ctxDiv = document.getElementById("ai-context-content");
    const btnRaw = document.getElementById("btn-raw-md");

    if (btnRaw) {
        btnRaw.disabled = true;
    }

    ctxDiv.classList.remove("showing-raw");
    ctxDiv.innerHTML = `<div class="text-center p-4 text-secondary"><div class="spinner-border spinner-border-sm me-2"></div>Loading Engineering Docs...</div>`;

    const response = await fetch(`/api/context?path=${encodeURIComponent(path)}`);
    const data = await response.json();

    if (data.status === "success") {
        currentRawMd = data.data;
        renderMarkdownWithMermaid(currentRawMd, "ai-context-content");

        if (btnRaw) {
            btnRaw.disabled = false;
            btnRaw.innerHTML = `<i class="bi bi-code-slash me-1"></i>View Raw`;
        }

        return;
    }

    currentRawMd = "";
    ctxDiv.innerHTML = `<div class="alert alert-dark border-secondary text-center small"><i class="bi bi-cpu me-2"></i>No AI context generated. Click Build Context above.</div>`;
}

async function buildAIContext(path) {
    const btn = document.getElementById("btn-build-ctx");
    const btnRaw = document.getElementById("btn-raw-md");

    btn.innerHTML = `<div class="spinner-border spinner-border-sm me-2"></div>Generating...`;
    btn.disabled = true;

    if (btnRaw) {
        btnRaw.disabled = true;
    }

    const response = await fetch("/api/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
    });

    const data = await response.json();

    btn.disabled = false;
    btn.innerHTML = `<i class="bi bi-stars me-2"></i>Update Context`;

    if (data.status === "success") {
        currentRawMd = data.data;
        renderMarkdownWithMermaid(currentRawMd, "ai-context-content");

        if (btnRaw) {
            btnRaw.disabled = false;
        }

        showToast("Context generated successfully", "success");
        fetchUpdate();
        return;
    }

    showToast(`Error: ${data.message}`, "error");
}

function showInspector(path) {
    const info = globalData.files[path];
    const inspector = document.getElementById("inspector");

    inspector.innerHTML = `
        <div class="d-flex justify-content-between align-items-start border-bottom border-secondary pb-3 mb-4">
            <div>
                <h4 class="text-white mb-1 fw-black">${path.split("/").pop()}</h4>
                <code class="text-secondary small font-monospace">${path}</code>
            </div>
            <div class="d-flex gap-2">
                <button id="btn-raw-md" class="btn btn-outline-info btn-sm fw-bold" onclick="toggleRawMd()" disabled>
                    <i class="bi bi-code-slash me-1"></i>View Raw
                </button>
                <button id="btn-build-ctx" class="btn btn-outline-warning btn-sm fw-bold" onclick="buildAIContext('${escapeSingleQuotes(path)}')">
                    <i class="bi bi-stars me-1"></i>${info.has_context ? "Update Context" : "Build Context"}
                </button>
            </div>
        </div>

        <div class="row">
            <div class="col-12">
                <div id="ai-context-content" class="md-content"></div>
            </div>
        </div>
    `;

    fetchAIContext(path);
}

async function renderMindmap() {
    const inspector = document.getElementById("inspector");
    inspector.innerHTML = `<div id="mindmap-container" class="p-3"><div class="mermaid" id="graph-target"></div></div>`;

    let graphData = "graph LR\n";

    globalData.routes.forEach((route) => {
        const routeId = `R_${route.path.replace(/[^a-z0-9]/gi, "_")}`;
        const controllerName = route.controller.replace(/[^a-z0-9]/gi, "_");
        graphData += `  ${routeId}["${route.path}"] -- maps to --> ${controllerName}\n`;
    });

    try {
        const { svg } = await mermaid.render(`mermaid-svg-${Date.now()}`, graphData);
        document.getElementById("graph-target").innerHTML = svg;
    } catch (error) {
        console.error(error);
    }
}

async function runAITool(toolType, btnElement) {
    const originalHtml = btnElement.innerHTML;
    btnElement.innerHTML = `<div class="spinner-border spinner-border-sm me-2 mb-2 d-block mx-auto"></div>GENERATING...`;
    btnElement.disabled = true;

    const endpoint = toolType === "gem_context" ? "/api/generate-gem-context" : "/api/ai-tool";
    const payload = toolType === "gem_context" ? {} : { type: toolType };

    const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    const data = await response.json();

    btnElement.disabled = false;
    btnElement.innerHTML = originalHtml;

    if (data.status === "success") {
        showToast(`Success: Saved to ${data.file || "output"}`, "success");

        const inspector = document.getElementById("inspector");
        inspector.innerHTML = `
            <div class="border-bottom border-secondary pb-3 mb-4">
                <h4 class="text-white mb-1 fw-black text-uppercase">AI OUTPUT: ${toolType.replace("_", " ")}</h4>
                <code class="text-secondary small font-monospace">Saved locally: ${data.file || "-"}</code>
                <div class="small text-secondary mt-2">Provider: ${data.provider || "-"} | Model: ${data.model || "-"}</div>
            </div>
            <div id="ai-context-content" class="md-content"></div>
        `;

        renderMarkdownWithMermaid(data.data, "ai-context-content");
        return;
    }

    showToast(`Error: ${data.message}`, "error");
}

function renderScripts() {
    document.getElementById("inspector").innerHTML = `
        <div class="p-4">
            <div class="border-bottom border-secondary pb-3 mb-4">
                <h5 class="text-white mb-1 uppercase fw-black">NEXUS SYSTEM CONTROL</h5>
                <p class="text-secondary small mb-0">Direct operations for project analysis and context bundling.</p>
            </div>

            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card bg-black border-secondary p-4 h-100 text-center">
                        <i class="bi bi-robot fs-1 text-warning mb-3"></i>
                        <h6 class="fw-bold">GENERATE GEM CONTEXT</h6>
                        <p class="text-secondary small">Reads entire codebase and creates a master system context file.</p>
                        <button class="btn btn-outline-warning w-100 py-3 mt-auto btn-nexus" onclick="runAITool('gem_context', this)">EXECUTE</button>
                    </div>
                </div>

                <div class="col-md-6">
                    <div class="card bg-black border-secondary p-4 h-100 text-center">
                        <i class="bi bi-shield-check fs-1 text-info mb-3"></i>
                        <h6 class="fw-bold">SECURITY & PERF AUDIT</h6>
                        <p class="text-secondary small">Deep scan for N+1 queries, anti-patterns, and validation gaps.</p>
                        <button class="btn btn-outline-info w-100 py-3 mt-auto btn-nexus" onclick="runAITool('audit', this)">EXECUTE</button>
                    </div>
                </div>

                <div class="col-md-6">
                    <div class="card bg-black border-secondary p-4 h-100 text-center">
                        <i class="bi bi-diagram-3 fs-1 text-success mb-3"></i>
                        <h6 class="fw-bold">GENERATE DB ERD</h6>
                        <p class="text-secondary small">Scans models and migrations to auto-generate a Mermaid ERD.</p>
                        <button class="btn btn-outline-success w-100 py-3 mt-auto btn-nexus" onclick="runAITool('erd', this)">EXECUTE</button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderChat() {
    const selectedFilesList = Array.from(selectedFiles);

    document.getElementById("inspector").innerHTML = `
        <div class="d-flex flex-column h-100">
            <div class="border-bottom border-secondary pb-3 mb-3">
                <div class="d-flex justify-content-between align-items-start gap-3">
                    <div>
                        <h4 class="text-white mb-1 fw-black">NEXUS COPILOT</h4>
                        <div class="small text-secondary">Grounded by current file selection.</div>
                    </div>

                    <div class="d-flex gap-2 align-items-center">
                        <select id="chat-mode" class="form-select form-select-sm bg-black border-secondary text-white">
                            <option value="ask">Ask</option>
                            <option value="analyze">Analyze</option>
                            <option value="plan">Plan</option>
                            <option value="refactor">Refactor</option>
                        </select>
                    </div>
                </div>

                <div class="mt-3">
                    <div class="small text-secondary mb-2">Selected files</div>
                    <div class="d-flex flex-wrap gap-2">
                        ${selectedFilesList.length
                            ? selectedFilesList.map((path) => `<span class="badge text-bg-secondary">${path}</span>`).join("")
                            : '<span class="badge text-bg-dark border border-secondary">No files selected</span>'}
                    </div>
                </div>
            </div>

            <div id="chat-messages" class="flex-grow-1 overflow-auto mb-3" style="min-height: 420px;"></div>

            <div class="border-top border-secondary pt-3">
                <div class="mb-3">
                    <textarea id="chat-input" class="form-control bg-black border-secondary text-white" rows="6" placeholder="Ask Nexus Copilot..."></textarea>
                </div>

                <div class="d-flex justify-content-end">
                    <button id="chat-send-btn" class="btn btn-danger btn-nexus px-4" onclick="sendChatMessage()">SEND</button>
                </div>
            </div>
        </div>
    `;
}

async function sendChatMessage() {
    const input = document.getElementById("chat-input");
    const mode = document.getElementById("chat-mode").value;
    const button = document.getElementById("chat-send-btn");
    const message = input.value.trim();

    if (!message) {
        return;
    }

    appendChatBubble("user", message);

    input.value = "";
    button.disabled = true;
    button.innerText = "SENDING...";

    const loadingId = appendChatBubble("assistant", "Thinking...");

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: message,
                mode: mode,
                selected_paths: Array.from(selectedFiles),
            }),
        });

        const data = await response.json();
        removeChatBubble(loadingId);

        if (data.status === "success") {
            appendChatBubble(
                "assistant",
                `${data.message}\n\n---\nProvider: ${data.provider || "-"} | Model: ${data.model || "-"}`
            );
        } else {
            appendChatBubble("assistant", `Error: ${data.message}`);
        }
    } catch (error) {
        removeChatBubble(loadingId);
        appendChatBubble("assistant", `Error: ${error.message}`);
    } finally {
        button.disabled = false;
        button.innerText = "SEND";
    }
}

function appendChatBubble(role, content) {
    const container = document.getElementById("chat-messages");
    const bubbleId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    const alignClass = role === "user" ? "justify-content-end" : "justify-content-start";
    const bubbleClass = role === "user" ? "border-danger" : "border-secondary";

    const wrapper = document.createElement("div");
    wrapper.className = `d-flex ${alignClass} mb-3`;
    wrapper.id = bubbleId;

    wrapper.innerHTML = `
        <div class="card bg-black ${bubbleClass}" style="max-width: 85%;">
            <div class="card-body p-3">
                <div class="small text-secondary text-uppercase mb-2">${role}</div>
                <div class="md-content">${marked.parse(content)}</div>
            </div>
        </div>
    `;

    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;

    return bubbleId;
}

function removeChatBubble(id) {
    const element = document.getElementById(id);
    if (element) {
        element.remove();
    }
}

setInterval(fetchUpdate, 3000);
fetchUpdate();
document.addEventListener("shown.bs.collapse", (event) => {
    expandedStates[event.target.id] = true;
});
document.addEventListener("hidden.bs.collapse", (event) => {
    expandedStates[event.target.id] = false;
});
