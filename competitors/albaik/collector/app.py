"""Read the official ALBAIK app's visible menu; never add items to an order."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import signal
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageStat

from competitors.albaik import app_config as config
from competitors.albaik.backend.app_store import save_failure, save_success
from competitors.hungerstation.collector import AndroidDevice, CollectionFailure, find_adb, utc_now
from competitors.hungerstation.emulator_lifecycle import emulator_session


def bounds(node: ET.Element) -> tuple[int, int, int, int]:
    return tuple(map(int, re.findall(r"-?\d+", node.get("bounds", "[0,0][0,0]"))))


def label(node: ET.Element) -> str:
    return node.get("content-desc") or node.get("text", "")


def identity(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:75]
    return f"{slug}-{hashlib.sha256(name.casefold().encode()).hexdigest()[:10]}"


def parse_detail(root: ET.Element, name: str) -> dict:
    texts = [n for n in root.iter("node") if n.get("class") == "android.widget.TextView" and n.get("text")]
    title = next((n for n in texts if n.get("text") == name), None)
    if title is None:
        raise CollectionFailure("PRODUCT_NOT_VISIBLE", f"Could not verify the detail page for {name}.")
    y = bounds(title)[1]
    price = next((n.get("text", "") for n in texts if abs(bounds(n)[1] - y) < 100
                  and re.search(r"(?:﷼|SAR|ر\.س)", n.get("text", ""))), None)
    if price is None:
        raise CollectionFailure("PRICE_MISSING", f"No displayed price for {name}.")
    match = re.search(r"\d+(?:[.,]\d+)?", price)
    if not match:
        raise CollectionFailure("PRICE_MISSING", f"Unreadable price for {name}.")
    description = next((n.get("text") for n in texts if bounds(n)[1] > bounds(title)[3]
                        and bounds(n)[1] < bounds(title)[3] + 160 and n.get("text") != "1"), "")
    calories = next((re.search(r"([\d.,]+)\s*kcal", n.get("text", "")) for n in texts
                     if re.search(r"^[\d.,]+\s*kcal", n.get("text", ""))), None)
    return {"price": float(match.group().replace(",", ".")), "description": description,
            "calories": calories.group(1).replace(",", "") if calories else None}


def observed_title(root: ET.Element) -> str | None:
    """The app changes the actual title when its Spicy toggle changes."""
    texts = [n for n in root.iter("node") if n.get("class") == "android.widget.TextView" and n.get("text")]
    order = next((n for n in root.iter("node") if n.get("resource-id") == "Add to order"), None)
    if order is None:
        return None
    price = next((n for n in texts if bounds(n)[1] < bounds(order)[1]
                  and re.search(r"(?:﷼|SAR|ر\.س)", n.get("text", ""))), None)
    if price is None:
        return None
    title = next((n for n in texts if bounds(n)[0] < bounds(price)[0]
                  and abs(bounds(n)[1] - bounds(price)[1]) < 100), None)
    return title.get("text") if title is not None else None


def size_controls(root: ET.Element) -> dict[str, ET.Element]:
    return {label(n).strip().removesuffix(" size"): n for n in root.iter("node")
            if n.get("class")=="android.view.ViewGroup"
            and re.fullmatch(r"(?:Large|Medium|Small) size\s*",label(n))}


def detail_header_bottom(root: ET.Element) -> int:
    """The pinned product header can cover controls still present in XML."""
    parents={child:parent for parent in root.iter() for child in parent}
    order=next((n for n in root.iter("node") if n.get("resource-id")=="Add to order"),None)
    if order is None:
        return 0
    parent=parents.get(order)
    return max(bounds(order)[3],bounds(parent)[3] if parent is not None else 0)


def product_cards(root: ET.Element, category_bottom: int, height: int) -> list[ET.Element]:
    result = []
    for n in root.iter("node"):
        x1, y1, x2, y2 = bounds(n)
        if (n.get("clickable") == "true" and n.get("content-desc") and not n.get("resource-id")
                and label(n) not in {"FOR YOU", "View All"} and x2 - x1 > 200
                and y2 - max(y1, category_bottom) > 120 and y1 < height - 180
                and any(c.get("class") == "android.widget.ImageView" for c in n.iter("node"))
                and not any(c.get("resource-id") == "item-list-text" for c in n.iter("node"))):
            result.append(n)
    return result


def cache_image(device: AndroidDevice, root: ET.Element, name: str, directory: Path) -> tuple[str, bool]:
    filename = f"{identity(name)}.jpg"
    path = directory / filename
    # This check deliberately precedes screencap: existing products never re-fetch their photo.
    if path.is_file() and path.stat().st_size > 0:
        return f"/albaik-app-images/{filename}", False
    images = [n for n in root.iter("node") if n.get("class") == "android.widget.ImageView"]
    if not images:
        raise CollectionFailure("IMAGE_MISSING", f"No product image for {name}.")
    box = max((bounds(n) for n in images), key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
    width, height = device.screen_size()
    box = (box[0], max(box[1], int(height * .11)), box[2], box[3])
    if box[2]-box[0] < width * .8 or box[3]-box[1] < height * .25:
        raise CollectionFailure("IMAGE_MISSING", f"Product image was not fully visible for {name}.")
    for _ in range(3):
        picture = Image.open(io.BytesIO(device.screenshot())).convert("RGB").crop(box)
        if max(ImageStat.Stat(picture).stddev) > 8:
            directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            picture.thumbnail((1000, 1200))
            picture.save(temporary, format="JPEG", quality=90)
            temporary.replace(path)
            return f"/albaik-app-images/{filename}", True
        time.sleep(1)
    raise CollectionFailure("IMAGE_MISSING", f"Product photo did not load for {name}.")


class AlbaikDevice(AndroidDevice):
    def dump(self) -> str:
        target = "/data/local/tmp/albaik-collection.xml"
        for _ in range(4):
            self.run("shell", "rm", "-f", target)
            try:
                output = self.run("shell", "timeout", "15", "uiautomator", "dump", target, attempts=1)
            except subprocess.SubprocessError:
                time.sleep(1)
                continue
            if "dumped to" in output:
                value = self.run("exec-out", "cat", target)
                try:
                    ET.fromstring(value)
                    return value
                except ET.ParseError:
                    pass
            time.sleep(1)
        raise CollectionFailure("UI_UNAVAILABLE", "The app did not provide a complete screen.")

    def start_app(self) -> None:
        self.wait_until_ready()
        # Boot-complete precedes Android's usable network, especially on a cold boot.
        # Starting ALBAIK earlier can leave its modal/loading screen stuck indefinitely.
        self.run("shell", "svc", "wifi", "enable")
        for _ in range(30):
            connectivity = self.run("shell", "dumpsys", "connectivity")
            if any("NetworkAgentInfo{" in line and "&VALIDATED" in line for line in connectivity.splitlines()):
                break
            time.sleep(2)
        else:
            raise CollectionFailure("NETWORK_UNAVAILABLE", "The emulator has no validated Internet connection.")
        time.sleep(5)
        if not self.run("shell", "pm", "path", config.PACKAGE).strip():
            raise CollectionFailure("APP_NOT_INSTALLED", "Install the official ALBAIK app from Google Play first.")
        if not self.run("shell", "pm", "path", "io.appium.settings").strip():
            raise CollectionFailure("LOCATION_HELPER_MISSING", "The emulator location helper is not installed.")
        self.run("shell", "appops", "set", "io.appium.settings", "android:mock_location", "allow")
        for package in ("io.appium.settings", config.PACKAGE):
            for permission in ("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"):
                self.run("shell", "pm", "grant", package, f"android.permission.{permission}")
        self.run("shell", "cmd", "alarm", "set-timezone", "Asia/Riyadh")
        self.run("emu", "geo", "fix", str(config.LONGITUDE), str(config.LATITUDE))
        self.run("shell", "am", "start-foreground-service", "-n", "io.appium.settings/.LocationService",
                 "--es", "longitude", str(config.LONGITUDE), "--es", "latitude", str(config.LATITUDE))
        self.run("shell", "am", "force-stop", config.PACKAGE)
        self.run("shell", "am", "start", "-n", config.ACTIVITY)
        time.sleep(5)


class Collector:
    def __init__(self, device: AlbaikDevice, channel: str, evidence: Path):
        self.device, self.channel, self.evidence = device, channel, evidence
        self.width, self.height = device.screen_size()
        self.sequence = 0
        self.images_new = 0
        self.items: dict[str, dict] = {}
        self.products_seen: set[str] = set()
        self.excluded_products: set[str] = set()
        self.unreadable_products: dict[str,str] = {}
        self.categories: list[str] = []
        self.resume_source: str | None = None
        self.evidence.mkdir(parents=True, exist_ok=True)

    def restore_progress(self, path: Path) -> None:
        """Resume recent observations only for the identical channel/location."""
        data=json.loads(path.read_text(encoding="utf-8"))
        if (data.get("complete") is not False or data.get("channel")!=self.channel
                or data.get("latitude")!=config.LATITUDE or data.get("longitude")!=config.LONGITUDE
                or time.time()-path.stat().st_mtime>3600):
            raise CollectionFailure("INVALID_PROGRESS","Progress must be less than one hour old and match the selected channel and location.")
        items=data.get("items",[])
        if not isinstance(items,list) or any(not p.get("id") or not p.get("base_name") for p in items):
            raise CollectionFailure("INVALID_PROGRESS","Progress does not contain valid product identities.")
        self.items={p["id"]:p for p in items if p["base_name"] not in config.EXCLUDED_PRODUCTS.get(self.channel,())}
        self.products_seen={p["base_name"] for p in self.items.values()}
        self.resume_source=str(path.resolve())
        print(f"ALBAIK_RESUMED channel={self.channel} products={len(self.items)}",flush=True)
        if self.channel in config.SKIP_UNREADABLE_CHANNELS:
            self.unreadable_products=dict(data.get("unreadable_products",{}))
            for name in self.unreadable_products:
                print(f"ALBAIK_SKIPPED channel={self.channel} reason=load-failed product={name}",flush=True)

    def screen(self, purpose: str = "screen") -> ET.Element:
        xml = self.device.dump()
        self.sequence += 1
        (self.evidence / f"{self.sequence:04d}-{purpose}.xml").write_text(xml, encoding="utf-8")
        return ET.fromstring(xml)

    def tap(self, node: ET.Element) -> None:
        x1,y1,x2,y2 = bounds(node)
        if x2 <= x1 or y2 <= y1:
            raise CollectionFailure("CONTROL_NOT_VISIBLE", f"The {label(node)} control is not visible.")
        self.device.tap((x1+x2)//2, (y1+y2)//2)

    def find(self, root: ET.Element, text: str, *, prefix: bool = False) -> ET.Element | None:
        return next((n for n in root.iter("node") if n.get("clickable") == "true"
                     and (label(n).startswith(text) if prefix else label(n) == text)), None)

    def wait(self, predicate, purpose: str, attempts: int = 12) -> ET.Element:
        recovered_anr = False
        for _ in range(attempts):
            root = self.screen(purpose)
            if any("isn't responding" in label(n) for n in root.iter("node")):
                wait_button = self.find(root, "Wait")
                if wait_button is not None and not recovered_anr:
                    self.tap(wait_button)
                    recovered_anr = True
                    continue
                raise CollectionFailure("APP_NOT_RESPONDING", "The ALBAIK app is not responding.")
            got_it = self.find(root, "Got it")
            if got_it is not None:
                self.tap(got_it)
                continue
            if any("Internet connection is not available" in label(n) for n in root.iter("node")):
                raise CollectionFailure("NETWORK_UNAVAILABLE", "The ALBAIK app reports that its Internet connection is unavailable.")
            if predicate(root):
                return root
            if any(label(n) in {"Sign In", "Register", "Enter your mobile number"} for n in root.iter("node")):
                raise CollectionFailure("LOGIN_REQUIRED", "Sign in to the ALBAIK app to continue selecting this location.")
            time.sleep(1)
        raise CollectionFailure("NAVIGATION_TIMEOUT", f"The app did not finish {purpose.replace('-', ' ')}.")

    def is_menu(self, root: ET.Element) -> bool:
        return any(n.get("text") == "MENU" for n in root.iter("node"))

    def navigate(self) -> ET.Element:
        self.device.start_app()
        for attempt in range(3):
            try:
                root = self.wait(lambda r: self.is_menu(r) or any(label(n)=="ORDER OPTIONS" for n in r.iter("node")), "launch")
                break
            except CollectionFailure as error:
                if error.code not in {"NETWORK_UNAVAILABLE", "UI_UNAVAILABLE"} or attempt==2:
                    raise
                self.device.run("shell", "am", "force-stop", config.PACKAGE)
                time.sleep(10)
                self.device.run("shell", "am", "start", "-n", config.ACTIVITY)
                time.sleep(5)
        if self.is_menu(root):
            header = next((n for n in root.iter("node") if n.get("clickable")=="true"
                           and label(n).startswith(("Delivery", "Pickup")) and bounds(n)[1] < self.height*.1), None)
            if header is None:
                raise CollectionFailure("CHANNEL_UNVERIFIED", "Could not find the app order options.")
            self.tap(header)
            root = self.wait(lambda r: self.find(r,"Delivery Service") is not None,"order-options")
        option = "Pickup from a restaurant" if self.channel=="PICKUP" else "Delivery Service"
        # Restoring the saved branch/channel is asynchronous. Pickup remains
        # disabled during bootstrap; wait for it before changing either mode.
        root = self.wait(lambda r: self.find(r,option,prefix=True) is not None
                         and self.find(r,"Pickup from a restaurant",prefix=True) is not None,
                         "channel-ready",attempts=20)
        node = self.find(root,option,prefix=True)
        if node is None:
            raise CollectionFailure("CHANNEL_UNAVAILABLE", f"The app does not offer {option}.")
        self.tap(node)
        action = "Choose a restaurant" if self.channel=="PICKUP" else "Choose an address"
        root = self.wait(lambda r: self.find(r,action) is not None,"location-options")
        self.tap(self.find(root,action))
        if self.channel=="PICKUP":
            def branch(r):
                return next((n for n in r.iter("node") if n.get("clickable")=="true"
                             and "riyadh" in label(n).casefold()
                             and any(label(n).casefold().startswith(a+",") for a in config.BRANCH_ALIASES)),None)
            root = self.wait(lambda r: branch(r) is not None,"nearby-restaurants",attempts=20)
            self.tap(branch(root))
            root = self.wait(lambda r:self.find(r,"Order Here") is not None,"branch-details")
            if not any(label(n).casefold() in config.BRANCH_ALIASES for n in root.iter("node")):
                raise CollectionFailure("BRANCH_MISMATCH", "The selected pickup branch is not Arubah in Olaya.")
            self.tap(self.find(root,"Order Here"))
        else:
            root = self.wait(lambda r:any(label(n)=="Delivery checker:" for n in r.iter("node")),"delivery-map")
            # The official app exposes no label for its current-location arrow.
            self.device.tap(round(self.width*.896),round(self.height*.661))
            root = self.wait(lambda r:any("we can deliver your order to that location" in label(n) for n in r.iter("node")),"delivery-coverage",attempts=20)
            node = self.find(root,"Confirm")
            if node is None:
                raise CollectionFailure("DELIVERY_UNAVAILABLE","The app did not enable confirmation for the nearby delivery location.")
            self.tap(node)
        root = self.wait(self.is_menu,"selected-menu",attempts=20)
        headers = [label(n) for n in root.iter("node") if n.get("clickable")=="true" and bounds(n)[1]<self.height*.1]
        if self.channel=="PICKUP":
            valid = any(h.startswith("Pickup,") and "riyadh" in h.casefold()
                        and any(a in h.casefold() for a in config.BRANCH_ALIASES) for h in headers)
        else:
            valid = "Delivery" in headers
        if not valid:
            raise CollectionFailure("CHANNEL_UNVERIFIED", "The selected menu did not confirm the requested channel and location.")
        return root

    def tabs(self, root: ET.Element) -> list[ET.Element]:
        menu = next((n for n in root.iter("node") if n.get("text")=="MENU"),None)
        if menu is None:
            raise CollectionFailure("MENU_NOT_VISIBLE","The app left the menu during collection.")
        my = bounds(menu)[1]
        return [n for n in root.iter("node") if n.get("clickable")=="true" and label(n)
                and my+70 < bounds(n)[1] < my+220 and 30 < bounds(n)[3]-bounds(n)[1] < 160
                and bounds(n)[2]>bounds(n)[0]]

    def discover_categories(self, root: ET.Element) -> ET.Element:
        previous = None
        for _ in range(10):
            tabs = self.tabs(root)
            names = [label(n) for n in tabs]
            for name in names:
                if name != "All" and name not in self.categories:
                    self.categories.append(name)
            signature = [(label(n),bounds(n)) for n in tabs]
            if signature==previous:
                if len(self.categories)<3:
                    raise CollectionFailure("CATEGORIES_MISSING","The app did not load its menu categories.")
                return root
            previous = signature
            y = sum(bounds(tabs[0])[i] for i in (1,3))//2
            self.device.swipe(int(self.width*.9),y,int(self.width*.1),y)
            root = self.screen("categories")
        raise CollectionFailure("CATEGORY_LIMIT","Category discovery did not reach the end.")

    def select_category(self, root: ET.Element, name: str) -> ET.Element:
        # Return to the beginning of the vertical menu without changing the chosen location.
        for _ in range(20):
            tabs=self.tabs(root)
            if tabs and bounds(tabs[0])[1] > self.height*.3:
                break
            self.device.swipe(int(self.width*.5),int(self.height*.3),int(self.width*.5),int(self.height*.9),150)
            root=self.screen("menu-top")
        for direction in (1,-1):
            for _ in range(6):
                tabs=self.tabs(root)
                node=next((n for n in tabs if label(n)==name and bounds(n)[2]-bounds(n)[0]>self.width*.17),None)
                if node is not None:
                    self.tap(node)
                    return self.screen("category-selected")
                y=(bounds(tabs[0])[1]+bounds(tabs[0])[3])//2
                self.device.swipe(int(self.width*(.1 if direction==1 else .9)),y,
                                  int(self.width*(.9 if direction==1 else .1)),y)
                root=self.screen("category-scroll")
        raise CollectionFailure("CATEGORY_UNAVAILABLE",f"Could not select {name}.")

    def detail(self, name: str, category: str) -> None:
        root=self.wait(lambda r:any(n.get("resource-id")=="Add to order" for n in r.iter("node")),"product-detail",attempts=8)
        base=parse_detail(root,name)
        image_url,is_new=cache_image(self.device,root,name,config.IMAGE_DIR)
        self.images_new+=int(is_new)
        options={}
        # Variations precede add-ons/nutrition. Read that section only, never tap add-to-order.
        for _ in range(6):
            for n in root.iter("node"):
                if n.get("resource-id","").startswith("variation-"):
                    variant=n.get("resource-id")[10:]
                    options[variant]=label(n)
            labels={label(n) for n in root.iter("node")}
            if "Try it with" in labels or "Nutritional Facts" in labels:
                break
            self.device.swipe(int(self.width*.85),int(self.height*.89),int(self.width*.85),int(self.height*.49),450)
            root=self.screen("product-variations")
        else:
            raise CollectionFailure("VARIATIONS_INCOMPLETE",f"Could not finish reading options for {name}.")
        variants={name:base}
        sizes=size_controls(root)
        if sizes:
            selected=next((size for size,node in sizes.items() if node.get("clickable")=="false"),None)
            if selected is None:
                raise CollectionFailure("SIZE_UNVERIFIED",f"The selected size is not identifiable for {name}.")
            variants={f"{name} — {selected}":{**base,"size":selected}}
            for size in sizes:
                if size==selected:
                    continue
                node=size_controls(root).get(size)
                if node is None or node.get("clickable")!="true":
                    raise CollectionFailure("SIZE_UNVERIFIED",f"Could not select {size} for {name}.")
                self.tap(node)
                root=self.screen("size-selected")
                chosen=size_controls(root).get(size)
                if chosen is None or chosen.get("clickable")!="false":
                    raise CollectionFailure("SIZE_UNVERIFIED",f"The app did not confirm {size} for {name}.")
                actual_name=observed_title(root)
                base_title=re.sub(r"\s*-\s*(small|medium|large) size$", "", (actual_name or "").strip(), flags=re.IGNORECASE)
                if base_title.strip().casefold()!=name.strip().casefold():
                    raise CollectionFailure("SIZE_UNVERIFIED",f"The {size} option did not identify {name}.")
                variants[f"{name} — {size}"]={**parse_detail(root,actual_name),"size":size,"observed_name":actual_name}
        # The app's variation-* IDs also describe optional cheese/sauce add-ons.
        # Spicy is a toggle between named products; do not invent combinations
        # of optional toppings or mistake a checkbox's accessible ✓ for its state.
        if "Spicy" in options and sizes:
            raise CollectionFailure("UNSUPPORTED_OPTIONS",f"Size and Spicy combinations need verification for {name}.")
        if "Spicy" in options:
            for _ in range(5):
                node=next((n for n in root.iter("node") if n.get("resource-id")=="variation-Spicy"),None)
                if (node is not None and bounds(node)[3]-bounds(node)[1]>100
                        and bounds(node)[1]>detail_header_bottom(root)):
                    break
                self.device.swipe(int(self.width*.85),int(self.height*.3),int(self.width*.85),int(self.height*.65),450)
                root=self.screen("spicy-option")
            else:
                raise CollectionFailure("VARIANT_NOT_VISIBLE",f"Could not verify the Spicy option for {name}.")
            self.tap(node)
            root=self.screen("variation-selected")
            for _ in range(5):
                product_name=observed_title(root)
                if product_name is not None:
                    break
                self.device.swipe(int(self.width*.85),int(self.height*.3),int(self.width*.85),int(self.height*.65),450)
                root=self.screen("variation-price")
            else:
                raise CollectionFailure("PRICE_MISSING",f"Could not read the Spicy option price for {name}.")
            canonical=lambda value: re.sub(r"\W+", "", re.sub(r"\bspicy\b", "", value.casefold()))
            for _ in range(3):
                if product_name.strip().casefold()!=name.strip().casefold():
                    break
                time.sleep(1)
                root=self.screen("variation-confirmed")
                product_name=observed_title(root) or name
            if product_name.strip().casefold()==name.strip().casefold():
                raise CollectionFailure("VARIANT_UNVERIFIED",f"The app did not confirm the Spicy option for {name}.")
            if canonical(product_name)!=canonical(name):
                raise CollectionFailure("VARIANT_MISMATCH",f"The Spicy option unexpectedly changed {name} to {product_name}.")
            variants[product_name]=parse_detail(root,product_name)
        for product_name,fields in variants.items():
            item={"id":identity(product_name),"name":product_name,"base_name":name,
                  "category":category,"image_url":image_url,"customizations":options,**fields}
            item["variant"]=fields.get("size") or ("Spicy" if "spicy" in product_name.casefold() else "")
            self.items[item["id"]]=item
        self.products_seen.add(name)
        self.checkpoint()
        print(f"ALBAIK_PROGRESS channel={self.channel} category={category} products={len(self.items)} images_new={self.images_new} latest={name}",flush=True)
        self.device.key("KEYCODE_BACK")

    def collect_category(self, root: ET.Element, category: str) -> ET.Element:
        previous=None
        stable=0
        discovered=set()
        for page in range(100):
            tabs=self.tabs(root)
            bottom=max(bounds(n)[3] for n in tabs)
            cards=product_cards(root,bottom,self.height)
            for card in cards:
                name=label(card)
                discovered.add(name)
                if name in config.EXCLUDED_PRODUCTS.get(self.channel, ()):
                    if name not in self.excluded_products:
                        self.excluded_products.add(name)
                        self.checkpoint()
                        print(f"ALBAIK_SKIPPED channel={self.channel} reason=user-excluded product={name}",flush=True)
                    continue
                if name in self.products_seen or name in self.unreadable_products:
                    continue
                for attempt in range(2):
                    current_bottom=max(bounds(n)[3] for n in self.tabs(root))
                    current=next((n for n in product_cards(root,current_bottom,self.height) if label(n)==name),None)
                    if current is None:
                        raise CollectionFailure("MENU_CHANGED",f"The menu moved before opening {name}.")
                    x1,y1,x2,y2=bounds(current)
                    self.device.tap((x1+x2)//2,(max(y1,current_bottom+20)+min(y2,self.height-150))//2)
                    try:
                        self.detail(name,category)
                        break
                    except CollectionFailure as error:
                        if error.code!="NAVIGATION_TIMEOUT":
                            raise
                        if attempt==1:
                            if self.channel in config.SKIP_UNREADABLE_CHANNELS:
                                self.unreadable_products[name]="Product detail did not open after two attempts."
                                self.device.key("KEYCODE_BACK")
                                root=self.wait(self.is_menu,"return-after-skipped-product")
                                self.checkpoint()
                                print(f"ALBAIK_SKIPPED channel={self.channel} reason=load-failed product={name}",flush=True)
                                break
                            raise CollectionFailure("PRODUCT_LOAD_FAILED",
                                f"The ALBAIK app did not load {name} after two attempts. Previous complete data kept.") from error
                        self.device.key("KEYCODE_BACK")
                        root=self.wait(self.is_menu,"return-after-product-load")
                root=self.screen("menu-return")
            signature=[(label(n),bounds(n)) for n in product_cards(root,bottom,self.height)]
            if signature==previous:
                stable+=1
                if stable>=2:
                    if not discovered and category!="Breakfast":
                        raise CollectionFailure("EMPTY_CATEGORY",f"The {category} menu was empty.")
                    return root
            else:
                stable=0
            previous=signature
            self.device.swipe(int(self.width*.55),int(self.height*.9),int(self.width*.55),
                              int(self.height*.4),600)
            root=self.screen("menu-page")
        raise CollectionFailure("MENU_LIMIT",f"The {category} menu did not reach its end.")

    def payload(self, *, complete: bool) -> dict:
        return {"complete":complete,"channel":self.channel,"categories":self.categories,
                "location":"Arubah (Olaya), Riyadh" if self.channel=="PICKUP" else "Near Arubah (Olaya), Riyadh",
                "latitude":config.LATITUDE,"longitude":config.LONGITUDE,"items":list(self.items.values()),
                "images_new":self.images_new,"base_products":len(self.products_seen),
                "excluded_products":sorted(self.excluded_products),"unreadable_products":self.unreadable_products,
                "resumed_from":self.resume_source}

    def checkpoint(self) -> None:
        """Keep verified progress on disk even if a later product fails."""
        temporary=self.evidence/"progress.tmp"
        temporary.write_text(json.dumps(self.payload(complete=False),ensure_ascii=False,indent=2),encoding="utf-8")
        temporary.replace(self.evidence/"progress.json")

    def collect(self) -> dict:
        for attempt in range(2):
            try:
                root=self.navigate()
                break
            except CollectionFailure as error:
                if error.code!="APP_NOT_RESPONDING" or attempt==1:
                    raise
                print(f"ALBAIK_RECOVERY channel={self.channel} action=restart-app reason=not-responding",flush=True)
        root=self.discover_categories(root)
        for category in [*self.categories,"All"]:
            root=self.select_category(root,category)
            root=self.collect_category(root,category)
        return self.payload(complete=True)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel",choices=["PICKUP","DELIVERY"],required=True)
    parser.add_argument("--serial",default=config.ADB_SERIAL)
    parser.add_argument("--adb")
    parser.add_argument("--resume",type=Path,help="Resume a progress.json less than one hour old for the same channel/location.")
    args=parser.parse_args()
    run_id=f"albaik-app-{args.channel.lower()}-{uuid.uuid4().hex[:12]}"
    started=utc_now()
    evidence=config.RAW_DIR/run_id
    evidence.mkdir(parents=True,exist_ok=True)
    device=AlbaikDevice(find_adb(args.adb),args.serial)
    def interrupted(signum, _frame):
        raise CollectionFailure("COLLECTION_TIMEOUT" if signum==signal.SIGALRM else "COLLECTION_INTERRUPTED",
                                "App collection exceeded its time limit." if signum==signal.SIGALRM else "App collection was interrupted.")
    previous_alarm=signal.signal(signal.SIGALRM,interrupted)
    previous_term=signal.signal(signal.SIGTERM,interrupted)
    previous_interrupt=signal.signal(signal.SIGINT,interrupted)
    # Leave cleanup time before the pull manager's 45-minute hard deadline.
    signal.alarm(42*60)
    try:
        with emulator_session(device,config.EMULATOR_SERVICE):
            try:
                collector=Collector(device,args.channel,evidence)
                if args.resume:
                    collector.restore_progress(args.resume)
                payload=collector.collect()
            except Exception:
                try:
                    (evidence/"failure.png").write_bytes(device.screenshot())
                except Exception:
                    pass
                raise
        payload.update(run_id=run_id,started_at=started,finished_at=utc_now())
        (evidence/"capture.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        save_success(payload)
        print(f"ALBAIK_RESULT channel={args.channel} status=SUCCESS products={len(payload['items'])} images_new={payload['images_new']} excluded={len(payload['excluded_products'])} skipped={len(payload['unreadable_products'])}",flush=True)
        return 0
    except Exception as error:
        code=error.code if isinstance(error,CollectionFailure) else "COLLECTION_FAILED"
        message=" ".join(str(error).split())[:500]
        save_failure(run_id,args.channel,started,utc_now(),f"{code}: {message}")
        (evidence/"failure.json").write_text(json.dumps({"code":code,"message":message},ensure_ascii=False),encoding="utf-8")
        print(f"ALBAIK_ERROR channel={args.channel} code={code} message={message}",flush=True)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,previous_alarm)
        signal.signal(signal.SIGTERM,previous_term)
        signal.signal(signal.SIGINT,previous_interrupt)


if __name__=="__main__":
    raise SystemExit(main())
