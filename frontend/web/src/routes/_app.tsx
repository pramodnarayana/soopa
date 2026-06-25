import { Outlet, createRoute } from '@tanstack/react-router'
import { Route as rootRoute } from './__root'
import { useAuth } from 'react-oidc-context'
import { Button } from '@/components/ui/button'

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  component: AppLayout,
})

function AppLayout() {
  const auth = useAuth()

  // Strict Authentication Guard
  if (!auth.isAuthenticated && !auth.isLoading) {
    // We cannot use standard router redirect here easily because auth state lives in React context
    // We can just trigger a sign-in or render a forbidden message.
    void auth.signinRedirect()
    return null
  }

  if (auth.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 rounded-full border-4 border-indigo-200 border-t-indigo-600 animate-spin" />
          <p className="text-slate-500 font-medium animate-pulse">Authenticating with ZITADEL...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      <header className="flex h-16 items-center justify-between border-b border-slate-200 px-6 bg-white shadow-sm z-10">
        <div className="flex items-center gap-3">
           <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shadow-md shadow-indigo-600/20">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
            </div>
          <h1 className="text-lg font-bold">EDI AS2 <span className="font-normal text-slate-500 ml-2">Console</span></h1>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="text-sm text-slate-600 font-medium bg-slate-100 px-3 py-1.5 rounded-full border border-slate-200">
            {auth.user?.profile.email}
          </div>
          <Button variant="outline" size="sm" onClick={() => void auth.signoutRedirect()} className="font-medium text-slate-600 hover:text-slate-900">
            Log out
          </Button>
        </div>
      </header>
      
      <main className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full">
        <Outlet />
      </main>
    </div>
  )
}
