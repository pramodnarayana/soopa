import { EdiUIProvider } from '@soopa/edi-ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/edi')({
  component: EdiLayout,
});

function EdiLayout() {
  return (
    <EdiUIProvider>
      <Outlet />
    </EdiUIProvider>
  );
}
