import type { PropsWithChildren } from "react";

interface ModalProps extends PropsWithChildren {
  open: boolean;
  onClose: () => void;
  overlayClassName?: string;
  contentClassName?: string;
}

export function Modal({
  open,
  onClose,
  overlayClassName = "fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4",
  contentClassName = "max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border border-slate-200 bg-white p-5",
  children,
}: ModalProps) {
  if (!open) return null;

  return (
    <div className={overlayClassName} onClick={onClose}>
      <div className={contentClassName} onClick={(event) => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
