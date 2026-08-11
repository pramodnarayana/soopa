import type React from 'react';

export interface AppLayoutProps {
  sidebarHeader: React.ReactNode;
  sidebarNavigation: React.ReactNode;
  userProfile: React.ReactNode;
  headerContent?: React.ReactNode;
  children: React.ReactNode;
}

export function AppLayout({
  sidebarHeader,
  sidebarNavigation,
  userProfile,
  headerContent,
  children,
}: AppLayoutProps) {
  return (
    <div className="flex min-h-screen bg-background font-sans text-foreground selection:bg-primary/20 selection:text-primary">
      {/* Sidebar - hidden on mobile, fixed at desktop */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-[340px] lg:flex-col border-r border-border bg-card">
        {/* Header */}
        <div className="flex h-20 items-center border-b border-border/40 px-8">{sidebarHeader}</div>

        {/* Navigation */}
        <nav className="flex flex-1 flex-col gap-1.5 overflow-y-auto px-4 py-8">
          {sidebarNavigation}
        </nav>

        {/* User Profile */}
        <div className="p-6">{userProfile}</div>
      </aside>

      {/* Main Content Area - no left margin on mobile */}
      <main className="flex-1 lg:ml-[340px] bg-background flex flex-col min-h-screen">
        <header className="h-20 bg-background/80 backdrop-blur-md border-b border-border/40 sticky top-0 z-40 px-8 flex items-center justify-end shadow-sm">
          {headerContent}
        </header>
        <div className="mx-auto w-full max-w-[1800px] p-8 lg:p-12 xl:p-16 flex-1">{children}</div>
      </main>
    </div>
  );
}
