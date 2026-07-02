export function useToast() {
  const toast = (options: { title?: string; description?: string; variant?: string }) => {
    if (options.variant === 'destructive') {
      console.error(options.title, options.description);
      alert(`${options.title}: ${options.description}`);
    } else {
      console.log(options.title, options.description);
      // In a real app, this would show a toast notification
    }
  };
  return { toast };
}
