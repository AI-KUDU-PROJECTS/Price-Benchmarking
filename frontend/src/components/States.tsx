export function LoadingState() {
  return <div className="card loading">Loading…</div>;
}

export function EmptyState({ message }: { message: string }) {
  return <div className="card empty">{message}</div>;
}

export function ErrorState({ error }: { error: Error }) {
  return <div className="card error-box">Could not load data. {error.message}</div>;
}
