window.NexusScripts = {
    async runAITool(toolType, btnElement) {
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
            NexusCore.showToast(`Success: Saved to ${data.file || "output"}`, "success");

            const inspector = document.getElementById("inspector");
            inspector.innerHTML = `
                <div class="border-bottom border-secondary pb-3 mb-4">
                    <h4 class="text-dark mb-1 fw-semibold text-uppercase">AI OUTPUT: ${toolType.replace("_", " ")}</h4>
                    <code class="text-secondary small font-monospace">Saved locally: ${data.file || "-"}</code>
                    <div class="small text-secondary mt-2">
                        Provider: ${data.provider || "-"} |
                        Model: ${data.model || "-"} |
                        Profile: ${data.task_profile || "-"} |
                        Selection: ${data.selection_mode || "-"}
                    </div>
                </div>
                <div id="ai-context-content" class="md-content"></div>
            `;

            NexusCore.renderMarkdownWithMermaid(data.data, "ai-context-content");
            return;
        }

        NexusCore.showToast(`Error: ${data.message}`, "error");
    },

    async buildChatBundle(btnElement) {
        const originalHtml = btnElement.innerHTML;
        btnElement.innerHTML = `<div class="spinner-border spinner-border-sm me-2 mb-2 d-block mx-auto"></div>BUILDING...`;
        btnElement.disabled = true;

        const payload = {
            mode: "task",
            message: "Build a task-oriented Nexus bundle for external AI review.",
            selected_paths: Array.from(NexusState.selectedFiles),
        };

        try {
            const response = await fetch("/api/chat-bundle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;

            if (data.status === "success") {
                NexusCore.showToast(`Bundle ready: ${data.txt_file}`, "success");

                const inspector = document.getElementById("inspector");
                inspector.innerHTML = `
                    <div class="border-bottom border-secondary pb-3 mb-4">
                        <h4 class="text-dark mb-1 fw-semibold text-uppercase">CHAT BUNDLE READY</h4>
                        <code class="text-secondary small font-monospace">TXT: ${data.txt_file}</code><br>
                        <code class="text-secondary small font-monospace">JSON: ${data.json_file}</code>
                        <div class="small text-secondary mt-2">
                            Selected files: ${data.selected_count} | Related files: ${data.related_count}
                        </div>
                    </div>
                    <div class="md-content">
                        <p>Use the generated TXT bundle when sending targeted context for review or refactor work.</p>
                    </div>
                `;
                return;
            }

            NexusCore.showToast(`Error: ${data.message}`, "error");
        } catch (error) {
            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async buildFullMinifiedBundle(btnElement) {
        const originalHtml = btnElement.innerHTML;
        btnElement.innerHTML = `<div class="spinner-border spinner-border-sm me-2 mb-2 d-block mx-auto"></div>BUILDING...`;
        btnElement.disabled = true;

        try {
            const response = await fetch("/api/bundle-all", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });

            const data = await response.json();

            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;

            if (data.status === "success") {
                NexusCore.showToast(`Bundle ready: ${data.file}`, "success");

                const inspector = document.getElementById("inspector");
                inspector.innerHTML = `
                    <div class="border-bottom border-secondary pb-3 mb-4">
                        <h4 class="text-dark mb-1 fw-semibold text-uppercase">FULL MINIFIED BUNDLE READY</h4>
                        <code class="text-secondary small font-monospace">${data.file}</code>
                        <div class="small text-secondary mt-2">Files bundled: ${data.file_count}</div>
                    </div>
                    <div class="md-content">
                        <p>Use this when you want a single full-project minified dump for external review.</p>
                    </div>
                `;
                return;
            }

            NexusCore.showToast(`Error: ${data.message}`, "error");
        } catch (error) {
            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    render() {
        document.getElementById("inspector").innerHTML = `
            <div class="p-4">
                <div class="border-bottom border-secondary pb-3 mb-4">
                    <h5 class="text-dark mb-1 text-uppercase fw-semibold">NEXUS SYSTEM CONTROL</h5>
                    <p class="text-secondary small mb-0">Direct operations for project analysis and context bundling.</p>
                </div>

                <div class="row g-4">
                    <div class="col-md-6">
                        <div class="card bg-white border p-4 h-100 text-center">
                            <i class="bi bi-robot fs-1 text-warning mb-3"></i>
                            <h6 class="fw-bold">GENERATE GEM CONTEXT</h6>
                            <p class="text-secondary small">Reads entire codebase and creates a master system context file.</p>
                            <button class="btn btn-outline-warning w-100 py-3 mt-auto btn-nexus" onclick="NexusScripts.runAITool('gem_context', this)">EXECUTE</button>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="card bg-white border p-4 h-100 text-center">
                            <i class="bi bi-shield-check fs-1 text-info mb-3"></i>
                            <h6 class="fw-bold">SECURITY & PERF AUDIT</h6>
                            <p class="text-secondary small">Deep scan for N+1 queries, anti-patterns, and validation gaps.</p>
                            <button class="btn btn-outline-info w-100 py-3 mt-auto btn-nexus" onclick="NexusScripts.runAITool('audit', this)">EXECUTE</button>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="card bg-white border p-4 h-100 text-center">
                            <i class="bi bi-diagram-3 fs-1 text-success mb-3"></i>
                            <h6 class="fw-bold">GENERATE DB ERD</h6>
                            <p class="text-secondary small">Scans models and migrations to auto-generate a Mermaid ERD.</p>
                            <button class="btn btn-outline-success w-100 py-3 mt-auto btn-nexus" onclick="NexusScripts.runAITool('erd', this)">EXECUTE</button>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="card bg-white border p-4 h-100 text-center">
                            <i class="bi bi-box-arrow-up-right fs-1 text-danger mb-3"></i>
                            <h6 class="fw-bold">BUILD CHAT BUNDLE</h6>
                            <p class="text-secondary small">Build a task-oriented export using selected files, related files, recent changes, and saved contexts.</p>
                            <button class="btn btn-outline-danger w-100 py-3 mt-auto btn-nexus" onclick="NexusScripts.buildChatBundle(this)">EXECUTE</button>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="card bg-white border p-4 h-100 text-center">
                            <i class="bi bi-file-earmark-zip fs-1 text-primary mb-3"></i>
                            <h6 class="fw-bold">BUILD FULL MINIFIED BUNDLE</h6>
                            <p class="text-secondary small">Bundle the entire target project into one minified text file.</p>
                            <button class="btn btn-outline-primary w-100 py-3 mt-auto btn-nexus" onclick="NexusScripts.buildFullMinifiedBundle(this)">EXECUTE</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },
};
