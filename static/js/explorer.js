window.NexusExplorer = {
    renderList() {
        if (!NexusState.globalData) {
            return;
        }

        const container = document.getElementById("file-list");
        const scrollPos = container.scrollTop;

        container.innerHTML = "";
        NexusState.indexToPathMap = [];

        let count = 1;
        const groups = { backend: {}, frontend: {}, other: {} };

        Object.entries(NexusState.globalData.files).sort().forEach(([path, info]) => {
            if (!groups[info.layer][info.role]) {
                groups[info.layer][info.role] = [];
            }

            groups[info.layer][info.role].push([path, info]);
        });

        ["backend", "frontend", "other"].forEach((layer) => {
            if (!Object.keys(groups[layer]).length) {
                return;
            }

            const layerId = `layer-${layer}`;
            if (NexusState.expandedStates[layerId] === undefined) {
                NexusState.expandedStates[layerId] = true;
            }

            const header = document.createElement("div");
            header.className = "layer-header text-uppercase px-2";
            header.innerHTML = `<span>${layer}</span> <i class="bi bi-chevron-${NexusState.expandedStates[layerId] ? "down" : "right"}"></i>`;
            header.onclick = () => {
                NexusState.expandedStates[layerId] = !NexusState.expandedStates[layerId];
                this.renderList();
            };
            container.appendChild(header);

            if (!NexusState.expandedStates[layerId]) {
                return;
            }

            Object.entries(groups[layer]).sort().forEach(([role, files]) => {
                const roleId = `role-${layer}-${role}`;
                if (NexusState.expandedStates[roleId] === undefined) {
                    NexusState.expandedStates[roleId] = true;
                }

                const roleHeader = document.createElement("div");
                roleHeader.className = "role-header text-uppercase ps-3";
                roleHeader.innerHTML = `<i class="bi bi-folder2 text-primary"></i> ${role}s`;
                roleHeader.onclick = (event) => {
                    event.stopPropagation();
                    NexusState.expandedStates[roleId] = !NexusState.expandedStates[roleId];
                    this.renderList();
                };
                container.appendChild(roleHeader);

                if (!NexusState.expandedStates[roleId]) {
                    return;
                }

                files.sort().forEach(([path, info]) => {
                    const idx = count++;
                    NexusState.indexToPathMap[idx] = path;

                    const isSelected = NexusState.selectedFiles.has(path);
                    const row = document.createElement("div");

                    row.className = `file-item ms-4 d-flex align-items-center ${isSelected ? "selected" : ""}`;
                    row.innerHTML = `
                        <span class="file-index">${idx}</span>
                        <input type="checkbox" class="file-checkbox" ${isSelected ? "checked" : ""} onchange="NexusExplorer.toggleFile('${NexusCore.escapeSingleQuotes(path)}')">
                        <span class="text-truncate flex-grow-1" onclick="NexusInspector.show('${NexusCore.escapeSingleQuotes(path)}')">
                            ${path.split("/").pop()}
                            ${info.has_context ? '<i class="bi bi-stars text-warning ms-1" title="Engineering Context Generated"></i>' : ""}
                        </span>
                    `;

                    container.appendChild(row);
                });
            });
        });

        container.scrollTop = scrollPos;
    },

    toggleFile(path) {
        if (NexusState.selectedFiles.has(path)) {
            NexusState.selectedFiles.delete(path);
        } else {
            NexusState.selectedFiles.add(path);
        }

        this.renderList();
    },

    clearSelections() {
        NexusState.selectedFiles.clear();
        this.renderList();
    },

    selectByNumbers() {
        const input = document.getElementById("number-input");
        const nums = input.value
            .split(/[,\s]+/)
            .map((value) => parseInt(value.trim(), 10))
            .filter((value) => !Number.isNaN(value));

        nums.forEach((num) => {
            if (NexusState.indexToPathMap[num]) {
                NexusState.selectedFiles.add(NexusState.indexToPathMap[num]);
            }
        });

        input.value = "";
        this.renderList();
    },

    copyAllPathsWithNumbers() {
        if (!NexusState.globalData) {
            return;
        }

        let text = "PROJECT FILE LIST:\n\n";
        let count = 1;

        Object.keys(NexusState.globalData.files).sort().forEach((path) => {
            text += `[${count}] ${path}\n`;
            count += 1;
        });

        navigator.clipboard.writeText(text).then(() => {
            NexusCore.showToast("Copied to clipboard");
        });
    },

    async bundleSelected() {
        if (NexusState.selectedFiles.size === 0) {
            NexusCore.showToast("Select files first!", "error");
            return;
        }

        const response = await fetch("/api/bundle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ paths: Array.from(NexusState.selectedFiles) }),
        });

        const data = await response.json();

        if (data.status === "success") {
            NexusCore.showToast("Bundle generated", "success");
        } else {
            NexusCore.showToast(data.message || "Bundle failed", "error");
        }
    },
};
