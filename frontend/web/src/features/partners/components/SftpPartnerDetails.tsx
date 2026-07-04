import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import type { SFTPPartner } from '../types';
import { useUpdateSftpPartnerMutation, useTestExistingSftpConnectionMutation } from '../api/partnerHooks';
import { Loader2, CheckCircle2, XCircle, Copy, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';

export function SftpPartnerDetails({ partner, onCancel }: { partner: SFTPPartner, onCancel?: () => void }) {
  const { toast } = useToast();

  const updateSftp = useUpdateSftpPartnerMutation();
  const testConnection = useTestExistingSftpConnectionMutation();
  const isSubmitting = updateSftp.isPending;

  const [testResult, setTestResult] = useState<{success: boolean; message: string} | null>(null);

  const { register, handleSubmit, reset, getValues, watch, formState: { isDirty } } = useForm({
    defaultValues: {
      name: partner.name,
      host: partner.host || '',
      username: partner.username || '',
      port: partner.port || 22,
      inbound_remote_path: partner.inbound_remote_path || '',
      outbound_remote_path: partner.outbound_remote_path || '',
      password: '',
    }
  });

  const watchAll = watch();

  useEffect(() => {
    setTestResult(null);
  }, [watchAll.host, watchAll.port, watchAll.username, watchAll.password]);

  const onSubmit = (formData: any) => {
    const payload: any = {};
    if (formData.name !== partner.name) payload.name = formData.name;
    if (formData.host !== partner.host) payload.host = formData.host;
    if (formData.username !== partner.username) payload.username = formData.username;
    if (formData.password?.trim()) payload.password = formData.password.trim();
    if (formData.port !== partner.port) payload.port = parseInt(formData.port, 10);
    if (formData.inbound_remote_path !== partner.inbound_remote_path) payload.inbound_remote_path = formData.inbound_remote_path;
    if (formData.outbound_remote_path !== partner.outbound_remote_path) payload.outbound_remote_path = formData.outbound_remote_path;

    updateSftp.mutate({ id: partner.id, payload }, {
      onSuccess: () => {
        toast({ title: 'Success', description: 'SFTP Partner updated successfully.' });
        reset(formData);
      },
    });
  };

  return (
    <div className="p-6 bg-slate-50/50 border-t border-slate-100">
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="flex justify-between items-start mb-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-1">SFTP Partner Details</h4>
          </div>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={testConnection.isPending}
              onClick={() => {
                const vals = getValues();
                testConnection.mutate(
                  {
                    id: partner.id,
                    payload: {
                      host: vals.host || partner.host || '',
                      port: parseInt(vals.port as any, 10) || partner.port || 22,
                      username: vals.username || partner.username || '',
                      password: vals.password || undefined,
                    }
                  },
                  {
                    onSuccess: (data: any) => setTestResult({ success: data.success, message: data.reason || 'Connection successful!' }),
                    onError: (error: any) => setTestResult({ success: false, message: error.response?.data?.detail || error.message || 'Connection failed' })
                  }
                );
              }}
              className="flex items-center gap-2"
            >
              {testConnection.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {testConnection.isPending ? 'Testing...' : 'Test Connection'}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                if (onCancel) onCancel();
              }}
              disabled={!isDirty || isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!isDirty || isSubmitting}
              className="min-w-[100px]"
            >
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>

        {testResult && (
          <div className={`flex items-start justify-between p-4 mb-6 rounded-xl border ${testResult.success ? 'bg-emerald-50 border-emerald-100 text-emerald-800' : 'bg-red-50 border-red-100 text-red-800'}`}>
            <div className="flex gap-3">
              {testResult.success ? <CheckCircle2 className="w-5 h-5 mt-0.5 text-emerald-600 shrink-0" /> : <XCircle className="w-5 h-5 mt-0.5 text-red-600 shrink-0" />}
              <div className="flex flex-col gap-1">
                <span className="font-semibold text-sm">{testResult.success ? 'Success' : 'Connection Failed'}</span>
                <span className="font-mono text-xs whitespace-pre-wrap break-all select-text">{testResult.message}</span>
              </div>
            </div>
            {!testResult.success && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2 -mr-2 text-red-600 hover:text-red-700 hover:bg-red-100 shrink-0"
                onClick={() => {
                  navigator.clipboard.writeText(testResult.message);
                  toast({ title: 'Copied to clipboard' });
                }}
              >
                <Copy className="w-4 h-4 mr-2" />
                Copy
              </Button>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-x-8 gap-y-4 mb-8">
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Name</Label>
            <Input {...register("name")} required />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Host</Label>
            <div className="flex gap-2">
              <Input {...register("host")} className="flex-1" required />
              <Input type="number" {...register("port", { valueAsNumber: true })} className="w-24" placeholder="22" required />
            </div>
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Username</Label>
            <Input {...register("username")} required />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">Password</Label>
            <Input type="password" {...register("password")} placeholder="••••••••" />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">From Trading Partner Path</Label>
            <Input {...register("inbound_remote_path")} placeholder="/inbound" />
          </div>
          <div>
            <Label className="text-xs text-slate-500 block mb-1">To Trading Partner Path</Label>
            <Input {...register("outbound_remote_path")} placeholder="/outbound" />
          </div>
        </div>
      </form>
    </div>
  );
}
