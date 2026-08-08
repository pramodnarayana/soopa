import { Box } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';

interface AppNotSubscribedProps {
  appName: string;
}

export function AppNotSubscribed({ appName }: AppNotSubscribedProps) {
  return (
    <div className="flex flex-1 items-center justify-center p-6 bg-muted/20 min-h-full">
      <Card className="max-w-md shadow-lg text-center border-dashed border-2 bg-background/50 backdrop-blur-sm">
        <CardHeader className="flex flex-col items-center gap-4 pb-4">
          <div className="p-4 rounded-full bg-primary/10">
            <Box className="w-12 h-12 text-primary" />
          </div>
          <div className="space-y-1.5">
            <CardTitle className="text-2xl font-bold tracking-tight">
              {appName} Not Subscribed
            </CardTitle>
            <CardDescription className="text-base">
              You don't have access to {appName}.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Contact your administrator to enable it.</p>
        </CardContent>
      </Card>
    </div>
  );
}
