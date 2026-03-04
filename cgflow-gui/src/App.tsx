import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import ConfigBuilder from '@/pages/ConfigBuilder';
import Dashboard from '@/pages/Dashboard';
import type { RunInfo, OptConfig } from '@shared/types';
import { Activity, Settings, LayoutDashboard, Atom } from 'lucide-react';

const pageVariants = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -20 },
};

const logoVariants = {
  initial: { scale: 0.8, opacity: 0 },
  animate: { 
    scale: 1, 
    opacity: 1,
    transition: { type: 'spring', stiffness: 200, damping: 15 }
  },
};

export default function App() {
  const [activeRun, setActiveRun] = useState<RunInfo | null>(null);
  const [, setCurrentConfig] = useState<OptConfig | null>(null);
  const [activeTab, setActiveTab] = useState('config');

  return (
    <div className="h-screen flex flex-col bg-background gradient-mesh overflow-hidden">
      {/* Animated background orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <motion.div
          className="absolute -top-40 -right-40 w-80 h-80 bg-primary/10 rounded-full blur-3xl"
          animate={{
            x: [0, 30, 0],
            y: [0, -20, 0],
          }}
          transition={{
            duration: 8,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
        <motion.div
          className="absolute -bottom-40 -left-40 w-80 h-80 bg-blue-500/10 rounded-full blur-3xl"
          animate={{
            x: [0, -30, 0],
            y: [0, 20, 0],
          }}
          transition={{
            duration: 10,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      </div>

      {/* Header */}
      <motion.header 
        className="relative z-10 border-b border-border/50 px-6 py-4 glass"
        initial={{ y: -50, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <motion.div
              variants={logoVariants}
              initial="initial"
              animate="animate"
              className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-blue-600 shadow-lg shadow-primary/25"
            >
              <Atom className="w-6 h-6 text-white" />
            </motion.div>
            <div>
              <motion.h1 
                className="text-xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.2 }}
              >
                CGFlow
              </motion.h1>
              <motion.p 
                className="text-xs text-muted-foreground"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 }}
              >
                Molecular optimization with Boltz-2
              </motion.p>
            </div>
          </div>

          <AnimatePresence mode="wait">
            {activeRun && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9, x: 20 }}
                animate={{ opacity: 1, scale: 1, x: 0 }}
                exit={{ opacity: 0, scale: 0.9, x: 20 }}
                className="flex items-center gap-3 px-4 py-2 rounded-full glass"
              >
                <div className="flex items-center gap-2">
                  <motion.div
                    className={`w-2 h-2 rounded-full ${
                      activeRun.status === 'running' 
                        ? 'bg-green-500' 
                        : activeRun.status === 'completed'
                        ? 'bg-blue-500'
                        : activeRun.status === 'error'
                        ? 'bg-red-500'
                        : 'bg-yellow-500'
                    }`}
                    animate={activeRun.status === 'running' ? {
                      scale: [1, 1.2, 1],
                      opacity: [1, 0.7, 1],
                    } : {}}
                    transition={{
                      duration: 1.5,
                      repeat: Infinity,
                      ease: 'easeInOut',
                    }}
                  />
                  <span className="text-sm text-muted-foreground">
                    {activeRun.name}
                  </span>
                </div>
                <Badge 
                  variant={activeRun.status === 'running' ? 'default' : 'secondary'}
                  className="text-xs"
                >
                  {activeRun.status === 'running' ? (
                    <span className="flex items-center gap-1">
                      <Activity className="w-3 h-3" />
                      Step {activeRun.currentStep}/{activeRun.totalSteps}
                    </span>
                  ) : (
                    activeRun.status
                  )}
                </Badge>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.header>

      {/* Main Content */}
      <main className="relative z-10 flex-1 overflow-hidden">
        <Tabs 
          value={activeTab} 
          onValueChange={setActiveTab} 
          className="h-full flex flex-col"
        >
          <motion.div 
            className="border-b border-border/50 px-6 glass"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
          >
            <TabsList className="h-14 bg-transparent gap-2">
              <TabsTrigger 
                value="config" 
                className="relative data-[state=active]:bg-primary/10 data-[state=active]:text-primary transition-all duration-300 gap-2"
              >
                <Settings className="w-4 h-4" />
                Configuration
                {activeTab === 'config' && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"
                    transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                  />
                )}
              </TabsTrigger>
              <TabsTrigger 
                value="dashboard" 
                className="relative data-[state=active]:bg-primary/10 data-[state=active]:text-primary transition-all duration-300 gap-2"
              >
                <LayoutDashboard className="w-4 h-4" />
                Dashboard
                {activeTab === 'dashboard' && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"
                    transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                  />
                )}
              </TabsTrigger>
            </TabsList>
          </motion.div>

          <div className="flex-1 min-h-0">
            <TabsContent value="config" className="h-full m-0 p-0">
              <motion.div
                variants={pageVariants}
                initial="initial"
                animate="animate"
                transition={{ duration: 0.3 }}
                className="h-full"
              >
                <ConfigBuilder
                  onConfigChange={setCurrentConfig}
                  onRunStarted={setActiveRun}
                  activeRun={activeRun}
                />
              </motion.div>
            </TabsContent>

            <TabsContent value="dashboard" className="h-full m-0 p-0 overflow-y-auto">
              <motion.div
                variants={pageVariants}
                initial="initial"
                animate="animate"
                transition={{ duration: 0.3 }}
                className="min-h-full"
              >
                <Dashboard
                  activeRun={activeRun}
                  onRunStatusChange={setActiveRun}
                />
              </motion.div>
            </TabsContent>
          </div>
        </Tabs>
      </main>
    </div>
  );
}
