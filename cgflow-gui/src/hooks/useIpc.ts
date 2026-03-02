import { useCallback, useEffect, useState } from 'react';
import type { IpcChannels, IpcEvents, RunInfo } from '@shared/types';
import { webFallback, isElectron } from '@/lib/webFallback';
import { runnerClient } from '@/lib/runnerClient';

// Typed IPC invoke hook - uses Electron API if available, falls back to web implementation
export function useIpcInvoke() {
  return useCallback(
    async <K extends keyof IpcChannels>(channel: K, ...args: Parameters<IpcChannels[K]>) => {
      const runnerChannels: Array<keyof IpcChannels> = [
        'run:start',
        'run:stop',
        'run:resume',
        'run:get-status',
        'run:list',
        'run:get-checkpoints',
        'db:get-top-molecules',
        'boltz:get-complex',
      ];

      if (runnerChannels.includes(channel)) {
        const available = await runnerClient.isAvailable();
        if (available) {
          switch (channel) {
            case 'run:start':
              return runnerClient.startRun(
                args[0] as Parameters<IpcChannels['run:start']>[0]
              ) as ReturnType<IpcChannels[K]>;
            case 'run:stop':
              return runnerClient.stopRun(args[0] as string) as ReturnType<IpcChannels[K]>;
            case 'run:resume':
              return runnerClient.resumeRun(
                args[0] as string,
                args[1] as string,
                args[2] as number | undefined
              ) as ReturnType<IpcChannels[K]>;
            case 'run:get-status':
              return runnerClient.getRun(args[0] as string) as ReturnType<IpcChannels[K]>;
            case 'run:list':
              return runnerClient.listRuns() as ReturnType<IpcChannels[K]>;
            case 'run:get-checkpoints':
              return runnerClient.getCheckpoints(args[0] as string) as ReturnType<IpcChannels[K]>;
            case 'db:get-top-molecules':
              return runnerClient.getTopMolecules(
                args[0] as string,
                args[1] as number | undefined
              ) as ReturnType<IpcChannels[K]>;
            case 'boltz:get-complex':
              return runnerClient.getComplex(
                args[0] as string,
                args[1] as number,
                args[2] as number
              ) as ReturnType<IpcChannels[K]>;
            default:
              break;
          }
        }
      }

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
    let unsubscribe: (() => void) | undefined;

    const setup = async () => {
      const runnerEvents: Array<keyof IpcEvents> = [
        'run:output',
        'run:status-changed',
        'run:checkpoint-saved',
        'run:error',
      ];

      if (runnerEvents.includes(channel)) {
        const available = await runnerClient.isAvailable();
        if (available) {
          unsubscribe = runnerClient.on(channel as any, handler as any);
          return;
        }
      }

      if (isElectron()) {
        unsubscribe = window.electronAPI.on(channel, handler);
      }
    };

    void setup();

    return () => {
      if (unsubscribe) unsubscribe();
    };
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

    let unsubscribe: (() => void) | undefined;
    const setup = async () => {
      const available = await runnerClient.isAvailable();
      if (available) {
        unsubscribe = runnerClient.on('run:status-changed', (info: RunInfo) => {
          if (info.id === runId) {
            setStatus(info);
          }
        });
        return;
      }
      if (isElectron()) {
        unsubscribe = window.electronAPI.on('run:status-changed', (info: RunInfo) => {
          if (info.id === runId) {
            setStatus(info);
          }
        });
      }
    };

    void setup();

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, [runId, invoke]);

  return status;
}

// Hook for run output
export function useRunOutput(runId: string | null) {
  const [output, setOutput] = useState<string[]>([]);

  useEffect(() => {
    if (!runId) {
      setOutput([]);
      return;
    }

    let unsubscribe: (() => void) | undefined;
    const setup = async () => {
      const available = await runnerClient.isAvailable();
      if (available) {
        unsubscribe = runnerClient.on('run:output', ({ runId: id, output: line }) => {
          if (id === runId) {
            setOutput((prev) => [...prev.slice(-500), line]);
          }
        });
        return;
      }

      if (isElectron()) {
        unsubscribe = window.electronAPI.on('run:output', (id: string, line: string) => {
          if (id === runId) {
            setOutput((prev) => [...prev.slice(-500), line]);
          }
        });
      }
    };

    void setup();

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, [runId]);

  return output;
}
