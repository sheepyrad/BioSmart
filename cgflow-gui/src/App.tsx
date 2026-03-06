import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import ConfigBuilder from '@/pages/ConfigBuilder';
import Dashboard from '@/pages/Dashboard';
import type { RunInfo, OptConfig } from '@shared/types';
import { Activity, LayoutDashboard, Settings } from 'lucide-react';

export default function App() {
  const [activeRun, setActiveRun] = useState<RunInfo | null>(null);
  const [, setCurrentConfig] = useState<OptConfig | null>(null);
  const [activeTab, setActiveTab] = useState('config');

  const runStatusVariant =
    activeRun?.status === 'running'
      ? 'success'
      : activeRun?.status === 'error'
        ? 'destructive'
        : activeRun?.status === 'paused'
          ? 'warning'
          : 'secondary';

  return (
    <div className="h-screen bg-background text-foreground">
      <div className="flex h-full flex-col">
        <header className="border-b border-border bg-card">
          <div className="flex items-start justify-between gap-6 px-6 py-5">
            <div className="space-y-1">
              <h1 className="text-[22px] font-semibold tracking-tight">CGFlow GUI</h1>
              <p className="text-sm text-muted-foreground">
                Configure, run, and inspect molecular optimization jobs.
              </p>
            </div>
            <div className="min-w-[240px] space-y-2 text-right">
              <p className="text-xs font-medium text-muted-foreground">Current run</p>
              {activeRun ? (
                <div className="space-y-1">
                  <div className="flex items-center justify-end gap-2">
                    <span className="truncate text-sm font-medium">{activeRun.name}</span>
                    <Badge variant={runStatusVariant}>{activeRun.status}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Step {activeRun.currentStep} of {activeRun.totalSteps}
                  </p>
                </div>
              ) : (
                <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
                  <Activity className="h-4 w-4" />
                  <span>No active run selected</span>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-hidden">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex h-full flex-col">
            <div className="border-b border-border bg-card px-6">
              <TabsList className="h-12">
                <TabsTrigger value="config" className="gap-2">
                <Settings className="w-4 h-4" />
                Configuration
                </TabsTrigger>
                <TabsTrigger value="dashboard" className="gap-2">
                <LayoutDashboard className="w-4 h-4" />
                Dashboard
                </TabsTrigger>
              </TabsList>
            </div>

            <div className="min-h-0 flex-1">
              <TabsContent value="config" className="m-0 h-full">
                <ConfigBuilder
                  onConfigChange={setCurrentConfig}
                  onRunStarted={setActiveRun}
                  activeRun={activeRun}
                />
              </TabsContent>

              <TabsContent value="dashboard" className="m-0 h-full overflow-y-auto">
                <Dashboard
                  activeRun={activeRun}
                  onRunStatusChange={setActiveRun}
                />
              </TabsContent>
            </div>
          </Tabs>
        </main>
      </div>
    </div>
  );
}
