import { Toaster as SonnerToaster, toast } from "sonner"
import { useTheme } from "next-themes"

const ToastProvider = ({ ...props }) => {
  const { theme = "system" } = useTheme()
  return (
    <SonnerToaster
      theme={theme as any}
      className="toaster group"
      richColors
      toastOptions={{
        classNames: {
          toast: "group toast group-[.toaster]:shadow-lg select-text",
          description: "select-text",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  )
}

const ToastViewport = () => null
const Toast = () => null
const ToastTitle = () => null
const ToastDescription = () => null
const ToastClose = () => null
const ToastAction = () => null

import * as React from "react"

type ToastProps = {
  className?: string
  variant?: "default" | "destructive"
}

type ToastActionElement = {
  label: React.ReactNode
  onClick: () => void
}

export {
  type ToastProps,
  type ToastActionElement,
  ToastProvider,
  ToastViewport,
  Toast,
  ToastTitle,
  ToastDescription,
  ToastClose,
  ToastAction,
  toast,
}
