'use strict';

/**
 * collector/price-resolver.js
 * ---------------------------------------------------------------------
 * Joins GetMenuSections catalog products to the store-scoped `storeMenu`
 * pricing API (RBI gateway). Prices are cents → SAR. For `_type:picker`
 * products, also builds a per-size list from pickerAspect options
 * (SANDWICH ONLY / GO REGULAR / GO MEDIUM / GO LARGE, or piece counts)
 * by looking up each option's Sanity/POS id in the same storeMenu map.
 *
 * Fallback: when storeMenu has no usable price (missing / all zeros),
 * callers may still fill `__price` from the DOM scraper.
 * ---------------------------------------------------------------------
 */

/** Maps BK picker-aspect labels/identifiers onto dashboard size columns. */
const SIZE_CANONICAL = [
  { column: 'Small', tests: [/alacarte/i, /sandwich\s*only/i, /\b6\s*pieces?\b/i, /\bsmall\b/i] },
  { column: 'Regular', tests: [/sizeregular/i, /\bgo\s*regular\b/i, /\bgo\s*value\b/i, /\b9\s*pieces?\b/i, /\bregular\b/i] },
  { column: 'Medium', tests: [/sizemedium/i, /\bgo\s*medium\b/i, /\bmedium\b/i] },
  { column: 'Large', tests: [/sizelarge/i, /\bgo\s*large\b/i, /\b12\s*pieces?\b/i, /\blarge\b/i] },
];

function centsToSar(cents) {
  const n = Number(cents);
  if (!Number.isFinite(n)) return null;
  return n / 100;
}

function buildStoreMenuIndex(storeMenuEntities) {
  const byId = new Map();
  for (const entity of storeMenuEntities || []) {
    if (!entity || entity.id == null) continue;
    byId.set(String(entity.id), entity);
  }
  return byId;
}

/**
 * Prefer default when > 0; else min when > 0; else null.
 * Never invents a price from max alone.
 */
function entityPriceSar(entity) {
  if (!entity || !entity.price) return null;
  const def = centsToSar(entity.price.default);
  if (def != null && def > 0) return def;
  const min = centsToSar(entity.price.min);
  if (min != null && min > 0) return min;
  return null;
}

function entityPriceRange(entity) {
  if (!entity || !entity.price) return { min: null, max: null };
  return {
    min: centsToSar(entity.price.min),
    max: centsToSar(entity.price.max),
  };
}

function canonicalSizeTitle(label, identifier) {
  const hay = `${identifier || ''} ${label || ''}`.trim();
  if (!hay) return null;
  for (const row of SIZE_CANONICAL) {
    if (row.tests.some((re) => re.test(hay))) return row.column;
  }
  return null;
}

/**
 * Builds [{title, label, price, optionId, isDefault}] from a picker's
 * options[], priced via storeMenu. Titles are canonical Small/Regular/
 * Medium/Large when the aspect maps cleanly; otherwise the raw label.
 */
function extractPickerSizes(product, storeById) {
  if (!product || product._type !== 'picker') return [];
  const aspectOptions = [];
  for (const aspect of product.pickerAspects || []) {
    for (const opt of aspect.pickerAspectOptions || []) {
      aspectOptions.push(opt);
    }
  }
  const sizes = [];
  const seen = new Set();
  for (const row of product.options || []) {
    if (!row || !row.option || !row.option._id) continue;
    const opt = row.option;
    const identifier = (row.pickerItemMappings && row.pickerItemMappings[0] && row.pickerItemMappings[0].pickerAspectValueIdentifier) || '';
    const label = (() => {
      const hit = aspectOptions.find((a) => a && a.identifier === identifier);
      return (hit && hit.name && hit.name.locale) || (opt.name && opt.name.locale) || identifier || null;
    })();
    const title = canonicalSizeTitle(label, identifier) || label;
    if (!title || seen.has(title)) continue;
    const entity = storeById.get(String(opt._id));
    const price = entityPriceSar(entity);
    const entry = {
      title,
      label: label || title,
      optionId: opt._id,
      isDefault: !!row.default,
    };
    if (price != null) entry.price = price;
    sizes.push(entry);
    seen.add(title);
  }
  return sizes;
}

/**
 * Mutates products in place: sets __price / __price_min / __price_max /
 * __price_source / __sizes from storeMenu. Returns match stats.
 */
function applyStoreMenuPrices(products, storeMenuEntities) {
  const storeById = buildStoreMenuIndex(storeMenuEntities);
  let matched = 0;
  let priced = 0;
  for (const product of products || []) {
    const id = product && product._id != null ? String(product._id) : null;
    if (!id) continue;
    const entity = storeById.get(id);
    if (!entity) continue;
    matched += 1;
    const range = entityPriceRange(entity);
    product.__price_min = range.min;
    product.__price_max = range.max;
    const price = entityPriceSar(entity);
    if (price != null) {
      product.__price = price;
      product.__price_source = 'storeMenu';
      priced += 1;
    }
    const sizes = extractPickerSizes(product, storeById);
    if (sizes.length) {
      product.__sizes = sizes;
      // If the parent card still has no price, prefer the default size
      // (or first priced size) so effective_price is not blank.
      if (product.__price == null) {
        const preferred = sizes.find((s) => s.isDefault && s.price != null) || sizes.find((s) => s.price != null);
        if (preferred) {
          product.__price = preferred.price;
          product.__price_source = 'storeMenu.size';
          priced += 1;
        }
      }
    }
  }
  return { matched, priced, storeEntityCount: storeById.size };
}

module.exports = {
  centsToSar,
  buildStoreMenuIndex,
  entityPriceSar,
  extractPickerSizes,
  applyStoreMenuPrices,
  canonicalSizeTitle,
};
