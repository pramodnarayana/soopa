import { useRoutesData } from '../api/useRoutesData'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { ArrowRightLeft, Network, ShieldCheck, Activity } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export function ActiveRoutesTable() {
  const { data: routes, isLoading, error } = useRoutesData()

  if (isLoading) {
    return (
      <Card className="col-span-full border-slate-200 shadow-sm animate-pulse">
        <CardHeader className="bg-slate-50/50 border-b border-slate-100">
          <div className="h-6 w-1/4 bg-slate-200 rounded mb-2"></div>
          <div className="h-4 w-1/3 bg-slate-200 rounded"></div>
        </CardHeader>
        <CardContent className="p-6">
          <div className="space-y-4">
            <div className="h-10 bg-slate-100 rounded w-full"></div>
            <div className="h-10 bg-slate-100 rounded w-full"></div>
            <div className="h-10 bg-slate-100 rounded w-full"></div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="col-span-full border-red-200 shadow-sm">
        <CardHeader className="bg-red-50/50 border-b border-red-100">
          <CardTitle className="text-red-700">Routes</CardTitle>
          <CardDescription className="text-red-600">Failed to load routes.</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card className="col-span-full border-slate-200 shadow-sm">
      <CardHeader className="bg-slate-50/50 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-emerald-100 text-emerald-700 rounded-lg">
              <Network className="w-5 h-5" />
            </div>
            <div>
              <CardTitle className="text-lg font-bold text-slate-800">Routes</CardTitle>
              <CardDescription>
                EDI data flows between your internal systems and external Trading Partners.
              </CardDescription>
            </div>
          </div>
          <Badge variant="outline" className="bg-white">
            {routes?.length || 0} Total
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {routes && routes.length > 0 ? (
          <Table>
            <TableHeader className="bg-slate-50/80">
              <TableRow>
                <TableHead className="w-[120px]">Direction</TableHead>
                <TableHead>Sender ID (ISA)</TableHead>
                <TableHead>Receiver ID (ISA)</TableHead>
                <TableHead>Trading Partner</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {routes.map((route) => (
                <TableRow key={route.route_id} className="hover:bg-slate-50">
                  <TableCell>
                    {route.direction === 'INBOUND' ? (
                      <Badge variant="secondary" className="bg-blue-50 text-blue-700 border-blue-200 font-medium">
                        <ArrowRightLeft className="w-3 h-3 mr-1 rotate-90" /> Inbound
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="bg-amber-50 text-amber-700 border-amber-200 font-medium">
                        <ArrowRightLeft className="w-3 h-3 mr-1" /> Outbound
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-sm text-slate-600">{route.isa_sender_id}</TableCell>
                  <TableCell className="font-mono text-sm text-slate-600">{route.isa_receiver_id}</TableCell>
                  <TableCell className="font-medium text-slate-900">{route.destination_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-slate-600">
                      {route.destination_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      {route.status}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
            <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mb-4">
              <Activity className="w-8 h-8 text-slate-400" />
            </div>
            <h3 className="text-lg font-medium text-slate-900 mb-1">No active routes</h3>
            <p className="text-slate-500 max-w-sm">
              You haven't configured any inbound or outbound EDI routes yet.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
