import { contextBridge, ipcRenderer } from 'electron';
import type { IpcChannels, IpcEvents } from '../shared/types';

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
  'boltz:read-complex',
  // Events (main -> renderer)
  'run:output',
  'run:status-changed',
  'run:checkpoint-saved',
  'run:error',
] as const;

function isAllowedChannel(channel: string): channel is (typeof ALLOWED_CHANNELS)[number] {
  return (ALLOWED_CHANNELS as readonly string[]).includes(channel);
}

// Type-safe invoke wrapper
function createInvoke() {
  return <K extends keyof IpcChannels>(
    channel: K,
    ...args: Parameters<IpcChannels[K]>
  ): ReturnType<IpcChannels[K]> => {
    if (!isAllowedChannel(channel)) {
      throw new Error('Invalid IPC channel');
    }
    return ipcRenderer.invoke(channel, ...args) as ReturnType<IpcChannels[K]>;
  };
}

// Type-safe event listener wrapper
function createOn() {
  return <K extends keyof IpcEvents>(
    channel: K,
    callback: IpcEvents[K]
  ): (() => void) => {
    if (!isAllowedChannel(channel)) {
      throw new Error('Invalid IPC channel');
    }
    const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => {
      (callback as (...args: unknown[]) => void)(...args);
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

// TypeScript declaration for renderer
export type ElectronAPI = typeof api;