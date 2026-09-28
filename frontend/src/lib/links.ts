import type { ChangeEvent } from "../api/types";

export function productHref(brandId: string, productId: string) {
  return `/competitors/${brandId}/products/${encodeURIComponent(productId)}`;
}

export function promotionHref(brandId: string, promotionId: string) {
  return `/competitors/${brandId}/promotions/${encodeURIComponent(promotionId)}`;
}

export function changeHref(event: ChangeEvent) {
  if (event.promotionId) return promotionHref(event.brandId, event.promotionId);
  if (event.productId) return productHref(event.brandId, event.productId);
  return `/changes/${encodeURIComponent(event.id)}`;
}
