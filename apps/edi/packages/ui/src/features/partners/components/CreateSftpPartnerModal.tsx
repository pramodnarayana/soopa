import { RadioGroup, RadioGroupItem } from '@soopa/ui';
import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import { CheckCircle2, Copy, Network, Play, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { FormModal } from '../../../components/ui/form-modal';
import { useToast } from '../../../hooks/use-toast';
import { useCreateSftpPartnerMutation, useTestSftpConnectionMutation } from '../api/partnerHooks';

export function CreateSftpPartnerModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');

  // SFTP state
  const [host, setHost] = useState('');
  const [port, setPort] = useState('22');
  const [username, setUsername] = useState('');
  const [inboundRemotePath, setInboundRemotePath] = useState('');
  const [outboundRemotePath, setOutboundRemotePath] = useState('');
  const [authMethod, setAuthMethod] = useState<'password' | 'key'>('password');
  const [password, setPassword] = useState('');
  const [sftpCredsVault, setSftpCredsVault] = useState('');
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  useEffect(() => {
    setTestResult(null);
  }, [host, port, username, password, sftpCredsVault, authMethod]);

  const { toast } = useToast();
  const createSftp = useCreateSftpPartnerMutation();
  const testConnection = useTestSftpConnectionMutation();

  const reset = () => {
    setName('');
    setHost('');
    setPort('22');
    setUsername('');
    setInboundRemotePath('');
    setOutboundRemotePath('');
    setAuthMethod('password');
    setPassword('');
    setSftpCredsVault('');
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) reset();
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!host || !port || !username) {
      toast({
        title: 'Error',
        description: 'Host, port, and username are required for SFTP',
        variant: 'destructive',
      });
      return;
    }
    const portNum = parseInt(port, 10);
    if (isNaN(portNum)) {
      toast({ title: 'Error', description: 'Invalid port number', variant: 'destructive' });
      return;
    }

    try {
      await createSftp.mutateAsync({
        name,
        host,
        port: portNum,
        username,
        inbound_remote_path: inboundRemotePath || undefined,
        outbound_remote_path: outboundRemotePath || undefined,
        password: authMethod === 'password' ? password : undefined,
        credentials_vault_ref: authMethod === 'key' ? sftpCredsVault : undefined,
      });
      setIsOpen(false);
      reset();
    } catch {
      // Error handled by mutation toast
    }
  };

  const handleTestConnection = async (e: React.MouseEvent) => {
    e.preventDefault();
    setTestResult(null);
    if (!host || !port || !username) {
      setTestResult({ success: false, message: 'Host, port, and username are required for SFTP' });
      return;
    }
    const portNum = parseInt(port, 10);
    if (isNaN(portNum)) {
      setTestResult({ success: false, message: 'Invalid port number' });
      return;
    }

    try {
      const result = await testConnection.mutateAsync({
        host,
        port: portNum,
        username,
        password: authMethod === 'password' ? password : undefined,
        credentials_vault_ref: authMethod === 'key' ? sftpCredsVault : undefined,
      });

      if (result.success) {
        setTestResult({ success: true, message: 'SFTP connection successful!' });
      } else {
        setTestResult({ success: false, message: result.reason || 'Connection failed' });
      }
    } catch (err: unknown) {
      const e = err as {
        response?: { data?: { detail?: string; message?: string } };
        message?: string;
      };
      const serverError = e.response?.data?.detail || e.response?.data?.message;
      const errorMessage =
        typeof serverError === 'string'
          ? serverError
          : Array.isArray(serverError)
            ? JSON.stringify(serverError)
            : e.message;
      setTestResult({ success: false, message: errorMessage || 'Failed to test connection' });
    }
  };

  return (
    <FormModal
      title="Add SFTP Trading Partner"
      triggerText="New SFTP"
      icon={<Network className="w-5 h-5" />}
      isOpen={isOpen}
      onOpenChange={handleOpenChange}
      onSubmit={handleSubmit}
      isPending={createSftp.isPending}
      submitText="Save SFTP Partner"
      submitDisabled={
        !host ||
        !port ||
        !username ||
        (authMethod === 'password' && !password) ||
        (authMethod === 'key' && !sftpCredsVault)
      }
      footerContent={
        <Button
          type="button"
          variant="outline"
          onClick={handleTestConnection}
          disabled={testConnection.isPending}
          className="flex items-center gap-2 h-11 px-8 rounded-xl"
        >
          <Play className="w-4 h-4" />
          {testConnection.isPending ? 'Testing...' : 'Test Connection'}
        </Button>
      }
    >
      <div className="grid gap-6 max-h-[60vh] overflow-y-auto pr-2">
        <div className="grid gap-2">
          <Label htmlFor="name" className="text-slate-600 font-medium">
            Partner Name
          </Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="e.g. XPO Logistics"
            className="h-10 rounded-xl"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="grid gap-2 col-span-2">
            <Label className="text-slate-600 font-medium">SFTP Host</Label>
            <Input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="sftp.partner.com"
              className="h-10 rounded-xl font-mono text-sm"
              required
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">Port</Label>
            <Input
              type="number"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              className="h-10 rounded-xl font-mono text-sm"
              required
            />
          </div>
        </div>

        <div className="grid gap-2">
          <Label className="text-slate-600 font-medium">Username</Label>
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="tenant_user"
            className="h-10 rounded-xl font-mono text-sm"
            required
          />
        </div>

        <div className="grid gap-4 mt-2">
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">Authentication Method</Label>
            <RadioGroup
              value={authMethod}
              onValueChange={(val: 'password' | 'key') => setAuthMethod(val)}
              className="flex gap-4"
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="password" id="r-password" />
                <Label htmlFor="r-password" className="font-medium text-slate-700 cursor-pointer">
                  Password
                </Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="key" id="r-key" />
                <Label htmlFor="r-key" className="font-medium text-slate-700 cursor-pointer">
                  SSH Key
                </Label>
              </div>
            </RadioGroup>
          </div>

          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">
              {authMethod === 'password' ? 'Password' : 'SSH Private Key (Vault Reference)'}
            </Label>
            {authMethod === 'password' ? (
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter SFTP Password"
                className="h-10 rounded-xl font-mono text-sm"
                required
              />
            ) : (
              <Input
                value={sftpCredsVault}
                onChange={(e) => setSftpCredsVault(e.target.value)}
                placeholder="e.g. vault:secret/sftp-key"
                className="h-10 rounded-xl font-mono text-sm"
                required
              />
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">From Trading Partner Path</Label>
            <Input
              value={inboundRemotePath}
              onChange={(e) => setInboundRemotePath(e.target.value)}
              placeholder="/inbound"
              className="h-10 rounded-xl font-mono text-sm"
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-slate-600 font-medium">To Trading Partner Path</Label>
            <Input
              value={outboundRemotePath}
              onChange={(e) => setOutboundRemotePath(e.target.value)}
              placeholder="/outbound"
              className="h-10 rounded-xl font-mono text-sm"
            />
          </div>
        </div>

        {testResult && (
          <div
            className={`flex items-start justify-between p-4 rounded-xl border ${testResult.success ? 'bg-emerald-50 border-emerald-100 text-emerald-800' : 'bg-red-50 border-red-100 text-red-800'}`}
          >
            <div className="flex gap-3">
              {testResult.success ? (
                <CheckCircle2 className="w-5 h-5 mt-0.5 text-emerald-600 shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 mt-0.5 text-red-600 shrink-0" />
              )}
              <div className="flex flex-col gap-1">
                <span className="font-semibold text-sm">
                  {testResult.success ? 'Success' : 'Connection Failed'}
                </span>
                <span className="font-mono text-xs whitespace-pre-wrap break-all select-text">
                  {testResult.message}
                </span>
              </div>
            </div>
            {!testResult.success && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2 -mr-2 text-red-600 hover:text-red-700 hover:bg-red-100 shrink-0"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(testResult.message);
                    toast({ title: 'Copied to clipboard' });
                  } catch {
                    toast({ title: 'Failed to copy', variant: 'destructive' });
                  }
                }}
              >
                <Copy className="w-4 h-4" />
              </Button>
            )}
          </div>
        )}
      </div>
    </FormModal>
  );
}
