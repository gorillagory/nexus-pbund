window.showToast = function (message, type = "success") {
    const toastElement = document.getElementById("nexusToast");
    const toastMessage = document.getElementById("toast-message");
    if (!toastElement || !toastMessage) {
        return;
    }

    const normalizedType = type === "error"
        ? "danger"
        : (type === "danger" || type === "success" || type === "primary" ? type : "success");
    toastMessage.textContent = message;
    toastElement.className = `toast align-items-center border-0 text-white bg-${normalizedType}`;
    bootstrap.Toast.getOrCreateInstance(toastElement).show();
};

window.NexusApp = {
    resourcePollTimer: null,
    healthPollTimer: null,
    factoryConsolePollTimer: null,
    healthCharts: {},
    lastNetworkSample: null,
    networkSeries: {
        labels: [],
        received: [],
        sent: [],
    },
    workspaceActive: false,
    autoPilotPollTimer: null,
    autoPilotState: {
        running: false,
        state: "idle",
    },
    executionMode: "manual",
    automaticAnalysisEnabled: false,
    latestWorkPacketPreview: null,
    latestStagedWorkPacket: null,
    latestCostLedger: null,
    latestFactoryConsole: null,
    latestPreflightStatus: null,
    latestCiStatus: null,
    promptVaultTemplates: [],
    selectedPromptTemplate: null,

    setTab(tab) {
        const tabViews = {
            arch: "explorer",
            chat: "chat",
            board: "board",
            prompts: "prompt-vault",
            history: "history",
            canvas: "canvas",
            agents: "agents",
            resources: "resources",
        };
        this.showView(tabViews[tab] || "dashboard");
    },

    showView(view) {
        const viewTabs = {
            dashboard: "dashboard",
            explorer: "arch",
            chat: "chat",
            board: "board",
            "prompt-vault": "prompts",
            history: "history",
            canvas: "canvas",
            agents: "agents",
            resources: "resources",
        };
        const viewTitles = {
            dashboard: "Dashboard",
            explorer: "File Explorer",
            chat: "CTO Copilot",
            board: "Orchestration Board",
            "prompt-vault": "Prompt Vault",
            history: "Project History",
            canvas: "Architecture Canvas",
            agents: "Workforce Hub",
            resources: "Resource Monitor",
        };
        const tab = viewTabs[view] || "dashboard";

        if (tab !== "resources") {
            this.stopResourcePolling();
        }
        if (tab !== "dashboard") {
            this.stopFactoryConsolePolling();
        }

        NexusState.currentTab = tab;
        document.querySelectorAll(".spa-view").forEach((container) => {
            container.classList.add("d-none");
        });
        document.getElementById(`view-${view}`)?.classList.remove("d-none");

        document.querySelectorAll("#app-sidebar .nav-link").forEach((button) => {
            button.classList.remove("active");
        });
        document.getElementById(`tab-${tab}-btn`)?.classList.add("active");
        document.getElementById("view-title").innerText = viewTitles[view] || viewTitles.dashboard;

        if (tab === "chat") {
            NexusChat.render();
            this.refreshContextCanvas();
            return;
        }

        if (tab === "board") {
            this.renderBoard();
            this.loadAutoPilotStatus();
            return;
        }

        if (tab === "prompts") {
            this.loadPromptVaultTemplates();
            return;
        }

        if (tab === "history") {
            this.loadProjectHistory(NexusState.currentWorkspaceId);
            return;
        }

        if (tab === "canvas") {
            this.loadCanvas();
            return;
        }

        if (tab === "agents") {
            this.loadAgents();
            return;
        }

        if (tab === "resources") {
            this.startResourcePolling();
            return;
        }

        if (tab === "dashboard") {
            this.loadFactoryConsole();
            this.startFactoryConsolePolling();
        }

        NexusExplorer.renderList();
    },

    async fetchUpdate() {
        try {
            const response = await fetch("/api/state");
            NexusState.globalData = await response.json();

            document.getElementById("status").innerText = `SYNC: ${NexusState.globalData.last_update}`;

            NexusExplorer.renderList();

            if (NexusState.globalData.recent_changes.length) {
                document.getElementById("recent-container").innerHTML = `
                    <div class="recent-box">
                        <small class="text-primary fw-bold text-uppercase">Live Updates</small>
                        <ul class="list-unstyled mb-0 small mt-1">
                            ${NexusState.globalData.recent_changes.map((file) => `
                                <li class="text-secondary">
                                    <i class="bi bi-record-fill text-primary me-1"></i>${file}
                                </li>
                            `).join("")}
                        </ul>
                    </div>
                `;
            } else {
                document.getElementById("recent-container").innerHTML = `
                    <div class="recent-box">
                        <small class="text-primary fw-bold text-uppercase">Live Updates</small>
                        <p class="text-secondary small mb-0 mt-2">No recent file changes.</p>
                    </div>
                `;
            }
        } catch (error) {
            console.error(error);
        }
    },

    async loadFactoryConsole() {
        const target = document.getElementById("factory-console-summary");
        if (target) {
            target.innerHTML = '<div class="col-12 text-secondary small">Loading factory console...</div>';
        }

        try {
            const response = await fetch("/api/factory/status");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load factory console.");
            }

            this.latestFactoryConsole = data;
            this.latestCiStatus = data.ci || this.latestCiStatus;
            this.renderFactoryConsole(data);
            this.loadFactoryPreflightStatus();
            this.loadFactoryCiStatus();
        } catch (error) {
            if (target) {
                target.innerHTML = "";
                const message = document.createElement("div");
                message.className = "col-12 text-danger small";
                message.textContent = `Unable to load factory console: ${error.message}`;
                target.appendChild(message);
            }
        }
    },

    startFactoryConsolePolling() {
        if (this.factoryConsolePollTimer) {
            return;
        }
        this.factoryConsolePollTimer = setInterval(() => {
            if (NexusState.currentTab === "dashboard") {
                this.loadFactoryConsole();
            }
        }, 10000);
    },

    stopFactoryConsolePolling() {
        if (this.factoryConsolePollTimer) {
            clearInterval(this.factoryConsolePollTimer);
            this.factoryConsolePollTimer = null;
        }
    },

    escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    },

    formatFactoryTime(value) {
        if (!value) return "-";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "-";
        return date.toLocaleString();
    },

    formatFactoryDuration(value) {
        if (value === null || value === undefined || value === "") return "-";
        const number = Number(value);
        if (Number.isNaN(number)) return String(value);
        return `${number.toFixed(number < 10 ? 2 : 1)}s`;
    },

    factoryStatusClass(status) {
        const normalized = String(status || "unknown").toLowerCase();
        if (["success", "completed", "done", "pass", "clean"].includes(normalized)) return "factory-status-pass";
        if (["failed", "fail", "error", "timeout", "dirty", "review"].includes(normalized)) return "factory-status-fail";
        if (["running", "starting", "active"].includes(normalized)) return "factory-status-running";
        if (["manual", "idle", "unknown"].includes(normalized)) return "factory-status-idle";
        return "factory-status-neutral";
    },

    factoryEventIcon(eventType) {
        const type = String(eventType || "").toLowerCase();
        if (type.includes("preflight")) return "bi-shield-check";
        if (type.includes("failed") || type.includes("timeout")) return "bi-x-circle";
        if (type.includes("completed") || type.includes("done")) return "bi-check-circle";
        if (type.includes("started") || type.includes("requested")) return "bi-play-circle";
        if (type.includes("git")) return "bi-git";
        if (type.includes("manual")) return "bi-pencil-square";
        return "bi-record-circle";
    },

    safeNextAction(factory, git) {
        const mode = String(factory?.execution_mode || "manual").toLowerCase();
        if (mode === "autopilot") {
            return {
                title: "Autopilot warning",
                body: "Automatic execution is enabled. Use manual, one_task, or one_packet for controlled factory work.",
                tone: "factory-status-fail",
            };
        }
        if (mode === "one_packet") {
            return {
                title: "Run selected packet only",
                body: "Review the staged packet, confirm Git state, then use the existing supervised packet control for one selected packet.",
                tone: "factory-status-pass",
            };
        }
        if (mode === "one_task") {
            return {
                title: "Run selected task only",
                body: "Pick one task from the board and use the existing Run One Task control. No queue automation is implied.",
                tone: "factory-status-running",
            };
        }
        return {
            title: git?.is_dirty ? "Review changes first" : "Stage packet or copy commands",
            body: git?.is_dirty
                ? "Git has local changes. Review the changed files before staging more work."
                : "Manual mode is safe for planning, staging a packet, or copying Codex commands without starting execution.",
            tone: "factory-status-idle",
        };
    },

    renderFactoryConsole(data) {
        const factory = data?.factory || {};
        const runner = factory.runner || {};
        const git = data?.git || {};
        const events = Array.isArray(data?.recent_events) ? data.recent_events : [];
        const runs = Array.isArray(data?.recent_runs) ? data.recent_runs : [];

        this.renderFactorySummaryCards(factory, git);
        this.renderFactoryCurrentState(factory, runner);
        this.renderFactorySafeActions(factory, git);
        this.renderFactoryFailureRecovery(factory, runner, runs);
        this.renderFactoryGitStatus(git);
        this.renderFactoryEvents(events);
        this.renderFactoryRuns(runs);
    },

    renderFactorySummaryCards(factory, git) {
        const target = document.getElementById("factory-console-summary");
        if (!target) return;

        const preflight = this.latestPreflightStatus || {};
        const ci = this.latestCiStatus || {};
        const cards = [
            ["Mode", factory?.execution_mode || "unknown", this.factoryStatusClass(factory?.execution_mode || "manual")],
            ["Automatic Analysis", factory?.automatic_analysis_enabled ? "enabled" : "disabled", factory?.automatic_analysis_enabled ? "factory-status-fail" : "factory-status-pass"],
            ["Git State", git?.is_dirty ? "dirty" : "clean", this.factoryStatusClass(git?.is_dirty ? "dirty" : "clean")],
            ["Recent Runs", factory?.recent_run_count ?? 0, "factory-status-neutral"],
            ["Recent Events", factory?.recent_event_count ?? 0, "factory-status-neutral"],
            ["Preflight Status", preflight?.local_last_result || ci?.local_preflight?.status || "unknown", this.factoryStatusClass(preflight?.local_last_result || ci?.local_preflight?.status || "unknown")],
        ];

        target.innerHTML = "";
        cards.forEach(([label, value, statusClass]) => {
            const column = document.createElement("div");
            column.className = "col-sm-6 col-xl-2";
            column.innerHTML = `
                <div class="factory-summary-card">
                    <div class="factory-summary-label">${this.escapeHtml(label)}</div>
                    <div class="factory-summary-value ${this.escapeHtml(statusClass)}">${this.escapeHtml(value)}</div>
                </div>
            `;
            target.appendChild(column);
        });
    },

    renderFactoryCurrentState(factory, runner) {
        const target = document.getElementById("factory-current-state-panel");
        if (!target) return;

        const currentState = runner?.running ? "running" : (factory?.current_state || "idle");
        const rows = [
            ["Current state", currentState],
            ["Runner mode", runner?.mode || "-"],
            ["Current packet", runner?.work_packet_id || "-"],
            ["Current task", runner?.current_task_title || runner?.current_task_id || "-"],
            ["Progress", runner?.total ? `${runner.completed || 0} / ${runner.total}` : "-"],
            ["Message", runner?.message || "-"],
        ];

        target.innerHTML = `
            <div class="d-flex justify-content-between align-items-center gap-2 mb-3">
                <h4 class="h6 fw-semibold mb-0">Current State</h4>
                <span class="factory-status-badge ${this.factoryStatusClass(currentState)}">${this.escapeHtml(currentState)}</span>
            </div>
            <dl class="factory-state-grid mb-0">
                ${rows.map(([label, value]) => `
                    <div>
                        <dt>${this.escapeHtml(label)}</dt>
                        <dd>${this.escapeHtml(value)}</dd>
                    </div>
                `).join("")}
            </dl>
        `;
    },

    renderFactorySafeActions(factory, git) {
        const target = document.getElementById("factory-safe-next-actions");
        if (!target) return;
        const guidance = this.safeNextAction(factory, git);
        target.innerHTML = `
            <div class="d-flex justify-content-between align-items-center gap-2 mb-3">
                <h4 class="h6 fw-semibold mb-0">Safe Next Actions</h4>
                <span class="factory-status-badge ${this.escapeHtml(guidance.tone)}">${this.escapeHtml(factory?.execution_mode || "manual")}</span>
            </div>
            <div class="factory-guidance-title">${this.escapeHtml(guidance.title)}</div>
            <p class="factory-guidance-copy mb-0">${this.escapeHtml(guidance.body)}</p>
        `;
    },

    latestFailedRun(runs) {
        return (Array.isArray(runs) ? runs : []).find((run) => {
            const status = String(run?.status || "").toLowerCase();
            return ["failed", "timeout", "error"].includes(status) || Number(run?.returncode || 0) !== 0;
        }) || null;
    },

    renderFactoryFailureRecovery(factory, runner, runs) {
        const target = document.getElementById("factory-failure-recovery-panel");
        if (!target) return;

        const failedRun = this.latestFailedRun(runs);
        if (!failedRun) {
            target.innerHTML = `
                <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-2">
                    <h4 class="h6 fw-semibold mb-0">Latest Failed Run</h4>
                    <span class="factory-status-badge factory-status-pass">clear</span>
                </div>
                <div class="text-secondary small">No failed execution run in the recent factory window.</div>
                <div id="factory-run-detail-panel" class="factory-run-detail-panel mt-3">
                    <div class="text-secondary small">Select a failed run to view recovery audit details.</div>
                </div>
            `;
            return;
        }

        const mode = String(factory?.execution_mode || "manual");
        const packetId = failedRun.work_packet_id || runner?.work_packet_id || "";
        const canRetry = mode === "one_task" && failedRun.task_id;
        const canContinue = mode === "one_packet" && packetId;
        const preview = (failedRun.stderr || failedRun.stdout || failedRun.error_message || "").slice(0, 220);
        target.innerHTML = `
            <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-3">
                <h4 class="h6 fw-semibold mb-0">Latest Failed Run</h4>
                <span class="factory-status-badge ${this.factoryStatusClass(failedRun.status)}">${this.escapeHtml(failedRun.status || "failed")}</span>
            </div>
            <div class="factory-recovery-grid">
                <div>
                    <div class="factory-summary-label">Run</div>
                    <div class="factory-summary-value">#${this.escapeHtml(failedRun.id || "-")}</div>
                </div>
                <div>
                    <div class="factory-summary-label">Task</div>
                    <div class="factory-summary-value">#${this.escapeHtml(failedRun.task_id || "-")}</div>
                </div>
                <div>
                    <div class="factory-summary-label">Packet</div>
                    <div class="factory-summary-value">#${this.escapeHtml(packetId || "-")}</div>
                </div>
                <div>
                    <div class="factory-summary-label">Return</div>
                    <div class="factory-summary-value">${this.escapeHtml(failedRun.returncode ?? "-")}</div>
                </div>
            </div>
            <pre class="factory-recovery-preview">${this.escapeHtml(preview || "No stderr/stdout preview.")}</pre>
            <label class="factory-recovery-note-label" for="factory-recovery-note">Operator note</label>
            <textarea id="factory-recovery-note" class="form-control form-control-sm factory-recovery-note" rows="2" placeholder="Add context for retry, review, or packet continue."></textarea>
            <div class="d-flex gap-2 flex-wrap">
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.viewFactoryRunDetails(${Number(failedRun.id) || 0})">View Run Details</button>
                ${failedRun.task_id ? `<button type="button" class="btn btn-outline-warning btn-sm" onclick="NexusApp.markTaskReviewRequired(${Number(failedRun.task_id) || 0})">Mark Review Required</button>` : ""}
                ${failedRun.task_id ? `<button type="button" class="btn btn-primary btn-sm" ${canRetry ? "" : "disabled"} onclick="NexusApp.retryOneTask(${Number(failedRun.task_id) || 0})">Retry One Task</button>` : ""}
                ${packetId ? `<button type="button" class="btn btn-outline-primary btn-sm" ${canContinue ? "" : "disabled"} onclick="NexusApp.continueWorkPacket(${Number(packetId) || 0})">Continue Packet</button>` : ""}
            </div>
            <div class="factory-recovery-warning mt-2">
                Retry runs only this task. Continue runs only this packet from the first unfinished task.
            </div>
            <div id="factory-run-detail-panel" class="factory-run-detail-panel mt-3">
                <div class="text-secondary small">View Run Details opens stdout, stderr, changed files, and recovery notes here.</div>
            </div>
        `;
    },

    recoveryOperatorNote() {
        const input = document.getElementById("factory-recovery-note");
        return input ? input.value.trim() : "";
    },

    renderFactoryRunDetails(data) {
        const target = document.getElementById("factory-run-detail-panel");
        if (!target) return;
        const run = data?.run || {};
        const task = data?.task || {};
        const changedFiles = Array.isArray(data?.changed_files) ? data.changed_files : [];
        const recoveryEvents = Array.isArray(data?.recovery_events) ? data.recovery_events : [];
        const relatedEvents = Array.isArray(data?.related_events) ? data.related_events : [];
        const latestNote = data?.latest_recovery_note || {};
        const latestFailure = data?.latest_failure_event || {};
        const stdout = data?.stdout_preview || run.stdout || "";
        const stderr = data?.stderr_preview || run.stderr || run.error_message || "";
        const tokenText = run.total_tokens !== null && run.total_tokens !== undefined ? run.total_tokens : "-";
        const costText = run.estimated_cost_usd !== null && run.estimated_cost_usd !== undefined
            ? `$${Number(run.estimated_cost_usd).toFixed(6)}`
            : "-";

        target.innerHTML = `
            <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-3">
                <h5 class="h6 fw-semibold mb-0">Run Detail Panel</h5>
                <span class="factory-status-badge ${this.factoryStatusClass(run.status)}">${this.escapeHtml(run.status || "unknown")}</span>
            </div>
            <div class="factory-run-detail-grid">
                <div><span>Status</span><strong>${this.escapeHtml(run.status || "-")}</strong></div>
                <div><span>Returncode</span><strong>${this.escapeHtml(run.returncode ?? "-")}</strong></div>
                <div><span>Tokens</span><strong>${this.escapeHtml(tokenText)}</strong></div>
                <div><span>Cost</span><strong>${this.escapeHtml(costText)}</strong></div>
                <div><span>Duration</span><strong>${this.escapeHtml(this.formatFactoryDuration(run.duration_seconds))}</strong></div>
                <div><span>Task</span><strong>${this.escapeHtml(task.title || (task.id ? `#${task.id}` : "-"))}</strong></div>
            </div>
            ${latestFailure?.event_type ? `
                <div class="factory-recovery-warning mt-3">
                    Previous failure context: ${this.escapeHtml(latestFailure.event_type)} ${latestFailure.message ? `- ${this.escapeHtml(latestFailure.message)}` : ""}
                </div>
            ` : ""}
            ${latestNote?.note ? `
                <div class="factory-recovery-note-view mt-3">
                    <div class="factory-summary-label">Latest recovery note</div>
                    <div>${this.escapeHtml(latestNote.note)}</div>
                    <div class="factory-event-meta">
                        ${this.escapeHtml(latestNote.action || "recovery")} ${latestNote.previous_status ? `from ${this.escapeHtml(latestNote.previous_status)}` : ""}
                    </div>
                </div>
            ` : ""}
            <div class="mt-3">
                <div class="factory-summary-label">Changed files</div>
                ${changedFiles.length ? `
                    <ul class="factory-changed-files mb-0">
                        ${changedFiles.map((file) => `
                            <li class="factory-changed-file">
                                <span class="factory-file-status">${this.escapeHtml(file.change_type || file.status || "?")}</span>
                                <span>${this.escapeHtml(file.file_path || file.path || "")}</span>
                            </li>
                        `).join("")}
                    </ul>
                ` : `<div class="text-secondary small">No changed files recorded for this run.</div>`}
            </div>
            <div class="factory-run-output-grid mt-3">
                <div>
                    <div class="factory-summary-label">stdout preview</div>
                    <pre class="factory-run-output">${this.escapeHtml(stdout || "No stdout captured.")}</pre>
                </div>
                <div>
                    <div class="factory-summary-label">stderr preview</div>
                    <pre class="factory-run-output">${this.escapeHtml(stderr || "No stderr captured.")}</pre>
                </div>
            </div>
            <div class="mt-3">
                <div class="factory-summary-label">Related recovery events</div>
                ${recoveryEvents.length ? recoveryEvents.slice(0, 8).map((event) => {
                    const payload = event.payload || {};
                    const note = payload.operator_note || payload.reason || "";
                    const previous = payload.previous_status ? `from ${payload.previous_status}` : "";
                    return `
                        <div class="factory-run-event">
                            <strong>${this.escapeHtml(event.event_type || "event")}</strong>
                            <span>${this.escapeHtml(payload.action || "")} ${this.escapeHtml(previous)}</span>
                            ${note ? `<div>${this.escapeHtml(note)}</div>` : ""}
                        </div>
                    `;
                }).join("") : `<div class="text-secondary small">No recovery notes recorded for this run.</div>`}
            </div>
            <div class="mt-3">
                <div class="factory-summary-label">Related events</div>
                <div class="factory-event-meta">${this.escapeHtml(relatedEvents.length)} event(s) linked to this task/run.</div>
            </div>
        `;
    },

    async viewFactoryRunDetails(runId) {
        if (!runId) return;
        try {
            const response = await fetch(`/api/factory/runs/${runId}`);
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load run details.");
            }
            this.renderFactoryRunDetails(data);
            NexusCore.showToast(`Run ${runId} details loaded.`, data?.run?.status === "success" ? "success" : "primary");
        } catch (error) {
            NexusCore.showToast(`Run details error: ${error.message}`, "error");
        }
    },

    async markTaskReviewRequired(taskId) {
        if (!taskId) return;
        try {
            const response = await fetch(`/api/tasks/${taskId}/mark-review-required`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    reason: "Marked review required from Factory Console recovery panel.",
                    operator_note: this.recoveryOperatorNote(),
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to mark review required.");
            }
            NexusCore.showToast("Task marked review required.", "success");
            await this.loadFactoryConsole();
            this.renderBoard();
        } catch (error) {
            NexusCore.showToast(`Review marker error: ${error.message}`, "error");
        }
    },

    async retryOneTask(taskId) {
        if (!taskId) return;
        try {
            const response = await fetch(`/api/tasks/${taskId}/retry-one`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    operator_note: this.recoveryOperatorNote(),
                    reason: "Retry requested from Factory Console recovery panel.",
                }),
            });
            const data = await response.json();
            if (!response.ok || !["success", "failed", "timeout"].includes(data.status)) {
                throw new Error(data.message || "Unable to retry task.");
            }
            NexusCore.showToast(
                data.status === "success" ? "Retry completed successfully." : "Retry finished with failure.",
                data.status === "success" ? "success" : "error",
            );
            await this.loadFactoryConsole();
            this.renderBoard();
        } catch (error) {
            NexusCore.showToast(`Retry error: ${error.message}`, "error");
        }
    },

    async continueWorkPacket(workPacketId) {
        if (!workPacketId) return;
        try {
            const response = await fetch(`/api/work-packets/${workPacketId}/continue`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    operator_note: this.recoveryOperatorNote(),
                    reason: "Continue requested from Factory Console recovery panel.",
                }),
            });
            const data = await response.json();
            if (!response.ok || !["success", "failed"].includes(data.status)) {
                throw new Error(data.message || "Unable to continue packet.");
            }
            NexusCore.showToast(
                data.status === "success" ? "Packet continue completed." : "Packet continue stopped after failure.",
                data.status === "success" ? "success" : "error",
            );
            await this.loadFactoryConsole();
            this.renderBoard();
        } catch (error) {
            NexusCore.showToast(`Packet continue error: ${error.message}`, "error");
        }
    },

    async loadFactoryPreflightStatus() {
        try {
            const response = await fetch("/api/factory/preflight/status");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load preflight status.");
            }
            this.latestPreflightStatus = data.preflight || {};
            this.renderFactoryPreflightStatus(this.latestPreflightStatus);
            if (this.latestFactoryConsole) {
                this.renderFactorySummaryCards(this.latestFactoryConsole.factory || {}, this.latestFactoryConsole.git || {});
            }
        } catch (error) {
            const target = document.getElementById("factory-preflight-status");
            if (target) {
                target.innerHTML = "";
                const message = document.createElement("div");
                message.className = "col-12 text-danger small";
                message.textContent = `Unable to load preflight status: ${error.message}`;
                target.appendChild(message);
            }
        }
    },

    async loadFactoryCiStatus() {
        try {
            const response = await fetch("/api/factory/ci-status");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load CI status.");
            }
            this.latestCiStatus = data.ci || {};
            this.renderFactoryCiStatus(this.latestCiStatus);
            if (this.latestFactoryConsole) {
                this.renderFactorySummaryCards(this.latestFactoryConsole.factory || {}, this.latestFactoryConsole.git || {});
            }
        } catch (error) {
            const target = document.getElementById("factory-ci-status");
            if (target) {
                target.innerHTML = "";
                const message = document.createElement("div");
                message.className = "text-danger small";
                message.textContent = `Unable to load CI status: ${error.message}`;
                target.appendChild(message);
            }
        }
    },

    renderFactoryCiStatus(ci) {
        const target = document.getElementById("factory-ci-status");
        if (!target) return;

        const local = ci?.local_preflight || {};
        const remote = ci?.remote_ci || {};
        const actionsUrl = ci?.actions_url || "";
        const rows = [
            ["Branch", ci?.branch || "-"],
            ["Commit", ci?.commit_short || (ci?.commit ? String(ci.commit).slice(0, 7) : "-")],
            ["Workflow", ci?.workflow_present ? "present" : "missing"],
            ["GitHub Repo", ci?.github_slug || "-"],
            ["Local Preflight", local?.status || "unknown"],
            ["Local Duration", this.formatFactoryDuration(local?.duration_seconds)],
            ["Local Last Run", this.formatFactoryTime(local?.finished_at)],
            ["Remote CI", remote?.status || "unknown"],
        ];

        target.innerHTML = `
            <div class="factory-ci-panel">
                <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-3">
                    <div class="factory-guidance-title mb-0">CI / Preflight Status</div>
                    <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.loadFactoryCiStatus()">Refresh CI Status</button>
                </div>
                <div class="factory-ci-grid">
                    ${rows.map(([label, value]) => `
                        <div class="factory-ci-metric">
                            <div class="factory-summary-label">${this.escapeHtml(label)}</div>
                            <div class="factory-summary-value ${this.factoryStatusClass(value)}">${this.escapeHtml(value)}</div>
                        </div>
                    `).join("")}
                </div>
                <div class="factory-ci-foot mt-3">
                    ${actionsUrl ? `<a href="${this.escapeHtml(actionsUrl)}" target="_blank" rel="noopener noreferrer">Open GitHub Actions</a>` : `<span>No GitHub Actions URL detected.</span>`}
                    <span>${this.escapeHtml(remote?.reason || "GitHub API integration not configured")}</span>
                </div>
            </div>
        `;
    },

    renderFactoryPreflightStatus(preflight) {
        const statusTarget = document.getElementById("factory-preflight-status");
        const commandTarget = document.getElementById("factory-preflight-commands");
        const outputTarget = document.getElementById("factory-preflight-output");
        const result = preflight?.local_last_result || "unknown";
        const resultClass = this.factoryStatusClass(result);
        const runTime = preflight?.local_last_run_at
            ? new Date(preflight.local_last_run_at).toLocaleString()
            : "Never";
        const duration = preflight?.local_last_duration_seconds !== null && preflight?.local_last_duration_seconds !== undefined
            ? `${preflight.local_last_duration_seconds}s`
            : "-";

        if (statusTarget) {
            statusTarget.innerHTML = "";
            [
                ["Workflow File", preflight?.workflow_present ? "present" : "missing", preflight?.workflow_present ? "factory-status-pass" : "factory-status-fail"],
                ["Last Local Result", result.toUpperCase(), resultClass],
                ["Last Run", runTime, "factory-status-neutral"],
                ["Duration", duration, "factory-status-neutral"],
                ["Run State", preflight?.run_active ? "running" : "idle", preflight?.run_active ? "factory-status-running" : "factory-status-idle"],
            ].forEach(([label, value, valueClass]) => {
                const column = document.createElement("div");
                column.className = "col-sm-6 col-lg";
                const metric = document.createElement("div");
                metric.className = "factory-preflight-metric";
                const labelEl = document.createElement("div");
                labelEl.className = "factory-summary-label";
                labelEl.textContent = label;
                const valueEl = document.createElement("div");
                valueEl.className = `factory-summary-value ${valueClass}`;
                valueEl.textContent = String(value);
                metric.appendChild(labelEl);
                metric.appendChild(valueEl);
                column.appendChild(metric);
                statusTarget.appendChild(column);
            });
        }

        if (commandTarget) {
            commandTarget.innerHTML = "";
            const quick = document.createElement("div");
            quick.textContent = `Quick: ${preflight?.quick_command || "-"}`;
            const ci = document.createElement("div");
            ci.textContent = `CI: ${preflight?.strict_ci_command || "-"}`;
            commandTarget.appendChild(quick);
            commandTarget.appendChild(ci);
        }

        if (outputTarget) {
            outputTarget.textContent = preflight?.local_last_output_excerpt || "No preflight output recorded.";
            outputTarget.className = `factory-preflight-output mb-0 ${result === "fail" ? "text-danger" : "text-secondary"}`;
        }
    },

    async runFactoryPreflight() {
        const button = document.getElementById("factory-preflight-run-btn");
        const originalLabel = button ? button.innerHTML : "";
        if (button) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Running...';
        }

        try {
            const response = await fetch("/api/factory/preflight/run", { method: "POST" });
            const data = await response.json();
            if ((!response.ok && !data.preflight) || (data.status !== "success" && data.status !== "error")) {
                throw new Error(data.message || "Unable to run local quick preflight.");
            }
            this.renderFactoryPreflightStatus(data.preflight || {});
            await this.loadFactoryConsole();
            const passed = data?.result?.result === "pass" || data.status === "success";
            NexusCore.showToast(
                passed ? "Local quick preflight passed." : "Local quick preflight failed.",
                passed ? "success" : "error",
            );
        } catch (error) {
            NexusCore.showToast(`Preflight error: ${error.message}`, "error");
            await this.loadFactoryPreflightStatus();
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML = originalLabel || '<i class="bi bi-play-fill me-2"></i>Run Local Quick Preflight';
            }
        }
    },

    async loadFactoryEvents() {
        try {
            const response = await fetch("/api/factory/events");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load factory events.");
            }
            this.renderFactoryEvents(data.events || []);
        } catch (error) {
            const target = document.getElementById("factory-events-list");
            if (target) {
                target.textContent = `Unable to load factory events: ${error.message}`;
                target.className = "border rounded bg-light p-3 small text-danger";
            }
        }
    },

    async loadFactoryRuns() {
        try {
            const response = await fetch("/api/factory/runs");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load factory runs.");
            }
            this.renderFactoryRuns(data.runs || []);
        } catch (error) {
            const target = document.getElementById("factory-runs-list");
            if (target) {
                target.textContent = `Unable to load factory runs: ${error.message}`;
                target.className = "border rounded bg-light p-3 small text-danger";
            }
        }
    },

    async loadFactoryGitStatus() {
        try {
            const response = await fetch("/api/factory/git-status");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load factory Git status.");
            }
            this.renderFactoryGitStatus(data.git || {});
        } catch (error) {
            const target = document.getElementById("factory-git-status");
            if (target) {
                target.textContent = `Unable to load Git status: ${error.message}`;
                target.className = "border rounded bg-light p-3 small text-danger";
            }
        }
    },

    renderFactoryGitStatus(git) {
        const filesTarget = document.getElementById("factory-git-status");
        const diffTarget = document.getElementById("factory-diff-stat");
        const changedFiles = Array.isArray(git?.changed_files) ? git.changed_files : [];

        if (filesTarget) {
            filesTarget.innerHTML = "";
            filesTarget.className = "factory-console-panel small text-secondary";
            const badge = document.createElement("span");
            badge.className = `factory-status-badge ${this.factoryStatusClass(git?.is_dirty ? "dirty" : "clean")}`;
            badge.textContent = git?.is_dirty ? "dirty" : "clean";
            filesTarget.appendChild(badge);
            if (!changedFiles.length) {
                const message = document.createElement("div");
                message.className = "mt-3";
                message.textContent = git?.is_dirty ? "Git changes detected." : "Git is clean.";
                filesTarget.appendChild(message);
            } else {
                const list = document.createElement("ul");
                list.className = "factory-changed-files";
                changedFiles.slice(0, 20).forEach((file) => {
                    const item = document.createElement("li");
                    item.className = "factory-changed-file";
                    const status = document.createElement("span");
                    status.className = "factory-file-status";
                    status.textContent = file.status || "?";
                    const path = document.createElement("span");
                    path.textContent = file.path || "";
                    item.appendChild(status);
                    item.appendChild(path);
                    list.appendChild(item);
                });
                filesTarget.appendChild(list);
            }
        }

        if (diffTarget) {
            diffTarget.textContent = git?.diff_stat || git?.diff_stat_error || "No diff stat.";
            diffTarget.className = "factory-diff-stat mb-0";
        }
    },

    renderFactoryEvents(events) {
        const target = document.getElementById("factory-events-list");
        if (!target) return;
        target.innerHTML = "";
        target.className = "factory-console-panel small text-secondary";
        if (!events.length) {
            target.textContent = "No factory events recorded yet.";
            return;
        }

        const list = document.createElement("div");
        list.className = "factory-event-timeline";
        events.slice(0, 10).forEach((event) => {
            const item = document.createElement("div");
            item.className = "factory-event-item";
            const payload = event.payload || {};
            const linkedIds = [
                event.task_id ? `task ${event.task_id}` : "",
                event.execution_run_id ? `run ${event.execution_run_id}` : "",
            ].filter(Boolean).join(" | ");
            const recoveryNote = payload.operator_note || payload.reason || "";
            const actionMeta = [
                payload.action ? `action ${payload.action}` : "",
                payload.previous_status ? `previous ${payload.previous_status}` : "",
                payload.triggered_by ? `by ${payload.triggered_by}` : "",
            ].filter(Boolean).join(" | ");
            item.innerHTML = `
                <div class="factory-event-icon"><i class="bi ${this.escapeHtml(this.factoryEventIcon(event.event_type))}"></i></div>
                <div class="factory-event-body">
                    <div class="factory-event-head">
                        <span class="factory-event-type">${this.escapeHtml(event.event_type || "event")}</span>
                        <span class="factory-event-time">${this.escapeHtml(this.formatFactoryTime(event.created_at))}</span>
                    </div>
                    <div class="factory-event-message">${this.escapeHtml(event.message || "")}</div>
                    ${linkedIds ? `<div class="factory-event-meta">${this.escapeHtml(linkedIds)}</div>` : ""}
                    ${actionMeta ? `<div class="factory-event-meta">${this.escapeHtml(actionMeta)}</div>` : ""}
                    ${recoveryNote ? `<div class="factory-event-note">Recovery note: ${this.escapeHtml(recoveryNote)}</div>` : ""}
                </div>
            `;
            list.appendChild(item);
        });
        target.appendChild(list);
    },

    renderFactoryRuns(runs) {
        const target = document.getElementById("factory-runs-list");
        if (!target) return;
        target.innerHTML = "";
        target.className = "factory-console-panel small text-secondary";
        if (!runs.length) {
            target.textContent = "No execution runs recorded yet.";
            return;
        }

        const tableWrap = document.createElement("div");
        tableWrap.className = "factory-runs-table-wrap";
        const table = document.createElement("table");
        table.className = "table table-sm align-middle factory-runs-table mb-0";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>id</th>
                    <th>task_id</th>
                    <th>status</th>
                    <th>return</th>
                    <th>duration</th>
                    <th>tokens</th>
                    <th>cost</th>
                    <th>started</th>
                    <th>stdout/stderr preview</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        const body = table.querySelector("tbody");
        runs.slice(0, 10).forEach((run) => {
            const preview = (run.stderr || run.stdout || "").slice(0, 160);
            const row = document.createElement("tr");
            row.innerHTML = `
                <td class="font-monospace">${this.escapeHtml(run.id || "-")}</td>
                <td class="font-monospace">${this.escapeHtml(run.task_id || "-")}</td>
                <td><span class="factory-status-badge ${this.factoryStatusClass(run.status)}">${this.escapeHtml(run.status || "unknown")}</span></td>
                <td class="font-monospace">${this.escapeHtml(run.returncode ?? "-")}</td>
                <td>${this.escapeHtml(this.formatFactoryDuration(run.duration_seconds))}</td>
                <td class="font-monospace">${this.escapeHtml(run.total_tokens ?? "-")}</td>
                <td class="font-monospace">${this.escapeHtml(run.estimated_cost_usd ?? "-")}</td>
                <td>${this.escapeHtml(this.formatFactoryTime(run.started_at || run.created_at))}</td>
                <td class="factory-run-preview">${this.escapeHtml(preview || "-")}</td>
            `;
            body.appendChild(row);
        });
        tableWrap.appendChild(table);
        target.appendChild(tableWrap);
    },

    async submitManualFactoryEvent() {
        const messageInput = document.getElementById("factory-event-message");
        const typeInput = document.getElementById("factory-event-type");
        const button = document.getElementById("factory-event-submit-btn");
        const message = (messageInput?.value || "").trim();
        const eventType = (typeInput?.value || "manual_note").trim() || "manual_note";
        if (!message) {
            NexusCore.showToast("Enter a factory event message before adding it.", "error");
            return;
        }

        const originalLabel = button ? button.textContent : "";
        if (button) {
            button.disabled = true;
            button.textContent = "Adding...";
        }

        try {
            const response = await fetch("/api/factory/events/manual", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    event_type: eventType,
                    message: message,
                    payload: { source: "dashboard" },
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to add factory event.");
            }
            if (messageInput) {
                messageInput.value = "";
            }
            await this.loadFactoryConsole();
            NexusCore.showToast("Factory event added.", "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = originalLabel || "Add Manual Event";
            }
        }
    },

    async loadPortfolio() {
        const selectors = [
            document.getElementById("landing-workspace-navigator"),
            document.getElementById("workspace-navigator"),
        ].filter(Boolean);

        try {
            const response = await fetch("/api/portfolio");
            const projects = await response.json();

            selectors.forEach((selector) => {
                selector.innerHTML = '<option value="">Select project...</option>';
                projects.forEach((project) => {
                    const option = document.createElement("option");
                    option.value = project.path;
                    option.textContent = project.name;
                    selector.appendChild(option);
                });
            });
        } catch (error) {
            selectors.forEach((selector) => {
                selector.innerHTML = '<option value="">Projects unavailable</option>';
            });
            NexusCore.showToast("Failed to load workspace portfolio", "error");
        }
    },

    async switchProject(path, sourceSelector) {
        if (!path) {
            return;
        }

        const selectors = [
            document.getElementById("landing-workspace-navigator"),
            document.getElementById("workspace-navigator"),
        ].filter(Boolean);
        const selectedProjectName = sourceSelector?.dataset?.projectName
            || sourceSelector?.selectedOptions?.[0]?.textContent
            || path.split("/").filter(Boolean).pop()
            || path;
        const controls = [...selectors];
        if (sourceSelector && !controls.includes(sourceSelector)) {
            controls.push(sourceSelector);
        }
        controls.forEach((control) => {
            control.disabled = true;
        });

        try {
            const response = await fetch("/api/switch-project", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: path }),
            });
            const data = await response.json();

            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Project switch failed");
            }

            NexusState.selectedFiles.clear();
            NexusState.expandedStates = {};
            NexusState.currentRawMd = "";
            this.workspaceActive = true;
            this.stopHealthPolling();
            selectors.forEach((selector) => {
                selector.value = path;
            });
            await this.fetchUpdate();
            await NexusKanban.activateWorkspace(data.workspace_id);
            NexusState.currentSessionId = `cto_workspace_${data.workspace_id}`;
            await NexusChat.loadChatHistory(data.workspace_id);
            document.getElementById("landing-view").classList.add("d-none");
            document.getElementById("app-shell").classList.remove("d-none");
            this.showView("dashboard");
            NexusCore.showToast(`Workspace active: ${selectedProjectName}`, "success");
        } catch (error) {
            if (sourceSelector?.matches("select")) {
                sourceSelector.value = "";
            }
            NexusCore.showToast(`Error: ${error.message}`, "error");
        } finally {
            controls.forEach((control) => {
                control.disabled = false;
            });
        }
    },

    showWelcome() {
        this.workspaceActive = false;
        this.stopResourcePolling();
        this.stopFactoryConsolePolling();
        this.stopAutoPilotPolling();
        NexusState.currentTab = "dashboard";
        NexusState.globalData = null;
        NexusState.expandedStates = {};
        NexusState.selectedFiles.clear();
        NexusState.indexToPathMap = [];
        NexusState.currentRawMd = "";
        NexusState.currentWorkspaceId = null;
        NexusState.currentSessionId = `session_${Date.now()}`;
        NexusState.tasks = [];

        const workspaceSelector = document.getElementById("workspace-navigator");
        if (workspaceSelector) {
            workspaceSelector.value = "";
        }

        const resourcesTable = document.getElementById("resources-table-body");
        if (resourcesTable) {
            resourcesTable.innerHTML = '<tr><td colspan="5" class="text-center text-secondary py-5">Open this view to load active processes.</td></tr>';
        }

        NexusChat.loadChatHistory(null);
        document.getElementById("app-shell").classList.add("d-none");
        document.getElementById("landing-view").classList.remove("d-none");
        this.startHealthPolling();
    },

    startHealthPolling() {
        this.stopHealthPolling();
        this.lastNetworkSample = null;
        this.loadServerHealth();
        this.healthPollTimer = window.setInterval(() => {
            if (!this.workspaceActive) {
                this.loadServerHealth();
            }
        }, 3000);
    },

    stopHealthPolling() {
        if (this.healthPollTimer !== null) {
            window.clearInterval(this.healthPollTimer);
            this.healthPollTimer = null;
        }
        this.lastNetworkSample = null;
    },

    formatUptime(bootTime) {
        const seconds = Math.max(0, Math.floor(Date.now() / 1000 - bootTime));
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return days ? `${days}d ${hours}h` : `${hours}h ${minutes}m`;
    },

    formatBandwidth(bytesPerSecond) {
        if (bytesPerSecond >= 1024 * 1024) {
            return `${(bytesPerSecond / (1024 * 1024)).toFixed(2)} MB/s`;
        }
        return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`;
    },

    async loadServerHealth() {
        try {
            const response = await fetch("/api/server-health");
            const health = await response.json();
            if (!response.ok) {
                throw new Error(health.message || "Unable to load server health.");
            }
            if (this.workspaceActive) {
                return;
            }

            document.getElementById("health-platform").textContent =
                `${health.platform.system} ${health.platform.release}`;
            document.getElementById("health-uptime").textContent = this.formatUptime(health.boot_time);
            document.getElementById("health-interface").textContent =
                health.network.interface
                    ? `${health.network.interface} (${health.network.type})`
                    : "Unavailable";

            const now = Date.now();
            let receivedPerSecond = 0;
            let sentPerSecond = 0;
            if (
                this.lastNetworkSample
                && this.lastNetworkSample.interface === health.network.interface
            ) {
                const secondsElapsed = Math.max((now - this.lastNetworkSample.timestamp) / 1000, 0.001);
                receivedPerSecond = Math.max(
                    0,
                    (health.network.bytes_recv - this.lastNetworkSample.received) / secondsElapsed,
                );
                sentPerSecond = Math.max(
                    0,
                    (health.network.bytes_sent - this.lastNetworkSample.sent) / secondsElapsed,
                );
            }
            this.lastNetworkSample = {
                interface: health.network.interface,
                received: health.network.bytes_recv,
                sent: health.network.bytes_sent,
                timestamp: now,
            };

            document.getElementById("health-bandwidth").textContent =
                `Down ${this.formatBandwidth(receivedPerSecond)} | Up ${this.formatBandwidth(sentPerSecond)}`;
            this.updateHealthCharts(health, receivedPerSecond, sentPerSecond);
        } catch (error) {
            console.error(error);
            const platformTarget = document.getElementById("health-platform");
            if (platformTarget) {
                platformTarget.textContent = "Unavailable";
            }
        }
    },

    updateHealthCharts(health, receivedPerSecond, sentPerSecond) {
        if (typeof Chart === "undefined") {
            return;
        }

        const commonOptions = {
            animation: false,
            maintainAspectRatio: false,
            responsive: true,
            plugins: {
                legend: { labels: { boxWidth: 10, font: { size: 10 } } },
            },
        };

        if (!this.healthCharts.cpu) {
            this.healthCharts.cpu = new Chart(document.getElementById("health-cpu-chart"), {
                type: "bar",
                data: {
                    labels: [],
                    datasets: [{ data: [], backgroundColor: "#0d6efd", borderRadius: 3 }],
                },
                options: {
                    ...commonOptions,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ticks: { font: { size: 9 } }, grid: { display: false } },
                        y: { beginAtZero: true, max: 100, ticks: { callback: (value) => `${value}%` } },
                    },
                },
            });
        }
        this.healthCharts.cpu.data.labels = health.cpu.cores.map((value, index) => `C${index + 1}`);
        this.healthCharts.cpu.data.datasets[0].data = health.cpu.cores;
        this.healthCharts.cpu.update();

        if (!this.healthCharts.storage) {
            this.healthCharts.storage = new Chart(document.getElementById("health-storage-chart"), {
                type: "doughnut",
                data: {
                    labels: ["Used", "Free"],
                    datasets: [
                        { label: "RAM", data: [], backgroundColor: ["#0d6efd", "#e7f1ff"] },
                        { label: "Disk", data: [], backgroundColor: ["#6f42c1", "#ede7f6"] },
                    ],
                },
                options: { ...commonOptions, cutout: "48%" },
            });
        }
        this.healthCharts.storage.data.datasets[0].data = [health.memory.percent, 100 - health.memory.percent];
        this.healthCharts.storage.data.datasets[1].data = [health.disk.percent, 100 - health.disk.percent];
        this.healthCharts.storage.update();

        const series = this.networkSeries;
        series.labels.push(new Date().toLocaleTimeString([], { minute: "2-digit", second: "2-digit" }));
        series.received.push(Number((receivedPerSecond / 1024).toFixed(2)));
        series.sent.push(Number((sentPerSecond / 1024).toFixed(2)));
        if (series.labels.length > 15) {
            series.labels.shift();
            series.received.shift();
            series.sent.shift();
        }

        if (!this.healthCharts.network) {
            this.healthCharts.network = new Chart(document.getElementById("health-network-chart"), {
                type: "line",
                data: {
                    labels: series.labels,
                    datasets: [
                        { label: "Down KB/s", data: series.received, borderColor: "#0d6efd", tension: 0.3 },
                        { label: "Up KB/s", data: series.sent, borderColor: "#198754", tension: 0.3 },
                    ],
                },
                options: {
                    ...commonOptions,
                    elements: { point: { radius: 0 } },
                    scales: { y: { beginAtZero: true } },
                },
            });
        } else {
            this.healthCharts.network.update();
        }
    },

    async loadProjectHistory(workspaceId) {
        const tableBody = document.getElementById("history-table-body");
        const countBadge = document.getElementById("history-count");
        if (!tableBody || !countBadge) return;

        if (!workspaceId) {
            countBadge.textContent = "0 records";
            tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary py-5">Select a project to view its history.</td></tr>';
            return;
        }

        tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary py-5">Loading project history...</td></tr>';
        try {
            const response = await fetch(`/api/history?workspace_id=${encodeURIComponent(workspaceId)}`);
            const history = await response.json();
            if (!response.ok) {
                throw new Error(history.message || "Unable to load project history.");
            }

            countBadge.textContent = `${history.length} record${history.length === 1 ? "" : "s"}`;
            if (history.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-secondary py-5">No recorded project activity yet.</td></tr>';
                return;
            }

            tableBody.innerHTML = "";
            history.forEach((record) => {
                const row = document.createElement("tr");

                const timestamp = document.createElement("td");
                timestamp.className = "px-4 text-secondary text-nowrap";
                timestamp.textContent = record.created_at ? new Date(record.created_at).toLocaleString() : "-";

                const persona = document.createElement("td");
                const personaBadge = document.createElement("span");
                personaBadge.className = "badge rounded-pill text-bg-light border text-dark";
                personaBadge.textContent = record.persona || "-";
                persona.appendChild(personaBadge);

                const actionType = document.createElement("td");
                actionType.className = "text-dark";
                actionType.textContent = record.action_type || "-";

                const preview = document.createElement("td");
                preview.className = "px-4 text-secondary";
                const content = record.content || "";
                preview.textContent = content.length > 140 ? `${content.slice(0, 140)}...` : content;
                preview.title = content;

                row.appendChild(timestamp);
                row.appendChild(persona);
                row.appendChild(actionType);
                row.appendChild(preview);
                tableBody.appendChild(row);
            });
        } catch (error) {
            countBadge.textContent = "--";
            tableBody.innerHTML = '<tr><td colspan="4" class="text-center text-danger py-5">Unable to load project history.</td></tr>';
            NexusCore.showToast(error.message, "error");
        }
    },

    startResourcePolling() {
        this.stopResourcePolling();
        this.loadResources();
        this.resourcePollTimer = window.setInterval(() => {
            if (NexusState.currentTab === "resources") {
                this.loadResources();
            }
        }, 5000);
    },

    stopResourcePolling() {
        if (this.resourcePollTimer !== null) {
            window.clearInterval(this.resourcePollTimer);
            this.resourcePollTimer = null;
        }
    },

    async loadResources() {
        const tableBody = document.getElementById("resources-table-body");
        if (!tableBody) return;

        try {
            const response = await fetch("/api/resources");
            const processes = await response.json();
            if (!response.ok) {
                throw new Error(processes.message || "Unable to load workspace resources.");
            }

            tableBody.innerHTML = "";
            if (processes.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="5" class="text-center text-secondary py-5">No processes found in the active workspace.</td></tr>';
                return;
            }

            processes.forEach((process) => {
                const row = document.createElement("tr");

                const pid = document.createElement("td");
                pid.className = "px-4 font-monospace";
                pid.textContent = process.pid;

                const name = document.createElement("td");
                name.textContent = process.name || "Unknown";

                const memory = document.createElement("td");
                memory.textContent = `${Number(process.memory_percent || 0).toFixed(2)}%`;

                const cpu = document.createElement("td");
                cpu.textContent = `${Number(process.cpu_percent || 0).toFixed(2)}%`;

                const action = document.createElement("td");
                action.className = "px-4 text-end";
                const killButton = document.createElement("button");
                killButton.type = "button";
                killButton.className = "btn btn-outline-danger btn-sm";
                killButton.textContent = "Kill";
                killButton.addEventListener("click", () => this.killProcess(process.pid));
                action.appendChild(killButton);

                row.appendChild(pid);
                row.appendChild(name);
                row.appendChild(memory);
                row.appendChild(cpu);
                row.appendChild(action);
                tableBody.appendChild(row);
            });
        } catch (error) {
            tableBody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-5">Unable to load active processes.</td></tr>';
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async killProcess(pid) {
        if (!(await NexusCore.confirmAction(`Send a termination signal to process ${pid}?`))) {
            return;
        }

        try {
            const response = await fetch("/api/kill-process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ pid: pid }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to terminate process.");
            }

            NexusCore.showToast(`Termination signal sent to PID ${pid}.`, "success");
            await this.loadResources();
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async runProfiler() {
        if (!NexusState.currentWorkspaceId) {
            NexusCore.showToast("Select an active workspace first.", "error");
            return;
        }

        const button = document.getElementById("sync-rag-btn");
        const originalLabel = button.innerHTML;
        button.disabled = true;
        button.textContent = "Syncing...";
        try {
            const response = await fetch("/api/run-profiler", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ workspace_id: NexusState.currentWorkspaceId }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Profile synchronization failed.");
            }

            NexusCore.showToast(
                `CTO brain synced: ${data.updated_count} preference${data.updated_count === 1 ? "" : "s"} updated.`,
                "success",
            );
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        } finally {
            button.disabled = false;
            button.innerHTML = originalLabel;
        }
    },

    async refreshContextCanvas() {
        const refreshButton = document.getElementById("refresh-canvas-btn");
        if (refreshButton) {
            refreshButton.disabled = true;
        }

        try {
            await Promise.all([
                this.loadProjectBrain(),
                this.loadContextArchitecture(),
                this.loadContextTasks(),
                this.loadTelemetryLogs(),
            ]);
        } finally {
            if (refreshButton) {
                refreshButton.disabled = false;
            }
        }
    },

    async loadProjectBrain() {
        const target = document.getElementById("context-brain-pane");
        if (!target) return;

        target.innerHTML = '<p class="text-secondary">Loading project brain...</p>';
        try {
            const response = await fetch("/api/project-brain");
            const data = await response.json();
            if (!response.ok || data.status === "error") {
                throw new Error(data.message || "Unable to load project brain.");
            }
            if (data.status === "empty" || !data.data.trim()) {
                target.innerHTML = `<p class="text-secondary">${data.message || "No project brain is available."}</p>`;
                return;
            }

            target.innerHTML = marked.parse(data.data);
        } catch (error) {
            target.innerHTML = `<p class="text-danger">Unable to load project brain: ${error.message}</p>`;
        }
    },

    async loadContextArchitecture() {
        return this.loadCanvas("context-architecture-pane");
    },

    async loadContextTasks() {
        const target = document.getElementById("context-tasks-pane");
        if (!target) return;

        if (!NexusState.currentWorkspaceId) {
            target.innerHTML = '<p class="text-secondary">Select a workspace to load active tasks.</p>';
            return;
        }

        target.innerHTML = '<p class="text-secondary">Loading active tasks...</p>';
        try {
            const response = await fetch(
                `/api/tasks?workspace_id=${encodeURIComponent(NexusState.currentWorkspaceId)}`,
            );
            const tasks = await response.json();
            if (!response.ok) {
                throw new Error(tasks.message || "Unable to load active tasks.");
            }
            if (!tasks.length) {
                target.innerHTML = '<p class="text-secondary">No active tasks recorded.</p>';
                return;
            }

            target.innerHTML = "";
            tasks.forEach((task) => {
                const card = document.createElement("div");
                card.className = "context-task-card card bg-light border mb-3";

                const body = document.createElement("div");
                body.className = "card-body p-3";

                const header = document.createElement("div");
                header.className = "d-flex justify-content-between align-items-start gap-2 mb-2";

                const title = document.createElement("h4");
                title.className = "h6 fw-semibold mb-0";
                title.textContent = task.title;

                const status = document.createElement("span");
                status.className = "badge text-bg-light border text-secondary text-uppercase";
                status.textContent = task.status || "todo";

                const description = document.createElement("p");
                description.className = "small text-secondary mb-0";
                description.textContent = task.description || "No task description.";

                header.appendChild(title);
                header.appendChild(status);
                body.appendChild(header);
                body.appendChild(description);
                card.appendChild(body);
                target.appendChild(card);
            });
        } catch (error) {
            target.innerHTML = `<p class="text-danger">Unable to load tasks: ${error.message}</p>`;
        }
    },

    async loadTelemetryLogs() {
        const target = document.getElementById("telemetry-log-output");
        if (!target) return;

        target.textContent = "Loading telemetry...";
        try {
            const response = await fetch("/api/telemetry");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load telemetry.");
            }

            target.textContent = data.logs.length
                ? data.logs.join("\n")
                : "No telemetry events recorded yet.";
        } catch (error) {
            target.textContent = `Unable to load telemetry: ${error.message}`;
        }
    },

    async copyTelemetryLogs() {
        const target = document.getElementById("telemetry-log-output");
        if (!target) return;

        try {
            await navigator.clipboard.writeText(target.textContent || "");
            NexusCore.showToast("Telemetry copied to clipboard.", "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async loadCanvas(targetId = "architecture-diagram") {
        const target = document.getElementById(targetId);
        if (!target) return;

        const isContextPane = targetId === "context-architecture-pane";
        if (isContextPane) {
            target.innerHTML = '<p class="text-secondary">Loading architecture...</p>';
        } else {
            target.className = "card-body p-4 text-center text-secondary";
            target.textContent = "Loading architecture canvas...";
        }

        try {
            const response = await fetch("/api/architecture");
            const data = await response.json();
            if (!response.ok || data.status === "error") {
                throw new Error(data.message || "Unable to load architecture canvas.");
            }

            if (data.status === "empty" || !data.data.trim()) {
                if (isContextPane) {
                    target.innerHTML = `<p class="text-secondary">${data.message || "No architecture canvas is available."}</p>`;
                } else {
                    target.textContent = data.message || "No architecture canvas is available.";
                }
                return;
            }

            const diagram = data.data
                .replace(/^```(?:mermaid)?\s*/i, "")
                .replace(/\s*```$/, "")
                .trim();
            const renderId = `${targetId}-${Date.now()}`;
            const rendered = await mermaid.render(renderId, diagram);
            if (!isContextPane) {
                target.className = "card-body p-4 overflow-auto text-center";
            }
            target.innerHTML = rendered.svg;
        } catch (error) {
            if (isContextPane) {
                target.innerHTML = `<p class="text-danger">Unable to render architecture: ${error.message}</p>`;
            } else {
                target.className = "card-body p-4 text-center text-danger";
                target.textContent = `Unable to render architecture canvas: ${error.message}`;
                NexusCore.showToast(`Error: ${error.message}`, "error");
            }
        }
    },

    async loadAgents() {
        try {
            const response = await fetch("/api/agents");
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || "Unable to load workforce settings.");
            }

            data.agents.forEach((agent) => {
                const model = document.getElementById(`agent-${agent.id}-model`);
                const prompt = document.getElementById(`agent-${agent.id}-prompt`);
                if (model) {
                    model.textContent = `${agent.active_model.provider} / ${agent.active_model.model}`;
                }
                if (prompt) {
                    prompt.textContent = agent.system_prompt;
                }
            });

            const habits = document.getElementById("agent-cto-habits");
            habits.innerHTML = "";
            const cto = data.agents.find((agent) => agent.id === "cto");
            if (!cto || cto.habits.length === 0) {
                const empty = document.createElement("li");
                empty.className = "text-secondary";
                empty.textContent = "No profiled habits recorded.";
                habits.appendChild(empty);
                return;
            }

            cto.habits.forEach((habit) => {
                const item = document.createElement("li");
                item.textContent = `${habit.key}: ${habit.value}`;
                habits.appendChild(item);
            });
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    renderBoard() {
        document.getElementById("board-panel").innerHTML = `
            <div class="p-2">
                <div class="border-bottom pb-3 mb-4">
                    <h4 class="text-dark mb-1 fw-semibold">Orchestration Board</h4>
                    <p class="text-secondary small mb-0">Track work across delivery stages for the active workspace.</p>
                </div>
                <div class="bg-light border rounded p-3 mb-4">
                    <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-3">
                        <div>
                            <h5 class="text-dark fw-semibold mb-1">Work Packet Manager</h5>
                            <p class="text-warning small fw-semibold mb-0">Manual Mode: staging and copying only. Codex is not executed.</p>
                        </div>
                        <div class="d-flex flex-wrap gap-2">
                            <button type="button" class="btn btn-outline-primary btn-sm" onclick="NexusApp.previewWorkPacket()">Preview Packet</button>
                            <button type="button" class="btn btn-primary btn-sm" onclick="NexusApp.stageWorkPacket()">Stage to Kanban</button>
                            <button id="run-packet-btn" type="button" class="btn btn-outline-success btn-sm" onclick="NexusApp.runWorkPacket()">Run Packet</button>
                            <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.copyAllWorkPacketCodexCommands()">Copy All Codex Commands</button>
                        </div>
                    </div>
                    <div id="work-packet-runner-status" class="border rounded bg-white p-3 mb-3 small text-secondary">
                        <div class="fw-semibold text-dark">Supervised Packet Runner</div>
                        <div>Supervised Packet Runner: runs only this packet and stops after first failure.</div>
                        <div id="latest-work-packet-status" class="mt-2">No staged packet selected.</div>
                    </div>
                    <textarea id="work-packet-input" class="form-control font-monospace small mb-3" rows="8" placeholder="Paste a work packet containing codex &quot;...&quot; commands"></textarea>
                    <div id="work-packet-preview" class="border rounded bg-white p-3 small text-secondary">
                        Preview extracted tasks before staging them to To-Do.
                    </div>
                </div>
                <div class="bg-light border rounded p-3 mb-4">
                    <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-3">
                        <div>
                            <h5 class="text-dark fw-semibold mb-1">Budget Guard</h5>
                            <p class="text-secondary small mb-0">Budget Guard: manual tracking only. No automatic spending is triggered here.</p>
                        </div>
                        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.loadCostLedger()">Refresh</button>
                    </div>
                    <div id="cost-ledger-summary" class="row g-2 mb-3">
                        <div class="col-12 small text-secondary">Loading cost tracking...</div>
                    </div>
                    <form id="manual-cost-entry-form" class="row g-2 align-items-end" onsubmit="NexusApp.submitManualCostEntry(); return false;">
                        <div class="col-md-2">
                            <label for="manual-cost-provider" class="form-label small text-secondary mb-1">Provider</label>
                            <input id="manual-cost-provider" type="text" class="form-control form-control-sm" maxlength="100" autocomplete="off">
                        </div>
                        <div class="col-md-2">
                            <label for="manual-cost-model" class="form-label small text-secondary mb-1">Model</label>
                            <input id="manual-cost-model" type="text" class="form-control form-control-sm" maxlength="120" autocomplete="off">
                        </div>
                        <div class="col-md-2">
                            <label for="manual-cost-source" class="form-label small text-secondary mb-1">Source</label>
                            <input id="manual-cost-source" type="text" class="form-control form-control-sm" maxlength="80" value="manual" autocomplete="off">
                        </div>
                        <div class="col-md-2">
                            <label for="manual-cost-task-id" class="form-label small text-secondary mb-1">Task ID</label>
                            <input id="manual-cost-task-id" type="text" class="form-control form-control-sm" maxlength="80" autocomplete="off">
                        </div>
                        <div class="col-md-2">
                            <label for="manual-cost-total-tokens" class="form-label small text-secondary mb-1">Total Tokens</label>
                            <input id="manual-cost-total-tokens" type="number" class="form-control form-control-sm" min="0" step="1" inputmode="numeric">
                        </div>
                        <div class="col-md-2">
                            <label for="manual-cost-estimated-cost" class="form-label small text-secondary mb-1">Cost USD</label>
                            <input id="manual-cost-estimated-cost" type="number" class="form-control form-control-sm" min="0" step="0.000001" inputmode="decimal">
                        </div>
                        <div class="col-md-10">
                            <label for="manual-cost-notes" class="form-label small text-secondary mb-1">Notes</label>
                            <input id="manual-cost-notes" type="text" class="form-control form-control-sm" maxlength="1000" autocomplete="off">
                        </div>
                        <div class="col-md-2 d-grid">
                            <button id="manual-cost-submit-btn" type="submit" class="btn btn-primary btn-sm">Add Entry</button>
                        </div>
                    </form>
                    <div id="cost-ledger-events" class="small text-secondary mt-3">No cost events loaded.</div>
                </div>
                <div class="row g-3">
                    <div class="col-md-4">
                        <div class="card bg-light border h-100 p-3">
                            <div class="d-flex justify-content-between align-items-start gap-2 mb-3 flex-wrap">
                                <div>
                                    <h6 class="text-primary fw-bold text-uppercase mb-2">To-Do</h6>
                                    <div class="d-flex align-items-center gap-2 flex-wrap">
                                        <span id="execution-mode-indicator" class="badge text-bg-warning border">Manual Mode - Auto-Pilot and automatic analysis disabled</span>
                                        <div class="btn-group btn-group-sm" role="group" aria-label="Execution mode">
                                            <button id="execution-mode-manual-btn" type="button" class="btn btn-outline-secondary" onclick="NexusApp.setExecutionMode('manual')">Manual</button>
                                            <button id="execution-mode-one-task-btn" type="button" class="btn btn-outline-secondary" onclick="NexusApp.setExecutionMode('one_task')">One Task</button>
                                            <button id="execution-mode-one-packet-btn" type="button" class="btn btn-outline-secondary" onclick="NexusApp.setExecutionMode('one_packet')">One Packet</button>
                                            <button id="execution-mode-autopilot-btn" type="button" class="btn btn-outline-secondary" onclick="NexusApp.setExecutionMode('autopilot')">Auto-Pilot</button>
                                        </div>
                                    </div>
                                </div>
                                <button id="auto-pilot-btn" type="button" class="btn btn-outline-primary btn-sm" onclick="NexusApp.engageAutoPilot()">
                                    Auto-Pilot Disabled in Manual Mode
                                </button>
                            </div>
                            <div id="tasks-todo" class="d-flex flex-column gap-3"></div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card bg-light border h-100 p-3">
                            <h6 class="text-warning fw-bold text-uppercase mb-3">Review</h6>
                            <div id="tasks-review" class="d-flex flex-column gap-3"></div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card bg-light border h-100 p-3">
                            <h6 class="text-success fw-bold text-uppercase mb-3">Done</h6>
                            <div id="tasks-done" class="d-flex flex-column gap-3"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.renderTasks(NexusState.tasks);
        this.renderWorkPacketPreview(this.latestWorkPacketPreview);
        this.renderWorkPacketRunnerStatus();
        this.renderExecutionMode();
        this.updateAutoPilotUI();
        this.renderCostLedger(this.latestCostLedger);
        this.loadCostLedger();
    },

    async loadKanban() {
        await this.loadTasks(NexusState.currentWorkspaceId);
        await this.loadContextTasks();
    },

    async refreshVisibleTasks() {
        if (!NexusState.currentWorkspaceId) {
            return;
        }

        if (NexusState.currentTab === "board") {
            await this.loadTasks(NexusState.currentWorkspaceId);
            return;
        }

        const contextTasksPane = document.getElementById("context-tasks-pane");
        if (
            NexusState.currentTab === "chat"
            && contextTasksPane?.classList.contains("active")
        ) {
            await this.loadKanban();
        }
    },

    async loadTasks(workspaceId) {
        if (!workspaceId) {
            NexusState.tasks = [];
            if (NexusState.currentTab === "board") {
                this.renderTasks([]);
            }
            return;
        }

        try {
            const response = await fetch(`/api/tasks?workspace_id=${encodeURIComponent(workspaceId)}`);
            const tasks = await response.json();
            if (!response.ok) {
                throw new Error(tasks.message || "Unable to load tasks.");
            }

            NexusState.tasks = tasks;
            if (NexusState.currentTab === "board") {
                this.renderTasks(tasks);
            }
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    renderTasks(tasks) {
        const columns = {
            todo: document.getElementById("tasks-todo"),
            review: document.getElementById("tasks-review"),
            done: document.getElementById("tasks-done"),
        };

        if (!columns.todo || !columns.review || !columns.done) {
            return;
        }

        Object.values(columns).forEach((column) => {
            column.innerHTML = "";
        });

        tasks.forEach((task) => {
            const status = Object.prototype.hasOwnProperty.call(columns, task.status)
                ? task.status
                : "todo";
            columns[status].appendChild(this.createTaskCard(task));
        });

        Object.values(columns).forEach((column) => {
            if (!column.children.length) {
                const empty = document.createElement("div");
                empty.className = "text-secondary small";
                empty.textContent = "No tasks.";
                column.appendChild(empty);
            }
        });
    },

    extractCodexCommand(description) {
        const match = String(description || "").match(/codex\s+"(?:\\.|[^"\\])*"/);
        return match ? match[0] : "";
    },

    getWorkPacketText() {
        const input = document.getElementById("work-packet-input");
        return input ? input.value : "";
    },

    async previewWorkPacket() {
        const packetText = this.getWorkPacketText();
        if (!packetText.trim()) {
            NexusCore.showToast("Paste a work packet before previewing.", "error");
            return;
        }

        try {
            const response = await fetch("/api/work-packets/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ packet_text: packetText }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to preview work packet.");
            }

            this.latestWorkPacketPreview = data.packet;
            this.renderWorkPacketPreview(data.packet);
            NexusCore.showToast(`Previewed ${data.task_count} work packet task${data.task_count === 1 ? "" : "s"}.`, "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async stageWorkPacket() {
        if (!NexusState.currentWorkspaceId) {
            NexusCore.showToast("Select an active workspace before staging tasks.", "error");
            return;
        }

        const packetText = this.getWorkPacketText();
        if (!packetText.trim()) {
            NexusCore.showToast("Paste a work packet before staging.", "error");
            return;
        }

        try {
            const response = await fetch("/api/work-packets/stage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    packet_text: packetText,
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to stage work packet.");
            }

            this.latestStagedWorkPacket = data;
            await this.loadKanban();
            this.renderWorkPacketRunnerStatus();
            NexusCore.showToast(`Staged ${data.created_count} task${data.created_count === 1 ? "" : "s"} to Kanban.`, "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    renderWorkPacketRunnerStatus() {
        const target = document.getElementById("latest-work-packet-status");
        const button = document.getElementById("run-packet-btn");
        const packet = this.latestStagedWorkPacket || {};
        const packetId = packet.work_packet_id;
        if (target) {
            target.textContent = packetId
                ? `Selected packet #${packetId}: ${packet.packet_title || "Untitled Work Packet"}`
                : "No staged packet selected.";
        }
        if (button) {
            const enabled = this.executionMode === "one_packet" && Boolean(packetId);
            button.disabled = !enabled;
            button.className = enabled
                ? "btn btn-success btn-sm"
                : "btn btn-outline-success btn-sm";
            button.title = enabled
                ? "Run the selected staged packet."
                : "Switch to One Packet mode and stage a packet first.";
        }
    },

    async runWorkPacket(button = null) {
        const trigger = button || document.getElementById("run-packet-btn");
        const packet = this.latestStagedWorkPacket || {};
        if (this.executionMode !== "one_packet") {
            NexusCore.showToast("Run Packet is available only in One Packet mode.", "error");
            return;
        }
        if (!NexusState.currentWorkspaceId || !packet.work_packet_id) {
            NexusCore.showToast("Stage a work packet before running it.", "error");
            return;
        }

        const originalLabel = trigger ? trigger.textContent : "";
        if (trigger) {
            trigger.disabled = true;
            trigger.textContent = "Running Packet...";
        }

        try {
            const response = await fetch("/api/work-packets/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    work_packet_id: packet.work_packet_id,
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || `Packet run ended with status ${data.status || "failed"}.`);
            }

            NexusCore.showToast("Run Packet completed successfully.", "success");
        } catch (error) {
            NexusCore.showToast(`Run Packet failed: ${error.message}`, "error");
        } finally {
            if (trigger) {
                trigger.disabled = false;
                trigger.textContent = originalLabel || "Run Packet";
            }
            await this.loadKanban();
            await this.loadCostLedger();
            await this.loadFactoryConsole();
            this.renderWorkPacketRunnerStatus();
        }
    },

    renderWorkPacketPreview(packet) {
        const preview = document.getElementById("work-packet-preview");
        if (!preview) {
            return;
        }

        preview.innerHTML = "";
        if (!packet) {
            preview.textContent = "Preview extracted tasks before staging them to To-Do.";
            return;
        }

        const heading = document.createElement("div");
        heading.className = "mb-3";

        const title = document.createElement("h6");
        title.className = "text-dark fw-semibold mb-2";
        title.textContent = packet.title || "Untitled Work Packet";
        heading.appendChild(title);

        const meta = document.createElement("div");
        meta.className = "d-flex flex-wrap gap-2";
        [
            `Risk: ${packet.risk_level || "unspecified"}`,
            `Stop: ${packet.stop_condition || "Stop after packet completion or first failure."}`,
            `Tasks: ${(packet.tasks || []).length}`,
        ].forEach((label) => {
            const badge = document.createElement("span");
            badge.className = "badge text-bg-light border text-secondary";
            badge.textContent = label;
            meta.appendChild(badge);
        });
        heading.appendChild(meta);
        preview.appendChild(heading);

        const tasks = packet.tasks || [];
        if (!tasks.length) {
            const empty = document.createElement("p");
            empty.className = "mb-0 text-secondary";
            empty.textContent = "No codex tasks found in this packet.";
            preview.appendChild(empty);
            return;
        }

        const list = document.createElement("div");
        list.className = "d-flex flex-column gap-3";
        tasks.forEach((task) => {
            const item = document.createElement("div");
            item.className = "border rounded p-3";

            const taskTitle = document.createElement("div");
            taskTitle.className = "fw-semibold text-dark mb-2";
            taskTitle.textContent = `${task.order || ""}. ${task.title || "Task"}`.trim();
            item.appendChild(taskTitle);

            const command = document.createElement("pre");
            command.className = "bg-light border rounded p-2 mb-0 text-wrap";
            command.textContent = task.codex_command || "";
            item.appendChild(command);

            list.appendChild(item);
        });
        preview.appendChild(list);
    },

    formatCostUsd(value) {
        const amount = Number(value || 0);
        return `$${amount.toFixed(6)}`;
    },

    formatTokenCount(value) {
        return Number(value || 0).toLocaleString();
    },

    async loadCostLedger() {
        const summaryTarget = document.getElementById("cost-ledger-summary");
        if (summaryTarget) {
            summaryTarget.innerHTML = '<div class="col-12 small text-secondary">Loading cost tracking...</div>';
        }

        try {
            const response = await fetch("/api/cost-ledger");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load cost ledger.");
            }

            this.latestCostLedger = data;
            this.renderCostLedger(data);
        } catch (error) {
            if (summaryTarget) {
                summaryTarget.innerHTML = "";
                const message = document.createElement("div");
                message.className = "col-12 small text-danger";
                message.textContent = `Unable to load cost tracking: ${error.message}`;
                summaryTarget.appendChild(message);
            }
        }
    },

    renderCostLedger(data) {
        const summaryTarget = document.getElementById("cost-ledger-summary");
        const eventsTarget = document.getElementById("cost-ledger-events");
        if (!summaryTarget && !eventsTarget) {
            return;
        }

        const summary = data?.summary || {};
        const events = Array.isArray(data?.events) ? data.events : [];

        if (summaryTarget) {
            summaryTarget.innerHTML = "";
            [
                ["Events", summary.event_count || 0],
                ["Total Tokens", this.formatTokenCount(summary.total_tokens || 0)],
                ["Input Tokens", this.formatTokenCount(summary.input_tokens || 0)],
                ["Output Tokens", this.formatTokenCount(summary.output_tokens || 0)],
                ["Estimated Cost", this.formatCostUsd(summary.estimated_cost_usd || 0)],
            ].forEach(([label, value]) => {
                const column = document.createElement("div");
                column.className = "col-sm-6 col-lg";

                const metric = document.createElement("div");
                metric.className = "border rounded bg-white p-2 h-100";

                const labelEl = document.createElement("div");
                labelEl.className = "text-secondary small";
                labelEl.textContent = label;

                const valueEl = document.createElement("div");
                valueEl.className = "fw-semibold text-dark";
                valueEl.textContent = String(value);

                metric.appendChild(labelEl);
                metric.appendChild(valueEl);
                column.appendChild(metric);
                summaryTarget.appendChild(column);
            });
        }

        if (eventsTarget) {
            eventsTarget.innerHTML = "";
            if (!events.length) {
                eventsTarget.textContent = "No manual cost events recorded yet.";
                return;
            }

            const list = document.createElement("div");
            list.className = "d-flex flex-column gap-2";
            events.slice(-5).reverse().forEach((event) => {
                const item = document.createElement("div");
                item.className = "border rounded bg-white p-2";

                const line = document.createElement("div");
                line.className = "d-flex justify-content-between gap-3 flex-wrap";

                const title = document.createElement("span");
                title.className = "fw-semibold text-dark";
                title.textContent = [
                    event.provider || "provider unknown",
                    event.model || "model unknown",
                ].join(" / ");

                const cost = document.createElement("span");
                cost.className = "text-secondary";
                cost.textContent = `${this.formatTokenCount(event.total_tokens || 0)} tokens | ${this.formatCostUsd(event.estimated_cost_usd || 0)}`;

                const meta = document.createElement("div");
                meta.className = "text-secondary";
                meta.textContent = [
                    event.source || "manual",
                    event.task_id ? `Task ${event.task_id}` : "",
                    event.timestamp ? new Date(event.timestamp).toLocaleString() : "",
                ].filter(Boolean).join(" | ");

                line.appendChild(title);
                line.appendChild(cost);
                item.appendChild(line);
                item.appendChild(meta);
                if (event.notes) {
                    const notes = document.createElement("div");
                    notes.className = "text-secondary mt-1";
                    notes.textContent = event.notes;
                    item.appendChild(notes);
                }
                list.appendChild(item);
            });
            eventsTarget.appendChild(list);
        }
    },

    async submitManualCostEntry() {
        const form = document.getElementById("manual-cost-entry-form");
        const button = document.getElementById("manual-cost-submit-btn");
        if (!form) {
            return;
        }

        const readValue = (id) => (document.getElementById(id)?.value || "").trim();
        const payload = {};
        [
            ["provider", "manual-cost-provider"],
            ["model", "manual-cost-model"],
            ["source", "manual-cost-source"],
            ["task_id", "manual-cost-task-id"],
            ["notes", "manual-cost-notes"],
        ].forEach(([field, id]) => {
            const value = readValue(id);
            if (value) {
                payload[field] = value;
            }
        });

        const totalTokens = readValue("manual-cost-total-tokens");
        const estimatedCost = readValue("manual-cost-estimated-cost");
        if (totalTokens) {
            payload.total_tokens = totalTokens;
        }
        if (estimatedCost) {
            payload.estimated_cost_usd = estimatedCost;
        }
        if (!totalTokens && !estimatedCost) {
            NexusCore.showToast("Enter total tokens or estimated cost before adding a manual entry.", "error");
            return;
        }

        const originalLabel = button ? button.textContent : "";
        if (button) {
            button.disabled = true;
            button.textContent = "Adding...";
        }

        try {
            const response = await fetch("/api/cost-ledger/manual-entry", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to add manual cost entry.");
            }

            ["manual-cost-total-tokens", "manual-cost-estimated-cost", "manual-cost-notes"].forEach((id) => {
                const input = document.getElementById(id);
                if (input) {
                    input.value = "";
                }
            });
            await this.loadCostLedger();
            NexusCore.showToast("Manual cost entry added.", "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = originalLabel || "Add Entry";
            }
        }
    },

    async copyTextToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            return;
        }

        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            const copied = document.execCommand("copy");
            if (!copied) {
                throw new Error("Clipboard copy failed.");
            }
        } finally {
            document.body.removeChild(textarea);
        }
    },

    async loadPromptVaultTemplates() {
        const list = document.getElementById("prompt-vault-template-list");
        const filter = document.getElementById("prompt-vault-category-filter");
        const category = filter ? filter.value : "";
        if (list) {
            list.textContent = "Loading Prompt Vault templates...";
        }
        try {
            const query = category ? `?category=${encodeURIComponent(category)}` : "";
            const response = await fetch(`/api/prompt-vault/templates${query}`);
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load prompt templates.");
            }
            this.promptVaultTemplates = Array.isArray(data.templates) ? data.templates : [];
            this.renderPromptVaultTemplateList();
            if (!this.selectedPromptTemplate && this.promptVaultTemplates.length) {
                this.renderPromptVaultTemplateDetail(this.promptVaultTemplates[0]);
            }
        } catch (error) {
            if (list) {
                list.textContent = `Prompt Vault unavailable: ${error.message}`;
            }
            NexusCore.showToast(`Prompt Vault error: ${error.message}`, "error");
        }
    },

    renderPromptVaultTemplateList() {
        const list = document.getElementById("prompt-vault-template-list");
        const count = document.getElementById("prompt-vault-count");
        if (count) {
            count.textContent = String(this.promptVaultTemplates.length);
        }
        if (!list) return;
        if (!this.promptVaultTemplates.length) {
            list.innerHTML = '<div class="text-secondary small">No active prompt templates found.</div>';
            return;
        }
        list.innerHTML = this.promptVaultTemplates.map((template) => `
            <button type="button" class="prompt-vault-list-item" onclick="NexusApp.selectPromptTemplate(${Number(template.id) || 0})">
                <span class="prompt-vault-list-title">${this.escapeHtml(template.title || "Untitled")}</span>
                <span class="prompt-vault-list-meta">
                    <span class="prompt-vault-badge">${this.escapeHtml(template.category || "feature")}</span>
                    <span class="prompt-vault-badge prompt-vault-risk-${this.escapeHtml(template.risk_level || "medium")}">${this.escapeHtml(template.risk_level || "medium")}</span>
                </span>
            </button>
        `).join("");
    },

    selectPromptTemplate(templateId) {
        const template = this.promptVaultTemplates.find((item) => Number(item.id) === Number(templateId));
        if (template) {
            this.renderPromptVaultTemplateDetail(template);
        }
    },

    renderPromptVaultTemplateDetail(template) {
        this.selectedPromptTemplate = template || null;
        const target = document.getElementById("prompt-vault-detail");
        if (!target) return;
        if (!template) {
            target.innerHTML = '<div class="text-secondary small">Select a Prompt Vault template to view and copy it.</div>';
            return;
        }
        const tags = Array.isArray(template.tags) ? template.tags : [];
        target.innerHTML = `
            <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-3">
                <div>
                    <h4 class="h5 fw-semibold mb-1">${this.escapeHtml(template.title || "Untitled")}</h4>
                    <div class="d-flex gap-2 flex-wrap">
                        <span class="prompt-vault-badge">${this.escapeHtml(template.category || "feature")}</span>
                        <span class="prompt-vault-badge prompt-vault-risk-${this.escapeHtml(template.risk_level || "medium")}">${this.escapeHtml(template.risk_level || "medium")}</span>
                        <span class="prompt-vault-badge">${this.escapeHtml(template.status || "active")}</span>
                    </div>
                </div>
                <div class="d-flex gap-2 flex-wrap">
                    <button type="button" class="btn btn-primary btn-sm" onclick="NexusApp.copySelectedPromptTemplate()">Copy Template</button>
                    <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.editSelectedPromptTemplate()">Edit</button>
                    <button type="button" class="btn btn-outline-warning btn-sm" onclick="NexusApp.archiveSelectedPromptTemplate()">Archive</button>
                </div>
            </div>
            <p class="text-secondary small">${this.escapeHtml(template.description || "No description.")}</p>
            <div class="prompt-vault-template-stats mb-3">
                <span>success ${this.escapeHtml(template.success_count ?? 0)}</span>
                <span>failure ${this.escapeHtml(template.failure_count ?? 0)}</span>
                <span>last used ${this.escapeHtml(this.formatFactoryTime(template.last_used_at))}</span>
            </div>
            ${tags.length ? `<div class="prompt-vault-tags mb-3">${tags.map((tag) => `<span>${this.escapeHtml(tag)}</span>`).join("")}</div>` : ""}
            <pre class="prompt-vault-body">${this.escapeHtml(template.body || "")}</pre>
        `;
    },

    promptTemplateFormData() {
        const tagsText = document.getElementById("prompt-template-tags")?.value || "";
        return {
            title: document.getElementById("prompt-template-title")?.value || "",
            category: document.getElementById("prompt-template-category")?.value || "feature",
            risk_level: document.getElementById("prompt-template-risk")?.value || "medium",
            description: document.getElementById("prompt-template-description")?.value || "",
            body: document.getElementById("prompt-template-body")?.value || "",
            variables: {},
            tags: tagsText.split(",").map((tag) => tag.trim()).filter(Boolean),
        };
    },

    fillPromptTemplateForm(template) {
        document.getElementById("prompt-template-id").value = template?.id || "";
        document.getElementById("prompt-template-title").value = template?.title || "";
        document.getElementById("prompt-template-category").value = template?.category || "feature";
        document.getElementById("prompt-template-risk").value = template?.risk_level || "medium";
        document.getElementById("prompt-template-description").value = template?.description || "";
        document.getElementById("prompt-template-tags").value = Array.isArray(template?.tags) ? template.tags.join(", ") : "";
        document.getElementById("prompt-template-body").value = template?.body || "";
    },

    editSelectedPromptTemplate() {
        if (!this.selectedPromptTemplate) return;
        this.fillPromptTemplateForm(this.selectedPromptTemplate);
        NexusCore.showToast("Template loaded into editor.", "primary");
    },

    resetPromptTemplateForm() {
        this.fillPromptTemplateForm(null);
    },

    async savePromptTemplate() {
        const templateId = document.getElementById("prompt-template-id")?.value || "";
        const data = this.promptTemplateFormData();
        try {
            const response = await fetch(templateId ? `/api/prompt-vault/templates/${templateId}` : "/api/prompt-vault/templates", {
                method: templateId ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "success") {
                throw new Error(payload.message || "Unable to save template.");
            }
            this.selectedPromptTemplate = payload.template;
            this.fillPromptTemplateForm(payload.template);
            await this.loadPromptVaultTemplates();
            this.renderPromptVaultTemplateDetail(payload.template);
            NexusCore.showToast("Prompt template saved.", "success");
        } catch (error) {
            NexusCore.showToast(`Prompt template error: ${error.message}`, "error");
        }
    },

    async copySelectedPromptTemplate() {
        if (!this.selectedPromptTemplate) return;
        try {
            await this.copyTextToClipboard(this.selectedPromptTemplate.body || "");
            await fetch(`/api/prompt-vault/templates/${this.selectedPromptTemplate.id}/mark-used`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ result: "success" }),
            });
            NexusCore.showToast("Prompt template copied.", "success");
            await this.loadPromptVaultTemplates();
        } catch (error) {
            NexusCore.showToast(`Copy Template error: ${error.message}`, "error");
        }
    },

    async archiveSelectedPromptTemplate() {
        if (!this.selectedPromptTemplate) return;
        try {
            const response = await fetch(`/api/prompt-vault/templates/${this.selectedPromptTemplate.id}/archive`, {
                method: "POST",
            });
            const payload = await response.json();
            if (!response.ok || payload.status !== "success") {
                throw new Error(payload.message || "Unable to archive template.");
            }
            this.selectedPromptTemplate = null;
            this.renderPromptVaultTemplateDetail(null);
            await this.loadPromptVaultTemplates();
            NexusCore.showToast("Prompt template archived.", "success");
        } catch (error) {
            NexusCore.showToast(`Archive error: ${error.message}`, "error");
        }
    },

    async copyCodexCommand(command) {
        try {
            await this.copyTextToClipboard(command);
            NexusCore.showToast("Codex command copied.", "success");
        } catch (error) {
            NexusCore.showToast("Unable to copy Codex command.", "error");
        }
    },

    async copyAllWorkPacketCodexCommands() {
        const tasks = this.latestWorkPacketPreview?.tasks || [];
        const commands = tasks
            .map((task) => task.codex_command)
            .filter((command) => command);

        if (!commands.length) {
            NexusCore.showToast("Preview a packet with codex commands before copying.", "error");
            return;
        }

        try {
            await this.copyTextToClipboard(commands.join("\n"));
            NexusCore.showToast("All Codex commands copied.", "success");
        } catch (error) {
            NexusCore.showToast("Unable to copy Codex commands.", "error");
        }
    },

    createTaskCard(task) {
        const card = document.createElement("div");
        card.className = "card bg-white border p-3";

        const header = document.createElement("div");
        header.className = "d-flex justify-content-between align-items-start gap-2 mb-2";

        const title = document.createElement("h6");
        title.className = "text-dark fw-bold mb-0";
        title.textContent = task.title;

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "btn btn-outline-danger btn-sm border-0 py-0 px-2";
        deleteButton.textContent = "🗑️";
        deleteButton.title = "Delete task";
        deleteButton.setAttribute("aria-label", `Delete task ${task.title}`);
        deleteButton.addEventListener("click", () => {
            this.deleteTask(task.id);
        });

        header.appendChild(title);
        header.appendChild(deleteButton);
        card.appendChild(header);

        const description = document.createElement("p");
        description.className = "text-secondary small mb-3";
        description.textContent = task.description;
        card.appendChild(description);

        const controls = document.createElement("div");
        controls.className = "d-flex flex-wrap gap-2";
        const codexCommand = this.extractCodexCommand(task.description);

        if (codexCommand) {
            if (this.executionMode === "one_task") {
                const runOneButton = document.createElement("button");
                runOneButton.type = "button";
                runOneButton.className = "btn btn-primary btn-sm";
                runOneButton.textContent = "Run One Task";
                runOneButton.addEventListener("click", () => {
                    this.runOneTask(task.id, runOneButton);
                });
                controls.appendChild(runOneButton);
            }

            const copyButton = document.createElement("button");
            copyButton.type = "button";
            copyButton.className = "btn btn-outline-secondary btn-sm";
            copyButton.textContent = "Copy Codex";
            copyButton.addEventListener("click", () => {
                this.copyCodexCommand(codexCommand);
            });
            controls.appendChild(copyButton);
        }

        const addStatusButton = (label, status, styleClass = "btn-outline-primary") => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `btn ${styleClass} btn-sm`;
            button.textContent = label;
            button.addEventListener("click", () => {
                this.advanceTask(task.id, status);
            });
            controls.appendChild(button);
        };

        if (task.status === "todo") {
            addStatusButton("Move to Review", "review");
        } else if (task.status === "review") {
            addStatusButton("Mark Done", "done");
            addStatusButton("⏪ Revert to To-Do", "todo", "btn-outline-secondary");
        } else if (task.status === "done") {
            addStatusButton("⏪ Revert to Review", "review", "btn-outline-secondary");
        }

        if (controls.children.length) {
            card.appendChild(controls);
        }

        return card;
    },

    async runOneTask(taskId, button = null) {
        if (this.executionMode !== "one_task") {
            NexusCore.showToast("Run One Task is available only in One Task mode.", "error");
            return;
        }

        if (!NexusState.currentWorkspaceId) {
            NexusCore.showToast("Select an active workspace before running one task.", "error");
            return;
        }

        const originalLabel = button ? button.textContent : "";
        if (button) {
            button.disabled = true;
            button.textContent = "Running...";
        }

        try {
            const response = await fetch("/api/tasks/run-one", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    workspace_id: NexusState.currentWorkspaceId,
                    task_id: taskId,
                }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.stderr || data.message || `Task run ended with status ${data.status || "failed"}.`);
            }

            NexusCore.showToast("Run One Task completed successfully.", "success");
        } catch (error) {
            NexusCore.showToast(`Run One Task failed: ${error.message}`, "error");
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = originalLabel || "Run One Task";
            }
            await this.loadKanban();
            await this.loadCostLedger();
            await this.loadFactoryConsole();
        }
    },

    async advanceTask(taskId, status) {
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: status }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || "Unable to update task.");
            }

            await this.loadKanban();
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async deleteTask(taskId) {
        if (!(await NexusCore.confirmAction("Permanently delete this task?"))) {
            return;
        }

        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: "DELETE",
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to delete task.");
            }

            await this.loadKanban();
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async loadExecutionMode() {
        try {
            const response = await fetch("/api/execution-mode");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load execution mode.");
            }

            this.executionMode = data.execution_mode || "manual";
            this.automaticAnalysisEnabled = Boolean(data.automatic_analysis_enabled);
            this.renderExecutionMode();
            this.updateAutoPilotUI();
            this.renderWorkPacketRunnerStatus();
            if (NexusState.currentTab === "board") {
                this.renderTasks(NexusState.tasks);
            }
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async setExecutionMode(mode) {
        try {
            const response = await fetch("/api/execution-mode", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ execution_mode: mode }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to update execution mode.");
            }

            this.executionMode = data.execution_mode || "manual";
            this.automaticAnalysisEnabled = Boolean(data.automatic_analysis_enabled);
            this.renderExecutionMode();
            this.updateAutoPilotUI();
            this.renderWorkPacketRunnerStatus();
            if (NexusState.currentTab === "board") {
                this.renderTasks(NexusState.tasks);
            }
            NexusCore.showToast(
                this.executionMode === "autopilot"
                    ? "Execution mode set to Auto-Pilot."
                    : (this.executionMode === "one_task"
                        ? "Execution mode set to One Task."
                        : (this.executionMode === "one_packet"
                            ? "Execution mode set to One Packet."
                            : "Execution mode set to Manual.")),
                "success",
            );
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    renderExecutionMode() {
        const isAutoPilot = this.executionMode === "autopilot";
        const isOneTask = this.executionMode === "one_task";
        const isOnePacket = this.executionMode === "one_packet";
        const label = isAutoPilot
            ? "Auto-Pilot Mode - automatic analysis enabled"
            : (isOneTask
                ? "One Task Mode - run a single selected Codex task"
                : (isOnePacket
                    ? "One Packet Mode - supervised packet runner"
                    : "Manual Mode - Auto-Pilot and automatic analysis disabled"));
        const indicatorClass = isAutoPilot
            ? "badge text-bg-primary border"
            : ((isOneTask || isOnePacket) ? "badge text-bg-info border" : "badge text-bg-warning border");

        ["execution-mode-indicator", "execution-mode-header"].forEach((id) => {
            const indicator = document.getElementById(id);
            if (!indicator) {
                return;
            }
            indicator.textContent = label;
            indicator.className = indicatorClass;
        });

        const manualButton = document.getElementById("execution-mode-manual-btn");
        const oneTaskButton = document.getElementById("execution-mode-one-task-btn");
        const onePacketButton = document.getElementById("execution-mode-one-packet-btn");
        const autoPilotButton = document.getElementById("execution-mode-autopilot-btn");
        if (manualButton) {
            manualButton.className = this.executionMode === "manual"
                ? "btn btn-warning"
                : "btn btn-outline-secondary";
        }
        if (oneTaskButton) {
            oneTaskButton.className = isOneTask
                ? "btn btn-info"
                : "btn btn-outline-secondary";
        }
        if (onePacketButton) {
            onePacketButton.className = isOnePacket
                ? "btn btn-info"
                : "btn btn-outline-secondary";
        }
        if (autoPilotButton) {
            autoPilotButton.className = isAutoPilot
                ? "btn btn-primary"
                : "btn btn-outline-secondary";
        }
    },

    updateAutoPilotUI() {
        const button = document.getElementById("auto-pilot-btn");
        if (!button) {
            return;
        }

        if (this.executionMode !== "autopilot") {
            button.disabled = true;
            button.className = "btn btn-outline-secondary btn-sm";
            button.innerHTML = this.executionMode === "one_task"
                ? "Auto-Pilot Disabled in One Task Mode"
                : (this.executionMode === "one_packet"
                    ? "Auto-Pilot Disabled in One Packet Mode"
                    : "Auto-Pilot Disabled in Manual Mode");
            return;
        }

        button.disabled = Boolean(this.autoPilotState.running);
        button.className = this.autoPilotState.running
            ? "btn btn-outline-success btn-sm"
            : "btn btn-outline-primary btn-sm";
        button.innerHTML = this.autoPilotState.running
            ? '<span class="status-pulse me-2"></span>System Running...'
            : "Engage Auto-Pilot";
    },

    startAutoPilotPolling() {
        if (this.autoPilotPollTimer) {
            return;
        }
        this.autoPilotPollTimer = setInterval(() => {
            this.loadAutoPilotStatus();
        }, 2000);
    },

    stopAutoPilotPolling() {
        if (this.autoPilotPollTimer) {
            clearInterval(this.autoPilotPollTimer);
            this.autoPilotPollTimer = null;
        }
    },

    async loadAutoPilotStatus() {
        try {
            const wasRunning = Boolean(this.autoPilotState.running);
            const response = await fetch("/api/tasks/auto-run/status");
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to load Auto-Pilot status.");
            }

            this.autoPilotState = data.queue;
            this.updateAutoPilotUI();
            if (data.queue.running) {
                this.startAutoPilotPolling();
                if (NexusState.currentTab === "board") {
                    await this.loadTasks(NexusState.currentWorkspaceId);
                }
                return;
            }

            this.stopAutoPilotPolling();
            if (wasRunning) {
                await this.loadKanban();
                showToast(
                    data.queue.message,
                    data.queue.state === "complete" ? "success" : "danger",
                );
            }
        } catch (error) {
            this.stopAutoPilotPolling();
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    async engageAutoPilot() {
        if (this.executionMode !== "autopilot") {
            showToast("Auto-Pilot is disabled while execution mode is manual.", "danger");
            this.updateAutoPilotUI();
            return;
        }

        if (!NexusState.currentWorkspaceId) {
            showToast("Select an active workspace before engaging Auto-Pilot.", "danger");
            return;
        }

        try {
            const response = await fetch("/api/tasks/auto-run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ workspace_id: NexusState.currentWorkspaceId }),
            });
            const data = await response.json();
            if (!response.ok || data.status !== "success") {
                throw new Error(data.message || "Unable to engage Auto-Pilot.");
            }

            this.autoPilotState = data.queue;
            this.updateAutoPilotUI();
            this.startAutoPilotPolling();
            showToast("Auto-Pilot engaged. Tasks will execute sequentially.", "success");
        } catch (error) {
            showToast(`Auto-Pilot failed to start: ${error.message}`, "danger");
        }
    },

    async boot() {
        NexusKanban.init();

        setInterval(() => {
            if (this.workspaceActive) {
                this.fetchUpdate();
                this.refreshVisibleTasks();
            }
        }, 3000);

        await this.loadPortfolio();
        this.startHealthPolling();

        try {
            const response = await fetch("/api/settings");
            const data = await response.json();
            NexusSettings.syncProviderSwitch(data.provider || "gemini");
        } catch (error) {
            console.error(error);
        }

        await this.loadExecutionMode();

        document.addEventListener("shown.bs.collapse", (event) => {
            NexusState.expandedStates[event.target.id] = true;
        });

        document.addEventListener("hidden.bs.collapse", (event) => {
            NexusState.expandedStates[event.target.id] = false;
        });
    },
};

NexusApp.boot();
