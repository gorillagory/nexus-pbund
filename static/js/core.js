window.NexusState = {
    currentTab: "arch",
    globalData: null,
    expandedStates: {},
    selectedFiles: new Set(),
    indexToPathMap: [],
    currentRawMd: "",
    currentSessionId: `session_${Date.now()}`,
};

const renderer = new marked.Renderer();

renderer.code = function (tokenOrText, language) {
    const text = typeof tokenOrText === "object" ? tokenOrText.text : tokenOrText;
    const lang = typeof tokenOrText === "object" ? tokenOrText.lang : language;

    if (lang === "mermaid") {
        return `<div class="mermaid">${text}</div>`;
    }

    return `<pre><code class="language-${lang || ""}">${text}</code></pre>`;
};

marked.use({ renderer: renderer });
mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });

window.NexusCore = {
    showToast(message, type = "primary") {
        const el = document.getElementById("nexusToast");
        document.getElementById("toast-message").innerText = message;
        el.className = `toast align-items-center border-0 text-white bg-${type === "error" ? "danger" : (type === "success" ? "success" : "primary")}`;
        new bootstrap.Toast(el).show();
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
