window.NexusSettings = {
    async open() {
        try {
            const response = await fetch("/api/settings");
            const data = await response.json();

            document.getElementById("input-provider").value = data.provider || "auto";
            document.getElementById("input-model-selection-mode").value = data.model_selection_mode || "auto";
            const geminiKeyEl = document.getElementById("input-gemini-api-key");
            geminiKeyEl.value = "";
            geminiKeyEl.placeholder = data.gemini_api_key_configured
                ? "Configured — leave blank to keep existing key"
                : "Enter API key";
            document.getElementById("input-gemini-model").value = data.gemini_model || "";
            const openaiKeyEl = document.getElementById("input-openai-api-key");
            openaiKeyEl.value = "";
            openaiKeyEl.placeholder = data.openai_api_key_configured
                ? "Configured — leave blank to keep existing key"
                : "Enter API key";
            document.getElementById("input-openai-model").value = data.openai_model || "";
            document.getElementById("input-discord-router-enabled").value = data.discord_router_enabled ? "true" : "false";
            document.getElementById("input-trusted-packet-mode-enabled").value = data.trusted_packet_mode_enabled ? "true" : "false";
            const discordSecretEl = document.getElementById("input-discord-ingest-secret");
            discordSecretEl.value = "";
            discordSecretEl.placeholder = data.discord_ingest_secret_configured
                ? "Configured — leave blank to keep existing secret"
                : "Set shared ingest secret";

            this.syncProviderSwitch(data.provider || "auto");
            await this.refreshModelPreview();

            new bootstrap.Modal(document.getElementById("settingsModal")).show();
        } catch (error) {
            NexusCore.showToast("Failed to load settings", "error");
        }
    },

    async save() {
        const payload = {
            provider: document.getElementById("input-provider").value,
            model_selection_mode: document.getElementById("input-model-selection-mode").value,
            gemini_api_key: document.getElementById("input-gemini-api-key").value.trim(),
            gemini_model: document.getElementById("input-gemini-model").value.trim(),
            openai_api_key: document.getElementById("input-openai-api-key").value.trim(),
            openai_model: document.getElementById("input-openai-model").value.trim(),
            discord_router_enabled: document.getElementById("input-discord-router-enabled").value === "true",
            discord_ingest_secret: document.getElementById("input-discord-ingest-secret").value.trim(),
            trusted_packet_mode_enabled: document.getElementById("input-trusted-packet-mode-enabled").value === "true",
        };

        try {
            const response = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (data.status === "success") {
                this.syncProviderSwitch(payload.provider);
                NexusCore.showToast("Settings saved successfully", "success");

                const modalEl = document.getElementById("settingsModal");
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) {
                    modal.hide();
                }

                return;
            }

            NexusCore.showToast("Failed to save settings", "error");
        } catch (error) {
            NexusCore.showToast("Error saving settings", "error");
        }
    },

    async switchProvider(provider) {
        try {
            const response = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ provider: provider }),
            });

            const data = await response.json();

            if (data.status === "success") {
                this.syncProviderSwitch(provider);
                NexusCore.showToast(`Active provider: ${provider}`, "success");
                return;
            }

            NexusCore.showToast("Failed to switch provider", "error");
        } catch (error) {
            NexusCore.showToast("Error switching provider", "error");
        }
    },

    syncProviderSwitch(provider) {
        const switchEl = document.getElementById("active-provider-switch");
        if (switchEl) {
            switchEl.value = provider || "auto";
        }
    },

    async refreshModelPreview() {
        const geminiEl = document.getElementById("gemini-model-preview");
        const openaiEl = document.getElementById("openai-model-preview");
        const geminiSummaryEl = document.getElementById("gemini-model-summary");
        const openaiSummaryEl = document.getElementById("openai-model-summary");

        if (geminiEl) {
            geminiEl.innerHTML = "Loading...";
        }

        if (openaiEl) {
            openaiEl.innerHTML = "Loading...";
        }

        if (geminiSummaryEl) {
            geminiSummaryEl.innerHTML = "";
        }

        if (openaiSummaryEl) {
            openaiSummaryEl.innerHTML = "";
        }

        try {
            const [geminiResponse, openaiResponse] = await Promise.all([
                fetch("/api/models/curated?provider=gemini"),
                fetch("/api/models/curated?provider=openai"),
            ]);

            const geminiData = await geminiResponse.json();
            const openaiData = await openaiResponse.json();

            if (geminiEl) {
                geminiEl.innerHTML = geminiData.status === "success"
                    ? this.renderCuratedCatalog(geminiData)
                    : `<span class="text-danger">${geminiData.message || "Unavailable"}</span>`;
            }

            if (openaiEl) {
                openaiEl.innerHTML = openaiData.status === "success"
                    ? this.renderCuratedCatalog(openaiData)
                    : `<span class="text-danger">${openaiData.message || "Unavailable"}</span>`;
            }

            if (geminiSummaryEl && geminiData.status === "success") {
                geminiSummaryEl.innerHTML = `Curated ${geminiData.curated_count} / Raw ${geminiData.raw_count}`;
            }

            if (openaiSummaryEl && openaiData.status === "success") {
                openaiSummaryEl.innerHTML = `Curated ${openaiData.curated_count} / Raw ${openaiData.raw_count}`;
            }
        } catch (error) {
            if (geminiEl) {
                geminiEl.innerHTML = `<span class="text-danger">Unavailable</span>`;
            }

            if (openaiEl) {
                openaiEl.innerHTML = `<span class="text-danger">Unavailable</span>`;
            }
        }
    },

    renderCuratedCatalog(data) {
        const recommended = data.recommended || {};
        const models = data.curated_models || [];

        const recommendedBlock = `
            <div class="mb-3">
                <div class="text-info">fast: ${recommended.fast || "-"}</div>
                <div class="text-info">balanced: ${recommended.balanced || "-"}</div>
                <div class="text-info">deep: ${recommended.deep || "-"}</div>
                <div class="text-info">coding: ${recommended.coding || "-"}</div>
                <div class="text-info">bulk: ${recommended.bulk || "-"}</div>
            </div>
        `;

        const listBlock = models.length
            ? models.map((model) => `<div>${model}</div>`).join("")
            : `<span class="text-secondary">No curated models found</span>`;

        return `${recommendedBlock}<div class="border-top border-secondary pt-2">${listBlock}</div>`;
    },
};
