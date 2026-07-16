import { useState, useEffect } from 'react';
import { useJobsQuery, useConfigQuery, useUpdateConfigMutation } from '../api/schedulerHooks';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Power } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

export const SchedulerDashboard = () => {
  const { data: jobs = [], isLoading: jobsLoading } = useJobsQuery();
  const { data: configs = [], isLoading: configLoading } = useConfigQuery();
  const { mutateAsync: updateConfig } = useUpdateConfigMutation();
  const getSweeperEnabled = () => {
    const cfg = configs.find((c: any) => c.key === 'outbox_sweeper_enabled');
    return cfg ? !!cfg.value : false;
  };

  const getSweeperInterval = () => {
    const cfg = configs.find((c: any) => c.key === 'outbox_sweeper_interval_seconds');
    return cfg ? cfg.value : 60;
  };

  const [localEnabled, setLocalEnabled] = useState<boolean>(false);
  const [localInterval, setLocalInterval] = useState<string>('');

  useEffect(() => {
    if (configs.length > 0) {
      setLocalEnabled(getSweeperEnabled());
      setLocalInterval(String(getSweeperInterval()));
    }
  }, [configs, getSweeperEnabled, getSweeperInterval]);

  const handleSave = async () => {
    try {
      if (localInterval) {
        await updateConfig({ key: 'outbox_sweeper_interval_seconds', value: parseInt(localInterval, 10) });
      }
      await updateConfig({ key: 'outbox_sweeper_enabled', value: localEnabled });
    } catch (e) {
      console.error('Failed to update config', e);
    }
  };

  const isDirty = localEnabled !== getSweeperEnabled() || localInterval !== String(getSweeperInterval());
  const isValid = localInterval.trim() !== '';
  const canSave = isDirty && isValid;

  if (jobsLoading || configLoading) return <div>Loading Scheduler Dashboard...</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Scheduler</h1>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-4">
          <div className="space-y-1">
            <CardTitle>Scheduled Jobs</CardTitle>
            {getSweeperEnabled() ? (
              <p className="text-sm font-medium text-emerald-600">
                {(() => {
                  const secs = getSweeperInterval();
                  return secs < 60
                    ? `Outbox Sweeper is scheduled to run every ${secs}s.`
                    : `Outbox Sweeper is scheduled to run every ${Math.round(secs / 60)} min${Math.round(secs / 60) !== 1 ? 's' : ''}.`;
                })()}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Outbox Sweeper is not currently scheduled.
              </p>
            )}
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <Label>Outbox Sweeper</Label>
              <button
                type="button"
                role="switch"
                aria-checked={localEnabled}
                onClick={() => setLocalEnabled(!localEnabled)}
                className={`relative inline-flex h-7 w-[90px] shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 ${localEnabled ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-100 border-slate-300'}`}
              >
                <span className={`absolute left-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${localEnabled ? 'opacity-100 text-emerald-700' : 'opacity-0'}`}>
                  Enable
                </span>
                <span className={`absolute right-2.5 text-[10px] font-bold uppercase tracking-wider transition-opacity duration-200 ${localEnabled ? 'opacity-0' : 'opacity-100 text-slate-500'}`}>
                  Disable
                </span>
                <span aria-hidden="true" className={`pointer-events-none absolute left-1 flex h-5 w-5 transform items-center justify-center rounded-full shadow ring-0 transition-transform duration-200 ease-in-out ${localEnabled ? 'translate-x-[62px] bg-emerald-600 text-white' : 'translate-x-0 bg-white text-slate-400'}`}>
                  <Power className="w-3 h-3" />
                </span>
              </button>
            </div>

            <div className="flex items-center gap-2">
              <Label>Interval (s)</Label>
              <Input
                type="number"
                placeholder={String(getSweeperInterval())}
                value={localInterval}
                onChange={(e) => setLocalInterval(e.target.value)}
                disabled={!localEnabled}
                className="w-20 h-8"
              />
              <Button size="sm" onClick={handleSave} disabled={!canSave}>
                Save
              </Button>
            </div>

            <Button variant="outline" size="sm" onClick={() => {
              // Refresh is handled by tanstack query
            }}>
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Error Message</TableHead>
                <TableHead>Next Run At</TableHead>
                <TableHead>Locked By</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job: any) => (
                <TableRow key={job.id}>
                  <TableCell className="font-medium text-xs">{job.id}</TableCell>
                  <TableCell>{job.name}</TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${job.status === 'COMPLETED' ? 'bg-green-100 text-green-800' :
                        job.status === 'FAILED' ? 'bg-red-100 text-red-800' :
                          job.status === 'RUNNING' ? 'bg-blue-100 text-blue-800' :
                            'bg-gray-100 text-gray-800'
                      }`}>
                      {job.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-red-600 max-w-xs truncate" title={job.error_message || ''}>
                    {job.error_message || '-'}
                  </TableCell>
                  <TableCell>{job.next_run_at ? new Date(job.next_run_at).toLocaleString() : 'Immediate'}</TableCell>
                  <TableCell>{job.locked_by || '-'}</TableCell>
                </TableRow>
              ))}
              {jobs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-4 text-muted-foreground">
                    No background jobs found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};
