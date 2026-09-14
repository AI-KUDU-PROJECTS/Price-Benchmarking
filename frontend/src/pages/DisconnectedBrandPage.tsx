import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";

const NAMES: Record<string, string> = {
  hardees: "Hardee's",
  "burger-king": "Burger King",
  herfy: "Herfy",
};

export function DisconnectedBrandPage({ brandId }: { brandId: string }) {
  return (
    <>
      <PageHeader
        title={NAMES[brandId] || brandId}
        subtitle="Visible in navigation, not connected in this slice."
      />
      <BrandTabs brandId={brandId} />
      <DataBanner health="disconnected" />
    </>
  );
}
