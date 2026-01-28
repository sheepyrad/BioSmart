import { useCallback, useEffect, useState } from 'react';
import type { IpcChannels, IpcEvents, RunInfo } from '@shared/types';
import { webFallback, isElectron } from '@/lib/webFallback';

// Typed IPC invoke hook - uses Electron API if available, falls back to web implementation
export function useIpcInvoke() {
  return useCallback(
    <K extends keyof IpcChannels>(channel: K, ...args: Parameters<IpcChannels[K]>) => {
      if (isElectron()) {
        return window.electronAPI.invoke(channel, ...args);
      }
      // Use web fallback
      return webFallback[channel](...args) as ReturnType<IpcChannels[K]>;
    },
    []
  );
}

// Hook for IPC events
export function useIpcEvent<K extends keyof IpcEvents>(
  channel: K,
  handler: IpcEvents[K]
) {
  useEffect(() => {
    if (!isElectron()) {
      // No events in web mode
      return;
    }
    const unsubscribe = window.electronAPI.on(channel, handler);
    return unsubscribe;
  }, [channel, handler]);
}

// Hook for run status changes
export function useRunStatus(runId: string | null) {
  const [status, setStatus] = useState<RunInfo | null>(null);
  const invoke = useIpcInvoke();

  useEffect(() => {
    if (!runId) {
      setStatus(null);
      return;
    }

    // Initial fetch
    invoke('run:get-status', runId).then(setStatus);

    // Listen for updates (Electron only)
    if (!isElectron()) {
      return;
    }
    
    const unsubscribe = window.electronAPI.on('run:status-changed', (info: RunInfo) => {
      if (info.id === runId) {
        setStatus(info);
      }
    });

    return unsubscribe;
  }, [runId, invoke]);

  return status;
}

// Hook for run output
export function useRunOutput(runId: string | null) {
  const [output, setOutput] = useState<string[]>([]);

  useEffect(() => {
    if (!runId || !isElectron()) {
      setOutput([]);
      return;
    }

    const unsubscribe = window.electronAPI.on('run:output', (id: string, line: string) => {
      if (id === runId) {
        setOutput((prev) => [...prev.slice(-500), line]); // Keep last 500 lines
      }
    });

    return unsubscribe;
  }, [runId]);

  return output;
}
