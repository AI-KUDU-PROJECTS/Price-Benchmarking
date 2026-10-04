import { ModalDialog } from "./ModalDialog";

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  destructive = false,
  busy = false,
  onConfirm,
  onRequestClose,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onRequestClose: () => void;
}) {
  return (
    <ModalDialog
      open={open}
      title={title}
      description={message}
      size="small"
      onRequestClose={busy ? () => undefined : onRequestClose}
      footer={(
        <>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onRequestClose}
            disabled={busy}
            autoFocus
          >
            Cancel
          </button>
          <button
            type="button"
            className={`btn ${destructive ? "btn-destructive" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      )}
    >
      <span />
    </ModalDialog>
  );
}

