import { createFileRoute } from '@tanstack/react-router';
import { Activity, Key, Server } from 'lucide-react';

export const Route = createFileRoute('/_authenticated/platform/')({
  component: PlatformDashboard,
});

function PlatformDashboard() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out fill-mode-both">
      <header className="mb-10">
        <h1 className="text-[28px] font-bold tracking-tight text-foreground">Platform Overview</h1>
        <p className="text-muted-foreground mt-1 text-[15px]">
          Monitor the health and activity of the global Soopa platform.
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-card p-8 rounded-2xl border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] hover:-translate-y-[2px] hover:shadow-[0_8px_24px_rgb(0,0,0,0.06)] transition-all duration-300 ease-out group cursor-default">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[13px] text-muted-foreground font-semibold uppercase tracking-[0.15em]">
              Total Tenants
            </h3>
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary group-hover:scale-110 transition-transform duration-300">
              <Server className="w-5 h-5" />
            </div>
          </div>
          <p className="text-[40px] leading-none font-semibold tracking-tight text-foreground">—</p>
          <p className="text-base text-emerald-500 mt-4 font-medium flex items-center gap-1.5">
            <Activity className="w-4 h-4" /> 100% SLA uptime
          </p>
        </div>

        <div className="bg-card p-8 rounded-2xl border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] hover:-translate-y-[2px] hover:shadow-[0_8px_24px_rgb(0,0,0,0.06)] transition-all duration-300 ease-out group cursor-default">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[13px] text-muted-foreground font-semibold uppercase tracking-[0.15em]">
              Active API Keys
            </h3>
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary group-hover:scale-110 transition-transform duration-300">
              <Key className="w-5 h-5" />
            </div>
          </div>
          <p className="text-[40px] leading-none font-semibold tracking-tight text-foreground">—</p>
        </div>

        <div className="bg-card p-8 rounded-2xl border border-border shadow-[0_2px_8px_rgb(0,0,0,0.04)] hover:-translate-y-[2px] hover:shadow-[0_8px_24px_rgb(0,0,0,0.06)] transition-all duration-300 ease-out group cursor-default relative overflow-hidden">
          <div className="absolute top-0 right-0 w-32 h-32 bg-destructive/5 rounded-bl-[100px] -z-10 group-hover:scale-110 transition-transform duration-500" />
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[13px] text-muted-foreground font-semibold uppercase tracking-[0.15em]">
              Failed Jobs (24h)
            </h3>
            <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center text-destructive group-hover:scale-110 transition-transform duration-300">
              <Activity className="w-5 h-5" />
            </div>
          </div>
          <p className="text-[40px] leading-none font-semibold tracking-tight text-foreground">—</p>
        </div>
      </div>
    </div>
  );
}
