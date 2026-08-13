'use strict';

/**
 * menu-crawler.js
 * ---------------------------------------------------------------------
 * Discovers menu categories, opens every one (up to MAX_CATEGORIES),
 * collects every product card (up to MAX_PRODUCTS), and delegates
 * per-product detail extraction to product-crawler.js. Exactly one
 * eligible product across the whole run is flagged to actually be added
 * to the cart (the "representative combination" from the spec) - every
 * other product is read-only DOM/API extraction.
 * ---------------------------------------------------------------------
 */

const CONFIG = require('../collector/config');
const safe = require('../collector/safe-actions');
const productCrawler = require('./product-crawler');

async function navigateToMenu(page, logger) {
  const strategies = [
    () => page.getByRole('link', { name: /explore.*menu/i }).first(),
    () => page.locator('button, a', { hasText: /explore.*menu/i }).first(),
    () => page.getByRole('link', { name: /^menu$/i }).first(),
    () => page.locator('a', { hasText: /^menu$/i }).first(),
  ];
  for (const build of strategies) {
    try {
      const locator = build();
      if ((await locator.count().catch(() => 0)) === 0) continue;
      await safe.safeClick(page, locator, logger, { label: 'nav:menu' });
      return true;
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
      // try next strategy
    }
  }
  return false;
}

async function collectCategories(page) {
  return page
    .evaluate(() => {
      function text(el) {
        return (el.innerText || '').replace(/\s+/g, ' ').trim();
      }
      const seen = new Set();
      const out = [];
      // Excludes both generic UI chrome AND the header's order-mode tabs
      // (Delivery / Self-Pickup / Drive-Thru / Carhop / Dine-In), which
      // also carry role="tab" and would otherwise be mistaken for menu
      // categories.
      const skip = /^(login|explore menu|add to cart|change|continue|confirm location|عربي|delivery|self-pickup|drive-thru|carhop|dine-in)$/i;
      const candidateSelectors = [
        '[role="tablist"] [role="tab"]',
        '[class*="categ" i] button',
        '[class*="categ" i] a',
        '[class*="Categ" i]',
        'nav [role="tab"]',
      ];
      for (const sel of candidateSelectors) {
        document.querySelectorAll(sel).forEach((el) => {
          const t = text(el);
          if (!t || t.length > 60 || skip.test(t) || seen.has(t.toLowerCase())) return;
          seen.add(t.toLowerCase());
          out.push(t);
        });
        if (out.length) break; // stop at the first selector family that actually yields results
      }
      return out;
    })
    .catch(() => []);
}

async function collectProductCards(page) {
  return page
    .evaluate(() => {
      const addButtons = Array.from(document.querySelectorAll('button')).filter((b) => /add to cart/i.test(b.innerText || ''));
      const cards = [];
      const seenNames = new Set();
      for (const btn of addButtons) {
        // Climb one ancestor at a time and stop at the SMALLEST ancestor
        // that both contains a name-like heading and is small enough to be
        // a single product card (not an entire "Top Deals" section that
        // happens to contain several cards plus its own heading).
        let card = btn;
        let nameEl = null;
        for (let i = 0; i < 8 && card.parentElement; i++) {
          card = card.parentElement;
          const candidate = card.querySelector('h1,h2,h3,h4,h5,h6,[class*="name" i],[class*="title" i]');
          const len = (card.innerText || '').length;
          if (candidate && len > 0 && len < 400) {
            nameEl = candidate;
            break;
          }
        }
        const cardText = (card.innerText || '').replace(/\s+/g, ' ').trim();
        const name = ((nameEl ? nameEl.innerText : cardText.split('\n')[0]) || '').trim();
        if (!name || seenNames.has(name)) continue;
        seenNames.add(name);
        const priceMatch = cardText.match(/(\d+(?:\.\d{1,2})?)/);
        const img = card.querySelector('img');
        cards.push({
          name,
          priceText: priceMatch ? priceMatch[1] : null,
          customisable: /customisable/i.test(cardText),
          soldOut: /(sold out|not available|unavailable)/i.test(cardText),
          imageUrl: img ? img.currentSrc || img.src : null,
        });
      }
      return cards;
    })
    .catch(() => []);
}

async function crawlMenu(page, context, logger, dataStore, robots) {
  logger.section('MENU CRAWL');
  await safe.dismissOverlays(page, logger);

  // robots.txt disallows *cart* on this site; RESPECT_ROBOTS_TXT=true
  // (default) means we must not click "Add to Cart" at all here, not just
  // skip cart-flow.js's own exploration later - the add-to-cart request
  // itself is a cart interaction, and it happens during this pass.
  const cartBlocked = !!(robots && robots.respect && robots.blocksCart);
  if (cartBlocked) {
    logger.warn('[SAFETY] robots.txt disallows cart-related paths - no product will be added to the cart this run (menu/product extraction is unaffected)');
  }

  const navigated = await navigateToMenu(page, logger);
  if (navigated) {
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
  } else {
    logger.tag('CATEGORY', 'No explicit "menu" navigation control found - assuming the menu/products are already visible on this page');
  }

  await safe.scrollGradually(page, 4, 300);

  let categories = await collectCategories(page);
  if (!categories.length) {
    logger.warn('[CATEGORY] No category tabs/list discovered - treating the page as a single implicit category');
    categories = ['All Items'];
  }
  categories = categories.slice(0, CONFIG.MAX_CATEGORIES);
  logger.tag('CATEGORY', `Discovered ${categories.length} categor${categories.length === 1 ? 'y' : 'ies'}`);

  let productCount = 0;
  let representativeChosen = false;

  for (let i = 0; i < categories.length; i++) {
    const categoryName = categories[i];
    logger.tag('CATEGORY', `[CATEGORY ${i + 1}/${categories.length}] ${categoryName}`);

    if (categoryName !== 'All Items') {
      try {
        const catLocator = page.getByText(categoryName, { exact: false }).first();
        await safe.safeClick(page, catLocator, logger, { label: `category:${categoryName}` });
        await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
      } catch (e) {
        if (e instanceof safe.SafetyBlockedError) throw e;
        logger.warn(`[CATEGORY] Could not click category "${categoryName}": ${e.message}`);
      }
    }

    await safe.scrollGradually(page, 3, 300);
    const cards = await collectProductCards(page);
    dataStore.menuCategories.push({
      id: `cat-${i}`,
      name: categoryName,
      url: page.url(),
      productCount: cards.length,
      timestamp: new Date().toISOString(),
    });
    logger.tag('CATEGORY', `Found ${cards.length} product card(s) in "${categoryName}"`);

    for (let p = 0; p < cards.length; p++) {
      if (productCount >= CONFIG.MAX_PRODUCTS) {
        logger.warn(`[PRODUCT] Reached MAX_PRODUCTS (${CONFIG.MAX_PRODUCTS}) - stopping product extraction`);
        break;
      }
      const card = cards[p];
      productCount += 1;
      logger.tag('PRODUCT', `[PRODUCT ${productCount}] ${card.name}`);

      try {
        const eligibleForCart = !cartBlocked && !representativeChosen && !card.soldOut;
        const result = await productCrawler.crawlProduct(page, logger, dataStore, { ...card, categoryName }, { addToCart: eligibleForCart });
        if (result.addedToCart) {
          representativeChosen = true;
          dataStore.cartState.representativeProduct = result.product;
        }
      } catch (e) {
        if (e instanceof safe.SafetyBlockedError) throw e;
        logger.error(`[PRODUCT] Failed to crawl "${card.name}": ${e.message}`);
      }

      await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
    }

    if (productCount >= CONFIG.MAX_PRODUCTS) break;
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
  }

  logger.success(`[CATEGORY] Menu crawl complete: ${categories.length} categories, ${productCount} products recorded`);
  return { categories: categories.length, products: productCount, representativeChosen };
}

module.exports = { crawlMenu, navigateToMenu, collectCategories, collectProductCards };
