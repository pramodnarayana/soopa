import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Network, Plus, CheckCircle2 } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export interface AS2PartnershipCardProps {
  count: number;
  availablePartners: { id: string; name: string; type: string; is_local?: boolean }[];
  onSave: (data: {
    local_partner_id: string;
    remote_partner_id: string;
    local_url: string;
    remote_url: string;
    mdn_type: string;
    encryption_algorithm: string;
    signature_algorithm: string;
    edi_version?: string;
    mdn_url?: string;
  }) => Promise<void> | void;
}

export function AS2PartnershipCard({ count, availablePartners, onSave }: AS2PartnershipCardProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [localPartnerId, setLocalPartnerId] = useState('')
  const [remotePartnerId, setRemotePartnerId] = useState('')
  const [mdnType, setMdnType] = useState('SYNC')
  const [encryptionAlgorithm, setEncryptionAlgorithm] = useState('AES256_CBC')
  const [signatureAlgorithm, setSignatureAlgorithm] = useState('SHA256')
  const [ediVersion, setEdiVersion] = useState('NONE')

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)

    await onSave({
      local_partner_id: localPartnerId,
      remote_partner_id: remotePartnerId,
      local_url: formData.get('local_url') as string,
      remote_url: formData.get('remote_url') as string,
      mdn_type: mdnType,
      mdn_url: (formData.get('mdn_url') as string) || undefined,
      encryption_algorithm: encryptionAlgorithm,
      signature_algorithm: signatureAlgorithm,
      edi_version: ediVersion === "NONE" ? undefined : ediVersion,
    })
    setIsOpen(false)
  }

  const localIdentities = availablePartners.filter(p => p.type === 'AS2' && p.is_local === true)
  const remoteIdentities = availablePartners.filter(p => p.type === 'AS2' && !p.is_local)

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-indigo-500/30 hover:-translate-y-0.5">

      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden text-indigo-600 transition-colors group-hover:bg-indigo-50/50">
            <Network className="h-7 w-7" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">AS2 Partnerships</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <CheckCircle2 className={`h-4 w-4 ${count > 0 ? 'text-emerald-500' : 'text-slate-300'}`} /> {count} Active
            </div>
          </div>
        </div>

        <Dialog open={isOpen} onOpenChange={setIsOpen}>
          <DialogTrigger asChild>
            <Button size="icon" variant="ghost" className="h-10 w-10 shrink-0 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-xl transition-colors">
              <Plus className="h-5 w-5" />
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[800px] rounded-2xl max-h-[85vh] overflow-y-auto" onPointerDownOutside={(e) => e.preventDefault()}>
            <DialogHeader>
              <DialogTitle className="text-xl">Create Partnership</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSave} className="grid gap-6 py-4">

              {/* Identities Section */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 bg-slate-50 rounded-xl border border-slate-100">
                <div className="grid gap-2">
                  <Label className="text-slate-600 font-medium">Local Station (Your AS2)</Label>
                  <Select value={localPartnerId} onValueChange={setLocalPartnerId} required>
                    <SelectTrigger className="h-10 rounded-xl bg-white">
                      <SelectValue placeholder="Select local Trading Partner" />
                    </SelectTrigger>
                    <SelectContent>
                      {localIdentities.map(p => (
                        <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                      ))}
                      {localIdentities.length === 0 && (
                        <SelectItem value="none" disabled>No local stations found</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>

                <div className="grid gap-2">
                  <Label className="text-slate-600 font-medium">Remote Station (Partner AS2)</Label>
                  <Select value={remotePartnerId} onValueChange={setRemotePartnerId} required>
                    <SelectTrigger className="h-10 rounded-xl bg-white">
                      <SelectValue placeholder="Select remote Trading Partner" />
                    </SelectTrigger>
                    <SelectContent>
                      {remoteIdentities.map(p => (
                        <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                      ))}
                      {remoteIdentities.length === 0 && (
                        <SelectItem value="none" disabled>No remote stations found</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Networking Section */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div className="grid gap-2">
                  <Label htmlFor="local_url" className="text-slate-600 font-medium">Local URL</Label>
                  <Input id="local_url" name="local_url" required placeholder="http://my-as2.com:10080/as2" className="h-10 rounded-xl" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="remote_url" className="text-slate-600 font-medium">Remote URL</Label>
                  <Input id="remote_url" name="remote_url" required placeholder="https://partner-as2.com/as2" className="h-10 rounded-xl" />
                </div>
              </div>

              {/* Advanced Settings */}
              <div className="flex flex-col gap-6 pt-2 border-t border-slate-100">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                  <div className="grid gap-2">
                    <Label className="text-slate-600 font-medium">MDN Delivery Type</Label>
                    <Select value={mdnType} onValueChange={setMdnType}>
                      <SelectTrigger className="h-10 rounded-xl">
                        <SelectValue placeholder="Select MDN type" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SYNC">Synchronous (Recommended)</SelectItem>
                        <SelectItem value="ASYNC">Asynchronous</SelectItem>
                        <SelectItem value="NONE">None (Fire and Forget)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {mdnType === 'ASYNC' && (
                    <div className="grid gap-2">
                      <Label htmlFor="mdn_url" className="text-slate-600 font-medium">Async MDN Receipt URL</Label>
                      <Input id="mdn_url" name="mdn_url" placeholder="https://my.as2.com/receipt" className="h-10 rounded-xl" />
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                  <div className="grid gap-2">
                    <Label className="text-slate-600 font-medium">Encryption</Label>
                    <Select value={encryptionAlgorithm} onValueChange={setEncryptionAlgorithm}>
                      <SelectTrigger className="h-10 rounded-xl">
                        <SelectValue placeholder="Algorithm" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="AES256_CBC">AES-256-CBC</SelectItem>
                        <SelectItem value="AES128_CBC">AES-128-CBC</SelectItem>
                        <SelectItem value="3DES">3DES (Legacy)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="grid gap-2">
                    <Label className="text-slate-600 font-medium">Signature</Label>
                    <Select value={signatureAlgorithm} onValueChange={setSignatureAlgorithm}>
                      <SelectTrigger className="h-10 rounded-xl">
                        <SelectValue placeholder="Algorithm" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SHA256">SHA-256</SelectItem>
                        <SelectItem value="SHA1">SHA-1 (Legacy)</SelectItem>
                        <SelectItem value="MD5">MD5 (Insecure)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="grid gap-2">
                    <Label className="text-slate-600 font-medium">EDI Version</Label>
                    <Select value={ediVersion} onValueChange={setEdiVersion}>
                      <SelectTrigger className="h-10 rounded-xl">
                        <SelectValue placeholder="Version" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="X12-004010">X12 4010</SelectItem>
                        <SelectItem value="X12-005010">X12 5010</SelectItem>
                        <SelectItem value="EDIFACT-D96A">EDIFACT D96A</SelectItem>
                        <SelectItem value="EDIFACT-D01B">EDIFACT D01B</SelectItem>
                        <SelectItem value="NONE">Not Applicable</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
              <Button type="submit" className="w-full h-11 mt-4 text-base font-semibold shadow-sm rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white">Create Partnership</Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-4">
        <span className="text-sm font-medium text-slate-400">Total volume</span>
        <span className="text-sm font-bold text-slate-700">0 MB</span>
      </div>
    </div>
  )
}
