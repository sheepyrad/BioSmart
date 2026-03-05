import type { BoltzMetricSeries, MoleculeResult, OptConfig, RunInfo } from '@shared/types';

const DEFAULT_RUNNER_URL =
  import.meta.env.VITE_RUNNER_URL || 'http://127.0.0.1:45731';

type RunnerStartPayload = {
  config: OptConfig;
  configPath?: string | null;
  configId?: string | null;
  name?: string | null;
};

type RunnerEventName = 'run:output' | 'run:status-changed' | 'run:checkpoint-saved' | 'run:error';

type RunnerEventMap = {
  'run:output': { runId: string; output: string };
  'run:status-changed': RunInfo;
  'run:checkpoint-saved': { runId: string; checkpointPath: string };
  'run:error': { runId: string; error: string };
};

class RunnerClient {
  private baseUrl: string;
  private eventSource: EventSource | null = null;
  private listeners = new Map<RunnerEventName, Set<(data: any) => void>>();
  private lastHealthCheck = 0;
  private lastHealthOk = false;

  constructor(baseUrl = DEFAULT_RUNNER_URL) {
    this.baseUrl = baseUrl;
  }

  async isAvailable(force = false): Promise<boolean> {
    const now = Date.now();
    if (!force && now - this.lastHealthCheck < 5000) {
      return this.lastHealthOk;
    }
    this.lastHealthCheck = now;
    try {
      const res = await fetch(`${this.baseUrl}/health`, { method: 'GET' });
      this.lastHealthOk = res.ok;
    } catch {
      this.lastHealthOk = false;
    }
    return this.lastHealthOk;
  }

  async listRuns(): Promise<RunInfo[]> {
    const res = await fetch(`${this.baseUrl}/runs`);
    if (!res.ok) throw new Error('Failed to list runs');
    return (await res.json()) as RunInfo[];
  }

  async getRun(runId: string): Promise<RunInfo | null> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to get run');
    return (await res.json()) as RunInfo;
  }

  async deleteRun(runId: string): Promise<void> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/delete`, {
      method: 'POST',
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to delete run');
    }
  }

  async startRun(payload: RunnerStartPayload): Promise<RunInfo> {
    const res = await fetch(`${this.baseUrl}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to start run');
    }
    return (await res.json()) as RunInfo;
  }

  async stopRun(runId: string): Promise<void> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/stop`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to stop run');
  }

  async resumeRun(runId: string, checkpointPath: string, oracleIdx?: number): Promise<RunInfo> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ checkpointPath, oracleIdx }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to resume run');
    }
    return (await res.json()) as RunInfo;
  }

  async getCheckpoints(runId: string): Promise<string[]> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/checkpoints`);
    if (!res.ok) throw new Error('Failed to get checkpoints');
    return (await res.json()) as string[];
  }

  async getOutput(runId: string, tail = 500): Promise<string[]> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/output?tail=${tail}`);
    if (!res.ok) throw new Error('Failed to get output');
    const data = (await res.json()) as { lines: string[] };
    return data.lines;
  }

  async deleteRun(runId: string): Promise<void> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to delete run');
    }
  }

  async getTopMolecules(runId: string, limit = 50): Promise<MoleculeResult[]> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/molecules?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to get molecules');
    return (await res.json()) as MoleculeResult[];
  }

  async getComplex(runId: string, oracleIdx: number, molIdx: number): Promise<string | null> {
    const res = await fetch(
      `${this.baseUrl}/runs/${encodeURIComponent(runId)}/complex?oracleIdx=${oracleIdx}&molIdx=${molIdx}`
    );
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to get complex');
    return await res.text();
  }

  async importExistingRun(resultDir: string, name?: string | null): Promise<RunInfo> {
    const res = await fetch(`${this.baseUrl}/runs/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resultDir, name: name ?? null }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to import run');
    }
    return (await res.json()) as RunInfo;
  }

  async syncRunToCloud(runId: string): Promise<RunInfo> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/sync-cloud`, {
      method: 'POST',
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to sync run to cloud');
    }
    return (await res.json()) as RunInfo;
  }

  async getBoltzMetrics(runId: string): Promise<BoltzMetricSeries | null> {
    const res = await fetch(`${this.baseUrl}/runs/${encodeURIComponent(runId)}/boltz-metrics`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('Failed to get boltz metrics');
    return (await res.json()) as BoltzMetricSeries | null;
  }

  on<K extends RunnerEventName>(event: K, handler: (data: RunnerEventMap[K]) => void): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(handler as any);
    this.ensureEventSource();

    return () => {
      const handlers = this.listeners.get(event);
      if (handlers) {
        handlers.delete(handler as any);
      }
    };
  }

  private ensureEventSource() {
    if (this.eventSource) return;
    this.eventSource = new EventSource(`${this.baseUrl}/events`);

    const forward = <K extends RunnerEventName>(event: K) => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunnerEventMap[K];
        const handlers = this.listeners.get(event);
        if (handlers) {
          for (const h of handlers) h(data as any);
        }
      } catch (err) {
        console.warn('Failed to parse runner event', event, err);
      }
    };

    this.eventSource.addEventListener('run:output', forward('run:output'));
    this.eventSource.addEventListener('run:status-changed', forward('run:status-changed'));
    this.eventSource.addEventListener('run:checkpoint-saved', forward('run:checkpoint-saved'));
    this.eventSource.addEventListener('run:error', forward('run:error'));

    this.eventSource.onerror = () => {
      // Allow reconnect on next subscription
      this.eventSource?.close();
      this.eventSource = null;
    };
  }
}

export const runnerClient = new RunnerClient();
