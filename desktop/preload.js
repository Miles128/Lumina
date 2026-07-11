const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("secretary", {
  request(method, route, body) {
    return ipcRenderer.invoke("backend:request", method, route, body);
  },
  minimize() {
    return ipcRenderer.invoke("window:minimize");
  },
  close() {
    return ipcRenderer.invoke("window:close");
  },
  openKnowledge() {
    return ipcRenderer.invoke("window:openKnowledge");
  },
  // openWorkspace is an intentional alias of openKnowledge — both IPC handlers
  // route to createKnowledgeWindow(). Kept as a distinct name so callers that
  // semantically mean "open the workspace" read clearly at the call site.
  openWorkspace() {
    return ipcRenderer.invoke("window:openWorkspace");
  },
  pickDirectory(defaultPath) {
    return ipcRenderer.invoke("dialog:pickDirectory", defaultPath || "");
  },
  pickFiles(defaultPath) {
    return ipcRenderer.invoke("dialog:pickFiles", defaultPath || "");
  },
});
