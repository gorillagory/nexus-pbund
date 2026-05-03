window.NexusInspector = {
    toggleRawMd() {
        const ctxDiv = document.getElementById("ai-context-content");
        const btnRaw = document.getElementById("btn-raw-md");

        if (ctxDiv.classList.contains("showing-raw")) {
            ctxDiv.classList.remove("showing-raw");
            NexusCore.renderMarkdownWithMermaid(NexusState.currentRawMd, "ai-context-content");
            btnRaw.innerHTML = `<i class="bi bi-code-slash me-1"></i>View Raw`;
            return;
        }

        ctxDiv.classList.add("showing-raw");
        const escapedMd = NexusState.currentRawMd.replace(/</g, "&lt;").replace(/>/g, "&gt;");
        ctxDiv.innerHTML = `<pre><code class="text-warning">${escapedMd}</code></pre>`;
        btnRaw.innerHTML = `<i class="bi bi-eye me-1"></i>Preview`;
    },

    async fetchContext(path) {
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
            NexusState.currentRawMd = data.data;
            await NexusCore.renderMarkdownWithMermaid(NexusState.currentRawMd, "ai-context-content");

            if (btnRaw) {
                btnRaw.disabled = false;
                btnRaw.innerHTML = `<i class="bi bi-code-slash me-1"></i>View Raw`;
            }

            return;
        }

        NexusState.currentRawMd = "";
        ctxDiv.innerHTML = `<div class="alert alert-dark border-secondary text-center small"><i class="bi bi-cpu me-2"></i>No AI context generated. Click Build Context above.</div>`;
    },

    async buildContext(path) {
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
            NexusState.currentRawMd = data.data;
            await NexusCore.renderMarkdownWithMermaid(NexusState.currentRawMd, "ai-context-content");

            if (btnRaw) {
                btnRaw.disabled = false;
            }

            NexusCore.showToast("Context generated successfully", "success");
            NexusApp.fetchUpdate();
            return;
        }

        NexusCore.showToast(`Error: ${data.message}`, "error");
    },

    show(path) {
        const info = NexusState.globalData.files[path];
        const inspector = document.getElementById("inspector");

        inspector.innerHTML = `
            <div class="d-flex justify-content-between align-items-start border-bottom border-secondary pb-3 mb-4">
                <div>
                    <h4 class="text-white mb-1 fw-black">${path.split("/").pop()}</h4>
                    <code class="text-secondary small font-monospace">${path}</code>
                </div>
                <div class="d-flex gap-2">
                    <button id="btn-raw-md" class="btn btn-outline-info btn-sm fw-bold" onclick="NexusInspector.toggleRawMd()" disabled>
                        <i class="bi bi-code-slash me-1"></i>View Raw
                    </button>
                    <button id="btn-build-ctx" class="btn btn-outline-warning btn-sm fw-bold" onclick="NexusInspector.buildContext('${NexusCore.escapeSingleQuotes(path)}')">
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

        this.fetchContext(path);
    },
};
