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
    latestCostLedger: null,
    latestFactoryConsole: null,

    setTab(tab) {
        const tabViews = {
            arch: "explorer",
            chat: "chat",
            board: "board",
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
            this.renderFactoryConsole(data);
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

    renderFactoryConsole(data) {
        const factory = data?.factory || {};
        const git = data?.git || {};
        const summaryTarget = document.getElementById("factory-console-summary");
        if (summaryTarget) {
            summaryTarget.innerHTML = "";
            [
                ["Execution Mode", factory.execution_mode || "unknown"],
                ["Automatic Analysis", factory.automatic_analysis_enabled ? "enabled" : "disabled"],
                ["Factory State", factory.current_state || "idle"],
                ["Git State", git.is_dirty ? "dirty" : "clean"],
                ["Recent Events", factory.recent_event_count || 0],
                ["Recent Runs", factory.recent_run_count || 0],
            ].forEach(([label, value]) => {
                const column = document.createElement("div");
                column.className = "col-sm-6 col-lg-4";
                const metric = document.createElement("div");
                metric.className = "border rounded bg-light p-3 h-100";
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

        this.renderFactoryGitStatus(git);
        this.renderFactoryEvents(data?.recent_events || []);
        this.renderFactoryRuns(data?.recent_runs || []);
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
            filesTarget.className = "border rounded bg-light p-3 small text-secondary";
            if (!changedFiles.length) {
                filesTarget.textContent = git?.is_dirty ? "Git changes detected." : "Git is clean.";
            } else {
                const list = document.createElement("ul");
                list.className = "list-unstyled mb-0";
                changedFiles.slice(0, 20).forEach((file) => {
                    const item = document.createElement("li");
                    item.className = "d-flex gap-2";
                    const status = document.createElement("span");
                    status.className = "font-monospace text-dark";
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
        }
    },

    renderFactoryEvents(events) {
        const target = document.getElementById("factory-events-list");
        if (!target) return;
        target.innerHTML = "";
        target.className = "border rounded bg-light p-3 small text-secondary";
        if (!events.length) {
            target.textContent = "No factory events recorded yet.";
            return;
        }

        const list = document.createElement("div");
        list.className = "d-flex flex-column gap-2";
        events.slice(0, 10).forEach((event) => {
            const item = document.createElement("div");
            item.className = "border rounded bg-white p-2";
            const title = document.createElement("div");
            title.className = "fw-semibold text-dark";
            title.textContent = event.event_type || "event";
            const message = document.createElement("div");
            message.textContent = event.message || "";
            const meta = document.createElement("div");
            meta.className = "text-secondary";
            meta.textContent = event.created_at ? new Date(event.created_at).toLocaleString() : "";
            item.appendChild(title);
            item.appendChild(message);
            item.appendChild(meta);
            list.appendChild(item);
        });
        target.appendChild(list);
    },

    renderFactoryRuns(runs) {
        const target = document.getElementById("factory-runs-list");
        if (!target) return;
        target.innerHTML = "";
        target.className = "border rounded bg-light p-3 small text-secondary";
        if (!runs.length) {
            target.textContent = "No execution runs recorded yet.";
            return;
        }

        const list = document.createElement("div");
        list.className = "d-flex flex-column gap-2";
        runs.slice(0, 10).forEach((run) => {
            const item = document.createElement("div");
            item.className = "border rounded bg-white p-2";
            const title = document.createElement("div");
            title.className = "fw-semibold text-dark";
            title.textContent = `${run.status || "unknown"} | task ${run.task_id || "-"}`;
            const meta = document.createElement("div");
            meta.className = "text-secondary";
            meta.textContent = [
                run.returncode !== null && run.returncode !== undefined ? `return ${run.returncode}` : "",
                run.total_tokens ? `${run.total_tokens} tokens` : "",
                run.started_at ? new Date(run.started_at).toLocaleString() : "",
            ].filter(Boolean).join(" | ");
            item.appendChild(title);
            item.appendChild(meta);
            list.appendChild(item);
        });
        target.appendChild(list);
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
                            <button type="button" class="btn btn-outline-secondary btn-sm" onclick="NexusApp.copyAllWorkPacketCodexCommands()">Copy All Codex Commands</button>
                        </div>
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

            await this.loadKanban();
            NexusCore.showToast(`Staged ${data.created_count} task${data.created_count === 1 ? "" : "s"} to Kanban.`, "success");
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
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
            if (NexusState.currentTab === "board") {
                this.renderTasks(NexusState.tasks);
            }
            NexusCore.showToast(
                this.executionMode === "autopilot"
                    ? "Execution mode set to Auto-Pilot."
                    : (this.executionMode === "one_task"
                        ? "Execution mode set to One Task."
                        : "Execution mode set to Manual."),
                "success",
            );
        } catch (error) {
            NexusCore.showToast(`Error: ${error.message}`, "error");
        }
    },

    renderExecutionMode() {
        const isAutoPilot = this.executionMode === "autopilot";
        const isOneTask = this.executionMode === "one_task";
        const label = isAutoPilot
            ? "Auto-Pilot Mode - automatic analysis enabled"
            : (isOneTask
                ? "One Task Mode - run a single selected Codex task"
                : "Manual Mode - Auto-Pilot and automatic analysis disabled");
        const indicatorClass = isAutoPilot
            ? "badge text-bg-primary border"
            : (isOneTask ? "badge text-bg-info border" : "badge text-bg-warning border");

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
                : "Auto-Pilot Disabled in Manual Mode";
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
