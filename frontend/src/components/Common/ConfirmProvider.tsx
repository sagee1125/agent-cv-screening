// Promise-based confirm dialog context, replacing window.confirm for async flows.
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Button } from "../ui/button";
import { Modal } from "./Modal";

interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
}

// Provider that renders a single confirm modal and exposes confirm() via context.
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      setPending({ options, resolve });
    });
  }, []);

  const handleClose = (result: boolean) => {
    if (pending) {
      pending.resolve(result);
    }
    setPending(null);
  };

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Modal
        open={pending !== null}
        onClose={() => handleClose(false)}
        contentClassName="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-xl"
      >
        {pending ? (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-slate-900">
              {pending.options.title}
            </h2>
            {pending.options.description ? (
              <p className="text-sm text-slate-600">
                {pending.options.description}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => handleClose(false)}
              >
                {pending.options.cancelLabel ?? "Cancel"}
              </Button>
              <Button
                variant={pending.options.destructive ? "default" : "default"}
                onClick={() => handleClose(true)}
              >
                {pending.options.confirmLabel ?? "Confirm"}
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </ConfirmContext.Provider>
  );
}

// Hook used by components/hook to await a confirmation dialog.
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) {
    throw new Error("useConfirm must be used within a ConfirmProvider");
  }
  return confirm;
}
