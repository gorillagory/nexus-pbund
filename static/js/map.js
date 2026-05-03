window.NexusMap = {
    async render() {
        const inspector = document.getElementById("inspector");
        inspector.innerHTML = `<div id="mindmap-container" class="p-3"><div class="mermaid" id="graph-target"></div></div>`;

        let graphData = "graph LR\n";

        NexusState.globalData.routes.forEach((route) => {
            const routeId = `R_${route.path.replace(/[^a-z0-9]/gi, "_")}`;
            const controllerName = route.controller.replace(/[^a-z0-9]/gi, "_");
            graphData += `  ${routeId}["${route.path}"] -- maps to --> ${controllerName}\n`;
        });

        try {
            const { svg } = await mermaid.render(`mermaid-svg-${Date.now()}`, graphData);
            document.getElementById("graph-target").innerHTML = svg;
        } catch (error) {
            console.error(error);
        }
    },
};
