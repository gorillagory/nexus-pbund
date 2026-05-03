window.NexusChat = {
    render() {
        const selectedFilesList = Array.from(NexusState.selectedFiles);

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
                            ${
                                selectedFilesList.length
                                    ? selectedFilesList.map((path) => `<span class="badge text-bg-secondary">${path}</span>`).join("")
                                    : '<span class="badge text-bg-dark border border-secondary">No files selected</span>'
                            }
                        </div>
                    </div>
                </div>

                <div id="chat-messages" class="flex-grow-1 overflow-auto mb-3" style="min-height: 420px;"></div>

                <div class="border-top border-secondary pt-3">
                    <div class="mb-3">
                        <textarea id="chat-input" class="form-control bg-black border-secondary text-white" rows="6" placeholder="Ask Nexus Copilot..."></textarea>
                    </div>

                    <div class="d-flex justify-content-between gap-2">
                        <button id="chat-bundle-btn" class="btn btn-outline-secondary btn-nexus px-4" onclick="NexusChat.buildBundle(this)">BUILD BUNDLE</button>
                        <button id="chat-send-btn" class="btn btn-danger btn-nexus px-4" onclick="NexusChat.send()">SEND</button>
                    </div>
                </div>
            </div>
        `;
    },

    async send() {
        const input = document.getElementById("chat-input");
        const mode = document.getElementById("chat-mode").value;
        const button = document.getElementById("chat-send-btn");
        const message = input.value.trim();

        if (!message) {
            return;
        }

        this.appendBubble("user", message);

        input.value = "";
        button.disabled = true;
        button.innerText = "SENDING...";

        const loadingId = this.appendBubble("assistant", "Thinking...");

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: NexusState.currentSessionId,
                    message: message,
                    mode: mode,
                    selected_paths: Array.from(NexusState.selectedFiles),
                }),
            });

            const data = await response.json();
            this.removeBubble(loadingId);

            if (data.status === "success") {
                this.appendBubble(
                    "assistant",
                    `${data.message}\n\n---\nProvider: ${data.provider || "-"} | Model: ${data.model || "-"} | Profile: ${data.task_profile || "-"} | Selection: ${data.selection_mode || "-"}`
                );
            } else {
                this.appendBubble("assistant", `Error: ${data.message}`);
            }
        } catch (error) {
            this.removeBubble(loadingId);
            this.appendBubble("assistant", `Error: ${error.message}`);
        } finally {
            button.disabled = false;
            button.innerText = "SEND";
        }
    },

    async buildBundle(btnElement) {
        const input = document.getElementById("chat-input");
        const mode = document.getElementById("chat-mode").value;
        const message = input.value.trim();
        const originalHtml = btnElement.innerHTML;

        btnElement.disabled = true;
        btnElement.innerHTML = "BUILDING...";

        try {
            const response = await fetch("/api/chat-bundle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mode: mode || "task",
                    message: message,
                    selected_paths: Array.from(NexusState.selectedFiles),
                }),
            });

            const data = await response.json();

            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;

            if (data.status === "success") {
                this.appendBubble(
                    "assistant",
                    `Bundle ready.\n\nTXT: ${data.txt_file}\nJSON: ${data.json_file}\nSelected files: ${data.selected_count}\nRelated files: ${data.related_count}`
                );
                NexusCore.showToast(`Bundle ready: ${data.txt_file}`, "success");
                return;
            }

            this.appendBubble("assistant", `Error: ${data.message}`);
            NexusCore.showToast(`Error: ${data.message}`, "error");
        } catch (error) {
            btnElement.disabled = false;
            btnElement.innerHTML = originalHtml;
            this.appendBubble("assistant", `Error: ${error.message}`);
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    appendBubble(role, content) {
        const container = document.getElementById("chat-messages");
        const bubbleId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

        const alignClass = role === "user" ? "justify-content-end" : "justify-content-start";
        const borderClass = role === "user" ? "border-danger" : "border-secondary";

        const wrapper = document.createElement("div");
        wrapper.className = `d-flex ${alignClass} mb-3`;
        wrapper.id = bubbleId;

        wrapper.innerHTML = `
            <div class="card bg-black ${borderClass}" style="max-width: 85%;">
                <div class="card-body p-3">
                    <div class="small text-secondary text-uppercase mb-2">${role}</div>
                    <div class="md-content">${marked.parse(content)}</div>
                </div>
            </div>
        `;

        container.appendChild(wrapper);
        container.scrollTop = container.scrollHeight;

        return bubbleId;
    },

    removeBubble(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    },
};
