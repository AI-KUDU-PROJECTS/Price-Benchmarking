"""Group channel prices conservatively and order complete menus before paging."""
from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata

from bff.contract import MenuRow, Product

CHANNEL_ORDER = {"pickup": 0, "delivery": 1, "hungerstation": 2}


def _text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = "".join(c for c in value if not unicodedata.combining(c) and c != "ـ")
    value = value.translate(str.maketrans("أإآىة", "ااايه"))
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def _name_key(value: str | None) -> str:
    # Preserve numbers, sizes, meal words and '+'; never use fuzzy image matches.
    return _text((value or "").replace("+", " plus ").replace("&", " and ")).replace(" ", "")


def _names(product: Product) -> set[str]:
    return {key for name in (product.name_en, product.name_ar) if (key := _name_key(name))}


def _variant(product: Product) -> tuple:
    """A shared translated name must not erase explicit size/quantity differences."""
    name = _text(f"{product.name_en or ''} {product.name_ar or ''}")
    sizes = tuple(label for label, pattern in (
        ("small", r"\b(small|صغير|صغيره)\b"),
        ("medium", r"\b(medium|متوسط|متوسطه)\b"),
        ("large", r"\b(large|كبير|كبيره)\b"),
        ("xl", r"\b(xl|extra large|اكسترا لارج)\b"),
    ) if re.search(pattern, name))
    quantities = tuple(sorted(set(re.findall(r"\d+", name))))
    meal = bool(re.search(r"\b(meals?|combos?|وجبه|وجبات|كومبو)\b", name))
    return sizes, quantities, meal


_MAIN = re.compile(
    r"\b(meals?|combos?|sandwich(?:es)?|burgers?|wraps?|buckets?|boxes|box|bundles?|"
    r"breakfast|tortilla|fillets?|strips|nuggets|wings|shrimp|وجبه|وجبات|"
    r"ساندوتش|ساندويتش|ساندويش|برجر|كومبو|بوكس|روبيان)\b"
)
_MEAL = re.compile(r"\b(meals?|combos?|buckets?|boxes|box|bundles?|وجبه|وجبات|كومبو|بوكس)\b")
_DRINK = re.compile(
    r"\b(drinks?|beverages?|juice|water|pepsi|coca\s*cola|coke|sprite|fanta|"
    r"7\s*up|7up|mirinda|mountain\s*dew|coffee|americano|cappuccino|latte|mocha|"
    r"espresso|macchiato|mochaccino|frappe|karak|hot\s*chocolate|iced\s*spanish|"
    r"tea|milk|milkshake|milk\s*shake|lemonade|mojito|smoothie|"
    r"مشروبات|مشروب|عصير|عصيرات|عصائر|ماء|مياه|بيبسي|كولا|سبرايت|فانتا|"
    r"سفن|ميرندا|قهوه|شاي|حليب|لاتيه|موكا|كابتشينو)\b"
)
_SAUCE = re.compile(r"\b(sauces?|dips?|dipping|ketchup|mayonnaise|mayo|mustard|sprinkles?|dressing|صوص|صوصات|صلصه|صلصات|كاتشب|مايونيز)\b")
_DESSERT = re.compile(r"\b(desserts?|ice\s*cream|sundae|cake|brownie|cookies?|donuts?|doughnuts?|churros|mc\s*flurry|sweet\s*treats|حلويات|حلي|كيك|ايس\s*كريم)\b")
_SIDE = re.compile(r"\b(sides?|fries|salads?|hash\s*brown|coleslaw|بطاطس|سلطه|سلطات|جانبيه|اضافات)\b")


def menu_section(product: Product) -> int:
    """Mains, sides, desserts, sauces, then drinks (including generic HS menus)."""
    name = _text(f"{product.name_en or ''} {product.name_ar or ''}")
    category = _text(f"{product.category or ''} {product.category_ar or ''}")
    # A meal containing a drink/sauce stays with the main dishes.
    if _MEAL.search(name) or (_MAIN.search(name) and not _DESSERT.search(name)):
        return 0
    if _DESSERT.search(name):
        return 2
    if _DRINK.search(name):
        return 4
    if _SAUCE.search(name):
        return 3
    if _SIDE.search(name):
        return 1
    if _DESSERT.search(category):
        return 2
    if _DRINK.search(category):
        return 4
    if _SAUCE.search(category):
        return 3
    if _SIDE.search(category):
        return 1
    return 0


def menu_sort_key(product: Product) -> tuple:
    return (menu_section(product), _text(product.category),
            _text(product.name_en or product.name_ar), product.id)


def _identity(product: Product) -> tuple[str, str] | None:
    if product.brand_id == "kudu":
        # The KUDU integration uses the same item IDs as the production catalog.
        return (product.brand_id, product.source_id) if product.source_id else None
    if product.channel == "hungerstation":
        return None  # Aggregator IDs are a different namespace.
    parts = product.source_id.split("|")
    if product.channel.upper() in parts:
        return product.brand_id, "|".join(p for p in parts if p != product.channel.upper())
    return None


def menu_rows(products: list[Product], *, compare: bool = True) -> list[MenuRow]:
    """Use shared source IDs or unambiguous exact English/Arabic names.

    At most one product per channel may occupy a row. Ambiguous names and
    unmatched variants retain their own rows, with other prices left unknown.
    Matching always sees the complete menu, before search or pagination.
    """
    if not compare:
        return [MenuRow(id=p.id, product=p, channels={p.channel: p})
                for p in sorted(products, key=menu_sort_key)]

    rows: list[MenuRow] = []
    identities: dict[tuple, set[int]] = defaultdict(set)
    names: dict[tuple, set[int]] = defaultdict(set)
    counts = Counter((p.brand_id, p.channel, name) for p in products for name in _names(p))
    ordered = sorted(products, key=lambda p: (CHANNEL_ORDER[p.channel], p.id))
    for product in ordered:
        identity = _identity(product)
        candidates = identities.get(identity, set()) if identity else set()
        by_identity = bool(candidates)
        if not candidates:
            candidates = set().union(*(
                names.get((product.brand_id, name), set())
                for name in _names(product)
                if counts[product.brand_id, product.channel, name] == 1
            ))
        match = next(iter(candidates)) if len(candidates) == 1 else None
        if match is not None and not by_identity and any(
            _variant(other) != _variant(product) for other in rows[match].channels.values()
        ):
            match = None
        if match is not None and product.channel not in rows[match].channels:
            row = rows[match]
            row.channels[product.channel] = product
        else:
            match = len(rows)
            row = MenuRow(id=product.id, product=product, channels={product.channel: product})
            rows.append(row)
        if identity:
            identities[identity].add(match)
        for name in _names(product):
            names[product.brand_id, name].add(match)

    return sorted(rows, key=lambda row: menu_sort_key(row.product))
