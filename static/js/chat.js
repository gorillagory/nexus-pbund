window.NexusChat = {
    render() {
        const panel = document.getElementById("chat-panel");
        if (panel.dataset.initialized === "true") {
            this.renderSelectedFiles();
            return;
        }

        panel.innerHTML = `
            <div class="d-flex flex-column h-100 chat-interface">
                <div class="mb-3">
                    <div class="small text-secondary mb-2">Selected files</div>
                    <div id="chat-selected-files" class="d-flex flex-wrap gap-2"></div>
                </div>

                <div id="chat-messages" class="flex-grow-1 overflow-auto mb-3"></div>

                <div class="border-top pt-3">
                    <div class="mb-3">
                        <textarea id="chat-input" class="form-control" rows="6" placeholder="Ask Nexus Copilot..."></textarea>
                    </div>

                    <div class="d-flex justify-content-between gap-2">
                        <button id="chat-bundle-btn" class="btn btn-outline-secondary btn-nexus px-4" onclick="NexusChat.buildBundle(this)">BUILD BUNDLE</button>
                        <button id="chat-send-btn" class="btn btn-primary btn-nexus px-4" onclick="NexusChat.send()">SEND</button>
                    </div>
                </div>
            </div>
        `;
        panel.dataset.initialized = "true";
        this.renderSelectedFiles();
    },

    renderSelectedFiles() {
        const selectedFilesContainer = document.getElementById("chat-selected-files");
        if (!selectedFilesContainer) {
            return;
        }

        const selectedFilesList = Array.from(NexusState.selectedFiles);
        selectedFilesContainer.innerHTML = selectedFilesList.length
            ? selectedFilesList.map((path) => `<span class="badge text-bg-primary">${path}</span>`).join("")
            : '<span class="badge text-bg-light border text-secondary">No files selected</span>';
    },

    async loadChatHistory(workspaceId) {
        this.render();
        const container = document.getElementById("chat-messages");
        container.innerHTML = "";

        if (!workspaceId) {
            return;
        }

        try {
            const response = await fetch(`/api/chat-history?workspace_id=${encodeURIComponent(workspaceId)}`);
            const messages = await response.json();
            if (!response.ok) {
                throw new Error(messages.message || "Unable to load chat history.");
            }

            messages.forEach((message) => {
                if (message.role !== "user" && message.role !== "assistant") {
                    return;
                }

                const bubbleId = this.appendBubble(message.role, message.content);
                if (message.role === "assistant") {
                    this.injectActionCards(document.getElementById(bubbleId), message.content);
                }
            });
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async send(persona = "cto") {
        const input = document.getElementById("chat-input");
        const button = document.getElementById("chat-send-btn");
        const message = input.value.trim();

        if (!message) {
            return;
        }

        this.appendBubble("user", message);

        input.value = "";
        button.disabled = true;
        button.innerText = "SENDING...";

        const assistantId = this.appendBubble("assistant", "Thinking...");

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: NexusState.currentSessionId,
                    message: message,
                    persona: persona,
                    selected_paths: Array.from(NexusState.selectedFiles),
                }),
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.message || "Chat request failed.");
            }

            if (!response.body) {
                throw new Error("Streaming response body is unavailable.");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let assistantText = "";

            const consumeEvents = () => {
                let boundary = buffer.indexOf("\n\n");

                while (boundary !== -1) {
                    const event = buffer.slice(0, boundary);
                    buffer = buffer.slice(boundary + 2);

                    const dataLine = event
                        .split("\n")
                        .find((line) => line.startsWith("data:"));

                    if (dataLine) {
                        const payload = JSON.parse(dataLine.slice(5).trim());
                        assistantText += payload.chunk || "";
                        this.updateBubble(assistantId, assistantText);
                    }

                    boundary = buffer.indexOf("\n\n");
                }
            };

            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    buffer += decoder.decode();
                    consumeEvents();
                    const messageContainer = document.querySelector(`#${assistantId} .md-content`);
                    if (messageContainer) {
                        messageContainer.innerHTML = marked.parse(assistantText);
                        this.injectDeployButtons(messageContainer);
                        this.injectTaskButtons(messageContainer);
                        this.injectActionCards(document.getElementById(assistantId), assistantText);
                        if (persona === "tech_lead") {
                            this.injectExecutionTaskCards(document.getElementById(assistantId), assistantText);
                        }
                    }
                    if (persona === "architect" && !assistantText.trimStart().startsWith("Error:")) {
                        bootstrap.Modal.getOrCreateInstance(document.getElementById("canvasModal")).show();
                        document.getElementById("context-architecture-tab")?.click();
                        await NexusApp.loadCanvas("context-architecture-pane");
                    }
                    if (persona === "tech_lead" && !assistantText.trimStart().startsWith("Error:")) {
                        bootstrap.Modal.getOrCreateInstance(document.getElementById("canvasModal")).show();
                        document.getElementById("context-tasks-tab")?.click();
                        await NexusApp.loadKanban();
                    }
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                consumeEvents();
            }

        } catch (error) {
            this.updateBubble(assistantId, `Error: ${error.message}`);
        } finally {
            button.disabled = false;
            button.innerText = "SEND";
        }
    },

    async buildBundle(btnElement) {
        const input = document.getElementById("chat-input");
        const message = input.value.trim();
        const originalHtml = btnElement.innerHTML;

        btnElement.disabled = true;
        btnElement.innerHTML = "BUILDING...";

        try {
            const response = await fetch("/api/chat-bundle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mode: "cto",
                    persona: "cto",
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
        const borderClass = role === "user" ? "border-primary" : "border";

        const wrapper = document.createElement("div");
        wrapper.className = `d-flex ${alignClass} mb-3`;
        wrapper.id = bubbleId;

        wrapper.innerHTML = `
            <div class="card bg-light ${borderClass}" style="max-width: 85%;">
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

    updateBubble(id, content) {
        const contentElement = document.querySelector(`#${id} .md-content`);
        const container = document.getElementById("chat-messages");
        if (contentElement) {
            contentElement.innerHTML = marked.parse(content);
            container.scrollTop = container.scrollHeight;
        }
    },

    injectDeployButtons(messageContainer) {
        if (!messageContainer) {
            return;
        }

        messageContainer.querySelectorAll("pre").forEach((preElement) => {
            if (preElement.dataset.hasDeployControls === "true") {
                return;
            }

            const controls = document.createElement("div");
            controls.className = "d-flex align-items-center gap-2 mb-2";

            const codeText = preElement.textContent || "";
            const suggestedPath = this.extractSuggestedPath(preElement, codeText);
            const filePathInput = document.createElement("input");
            filePathInput.type = "text";
            filePathInput.className = "form-control form-control-sm";
            filePathInput.placeholder = "Path...";
            filePathInput.style.width = "70%";
            filePathInput.value = suggestedPath || "";

            const deployButton = document.createElement("button");
            deployButton.type = "button";
            deployButton.className = "btn btn-sm btn-outline-primary text-nowrap";
            deployButton.innerText = "Deploy";
            deployButton.addEventListener("click", () => {
                this.deployCodeBlock(filePathInput, codeText, deployButton);
            });

            controls.appendChild(filePathInput);
            controls.appendChild(deployButton);
            preElement.parentNode.insertBefore(controls, preElement);
            preElement.dataset.hasDeployControls = "true";
        });
    },

    injectTaskButtons(messageContainer) {
        if (!messageContainer) {
            return;
        }

        messageContainer.querySelectorAll("pre code").forEach((codeElement) => {
            const preElement = codeElement.closest("pre");
            if (!preElement || preElement.dataset.hasTaskImportControls === "true") {
                return;
            }

            let tasks;
            try {
                tasks = JSON.parse((codeElement.textContent || "").trim());
            } catch (error) {
                return;
            }

            const canImport = Array.isArray(tasks)
                && tasks.length > 0
                && tasks.every((task) => (
                    task
                    && typeof task === "object"
                    && !Array.isArray(task)
                    && typeof task.title === "string"
                    && task.title.trim()
                    && typeof task.description === "string"
                ));

            if (!canImport) {
                return;
            }

            const controls = document.createElement("div");
            controls.className = "d-flex align-items-center gap-2 mb-2";

            const importButton = document.createElement("button");
            importButton.type = "button";
            importButton.className = "btn btn-sm btn-outline-success text-nowrap";
            importButton.innerText = "Import to Board";
            importButton.addEventListener("click", () => {
                this.importTasksToBoard(tasks, importButton);
            });

            controls.appendChild(importButton);
            preElement.parentNode.insertBefore(controls, preElement);
            preElement.dataset.hasTaskImportControls = "true";
        });
    },

    injectActionCards(messageElement, assistantText) {
        if (!messageElement || messageElement.dataset.hasActionCards === "true") {
            return;
        }

        const actionPattern = /Delegating to (Architect|Tech Lead)[^:\n]*:\s*(.+)/gi;
        const actions = [];
        let match = actionPattern.exec(assistantText);
        while (match) {
            const prompt = match[2].trim();
            if (prompt) {
                actions.push({
                    delegate: match[1],
                    prompt: prompt,
                    codexCommand: this.extractCodexCommand(prompt),
                });
            }
            match = actionPattern.exec(assistantText);
        }

        if (!actions.length) {
            return;
        }

        const body = messageElement.querySelector(".card-body");
        const actionList = document.createElement("div");
        actionList.className = "mt-3 pt-3 border-top d-flex flex-column gap-3";

        actions.forEach((action) => {
            const card = document.createElement("div");
            card.className = "card border-primary-subtle bg-white shadow-sm delegation-action-card";

            const cardBody = document.createElement("div");
            cardBody.className = "card-body p-3";

            const heading = document.createElement("div");
            heading.className = "d-flex align-items-center gap-2 mb-2";
            heading.innerHTML = '<i class="bi bi-lightning-charge-fill text-primary"></i>';

            const title = document.createElement("span");
            title.className = "fw-semibold text-dark";
            title.textContent = `${action.delegate} Action`;
            heading.appendChild(title);

            const badge = document.createElement("span");
            badge.className = "badge text-bg-primary-subtle text-primary ms-auto";
            badge.textContent = "Action Card";
            heading.appendChild(badge);

            const detail = document.createElement("p");
            detail.className = "small text-secondary mb-3";
            detail.textContent = action.prompt;

            const controls = document.createElement("div");
            controls.className = "d-flex flex-wrap gap-2";
            controls.appendChild(this.createActionButton(
                "Save to Kanban",
                "btn-outline-secondary",
                (button) => this.saveActionToKanban(action, button)
            ));
            controls.appendChild(this.createActionButton(
                "Execute via Internal AI",
                "btn-outline-primary",
                (button) => this.executeViaInternalAI(action, button)
            ));
            controls.appendChild(this.createActionButton(
                "Execute via Local Codex",
                "btn-primary",
                (button) => this.executeViaLocalCodex(action, button)
            ));

            cardBody.appendChild(heading);
            cardBody.appendChild(detail);
            cardBody.appendChild(controls);
            card.appendChild(cardBody);
            actionList.appendChild(card);
        });

        body.appendChild(actionList);
        messageElement.dataset.hasActionCards = "true";
    },

    extractCodexCommand(text) {
        const match = text.match(/codex\s+"(?:\\.|[^"\\])*"/);
        return match ? match[0] : "";
    },

    injectExecutionTaskCards(messageElement, assistantText) {
        if (!messageElement || messageElement.dataset.hasExecutionTaskCards === "true") {
            return;
        }

        const headingPattern = /^\s*\d+[.)]\s*(?:Task:\s*)?([^\r\n]+)/gm;
        const headings = [...assistantText.matchAll(headingPattern)];
        const tasks = headings.map((match, index) => {
            const end = headings[index + 1]?.index ?? assistantText.length;
            const body = assistantText.slice(match.index, end);
            return {
                title: match[1].trim(),
                prompt: body.trim(),
                codexCommand: this.extractCodexCommand(body),
            };
        }).filter((task) => task.codexCommand);

        if (!tasks.length) {
            return;
        }

        const list = document.createElement("div");
        list.className = "mt-3 pt-3 border-top d-flex flex-column gap-3";
        tasks.forEach((task) => {
            const card = document.createElement("div");
            card.className = "card border-primary-subtle bg-white shadow-sm delegation-action-card";
            const body = document.createElement("div");
            body.className = "card-body p-3";

            const title = document.createElement("div");
            title.className = "d-flex justify-content-between align-items-center gap-2 mb-2";
            title.innerHTML = '<span class="fw-semibold text-dark"><i class="bi bi-list-check text-primary me-2"></i>Execution Task</span><span class="badge text-bg-success-subtle text-success">Added to Kanban</span>';

            const description = document.createElement("p");
            description.className = "small text-secondary mb-2";
            description.textContent = task.title;

            const command = document.createElement("code");
            command.className = "d-block bg-light border rounded p-2 small mb-3 text-dark";
            command.textContent = task.codexCommand;

            const executeButton = this.createActionButton(
                "Execute via Local Codex",
                "btn-primary",
                (button) => this.executeViaLocalCodex(
                    {
                        delegate: "Tech Lead",
                        prompt: task.prompt,
                        codexCommand: task.codexCommand,
                    },
                    button,
                ),
            );

            body.appendChild(title);
            body.appendChild(description);
            body.appendChild(command);
            body.appendChild(executeButton);
            card.appendChild(body);
            list.appendChild(card);
        });

        messageElement.querySelector(".card-body")?.appendChild(list);
        messageElement.dataset.hasExecutionTaskCards = "true";
    },

    createActionButton(label, styleClass, handler) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `btn btn-sm ${styleClass}`;
        button.textContent = label;
        button.addEventListener("click", () => handler(button));
        return button;
    },

    async saveActionToKanban(action, button) {
        if (!NexusState.currentWorkspaceId) {
            NexusCore.showToast("Select an active workspace first.", "error");
            return;
        }

        button.disabled = true;
        try {
            const response = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    title: `${action.delegate} delegation`,
                    description: action.prompt,
                }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || "Unable to save action.");
            }

            button.textContent = "Saved to Kanban";
            await NexusApp.loadTasks(NexusState.currentWorkspaceId);
            NexusCore.showToast("Action saved to the orchestration board.", "success");
        } catch (error) {
            button.disabled = false;
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    executeViaInternalAI(action, button) {
        const input = document.getElementById("chat-input");
        input.value = `Execute the delegated ${action.delegate} action:\n${action.prompt}`;
        button.disabled = true;
        button.textContent = "Submitted to Internal AI";
        const persona = action.delegate === "Architect" ? "architect" : "tech_lead";
        this.send(persona);
    },

    async executeViaLocalCodex(action, button) {
        if (!NexusState.currentWorkspaceId) {
            NexusCore.showToast("Select an active workspace first.", "error");
            return;
        }

        button.disabled = true;
        button.textContent = "Executing... (Waiting)";
        try {
            const commandPrompt = action.codexCommand
                || this.extractCodexCommand(action.prompt)
                || `Delegated to ${action.delegate} for execution:\n${action.prompt}`;
            const response = await fetch("/api/execute-codex", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    prompt: commandPrompt,
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success" || (data.stderr || "").trim()) {
                throw new Error((data.stderr || data.stdout || "Codex execution failed.").trim());
            }

            button.textContent = "✅ Executed";
            NexusCore.showToast("Local Codex execution completed.", "success");
        } catch (error) {
            button.disabled = false;
            button.textContent = "Execute via Local Codex";
            showToast(`Codex execution failed: ${error.message}`, "danger");
        }
    },

    extractSuggestedPath(preElement, codeText) {
        const pathPattern = /[\w\/\.-]+\.\w+/;
        const firstCodeLine = codeText.split(/\r?\n/, 1)[0];
        const codePathMatch = firstCodeLine.match(pathPattern);
        if (codePathMatch) {
            return codePathMatch[0];
        }

        const precedingElement = preElement.previousElementSibling;
        const precedingText = precedingElement ? precedingElement.textContent || "" : "";
        const precedingPathMatch = precedingText.match(pathPattern);
        if (precedingPathMatch) {
            return precedingPathMatch[0];
        }

        return "";
    },

    async deployCodeBlock(filePathInput, codeText, deployButton) {
        const filePath = filePathInput.value.trim();
        if (!filePath) {
            showToast("Enter a file path before deploying.", "danger");
            return;
        }

        deployButton.disabled = true;

        try {
            const response = await fetch("/api/write-file", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    file_path: filePath,
                    content: codeText,
                }),
            });
            const data = await response.json();

            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Failed to deploy file.");
            }

            deployButton.innerText = "Deployed!";
        } catch (error) {
            deployButton.disabled = false;
            showToast(`Deploy failed: ${error.message}`, "danger");
        }
    },

    async importTasksToBoard(tasks, importButton) {
        const workspaceId = NexusState.currentWorkspaceId;
        if (!workspaceId) {
            showToast("Select an active workspace before importing tasks.", "danger");
            return;
        }

        importButton.disabled = true;

        try {
            for (const task of tasks) {
                const response = await fetch("/api/tasks", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        workspace_id: workspaceId,
                        title: task.title,
                        description: task.description,
                    }),
                });
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.message || "Failed to import task.");
                }
            }

            importButton.innerText = "Imported!";
            if (window.NexusApp && typeof NexusApp.loadTasks === "function") {
                await NexusApp.loadTasks(workspaceId);
            }
        } catch (error) {
            importButton.disabled = false;
            showToast(`Import failed: ${error.message}`, "danger");
        }
    },

    removeBubble(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    },
};
