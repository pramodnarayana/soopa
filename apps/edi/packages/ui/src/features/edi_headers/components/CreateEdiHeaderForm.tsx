import { Button } from '@soopa/ui/components/ui/button';
import { Input } from '@soopa/ui/components/ui/input';
import { Label } from '@soopa/ui/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { useState } from 'react';
import { useToast } from '../../../hooks/use-toast';
import { useCreateEdiHeaderMutation } from '../api/ediHeadersApi';

export function CreateEdiHeaderForm({ onSuccess }: { onSuccess: () => void }) {
  const [name, setName] = useState('');
  const [tradingPartnerId, setTradingPartnerId] = useState('');
  const [transactionType, setTransactionType] = useState('*');

  // Envelope fields
  const [isaSender, setIsaSender] = useState('');
  const [isaSenderQual, setIsaSenderQual] = useState('ZZ');
  const [isaReceiver, setIsaReceiver] = useState('');
  const [isaReceiverQual, setIsaReceiverQual] = useState('ZZ');
  const [gsSender, setGsSender] = useState('');
  const [gsReceiver, setGsReceiver] = useState('');
  const [defaultStandard, setDefaultStandard] = useState('x12');
  const [defaultVersion, setDefaultVersion] = useState('004010');

  const { toast } = useToast();
  const createEdiHeader = useCreateEdiHeaderMutation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !name ||
      !tradingPartnerId ||
      !isaSender ||
      !isaReceiver ||
      !gsSender ||
      !gsReceiver ||
      !transactionType
    ) {
      toast({ title: 'Please fill all required fields', variant: 'destructive' });
      return;
    }

    try {
      await createEdiHeader.mutateAsync({
        trading_partner_id: tradingPartnerId,
        name,
        isa_sender_id: isaSender,
        isa_sender_qualifier: isaSenderQual,
        isa_receiver_id: isaReceiver,
        isa_receiver_qualifier: isaReceiverQual,
        gs_sender_id: gsSender,
        gs_receiver_id: gsReceiver,
        default_standard: defaultStandard,
        default_version: defaultVersion,
        transaction_type: transactionType,
      });

      toast({ title: 'EDI Header created successfully' });
      onSuccess();
    } catch (err) {
      toast({
        title: 'Failed to create EDI Header',
        description: String(err),
        variant: 'destructive',
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      {/* General Settings */}
      <div className="bg-slate-50/50 border border-slate-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-slate-800">General Settings</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="header_name" className="text-slate-600 font-medium">
              Name *
            </Label>
            <Input
              id="header_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Target Outbound Settings"
              className="h-10 bg-white"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="trading_partner_id" className="text-slate-600 font-medium">
              Trading Partner ID *
            </Label>
            <Input
              id="trading_partner_id"
              value={tradingPartnerId}
              onChange={(e) => setTradingPartnerId(e.target.value)}
              placeholder="e.g. TARGET_OUT"
              className="h-10 bg-white font-mono uppercase text-sm"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="transaction_type" className="text-slate-600 font-medium">
              Transaction Type *
            </Label>
            <Input
              id="transaction_type"
              value={transactionType}
              onChange={(e) => setTransactionType(e.target.value)}
              placeholder="e.g. 850 or *"
              className="h-10 bg-white font-mono text-sm"
            />
          </div>
        </div>
      </div>

      {/* EDI Envelope Settings */}
      <div className="bg-emerald-50/30 border border-emerald-100 p-4 rounded-xl space-y-4">
        <h3 className="text-sm font-semibold text-emerald-800">EDI Envelope Configuration</h3>

        <div className="grid grid-cols-4 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="isa_sender_qual" className="text-slate-600 font-medium text-sm">
              ISA Sender Qual
            </Label>
            <Input
              id="isa_sender_qual"
              value={isaSenderQual}
              onChange={(e) => setIsaSenderQual(e.target.value)}
              className="h-10 bg-white font-mono text-sm"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_sender" className="text-slate-600 font-medium text-sm font-bold">
              ISA Sender ID *
            </Label>
            <Input
              id="isa_sender"
              value={isaSender}
              onChange={(e) => setIsaSender(e.target.value)}
              placeholder="ACME_CORP"
              className="h-10 bg-white font-mono text-sm uppercase"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_receiver_qual" className="text-slate-600 font-medium text-sm">
              ISA Receiver Qual
            </Label>
            <Input
              id="isa_receiver_qual"
              value={isaReceiverQual}
              onChange={(e) => setIsaReceiverQual(e.target.value)}
              className="h-10 bg-white font-mono text-sm"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="isa_receiver" className="text-slate-600 font-medium text-sm font-bold">
              ISA Receiver ID *
            </Label>
            <Input
              id="isa_receiver"
              value={isaReceiver}
              onChange={(e) => setIsaReceiver(e.target.value)}
              placeholder="PARTNER"
              className="h-10 bg-white font-mono text-sm uppercase"
            />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4 pt-2">
          <div className="grid gap-2">
            <Label htmlFor="gs_sender" className="text-slate-600 font-medium text-sm font-bold">
              GS Sender ID *
            </Label>
            <Input
              id="gs_sender"
              value={gsSender}
              onChange={(e) => setGsSender(e.target.value)}
              placeholder="ACME"
              className="h-10 bg-white font-mono text-sm uppercase"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="gs_receiver" className="text-slate-600 font-medium text-sm font-bold">
              GS Receiver ID *
            </Label>
            <Input
              id="gs_receiver"
              value={gsReceiver}
              onChange={(e) => setGsReceiver(e.target.value)}
              placeholder="PARTNER"
              className="h-10 bg-white font-mono text-sm uppercase"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="default_standard" className="text-slate-600 font-medium text-sm">
              Standard
            </Label>
            <Select value={defaultStandard} onValueChange={setDefaultStandard}>
              <SelectTrigger className="h-10 bg-white text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="x12">X12</SelectItem>
                <SelectItem value="edifact">EDIFACT</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="default_version" className="text-slate-600 font-medium text-sm">
              Version
            </Label>
            <Input
              id="default_version"
              value={defaultVersion}
              onChange={(e) => setDefaultVersion(e.target.value)}
              placeholder="004010"
              className="h-10 bg-white font-mono text-sm"
            />
          </div>
        </div>
      </div>

      <div className="flex justify-end mt-2">
        <Button type="submit" size="cta" disabled={createEdiHeader.isPending}>
          {createEdiHeader.isPending ? 'Creating...' : 'Create EDI Header'}
        </Button>
      </div>
    </form>
  );
}
