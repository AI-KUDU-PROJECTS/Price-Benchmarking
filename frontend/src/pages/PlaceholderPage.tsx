import { PageHeader } from "../components/PageHeader";

export function PlaceholderPage({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <>
      <PageHeader title={title} subtitle="Placeholder for a later phase." />
      <div className="card empty">{message}</div>
    </>
  );
}
