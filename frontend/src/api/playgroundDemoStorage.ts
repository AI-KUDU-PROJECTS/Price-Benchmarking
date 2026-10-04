import type {
  Brand,
  Channel,
  MappingCompetitor,
  MappingProduct,
  PriceMapping,
  PriceMappingList,
  PriceMappingWrite,
  Product,
} from "./types";

export const PLAYGROUND_DEMO_STORAGE_KEY = "kudu-price-benchmark.playground-demo.v1";

interface StoredProductReference {
  brandId: string;
  brandNameSnapshot: string;
  productId: string;
  productNameSnapshot: string;
}

interface StoredMapping {
  id: string;
  name: string;
  channel: Channel;
  kuduItem: StoredProductReference;
  competitorItems: StoredProductReference[];
  createdAt: string;
  updatedAt: string;
}

interface StoredDocument {
  version: 1;
  items: StoredMapping[];
}

interface DemoStorageDependencies {
  storage: Storage;
  loadBrands: () => Promise<Brand[]>;
  loadProduct: (brandId: string, productId: string) => Promise<Product | null>;
  now?: () => Date;
  randomId?: () => string;
}

function emptyDocument(): StoredDocument {
  return { version: 1, items: [] };
}

function readDocument(storage: Storage): StoredDocument {
  const value = storage.getItem(PLAYGROUND_DEMO_STORAGE_KEY);
  if (!value) return emptyDocument();

  try {
    const parsed = JSON.parse(value) as Partial<StoredDocument>;
    if (parsed.version !== 1 || !Array.isArray(parsed.items)) return emptyDocument();
    return { version: 1, items: parsed.items as StoredMapping[] };
  } catch {
    return emptyDocument();
  }
}

function writeDocument(storage: Storage, document: StoredDocument): void {
  try {
    storage.setItem(PLAYGROUND_DEMO_STORAGE_KEY, JSON.stringify(document));
  } catch {
    throw new Error("This browser could not save the demo mapping. Check browser storage settings and try again.");
  }
}

function productName(product: Product): string {
  return product.nameEn || product.nameAr || product.id;
}

function effectivePrice(product: Product): number | null {
  return product.specialPrice ?? product.regularPrice;
}

function mappingProduct(
  reference: StoredProductReference,
  product: Product | null,
  channel: Channel,
): MappingProduct {
  if (!product || product.channel !== channel) {
    return {
      brandId: reference.brandId,
      brandName: reference.brandNameSnapshot,
      productId: reference.productId,
      nameAr: null,
      nameEn: reference.productNameSnapshot,
      category: null,
      imageUrl: null,
      effectivePrice: null,
      currency: null,
      missing: true,
    };
  }

  return {
    brandId: reference.brandId,
    brandName: reference.brandNameSnapshot,
    productId: reference.productId,
    nameAr: product.nameAr,
    nameEn: product.nameEn,
    category: product.category,
    imageUrl: product.imageUrl,
    effectivePrice: effectivePrice(product),
    currency: product.currency,
    missing: false,
  };
}

function competitorProduct(
  product: MappingProduct,
  kudu: MappingProduct,
): MappingCompetitor {
  let differenceAmount: number | null = null;
  let differencePercentage: number | null = null;
  let pricePosition: MappingCompetitor["pricePosition"] = "unavailable";

  if (
    !kudu.missing
    && !product.missing
    && kudu.effectivePrice !== null
    && product.effectivePrice !== null
    && Boolean(kudu.currency)
    && kudu.currency === product.currency
  ) {
    differenceAmount = Math.round((product.effectivePrice - kudu.effectivePrice) * 100) / 100;
    if (kudu.effectivePrice !== 0) {
      differencePercentage = Math.round((differenceAmount / kudu.effectivePrice) * 10000) / 100;
    }
    pricePosition = differenceAmount > 0 ? "higher" : differenceAmount < 0 ? "lower" : "equal";
  }

  return {
    ...product,
    differenceAmount,
    differencePercentage,
    pricePosition,
  };
}

function validationError(message: string): Error {
  return new Error(message);
}

export function createPlaygroundDemoApi({
  storage,
  loadBrands,
  loadProduct,
  now = () => new Date(),
  randomId = () => crypto.randomUUID(),
}: DemoStorageDependencies) {
  async function hydrate(stored: StoredMapping): Promise<PriceMapping> {
    const [kuduProduct, ...competitorProducts] = await Promise.all([
      loadProduct(stored.kuduItem.brandId, stored.kuduItem.productId),
      ...stored.competitorItems.map((item) => loadProduct(item.brandId, item.productId)),
    ]);
    const kuduItem = mappingProduct(stored.kuduItem, kuduProduct, stored.channel);
    const competitors = stored.competitorItems.map((item, index) =>
      competitorProduct(mappingProduct(item, competitorProducts[index], stored.channel), kuduItem),
    );

    return {
      id: stored.id,
      name: stored.name,
      channel: stored.channel,
      kuduItem,
      competitorItems: competitors,
      createdAt: stored.createdAt,
      updatedAt: stored.updatedAt,
    };
  }

  async function validatedRecord(
    payload: PriceMappingWrite,
    existing?: StoredMapping,
  ): Promise<StoredMapping> {
    const name = payload.name.trim();
    if (!name) throw validationError("Mapping name cannot be blank.");
    if (payload.competitorItems.length === 0) {
      throw validationError("Select at least one competitor item.");
    }

    const duplicateKeys = new Set<string>();
    for (const item of payload.competitorItems) {
      if (item.brandId === "kudu") {
        throw validationError("KUDU cannot be selected as a competitor.");
      }
      const key = `${item.brandId}::${item.productId}`;
      if (duplicateKeys.has(key)) {
        throw validationError("The same competitor item was selected more than once.");
      }
      duplicateKeys.add(key);
    }

    const [brands, kuduProduct, ...competitorProducts] = await Promise.all([
      loadBrands(),
      loadProduct("kudu", payload.kuduProductId),
      ...payload.competitorItems.map((item) => loadProduct(item.brandId, item.productId)),
    ]);
    if (!kuduProduct || kuduProduct.channel !== payload.channel) {
      throw validationError("The selected KUDU item does not exist in this channel.");
    }
    const kuduPrice = effectivePrice(kuduProduct);
    if (kuduPrice === null || !kuduProduct.currency) {
      throw validationError("The selected KUDU item does not have a comparable price.");
    }

    const brandNames = new Map(brands.map((brand) => [brand.id, brand.name]));
    const competitors = payload.competitorItems.map((selection, index): StoredProductReference => {
      const product = competitorProducts[index];
      if (!product || product.brandId !== selection.brandId || product.channel !== payload.channel) {
        throw validationError("The selected competitor item does not exist in this channel.");
      }
      const price = effectivePrice(product);
      if (price === null || !product.currency) {
        throw validationError("The selected competitor item does not have a comparable price.");
      }
      if (product.currency !== kuduProduct.currency) {
        throw validationError("The selected item uses a different currency from the KUDU item.");
      }
      return {
        brandId: selection.brandId,
        brandNameSnapshot: brandNames.get(selection.brandId) || selection.brandId,
        productId: selection.productId,
        productNameSnapshot: productName(product),
      };
    });

    const timestamp = now().toISOString();
    return {
      id: existing?.id || randomId(),
      name,
      channel: payload.channel,
      kuduItem: {
        brandId: "kudu",
        brandNameSnapshot: brandNames.get("kudu") || "KUDU",
        productId: kuduProduct.id,
        productNameSnapshot: productName(kuduProduct),
      },
      competitorItems: competitors,
      createdAt: existing?.createdAt || timestamp,
      updatedAt: timestamp,
    };
  }

  return {
    async list(): Promise<PriceMappingList> {
      const document = readDocument(storage);
      const items = await Promise.all(
        [...document.items]
          .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
          .map(hydrate),
      );
      return { items };
    },

    async get(id: string): Promise<PriceMapping | null> {
      const stored = readDocument(storage).items.find((item) => item.id === id);
      return stored ? hydrate(stored) : null;
    },

    async create(payload: PriceMappingWrite): Promise<PriceMapping> {
      const document = readDocument(storage);
      const stored = await validatedRecord(payload);
      writeDocument(storage, { ...document, items: [stored, ...document.items] });
      return hydrate(stored);
    },

    async update(id: string, payload: PriceMappingWrite): Promise<PriceMapping | null> {
      const document = readDocument(storage);
      const index = document.items.findIndex((item) => item.id === id);
      if (index < 0) return null;
      const stored = await validatedRecord(payload, document.items[index]);
      const items = [...document.items];
      items[index] = stored;
      writeDocument(storage, { ...document, items });
      return hydrate(stored);
    },

    async delete(id: string): Promise<boolean> {
      const document = readDocument(storage);
      const items = document.items.filter((item) => item.id !== id);
      if (items.length === document.items.length) return false;
      writeDocument(storage, { ...document, items });
      return true;
    },
  };
}
