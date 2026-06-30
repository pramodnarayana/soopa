import { useState, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Server, Plus, CheckCircle2, UploadCloud, FileCode } from 'lucide-react'

export interface AS2PartnerCardProps {
  count: number;
  onSave: (data: { name: string; type: string; as2_id: string; is_local: boolean; public_cert_pem?: string }) => Promise<void> | void;
}

export function AS2PartnerCard({ count, onSave }: AS2PartnerCardProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isLocal, setIsLocal] = useState(false)
  const [certPem, setCertPem] = useState("")
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileUpload = (file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result as string
      if (content) setCertPem(content)
    }
    reader.readAsText(file)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0])
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!isLocal && !certPem) {
      alert("Remote AS2 partners require a public certificate.");
      return;
    }
    const formData = new FormData(e.currentTarget)
    await onSave({
      name: formData.get('name') as string,
      type: 'AS2',
      as2_id: formData.get('as2_id') as string,
      is_local: isLocal,
      public_cert_pem: isLocal ? undefined : certPem,
    })
    setIsOpen(false)
    setCertPem("") // Reset after save
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  return (
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-indigo-500/30 hover:-translate-y-0.5">

      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden text-indigo-600 transition-colors group-hover:bg-indigo-50/50">
            <Server className="h-7 w-7" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">AS2 Trading Partner</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <CheckCircle2 className={`h-4 w-4 ${count > 0 ? 'text-emerald-500' : 'text-slate-300'}`} /> {count} Active
            </div>
          </div>
        </div>

        <Dialog open={isOpen} onOpenChange={(open) => {
          setIsOpen(open)
          if (!open) {
            setIsLocal(false)
            setCertPem("")
            if (fileInputRef.current) fileInputRef.current.value = ""
          }
        }}>
          <DialogTrigger asChild>
            <Button size="icon" variant="ghost" className="h-10 w-10 shrink-0 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-xl transition-colors">
              <Plus className="h-5 w-5" />
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[600px] rounded-2xl" onPointerDownOutside={(e) => e.preventDefault()}>
            <DialogHeader>
              <DialogTitle className="text-xl">Add AS2 Partner</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSave} className="grid gap-6 py-4">

              <div className="flex items-center gap-2 pb-2 border-b border-slate-100">
                <Input type="checkbox" id="is_local" name="is_local" checked={isLocal} onChange={(e) => setIsLocal(e.target.checked)} className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600" />
                <Label htmlFor="is_local" className="text-slate-600 font-medium">This is a Local Trading Partner (Generates Certificate automatically)</Label>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div className="grid gap-2">
                  <Label htmlFor="name" className="text-slate-600 font-medium">Partner Name</Label>
                  <Input id="name" name="name" required placeholder="e.g. Acme Corp" className="h-10 rounded-xl" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="as2_id" className="text-slate-600 font-medium">AS2 ID</Label>
                  <Input id="as2_id" name="as2_id" required placeholder="ACME_AS2" className="h-10 rounded-xl" />
                </div>
              </div>

              {!isLocal && (
                  <div className="grid gap-2">
                    <Label className="text-slate-600 font-medium">Public Certificate</Label>

                    <div
                      className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 transition-colors ${isDragging ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}`}
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                    >
                      <input
                        type="file"
                        ref={fileInputRef}
                        className="hidden"
                        accept=".cer,.crt,.pem,.txt"
                        onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
                      />

                      {certPem ? (
                        <div className="flex flex-col items-center gap-3">
                          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                            <FileCode className="h-6 w-6" />
                          </div>
                          <div className="text-center">
                            <span className="block text-sm font-semibold text-slate-700">Certificate Loaded</span>
                            <span className="block text-xs text-slate-500 mt-1 truncate max-w-[200px]">
                              {certPem.substring(0, 30)}...
                            </span>
                          </div>
                          <Button type="button" variant="outline" onClick={() => setCertPem('')} className="h-8 text-xs px-3 rounded-lg mt-1 border-slate-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200">
                            Replace File
                          </Button>
                        </div>
                      ) : (
                        <div
                          className="flex flex-col items-center gap-3 text-center"
                          onClick={() => fileInputRef.current?.click()}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click(); } }}
                          tabIndex={0}
                          role="button"
                        >
                          <div className="rounded-full bg-white p-3 shadow-sm border border-slate-100 cursor-pointer group-hover:border-indigo-200">
                            <UploadCloud className="h-6 w-6 text-indigo-500" />
                          </div>
                          <div>
                            <span className="text-sm font-semibold text-indigo-600 cursor-pointer hover:underline">Click to upload</span>
                            <span className="text-sm text-slate-500"> or drag and drop</span>
                          </div>
                          <span className="text-xs text-slate-400">PEM, CER, or CRT up to 10MB</span>
                        </div>
                      )}
                    </div>

                    {/* Hidden input to pass data to formData */}
                    <input type="hidden" name="public_cert_pem" value={certPem} />
                  </div>
                )}
              <Button type="submit" className="w-full h-11 mt-2 text-base font-semibold shadow-sm rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white">Save Trading Partner</Button>
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
