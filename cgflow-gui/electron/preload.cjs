const { contextBridge, ipcRenderer } = require('electron');

function createInvoke() {
  return (channel, ...args) => {
    return ipcRenderer.invoke(channel, ...args);
  };
}

function createOn() {
  return (channel, callback) => {
    const handler = (_event, ...args) => {
      callback(...args);
    };
    ipcRenderer.on(channel, handler);
    return () => {
      ipcRenderer.removeListener(channel, handler);
    };
  };
}

const api = {
  invoke: createInvoke(),
  on: createOn(),
};

contextBridge.exposeInMainWorld('electronAPI', api);
