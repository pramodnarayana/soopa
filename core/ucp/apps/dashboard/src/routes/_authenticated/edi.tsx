import { createFileRoute, Outlet } from '@tanstack/react-router';
import { EdiUIProvider } from '@soopa/edi-ui';

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
