window.NexusKanban = {
    init() {
        const workspaceSelector = document.getElementById("workspace-navigator");
        const boardTab = document.getElementById("tab-board-btn");

        workspaceSelector.addEventListener("change", () => {
            const workspaceId = this.getSelectedWorkspaceId();
            if (workspaceId) {
                NexusState.currentWorkspaceId = workspaceId;
                NexusApp.loadTasks(workspaceId);
                return;
            }

            NexusState.currentWorkspaceId = null;
            NexusState.tasks = [];
            if (NexusState.currentTab === "board") {
                NexusApp.renderTasks([]);
            }
        });

        boardTab.addEventListener("click", () => {
            const workspaceId = this.getSelectedWorkspaceId();
            if (workspaceId) {
                NexusApp.loadTasks(workspaceId);
            }
        });
    },

    getSelectedWorkspaceId() {
        const selectedOption = document.getElementById("workspace-navigator").selectedOptions[0];
        return selectedOption && selectedOption.dataset.workspaceId
            ? Number(selectedOption.dataset.workspaceId)
            : null;
    },

    async activateWorkspace(workspaceId) {
        const selectedOption = document.getElementById("workspace-navigator").selectedOptions[0];
        if (selectedOption) {
            selectedOption.dataset.workspaceId = String(workspaceId);
        }

        NexusState.currentWorkspaceId = workspaceId;
        await NexusApp.loadTasks(workspaceId);
    },
};
