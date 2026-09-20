import { PageHeader } from "../components/PageHeader";
import { EmptyState } from "../components/States";

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
      <EmptyState message={message} />
    </>
  );
}
