'use strict';

/**
 * product-crawler.js
 * ---------------------------------------------------------------------
 * Opens a single product's detail view/modal, extracts everything the
 * spec asks for (name, id, price, discount, calories, description,
 * image, option groups with min/max/required/price), and optionally
 * selects one minimal valid combination and adds it to the cart (the
 * "representative combination" - we never generate every combination).
 *
 * DOM structure for the product detail modal was not fully observable
 * during development recon (the live site is timing-sensitive and the
 * modal wasn't reached in every trial run), so extraction here uses
 * several independent, defensive heuristics and cross-references any
 * captured getMenu/getMenuConfig API JSON when available for higher
 * fidelity. Every step degrades gracefully and logs what it could not
 * find rather than throwing.
 * ---------------------------------------------------------------------
 */

const CONFIG = require('../collector/config');
const safe = require('../collector/safe-actions');
const urlUtils = require('../collector/url-utils');

const CURRENCY = 'SAR'; // Saudi Riyal - the site shows a currency glyph/icon, not a text code.

function parsePrice(text) {
  if (!text) return null;
  const match = String(text).replace(/,/g, '').match(/(\d+(?:\.\d{1,2})?)/);
  return match ? parseFloat(match[1]) : null;
}

function slugify(text) {
  return (text || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 60);
}

async function findDetailModal(page) {
  const candidates = [
    '[role="dialog"]',
    '.MuiDialog-root [role="presentation"]',
    '[class*="ProductModal" i]',
    '[class*="product-detail" i]',
    '[class*="itemDetail" i]',
    '[class*="modal" i]',
  ];
  for (const sel of candidates) {
    const loc = page.locator(sel).first();
    if (await loc.isVisible({ timeout: 500 }).catch(() => false)) return loc;
  }
  return null;
}

async function openProductDetail(page, logger, productRef) {
  const nameLocator = page.getByText(productRef.name, { exact: false }).first();
  if ((await nameLocator.count().catch(() => 0)) === 0) {
    logger.warn(`[PRODUCT] Could not locate "${productRef.name}" on the page to open its detail view`);
    return null;
  }
  try {
    await safe.safeClick(page, nameLocator, logger, { label: `product-card:${productRef.name}` });
  } catch (e) {
    if (e instanceof safe.SafetyBlockedError) throw e;
    logger.warn(`[PRODUCT] Click to open "${productRef.name}" failed: ${e.message}`);
    return null;
  }
  const modal = await safe.pollUntil(page, () => findDetailModal(page), { timeoutMs: 6000, intervalMs: 400 });
  return modal;
}

async function closeProductDetail(page, logger) {
  try {
    const closeBtn = page.locator('[role="dialog"] [aria-label="close" i], [role="dialog"] button[class*="close" i], .MuiDialog-root button[aria-label="Close" i]').first();
    if (await closeBtn.isVisible({ timeout: 500 }).catch(() => false)) {
      await safe.safeClick(page, closeBtn, logger, { label: 'close-product-modal' }).catch((e) => {
        if (e instanceof safe.SafetyBlockedError) throw e;
      });
      return;
    }
  } catch (e) {
    if (e instanceof safe.SafetyBlockedError) throw e;
    /* fall through to Escape */
  }
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);
}

/** Best-effort scan of the open detail modal for descriptive fields. */
async function extractDetailFields(modal) {
  return modal
    .evaluate((root) => {
      const text = (root.innerText || '').replace(/\r/g, '');
      const caloriesMatch = text.match(/(\d{2,4})\s*(k?cal|calories)/i);
      const imgEl = root.querySelector('img');
      const headingEl = root.querySelector('h1, h2, h3, [class*="title" i], [class*="name" i]');
      const descEl = root.querySelector('[class*="description" i], [class*="desc" i], p');
      const soldOut = /(sold out|not available|unavailable|currently unavailable)/i.test(text);

      // Price: look for currency-ish numbers; the first is usually current
      // price, a second lower/struck-through number nearby is the regular
      // (pre-discount) price when a promotion is active.
      const priceEls = Array.from(root.querySelectorAll('[class*="price" i]'));
      const priceTexts = priceEls.map((e) => e.innerText.trim()).filter(Boolean);

      return {
        rawText: text.slice(0, 4000),
        heading: headingEl ? headingEl.innerText.trim() : null,
        description: descEl ? descEl.innerText.trim().slice(0, 500) : null,
        imageUrl: imgEl ? imgEl.currentSrc || imgEl.src : null,
        calories: caloriesMatch ? caloriesMatch[1] : null,
        soldOut,
        priceTexts,
      };
    })
    .catch(() => ({}));
}

/**
 * Scan the modal for option groups: a heading followed by a list of
 * selectable controls (radio/checkbox/stepper buttons). Structure varies a
 * lot across sites, so this looks for repeated visual "blocks" rather than
 * one fixed selector.
 */
async function extractOptionGroups(modal) {
  return modal
    .evaluate(() => {
      function textOf(el) {
        return (el.innerText || '').replace(/\s+/g, ' ').trim();
      }
      const headings = Array.from(
        document.querySelectorAll(
          '[role="dialog"] h1, [role="dialog"] h2, [role="dialog"] h3, [role="dialog"] h4, ' +
            '[role="dialog"] [class*="groupTitle" i], [role="dialog"] [class*="optionTitle" i], ' +
            '[role="dialog"] [class*="section" i] > [class*="title" i]'
        )
      );
      const groups = [];
      headings.forEach((h, idx) => {
        const label = textOf(h);
        if (!label) return;
        // Collect option-looking controls between this heading and the next one.
        let node = h.nextElementSibling;
        const optionEls = [];
        let guard = 0;
        while (node && !headings.includes(node) && guard < 400) {
          optionEls.push(...node.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"], button'));
          node = node.nextElementSibling;
          guard += 1;
        }
        if (!optionEls.length) return;
        const requiredHint = /required|choose\s*\d|select\s*\d|min(imum)?\s*\d/i.test(label + ' ' + (h.parentElement ? textOf(h.parentElement) : ''));
        const minMaxMatch = (h.parentElement ? textOf(h.parentElement) : label).match(/choose\s*(\d+)(?:\s*-\s*(\d+))?/i);
        const options = optionEls
          .map((el) => {
            const t = textOf(el);
            const priceMatch = t.match(/([+-]?\s*\d+(?:\.\d{1,2})?)\s*(?:sar)?$/i);
            return {
              name: t.replace(/[+-]?\s*\d+(?:\.\d{1,2})?\s*(sar)?$/i, '').trim() || t,
              additionalPrice: priceMatch ? parseFloat(priceMatch[1].replace(/\s/g, '')) : 0,
              defaultSelected: !!(el.checked || el.getAttribute('aria-checked') === 'true' || (el.className || '').toString().toLowerCase().includes('selected')),
              disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
            };
          })
          .filter((o) => o.name);
        if (options.length) {
          groups.push({
            groupName: label,
            required: requiredHint,
            minSelections: minMaxMatch ? parseInt(minMaxMatch[1], 10) : requiredHint ? 1 : 0,
            maxSelections: minMaxMatch && minMaxMatch[2] ? parseInt(minMaxMatch[2], 10) : options.length > 1 ? 1 : options.length,
            options,
          });
        }
      });
      return groups;
    })
    .catch(() => []);
}

function findApiEnrichedProduct(dataStore, name) {
  const responses = dataStore._rawMenuApiResponses || [];
  for (const entry of responses) {
    const match = urlUtils.fuzzyFindObjectByName(entry.body, name);
    if (match) return { match, sourceUrl: entry.url };
  }
  return null;
}

/**
 * Select one minimal valid option combination: for every required group,
 * pick the first enabled option; leave optional groups alone. This is the
 * "representative combination" - never every possible combination.
 */
async function selectRepresentativeCombination(modal, groups, logger) {
  for (const group of groups) {
    if (!group.required) continue;
    const enabledOption = (group.options || []).find((o) => !o.disabled);
    if (!enabledOption) {
      logger.warn(`[PRODUCT] Required option group "${group.groupName}" has no available (non-disabled) option`);
      continue;
    }
    try {
      const modalPage = modal.page();
      const optLocator = modal.locator('input[type="radio"], input[type="checkbox"], [role="radio"], button', { hasText: enabledOption.name.slice(0, 30) }).first();
      if (await optLocator.count().catch(() => 0)) {
        await safe.safeClick(modalPage, optLocator, logger, { label: `option:${group.groupName}:${enabledOption.name}` }).catch(() => {});
        await modalPage.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS / 2);
      }
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
      logger.warn(`[PRODUCT] Could not select option "${enabledOption.name}" in group "${group.groupName}": ${e.message}`);
    }
  }
}

/**
 * Crawl a single product: open its detail view, extract everything we can,
 * record product-options rows, and optionally add one representative
 * combination to the cart (options.addToCart).
 */
async function crawlProduct(page, logger, dataStore, productRef, options = {}) {
  const timestamp = new Date().toISOString();
  const productId = productRef.id || `derived-${slugify(productRef.categoryName)}-${slugify(productRef.name)}`;

  const modal = await openProductDetail(page, logger, productRef);
  let fields = {};
  let groups = [];
  if (modal) {
    fields = await extractDetailFields(modal);
    groups = await extractOptionGroups(modal);
  } else {
    logger.tag('PRODUCT', `No detail modal opened for "${productRef.name}" - recording card-level data only`);
  }

  const enriched = findApiEnrichedProduct(dataStore, productRef.name);
  const apiFields = enriched
    ? {
        id: urlUtils.firstByKeyPattern(enriched.match, [/^id$/i, /productid/i, /itemid/i, /sku/i]),
        price: urlUtils.firstByKeyPattern(enriched.match, [/^price$/i, /baseprice/i, /^amount$/i, /regularprice/i]),
        discountedPrice: urlUtils.firstByKeyPattern(enriched.match, [/discountedprice/i, /saleprice/i, /offerprice/i, /promoprice/i]),
        calories: urlUtils.firstByKeyPattern(enriched.match, [/calor/i, /kcal/i, /energy/i]),
        description: urlUtils.firstByKeyPattern(enriched.match, [/description/i, /^desc$/i]),
        imageUrl: urlUtils.firstByKeyPattern(enriched.match, [/imageurl/i, /^image$/i, /imagepath/i, /thumbnail/i]),
        availability: urlUtils.firstByKeyPattern(enriched.match, [/available/i, /instock/i, /isactive/i]),
      }
    : null;

  const regularPrice = apiFields && apiFields.price != null ? Number(apiFields.price) : parsePrice(productRef.priceText) ?? parsePrice((fields.priceTexts || [])[0]);
  const discountedPrice = apiFields && apiFields.discountedPrice != null ? Number(apiFields.discountedPrice) : parsePrice((fields.priceTexts || [])[1]);

  const productRecord = {
    productName: fields.heading || productRef.name,
    productId: apiFields && apiFields.id != null ? String(apiFields.id) : productId,
    category: productRef.categoryName || null,
    description: (apiFields && apiFields.description) || fields.description || null,
    regularPrice: Number.isFinite(regularPrice) ? regularPrice : null,
    discountedPrice: Number.isFinite(discountedPrice) ? discountedPrice : null,
    currency: CURRENCY,
    imageUrl: (apiFields && apiFields.imageUrl) || fields.imageUrl || productRef.imageUrl || null,
    availability: apiFields && apiFields.availability != null ? !!apiFields.availability : !(fields.soldOut || productRef.soldOut),
    calories: (apiFields && apiFields.calories) || fields.calories || null,
    productUrl: page.url(),
    apiEndpointSource: enriched ? enriched.sourceUrl : dataStore._lastMenuApiUrl || null,
    extractionTimestamp: timestamp,
  };
  dataStore.menuProducts.push(productRecord);

  groups.forEach((group, gIdx) => {
    const groupId = `${productRecord.productId}-group-${gIdx}`;
    (group.options || []).forEach((opt, oIdx) => {
      dataStore.productOptions.push({
        productId: productRecord.productId,
        optionGroupName: group.groupName,
        optionGroupId: groupId,
        requiredOrOptional: group.required ? 'required' : 'optional',
        minSelections: group.minSelections,
        maxSelections: group.maxSelections,
        optionName: opt.name,
        optionId: `${groupId}-opt-${oIdx}`,
        additionalPrice: opt.additionalPrice || 0,
        defaultSelection: !!opt.defaultSelected,
        availability: !opt.disabled,
      });
    });
  });

  logger.tag(
    'PRODUCT',
    `Extracted "${productRecord.productName}" (category=${productRecord.category || 'n/a'}, price=${productRecord.regularPrice ?? 'n/a'}, options groups=${groups.length})`
  );

  let addedToCart = false;
  if (modal && options.addToCart && productRecord.availability !== false) {
    try {
      await selectRepresentativeCombination(modal, groups, logger);
      const addBtn = modal.locator('button', { hasText: /add to cart/i }).first();
      if (await addBtn.count().catch(() => 0)) {
        await safe.safeClick(page, addBtn, logger, { label: `add-to-cart:${productRecord.productName}` });
        addedToCart = true;
        logger.success(`[CART] Added representative product to cart: ${productRecord.productName}`);
        await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
      } else {
        logger.warn(`[PRODUCT] No "ADD TO CART" control found inside detail modal for "${productRecord.productName}"`);
      }
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
      logger.warn(`[PRODUCT] Could not add "${productRecord.productName}" to cart: ${e.message}`);
    }
  }

  if (modal && !addedToCart) {
    await closeProductDetail(page, logger);
  }

  return { product: productRecord, optionGroups: groups, addedToCart };
}

module.exports = {
  crawlProduct,
  openProductDetail,
  closeProductDetail,
  extractDetailFields,
  extractOptionGroups,
  parsePrice,
};
