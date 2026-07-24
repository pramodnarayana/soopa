import { Copy } from 'lucide-react';
import * as React from 'react';
import { type ExternalToast, toast as sonnerToast } from 'sonner';

import type { ToastActionElement } from '@/components/ui/toast';

const TOAST_LIMIT = 1;
const TOAST_REMOVE_DELAY = 3000;

type ToasterToast = {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: ToastActionElement;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  variant?: 'default' | 'destructive';
};

let count = 0;

function genId() {
  count = (count + 1) % Number.MAX_SAFE_INTEGER;
  return count.toString();
}

type Action =
  | {
      type: 'ADD_TOAST';
      toast: ToasterToast;
    }
  | {
      type: 'UPDATE_TOAST';
      toast: Partial<ToasterToast>;
    }
  | {
      type: 'DISMISS_TOAST';
      toastId?: ToasterToast['id'];
    }
  | {
      type: 'REMOVE_TOAST';
      toastId?: ToasterToast['id'];
    };

interface State {
  toasts: ToasterToast[];
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) {
    return;
  }

  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId);
    dispatch({
      type: 'REMOVE_TOAST',
      toastId: toastId,
    });
  }, TOAST_REMOVE_DELAY);

  toastTimeouts.set(toastId, timeout);
};

export const reducer = (state: State, action: Action): State => {
  switch (action.type) {
    case 'ADD_TOAST':
      return {
        ...state,
        toasts: [action.toast, ...state.toasts].slice(0, TOAST_LIMIT),
      };

    case 'UPDATE_TOAST':
      return {
        ...state,
        toasts: state.toasts.map((t) => (t.id === action.toast.id ? { ...t, ...action.toast } : t)),
      };

    case 'DISMISS_TOAST': {
      const { toastId } = action;

      if (toastId) {
        addToRemoveQueue(toastId);
      } else {
        state.toasts.forEach((toast) => {
          addToRemoveQueue(toast.id);
        });
      }

      return {
        ...state,
        toasts: state.toasts.map((t) =>
          t.id === toastId || toastId === undefined
            ? {
                ...t,
                open: false,
              }
            : t,
        ),
      };
    }
    case 'REMOVE_TOAST':
      if (action.toastId === undefined) {
        return {
          ...state,
          toasts: [],
        };
      }
      return {
        ...state,
        toasts: state.toasts.filter((t) => t.id !== action.toastId),
      };
  }
};

const listeners: Array<(state: State) => void> = [];

let memoryState: State = { toasts: [] };

function dispatch(action: Action) {
  memoryState = reducer(memoryState, action);
  listeners.forEach((listener) => {
    listener(memoryState);
  });
}

type Toast = Omit<ToasterToast, 'id'>;

const ERROR_TOAST_DURATION = 10000; // Errors persist for 10s (auto-pauses on hover)

function dispatchSonnerToast(props: Partial<ToasterToast>, id: string) {
  const sonnerOpts: ExternalToast = {
    description: props.description,
    id,
  };

  if (props.action) {
    sonnerOpts.action = {
      label: props.action.label,
      onClick: props.action.onClick,
    };
  }

  if (props.variant === 'destructive') {
    // Apply global defaults for all error-level toasts
    sonnerOpts.duration = ERROR_TOAST_DURATION;

    const ToastContent = () => (
      <div className="flex items-start justify-between w-full gap-3 group/toast-inner">
        <div className="flex flex-col gap-1 pr-4">
          <span className="font-semibold">{props.title}</span>
          {props.description && <span className="text-sm opacity-90">{props.description}</span>}
        </div>
        <button
          onClick={async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const textToCopy =
              `${typeof props.title === 'string' ? props.title : ''}\n${typeof props.description === 'string' ? props.description : ''}`.trim();
            try {
              await navigator.clipboard.writeText(textToCopy);
              sonnerToast.success('Copied to clipboard', { duration: 2000 });
            } catch {
              sonnerToast.error('Failed to copy to clipboard', { duration: 2000 });
            }
          }}
          className="p-1 rounded-md hover:bg-black/10 dark:hover:bg-white/10 text-muted-foreground hover:text-foreground transition-colors shrink-0"
          title="Copy error message"
        >
          <Copy className="w-4 h-4" />
        </button>
      </div>
    );

    sonnerToast.error(<ToastContent />, sonnerOpts);
  } else {
    sonnerToast(props.title, sonnerOpts);
  }
}

function toast({ ...props }: Toast) {
  const id = genId();

  const update = (props: ToasterToast) => {
    dispatch({
      type: 'UPDATE_TOAST',
      toast: { ...props, id },
    });

    dispatchSonnerToast(props, id);
  };

  const dismiss = () => {
    dispatch({ type: 'DISMISS_TOAST', toastId: id });
    sonnerToast.dismiss(id);
  };

  dispatch({
    type: 'ADD_TOAST',
    toast: {
      ...props,
      id,
      open: true,
      onOpenChange: (open: boolean) => {
        if (!open) dismiss();
      },
    },
  });

  // Call Sonner toast under the hood for actual display
  dispatchSonnerToast(props, id);

  return {
    id: id,
    dismiss,
    update,
  };
}

function useToast() {
  const [state, setState] = React.useState<State>(memoryState);

  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const index = listeners.indexOf(setState);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    };
  }, [state]);

  return {
    ...state,
    toast,
    dismiss: (toastId?: string) => dispatch({ type: 'DISMISS_TOAST', toastId }),
  };
}

export { toast, useToast };
