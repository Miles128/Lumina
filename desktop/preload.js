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
  openWorkspace() {
    return ipcRenderer.invoke("window:openWorkspace");
  },
});
