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
    <div className="flex min-h-screen flex-col bg-background font-sans text-foreground selection:bg-primary/15 selection:text-foreground">
      <div className="flex flex-1">
        {/* Casdoor Compact Sidebar (w-60 / 240px) */}
        <aside className="hidden lg:fixed lg:inset-y-0 lg:z-40 lg:flex lg:w-60 lg:flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
          {/* Brand Bar (h-14 / 56px) */}
          <div className="flex h-14 items-center border-b border-sidebar-border px-3">
            {sidebarHeader}
          </div>

          {/* Navigation */}
          <nav className="scrollbar-thin flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-3">
            {sidebarNavigation}
          </nav>

          {/* User Profile Footer */}
          <div className="border-t border-sidebar-border p-2.5">{userProfile}</div>
        </aside>

        {/* Main Content Area */}
        <div className="flex min-h-screen min-w-0 flex-1 flex-col bg-background lg:ml-60">
          {headerContent ? (
            <header className="sticky top-0 z-30 flex h-14 items-center justify-end gap-3 border-b border-border bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              {headerContent}
            </header>
          ) : null}
          <main className="mx-auto w-full max-w-[1600px] flex-1 p-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
