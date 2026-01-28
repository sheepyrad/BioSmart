import { contextBridge, ipcRenderer } from 'electron';
import type { IpcChannels, IpcEvents } from '../shared/types';

// Type-safe invoke wrapper
function createInvoke() {
  return <K extends keyof IpcChannels>(
    channel: K,
    ...args: Parameters<IpcChannels[K]>
  ): ReturnType<IpcChannels[K]> => {
    return ipcRenderer.invoke(channel, ...args) as ReturnType<IpcChannels[K]>;
  };
}

// Type-safe event listener wrapper
function createOn() {
  return <K extends keyof IpcEvents>(
    channel: K,
    callback: IpcEvents[K]
  ): (() => void) => {
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
