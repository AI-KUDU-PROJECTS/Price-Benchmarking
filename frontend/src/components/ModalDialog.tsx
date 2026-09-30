import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

export function ModalDialog({
  open,
  title,
  description,
  onRequestClose,
  children,
  footer,
  size = "large",
}: {
  open: boolean;
  title: string;
  description?: string;
  onRequestClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "small" | "large";
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className={`modal-dialog modal-${size}`}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onRequestClose();
      }}
    >
      <div className="modal-header">
        <div>
          <h2 id={titleId} className="modal-title">{title}</h2>
          {description ? <p id={descriptionId} className="modal-description">{description}</p> : null}
        </div>
        <button
          type="button"
          className="modal-close"
          onClick={onRequestClose}
          aria-label={`Close ${title}`}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="modal-body">{children}</div>
      {footer ? <div className="modal-footer">{footer}</div> : null}
    </dialog>
  );
}

