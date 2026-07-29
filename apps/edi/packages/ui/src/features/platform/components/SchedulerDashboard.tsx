import { Button } from '@soopa/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@soopa/ui/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@soopa/ui/components/ui/dialog';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui/components/ui/table';
import { Clock, Pause, Play } from 'lucide-react';
import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../components/ui/tabs';
import type { JobResponse } from '../api/schedulerApi';
import { useJobsQuery, useUpdateJobMutation } from '../api/schedulerHooks';
import { CronBuilder } from './CronBuilder';

export const SchedulerDashboard = () => {
  const { data: jobs = [], isLoading: jobsLoading, refetch: refetchJobs } = useJobsQuery();
  const { mutateAsync: updateJob } = useUpdateJobMutation();

  const [editingJob, setEditingJob] = useState<JobResponse | null>(null);
  const [scheduleType, setScheduleType] = useState<'interval' | 'cron'>('interval');
  const [intervalValue, setIntervalValue] = useState<string>('1');
  const [intervalUnit, setIntervalUnit] = useState<string>('minutes');
  const [newCron, setNewCron] = useState<string>('0 * * * *');

  const handleTogglePause = async (job: JobResponse) => {
    const newStatus = job.status === 'PAUSED' ? 'PENDING' : 'PAUSED';
    try {
      await updateJob({ name: job.name, data: { status: newStatus } });
    } catch (e) {
      console.error('Failed to toggle job status', e);
    }
  };

  const [intervalError, setIntervalError] = useState<string | null>(null);

  const getIntervalParts = (seconds: number) => {
    if (seconds % (30 * 24 * 3600) === 0)
      return { val: seconds / (30 * 24 * 3600), unit: 'months' };
    if (seconds % (24 * 3600) === 0) return { val: seconds / (24 * 3600), unit: 'days' };
    if (seconds % 3600 === 0) return { val: seconds / 3600, unit: 'hours' };
    if (seconds % 60 === 0) return { val: seconds / 60, unit: 'minutes' };
    return { val: seconds, unit: 'seconds' };
  };

  const handleEditIntervalClick = (job: JobResponse) => {
    setEditingJob(job);
    if (job.cron_expression) {
      setScheduleType('cron');
      setNewCron(job.cron_expression);
      const parts = getIntervalParts(job.interval_seconds || 60);
      setIntervalValue(String(parts.val));
      setIntervalUnit(parts.unit);
    } else {
      setScheduleType('interval');
      const parts = getIntervalParts(job.interval_seconds || 60);
      setIntervalValue(String(parts.val));
      setIntervalUnit(parts.unit);
      setNewCron('0 * * * *');
    }
    setIntervalError(null);
  };

  const handleSaveSchedule = async () => {
    if (!editingJob) return;

    try {
      if (scheduleType === 'interval') {
        if (!/^\d+$/.test(intervalValue) || parseInt(intervalValue, 10) <= 0) {
          setIntervalError('Interval must be a positive integer.');
          return;
        }
        const val = parseInt(intervalValue, 10);

        let multiplier = 1;
        if (intervalUnit === 'minutes') multiplier = 60;
        else if (intervalUnit === 'hours') multiplier = 3600;
        else if (intervalUnit === 'days') multiplier = 86400;
        else if (intervalUnit === 'months') multiplier = 2592000;

        const totalSeconds = val * multiplier;

        await updateJob({
          name: editingJob.name,
          data: { interval_seconds: totalSeconds, cron_expression: null, timezone: null },
        });
      } else {
        await updateJob({
          name: editingJob.name,
          data: { cron_expression: newCron, timezone: 'UTC', interval_seconds: null },
        });
      }
      setEditingJob(null);
      setIntervalError(null);
    } catch (e: unknown) {
      setIntervalError((e as Error).message || 'Failed to update job schedule');
    }
  };

  if (jobsLoading) return <div>Loading Scheduler Dashboard...</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Scheduler</h1>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-4">
          <div className="space-y-1">
            <CardTitle>Scheduled Jobs</CardTitle>
            <p className="text-sm text-muted-foreground">
              Overview of all background jobs running in the platform.
            </p>
          </div>
          <div className="flex items-center gap-6">
            <Button variant="outline" size="sm" onClick={() => refetchJobs()}>
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Next Run At</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job: JobResponse) => (
                <TableRow key={job.id}>
                  <TableCell className="font-medium">{job.name}</TableCell>
                  <TableCell>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        job.status === 'COMPLETED'
                          ? 'bg-green-100 text-green-800'
                          : job.status === 'FAILED'
                            ? 'bg-red-100 text-red-800'
                            : job.status === 'RUNNING'
                              ? 'bg-blue-100 text-blue-800'
                              : job.status === 'PAUSED'
                                ? 'bg-orange-100 text-orange-800'
                                : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {job.status}
                    </span>
                  </TableCell>
                  <TableCell>
                    {job.cron_expression ? (
                      <span className="font-mono bg-muted px-1 rounded">{job.cron_expression}</span>
                    ) : job.interval_seconds ? (
                      `${job.interval_seconds}s`
                    ) : (
                      '-'
                    )}
                  </TableCell>
                  <TableCell>
                    {job.next_run_at ? new Date(job.next_run_at).toLocaleString() : 'Immediate'}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" size="sm" onClick={() => handleTogglePause(job)}>
                        {job.status === 'PAUSED' ? (
                          <Play className="w-4 h-4 mr-1" />
                        ) : (
                          <Pause className="w-4 h-4 mr-1" />
                        )}
                        {job.status === 'PAUSED' ? 'Resume' : 'Pause'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleEditIntervalClick(job)}
                      >
                        <Clock className="w-4 h-4 mr-1" />
                        Schedule
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {jobs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-4 text-muted-foreground">
                    No background jobs found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={!!editingJob} onOpenChange={(open) => !open && setEditingJob(null)}>
        <DialogContent className="sm:max-w-[900px]">
          <DialogHeader>
            <DialogTitle>Edit Job Schedule</DialogTitle>
            <DialogDescription>
              Set how often the {editingJob?.name} job runs.
              {editingJob?.min_interval_seconds && editingJob?.max_interval_seconds && (
                <span className="block mt-1 text-orange-600">
                  Allowed range (if using interval): {editingJob.min_interval_seconds}s -{' '}
                  {editingJob.max_interval_seconds}s
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          <Tabs
            defaultValue="interval"
            value={scheduleType}
            onValueChange={(v) => setScheduleType(v)}
          >
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="interval">Interval</TabsTrigger>
              <TabsTrigger value="cron">Cron Expression</TabsTrigger>
            </TabsList>
            <TabsContent value="interval" className="py-4 space-y-4">
              <div className="flex items-center gap-3">
                <Label htmlFor="interval" className="shrink-0">
                  Every
                </Label>
                <Input
                  id="interval"
                  type="number"
                  value={intervalValue}
                  onChange={(e) => {
                    setIntervalValue(e.target.value);
                    setIntervalError(null);
                  }}
                  className={`w-24 ${intervalError ? 'border-red-500' : ''}`}
                />
                <select
                  className="flex h-10 w-32 items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  value={intervalUnit}
                  onChange={(e) => setIntervalUnit(e.target.value)}
                >
                  <option value="seconds">Seconds</option>
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days">Days</option>
                  <option value="months">Months</option>
                </select>
              </div>
            </TabsContent>
            <TabsContent value="cron" className="py-4">
              <CronBuilder
                value={newCron}
                onChange={(val) => {
                  setNewCron(val);
                  setIntervalError(null);
                }}
              />
              <div className="mt-4 p-3 bg-muted rounded-md text-sm">
                <span className="font-semibold block mb-1">Generated Cron:</span>
                <span className="font-mono">{newCron}</span>
              </div>
            </TabsContent>
          </Tabs>

          {intervalError && <p className="text-sm text-red-600 -mt-2 mb-2">{intervalError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingJob(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveSchedule}>Save changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
