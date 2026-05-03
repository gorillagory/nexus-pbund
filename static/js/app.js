window.NexusApp = {
    setTab(tab) {
        NexusState.currentTab = tab;

        document.querySelectorAll(".nav-link").forEach((button) => {
            button.classList.toggle("active", false);
        });

        document.getElementById(`tab-${tab}-btn`)?.classList.add("active");

        if (tab === "scripts") {
            NexusScripts.render();
            return;
        }

        if (tab === "map") {
            NexusMap.render();
            return;
        }

        if (tab === "chat") {
            NexusChat.render();
            return;
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
                        <small class="text-danger fw-black uppercase">Live Updates</small>
                        <ul class="list-unstyled mb-0 small mt-1">
                            ${NexusState.globalData.recent_changes.map((file) => `
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
    },

    async boot() {
        setInterval(() => {
            this.fetchUpdate();
        }, 3000);

        await this.fetchUpdate();

        try {
            const response = await fetch("/api/settings");
            const data = await response.json();
            NexusSettings.syncProviderSwitch(data.provider || "gemini");
        } catch (error) {
            console.error(error);
        }

        document.addEventListener("shown.bs.collapse", (event) => {
            NexusState.expandedStates[event.target.id] = true;
        });

        document.addEventListener("hidden.bs.collapse", (event) => {
            NexusState.expandedStates[event.target.id] = false;
        });
    },
};

NexusApp.boot();
