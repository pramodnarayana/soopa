import type React from 'react';

export interface AppLayoutProps {
  sidebarHeader: React.ReactNode;
  sidebarNavigation: React.ReactNode;
  userProfile: React.ReactNode;
  children: React.ReactNode;
}

export function AppLayout({
  sidebarHeader,
  sidebarNavigation,
  userProfile,
  children,
}: AppLayoutProps) {
  return (
    <div className="flex min-h-screen bg-background font-sans text-foreground selection:bg-primary/20 selection:text-primary">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 z-50 flex w-[340px] flex-col border-r border-border bg-card">
        {/* Header */}
        <div className="flex h-20 items-center border-b border-border/40 px-8">{sidebarHeader}</div>

        {/* Navigation */}
        <nav className="flex flex-1 flex-col gap-1.5 overflow-y-auto px-4 py-8">
          {sidebarNavigation}
        </nav>

        {/* User Profile */}
        <div className="p-6">{userProfile}</div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 ml-[340px] bg-background">
        <div className="mx-auto w-full max-w-[1800px] p-8 lg:p-12 xl:p-16">{children}</div>
      </main>
    </div>
  );
}
