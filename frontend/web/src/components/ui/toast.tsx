import { Toaster as SonnerToaster, toast } from "sonner"
import { useTheme } from "next-themes"

const ToastProvider = ({ ...props }) => {
  const { theme = "system" } = useTheme()
  return (
    <SonnerToaster
      theme={theme as any}
      className="toaster group"
      toastOptions={{
        classNames: {
          toast: "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
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

type ToastProps = any
type ToastActionElement = any

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
