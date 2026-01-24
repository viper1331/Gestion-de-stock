import { FormEvent, ReactNode } from "react";

import { DraggableModal } from "./DraggableModal";

interface PurchaseOrderCreateModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  children: ReactNode;
  isSubmitting?: boolean;
  submitLabel?: string;
  formId: string;
}

export function PurchaseOrderCreateModal({
  open,
  title,
  onClose,
  onSubmit,
  children,
  isSubmitting = false,
  submitLabel = "Enregistrer",
  formId
}: PurchaseOrderCreateModalProps) {
  return (
    <DraggableModal
      open={open}
      title={title}
      onClose={onClose}
      maxWidthClassName="max-w-[min(96vw,900px)]"
      bodyClassName="px-6 py-4"
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
          >
            Annuler
          </button>
          <button
            type="submit"
            form={formId}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
            disabled={isSubmitting}
          >
            {submitLabel}
          </button>
        </div>
      }
    >
      <form id={formId} className="flex min-w-0 flex-col gap-4" onSubmit={onSubmit}>
        {children}
      </form>
    </DraggableModal>
  );
}
