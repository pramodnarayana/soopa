import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FileDown, Plus, CheckCircle2 } from 'lucide-react'
import { usePartners } from '@/features/partners/context/PartnersContext'

export function SFTPPartnerCard() {
  const [isOpen, setIsOpen] = useState(false)
  const { partners, addPartner } = usePartners()

  const sftpCount = partners.filter(p => p.type === 'SFTP').length

  const handleSave = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    addPartner({
      name: formData.get('name') as string,
      type: 'SFTP',
      username: formData.get('username') as string,
      host: formData.get('host') as string,
    })
    setIsOpen(false)
  }

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-sky-500/30 hover:-translate-y-0.5">

      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden text-sky-600 transition-colors group-hover:bg-sky-50/50">
            <FileDown className="h-7 w-7" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">SFTP</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <CheckCircle2 className={`h-4 w-4 ${sftpCount > 0 ? 'text-emerald-500' : 'text-slate-300'}`} /> {sftpCount} Active
            </div>
          </div>
        </div>

        <Dialog open={isOpen} onOpenChange={setIsOpen}>
          <DialogTrigger asChild>
            <Button size="icon" variant="ghost" className="h-8 w-8 rounded-full text-slate-400 hover:text-sky-600 hover:bg-sky-50">
              <Plus className="h-5 w-5" />
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[425px] rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl">Add SFTP Partner</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSave} className="grid gap-5 py-4">
              <div className="grid gap-2">
                <Label htmlFor="name" className="text-slate-600 font-medium">Partner Name</Label>
                <Input id="name" name="name" required placeholder="e.g. Globex" className="h-10 rounded-xl" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="host" className="text-slate-600 font-medium">SFTP Host</Label>
                <Input id="host" name="host" required placeholder="sftp.globex.com" className="h-10 rounded-xl" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="username" className="text-slate-600 font-medium">Username</Label>
                  <Input id="username" name="username" required placeholder="globex_usr" className="h-10 rounded-xl" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="port" className="text-slate-600 font-medium">Port</Label>
                  <Input id="port" name="port" type="number" defaultValue="22" className="h-10 rounded-xl" />
                </div>
              </div>
              <Button type="submit" className="w-full h-11 mt-2 text-base font-semibold shadow-sm rounded-xl bg-sky-600 hover:bg-sky-700">Save Partner</Button>
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
