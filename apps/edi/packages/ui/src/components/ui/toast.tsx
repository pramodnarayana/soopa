import { useTheme } from 'next-themes';
import { Toaster as SonnerToaster, toast } from 'sonner';

const ToastProvider = ({ ...props }) => {
  const { theme = 'system' } = useTheme();
  return (
    <SonnerToaster
      theme={theme as 'system' | 'light' | 'dark'}
      className="toaster group"
      richColors
      toastOptions={{
        classNames: {
          toast: 'group toast group-[.toaster]:shadow-lg select-text',
          description: 'select-text',
          actionButton: 'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground',
          cancelButton: 'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground',
        },
      }}
      {...props}
    />
  );
};

const ToastViewport = () => null;
const Toast = () => null;
const ToastTitle = () => null;
const ToastDescription = () => null;
const ToastClose = () => null;
const ToastAction = () => null;

import * as React from 'react';

type ToastProps = {
  className?: string;
  variant?: 'default' | 'destructive';
};

type ToastActionElement = {
  label: React.ReactNode;
  onClick: () => void;
};

export {
  Toast,
  ToastAction,
  type ToastActionElement,
  ToastClose,
  ToastDescription,
  type ToastProps,
  ToastProvider,
  ToastTitle,
  ToastViewport,
  toast,
};
