import { createRoute } from '@tanstack/react-router'
import { Route as marketingRoute } from '../_marketing'

export const Route = createRoute({
  getParentRoute: () => marketingRoute,
  path: '/',
  component: LandingPage,
})

export function LandingPage() {
  return (
    <div className="relative flex-1 flex flex-col items-center justify-center overflow-hidden bg-white">
      {/* Subtle Dot Pattern */}
      <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMSIgY3k9IjEiIHI9IjEiIGZpbGw9IiNlNWU3ZWIiLz48L3N2Zz4=')] [mask-image:radial-gradient(circle_at_center,white,transparent_80%)] pointer-events-none" />

      {/* Completely Minimal Hero Content */}
      <div className="relative z-10 max-w-4xl mx-auto px-6 text-center py-20 md:py-32">
        <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight text-slate-900 mb-6">
          Modern B2B Integration.
        </h1>
      </div>
    </div>
  )
}
