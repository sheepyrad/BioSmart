const { contextBridge, ipcRenderer } = require('electron');

const ALLOWED_CHANNELS = [
  // File operations
  'file:select-pdb',
  'file:select-ligand',
  'file:select-json',
  'file:select-msa',
  'file:select-yaml',
  'file:select-directory',
  'file:read-pdb',
  'file:read-text',
  'file:read-yaml',
  'file:write-yaml',
  'file:exists',
  // Run management
  'run:start',
  'run:stop',
  'run:resume',
  'run:get-status',
  'run:list',
  'run:delete',
  'run:get-checkpoints',
  'run:get-output',
  'run:import-existing',
  'run:sync-to-cloud',
  'run:get-boltz-metrics',
  // Database queries
  'db:get-generated-objects',
  'db:get-boltz-scores',
  'db:get-reward-cache',
  'db:get-top-molecules',
  // Boltz complex files
  'boltz:get-complex-path',
  'boltz:get-complex',
  // Events (main -> renderer)
  'run:output',
  'run:status-changed',
  'run:checkpoint-saved',
  'run:error',
];

function isAllowedChannel(channel) {
  return ALLOWED_CHANNELS.includes(channel);
}

function createInvoke() {
  return (channel, ...args) => {
    if (!isAllowedChannel(channel)) {
      throw new Error('Invalid IPC channel');
    }
    return ipcRenderer.invoke(channel, ...args);
  };
}

function createOn() {
  return (channel, callback) => {
    if (!isAllowedChannel(channel)) {
      throw new Error('Invalid IPC channel');
    }
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
