import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Network, Plus, ArrowRightLeft } from 'lucide-react'

export function RouteConfigCard() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-violet-500/30 hover:-translate-y-0.5 xl:col-span-2">

      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden text-violet-600 transition-colors group-hover:bg-violet-50/50">
            <Network className="h-7 w-7" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">Routing Rules</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <ArrowRightLeft className="h-4 w-4 text-violet-500" /> ISA Sender/Receiver mapping
            </div>
          </div>
        </div>

        <Dialog open={isOpen} onOpenChange={setIsOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="bg-slate-900 hover:bg-slate-800 text-white shadow-md z-10 w-full sm:w-auto rounded-xl">
              <Plus className="w-4 h-4 mr-2" />
              Add Route
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[500px] rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl">Add Route Config</DialogTitle>
            </DialogHeader>
            <div className="grid gap-5 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="direction" className="text-slate-600 font-medium">Direction</Label>
                  <Select defaultValue="INBOUND">
                    <SelectTrigger className="h-10 rounded-xl">
                      <SelectValue placeholder="Select direction" />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl">
                      <SelectItem value="INBOUND">INBOUND</SelectItem>
                      <SelectItem value="OUTBOUND">OUTBOUND</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="transaction_type" className="text-slate-600 font-medium">Transaction Type</Label>
                  <Input id="transaction_type" placeholder="e.g. 850 or *" className="h-10 rounded-xl" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="sender_id" className="text-slate-600 font-medium">ISA Sender ID</Label>
                  <Input id="sender_id" placeholder="e.g. SENDER_ID" className="h-10 rounded-xl" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="receiver_id" className="text-slate-600 font-medium">ISA Receiver ID</Label>
                  <Input id="receiver_id" placeholder="e.g. RECEIVER_ID" className="h-10 rounded-xl" />
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="target" className="text-slate-600 font-medium">Target Destination</Label>
                <Select>
                  <SelectTrigger className="h-10 rounded-xl">
                    <SelectValue placeholder="Select target partner" />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    <SelectItem value="webhook1">Webhook: API Gateway</SelectItem>
                    <SelectItem value="sftp1">SFTP: Acme Corp</SelectItem>
                    <SelectItem value="as21">AS2: Walmart</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button className="w-full h-11 mt-2 text-base font-semibold shadow-sm rounded-xl" onClick={() => setIsOpen(false)}>Save Route</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="pt-6 mt-2 border-t border-slate-100 min-h-[120px] flex items-center justify-center">
        <div className="flex flex-col items-center gap-2">
           <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-50 border border-slate-100">
             <ArrowRightLeft className="h-5 w-5 text-slate-300" />
           </div>
           <span className="text-sm font-medium text-slate-400">No routing rules configured</span>
        </div>
      </div>
    </div>
  )
}
