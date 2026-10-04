import type { Channel } from "../api/types";

export interface FlowProduct {
  brandId: string;
  brandName: string;
  productId: string;
  nameAr: string | null;
  nameEn: string | null;
  category: string | null;
  imageUrl: string | null;
  effectivePrice: number | null;
  currency: string | null;
  missing: boolean;
}

export interface PriceComparison {
  difference: number | null;
  percentage: number | null;
  position: "higher" | "lower" | "equal" | "unavailable";
}

const CHANNEL_LABELS: Record<Channel, string> = {
  pickup: "Pickup",
  delivery: "Delivery",
  hungerstation: "HungerStation",
};

export function channelLabel(channel: Channel): string {
  return CHANNEL_LABELS[channel];
}

export function flowProductKey(product: Pick<FlowProduct, "brandId" | "productId">): string {
  return `${product.brandId}::${product.productId}`;
}

export function flowProductName(
  product: Pick<FlowProduct, "nameEn" | "nameAr" | "productId">,
): string {
  return product.nameEn || product.nameAr || product.productId;
}

export function comparePrices(
  competitor: FlowProduct,
  kudu: FlowProduct | null,
): PriceComparison {
  if (
    !kudu
    || kudu.missing
    || competitor.missing
    || kudu.effectivePrice === null
    || competitor.effectivePrice === null
    || !kudu.currency
    || kudu.currency !== competitor.currency
  ) {
    return { difference: null, percentage: null, position: "unavailable" };
  }

  const difference = Math.round((competitor.effectivePrice - kudu.effectivePrice) * 100) / 100;
  const percentage = kudu.effectivePrice === 0
    ? null
    : Math.round((difference / kudu.effectivePrice) * 10000) / 100;
  const position = difference > 0 ? "higher" : difference < 0 ? "lower" : "equal";
  return { difference, percentage, position };
}

export function signedMoney(value: number | null, currency: string | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${currency || "SAR"} ${sign}${value.toFixed(2)}`;
}

export function signedPercent(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function comparisonCopy(comparison: PriceComparison, currency: string | null): string {
  if (comparison.difference === null) return "Price comparison unavailable";
  if (comparison.position === "equal") return "Same price as KUDU";
  if (comparison.position === "higher") {
    return `${signedMoney(comparison.difference, currency)} higher than KUDU`;
  }
  return `${currency || "SAR"} ${Math.abs(comparison.difference).toFixed(2)} lower than KUDU`;
}
