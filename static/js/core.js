window.NexusState = {
    currentTab: "arch",
    globalData: null,
    expandedStates: {},
    selectedFiles: new Set(),
    indexToPathMap: [],
    currentRawMd: "",
    currentSessionId: `session_${Date.now()}`,
    currentWorkspaceId: null,
    tasks: [],
};

const renderer = new marked.Renderer();

renderer.code = function (tokenOrText, language) {
    const text = typeof tokenOrText === "object" ? tokenOrText.text : tokenOrText;
    const lang = typeof tokenOrText === "object" ? tokenOrText.lang : language;

    if (lang === "mermaid") {
        return `<div class="mermaid">${text}</div>`;
    }

    const escapedText = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    return `<pre><code class="language-${lang || ""}">${escapedText}</code></pre>`;
};

marked.use({ renderer: renderer });
mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });

window.NexusCore = {
    showToast(message, type = "primary") {
        const el = document.getElementById("nexusToast");
        document.getElementById("toast-message").innerText = message;
        el.className = `toast align-items-center border-0 text-white bg-${type === "error" ? "danger" : (type === "success" ? "success" : "primary")}`;
        new bootstrap.Toast(el).show();
    },

    confirmAction(message, options = {}) {
        const modalElement = document.getElementById("confirmActionModal");
        const messageElement = document.getElementById("confirmActionMessage");
        const titleElement = document.getElementById("confirmActionTitle");
        const yesButton = document.getElementById("confirmActionYes");
        const noButton = document.getElementById("confirmActionNo");

        if (!modalElement || !messageElement || !titleElement || !yesButton || !noButton) {
            return Promise.resolve(false);
        }

        return new Promise((resolve) => {
            const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
            let resolved = false;

            const complete = (value) => {
                if (resolved) return;
                resolved = true;
                yesButton.removeEventListener("click", onYes);
                noButton.removeEventListener("click", onNo);
                modalElement.removeEventListener("hidden.bs.modal", onHidden);
                modal.hide();
                resolve(value);
            };
            const onYes = () => complete(true);
            const onNo = () => complete(false);
            const onHidden = () => complete(false);

            titleElement.textContent = options.title || "Confirm Action";
            messageElement.textContent = message;
            yesButton.textContent = options.confirmLabel || "Yes";
            noButton.textContent = options.cancelLabel || "No";
            yesButton.className = `btn btn-${options.variant || "danger"} btn-sm px-3`;

            yesButton.addEventListener("click", onYes);
            noButton.addEventListener("click", onNo);
            modalElement.addEventListener("hidden.bs.modal", onHidden);
            modal.show();
        });
    },

    escapeSingleQuotes(value) {
        return value.replace(/'/g, "\\'");
    },

    async renderMarkdownWithMermaid(mdContent, containerId) {
        const container = document.getElementById(containerId);
        container.innerHTML = marked.parse(mdContent);

        try {
            await mermaid.run({ querySelector: ".mermaid" });
        } catch (error) {
            console.warn("Mermaid parsing failed", error);
            document.querySelectorAll(".mermaid").forEach((element) => {
                if (!element.querySelector("svg")) {
                    element.innerHTML = `
                        <div class="mermaid-error">
                            <strong><i class="bi bi-exclamation-triangle me-2"></i>Mermaid Render Error</strong><br>
                            AI generated invalid syntax.<br>
                            ${error.message.split("\n")[0]}
                        </div>
                    `;
                }
            });
        }
    },
};

window.confirmAction = (message, options = {}) => NexusCore.confirmAction(message, options);
