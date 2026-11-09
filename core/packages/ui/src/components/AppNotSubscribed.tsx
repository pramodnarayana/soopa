import { AlertCircle } from 'lucide-react';
import { Card, CardDescription, CardHeader, CardTitle } from './ui/card';

interface AppNotSubscribedProps {
  appName: string;
}

export function AppNotSubscribed({ appName }: AppNotSubscribedProps) {
  return (
    <div className="flex flex-1 items-center justify-center min-h-[50vh] p-4">
      <div className="w-full max-w-md">
        <Card>
          <CardHeader>
            <div className="flex justify-center mb-4">
              <div className="rounded-full bg-status-critical-bg p-3">
                <AlertCircle className="h-8 w-8 text-status-critical-fg" />
              </div>
            </div>
            <div className="text-center">
              <CardTitle>Subscription Required</CardTitle>
            </div>
            <div className="text-center">
              <CardDescription>
                You do not have access to {appName}. Please contact your administrator or subscribe
                to this application to continue.
              </CardDescription>
            </div>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
