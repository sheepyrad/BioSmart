import { useState } from 'react';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import ConfigBuilder from '@/pages/ConfigBuilder';
import Dashboard from '@/pages/Dashboard';
import type { RunInfo, OptConfig } from '@shared/types';
import { Activity, LayoutDashboard, Settings, FlaskConical, Hexagon } from 'lucide-react';

function NavItem({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`group flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-all duration-200
        ${active
          ? 'bg-primary/10 text-primary glow-subtle'
          : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
        }`}
    >
      <Icon className={`h-[18px] w-[18px] transition-colors ${active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'}`} />
      <span>{label}</span>
      {active && (
        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary animate-pulse-glow" />
      )}
    </button>
  );
}

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
    <div className="h-screen bg-background text-foreground noise-bg">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex h-full">
        {/* Sidebar */}
        <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-card/50">
          {/* Logo */}
          <div className="flex items-center gap-3 px-5 py-5">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 glow-subtle">
              <Hexagon className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h1 className="font-display text-lg font-semibold tracking-tight text-foreground">
                CGFlow
              </h1>
              <p className="text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
                Molecular Opt.
              </p>
            </div>
          </div>

          <div className="h-px bg-gradient-to-r from-transparent via-border to-transparent" />

          {/* Navigation */}
          <nav className="space-y-1 px-3 py-4">
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground/70">
              Workspace
            </p>
            <NavItem
              icon={Settings}
              label="Configuration"
              active={activeTab === 'config'}
              onClick={() => setActiveTab('config')}
            />
            <NavItem
              icon={LayoutDashboard}
              label="Dashboard"
              active={activeTab === 'dashboard'}
              onClick={() => setActiveTab('dashboard')}
            />
          </nav>

          <div className="flex-1" />

          {/* Run status at bottom of sidebar */}
          <div className="border-t border-border p-4">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground/70">
              Active Run
            </p>
            {activeRun ? (
              <div className="space-y-2 animate-fade-in">
                <div className="flex items-center gap-2">
                  <FlaskConical className="h-3.5 w-3.5 text-primary" />
                  <span className="truncate text-sm font-medium text-foreground">
                    {activeRun.name}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <Badge variant={runStatusVariant} className="text-[10px]">
                    {activeRun.status}
                  </Badge>
                  <span className="font-data text-[11px] text-muted-foreground tabular-nums">
                    {activeRun.currentStep}/{activeRun.totalSteps}
                  </span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-secondary">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-500"
                    style={{
                      width: `${Math.min(
                        100,
                        activeRun.totalSteps > 0
                          ? (activeRun.currentStep / activeRun.totalSteps) * 100
                          : 0
                      )}%`,
                    }}
                  />
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Activity className="h-3.5 w-3.5" />
                <span className="text-xs">No active run</span>
              </div>
            )}
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-hidden">
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
        </main>
      </Tabs>
    </div>
  );
}
