import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from copy import deepcopy
import os
import time

import pytest
from PIL import Image, ImageDraw

from competitors.albaik.collector.app import Collector, cache_image, observed_title, parse_detail, product_cards
from competitors.albaik import app_config
from competitors.hungerstation.collector import CollectionFailure


def detail():
    return ET.fromstring('''<hierarchy>
      <node class="android.widget.ImageView" bounds="[0,102][1080,1422]" />
      <node class="android.widget.TextView" text="Pepsi" bounds="[26,1480][835,1558]" />
      <node class="android.widget.TextView" text="3.50 ﷼" bounds="[848,1475][1054,1562]" />
      <node class="android.widget.TextView" text="Pepsi – 360ml" bounds="[26,1575][1054,1644]" />
      <node class="android.widget.TextView" text="96 kcal" bounds="[263,1919][382,1977]" />
      <node class="android.widget.TextView" text="1.75 ﷼" bounds="[100,2225][240,2298]" />
    </hierarchy>''')


def test_observed_product_price_does_not_take_an_addon_price():
    assert parse_detail(detail(),"Pepsi")=={"price":3.5,"description":"Pepsi – 360ml","calories":"96"}
    with pytest.raises(CollectionFailure,match="verify"):
        parse_detail(detail(),"Different product")
    root=detail()
    root.remove(root[2])
    with pytest.raises(CollectionFailure,match="price"):
        parse_detail(root,"Pepsi")


def test_photo_is_captured_once_and_shared_across_runs_and_channels(tmp_path):
    class Device:
        calls=0
        def screen_size(self):return 1080,2400
        def screenshot(self):
            self.calls+=1
            picture=Image.new("RGB",(1080,2400),"white")
            ImageDraw.Draw(picture).rectangle((300,400,800,1100),fill="red")
            output=io.BytesIO()
            picture.save(output,format="PNG")
            return output.getvalue()
    device=Device()
    url,created=cache_image(device,detail(),"Pepsi",tmp_path)
    assert created and device.calls==1
    assert cache_image(device,detail(),"Pepsi",tmp_path)==(url,False)
    assert device.calls==1
    cache_image(device,detail(),"New drink",tmp_path)
    assert device.calls==2


def test_product_cards_exclude_promotional_banner_and_hidden_cards():
    root=ET.fromstring('''<hierarchy>
      <node content-desc="FOR YOU" clickable="true" bounds="[0,221][1080,1400]"><node class="android.widget.ImageView" /></node>
      <node content-desc="Pepsi" clickable="true" bounds="[0,500][347,900]"><node class="android.widget.ImageView" /></node>
      <node content-desc="Hidden" clickable="true" bounds="[0,2300][347,2400]"><node class="android.widget.ImageView" /></node>
    </hierarchy>''')
    assert [n.get("content-desc") for n in product_cards(root,458,2400)]==["Pepsi"]


def test_spicy_toggle_reads_actual_title_without_inventing_cheese_sauce_products(tmp_path,monkeypatch):
    fixture=Path(__file__).parent/"fixtures"
    screens=iter(E for E in [ET.parse(fixture/name).getroot() for name in
                            ("egg-default.xml","egg-options.xml","egg-spicy.xml")])
    class Device:
        def screen_size(self):return 1080,2400
        def swipe(self,*_):pass
        def tap(self,*_):pass
        def key(self,key):assert key=="KEYCODE_BACK"
    collector=Collector(Device(),"PICKUP",tmp_path)
    monkeypatch.setattr(collector,"screen",lambda *_:next(screens))
    monkeypatch.setattr("competitors.albaik.collector.app.cache_image",lambda *_:("/albaik-app-images/egg.jpg",False))
    collector.detail("Egg Sandwich with Chicken and Cheese","Breakfast")
    items=list(collector.items.values())
    assert [item["name"] for item in items]==["Egg Sandwich with Chicken and Cheese","Spicy Egg Sandwich with Chicken and Cheese"]
    assert [item["price"] for item in items]==[7.5,7.5]
    assert items[0]["image_url"]==items[1]["image_url"]
    assert set(items[0]["customizations"])=={"Spicy","Cheese","Sauce"}
    assert observed_title(ET.parse(fixture/"egg-spicy.xml").getroot())==items[1]["name"]


@pytest.mark.parametrize("name,trailing_space",[("Orange Juice",""),("Mixed Fruit Juice"," ")])
def test_juice_sizes_keep_their_observed_prices_and_share_one_photo(tmp_path,monkeypatch,name,trailing_space):
    fixture=Path(__file__).parent/"fixtures"
    roots=[ET.parse(fixture/file).getroot() for file in ("juice-default.xml","juice-options.xml","juice-small.xml")]
    for root in roots:
        for node in root.iter("node"):
            if node.get("text","").startswith("Orange Juice"):
                value=node.get("text").replace("Orange Juice",name)
                node.set("text",value+trailing_space if "small size" in value else value)
    screens=iter(roots)
    class Device:
        def screen_size(self):return 1080,2400
        def swipe(self,*_):pass
        def tap(self,*_):pass
        def key(self,key):assert key=="KEYCODE_BACK"
    collector=Collector(Device(),"DELIVERY",tmp_path)
    monkeypatch.setattr(collector,"screen",lambda *_:next(screens))
    monkeypatch.setattr("competitors.albaik.collector.app.cache_image",lambda *_:("/albaik-app-images/orange.jpg",False))
    collector.detail(name,"Beverages")
    items=list(collector.items.values())
    assert [(p["name"],p["price"]) for p in items]==[(f"{name} — Large",3),(f"{name} — Small",2)]
    assert "300ml" in items[0]["description"] and "200ml" in items[1]["description"]
    assert items[0]["image_url"]==items[1]["image_url"]


@pytest.mark.parametrize("recovers", [True, False])
@pytest.mark.parametrize("channel", ["PICKUP", "DELIVERY"])
def test_stalled_product_is_reopened_once_and_failure_names_the_product(tmp_path, monkeypatch, recovers, channel):
    root=ET.fromstring('''<hierarchy>
      <node text="MENU" bounds="[118,259][242,313]" />
      <node content-desc="Chicken" clickable="true" bounds="[551,366][788,458]" />
      <node content-desc="Chicken burger" clickable="true" bounds="[0,500][1067,1200]">
        <node class="android.widget.ImageView" />
      </node>
    </hierarchy>''')
    class Device:
        backs=0
        def screen_size(self):return 1080,2400
        def tap(self,*_):pass
        def swipe(self,*_):pass
        def key(self,key):
            assert key=="KEYCODE_BACK"
            self.backs+=1
    device=Device()
    collector=Collector(device,channel,tmp_path)
    monkeypatch.setattr(collector,"screen",lambda *_:root)
    opened=[]
    def open_detail(name,category):
        opened.append(name)
        if len(opened)==1 or not recovers:
            raise CollectionFailure("NAVIGATION_TIMEOUT","Loading spinner")
        collector.products_seen.add(name)
    monkeypatch.setattr(collector,"detail",open_detail)
    if recovers or channel=="DELIVERY":
        collector.collect_category(root,"Chicken")
    else:
        with pytest.raises(CollectionFailure,match="Chicken burger after two attempts") as error:
            collector.collect_category(root,"Chicken")
        assert error.value.code=="PRODUCT_LOAD_FAILED"
    assert opened==["Chicken burger","Chicken burger"]
    assert device.backs==(2 if channel=="DELIVERY" and not recovers else 1)
    if channel=="DELIVERY" and not recovers:
        assert list(collector.unreadable_products)==["Chicken burger"]
        assert json.loads((tmp_path/"progress.json").read_text())["unreadable_products"]==collector.unreadable_products


@pytest.mark.parametrize("channel", ["PICKUP", "DELIVERY"])
def test_requested_exclusion_only_skips_delivery_and_preserves_progress(tmp_path, monkeypatch, channel):
    excluded="BAIKEEZ Burger with Lahaleebo Sauce"
    root=ET.fromstring(f'''<hierarchy>
      <node text="MENU" bounds="[118,259][242,313]" />
      <node content-desc="Chicken" clickable="true" bounds="[551,366][788,458]" />
      <node content-desc="{excluded}" clickable="true" bounds="[0,500][1067,1200]">
        <node class="android.widget.ImageView" />
      </node>
      <node content-desc="Other burger" clickable="true" bounds="[0,1200][1067,1900]">
        <node class="android.widget.ImageView" />
      </node>
    </hierarchy>''')
    class Device:
        def screen_size(self):return 1080,2400
        def tap(self,*_):pass
        def swipe(self,*_):pass
    collector=Collector(Device(),channel,tmp_path)
    monkeypatch.setattr(collector,"screen",lambda *_:root)
    opened=[]
    def detail(name,category):
        opened.append(name)
        collector.items[name]={"name":name}
        collector.products_seen.add(name)
        collector.checkpoint()
    monkeypatch.setattr(collector,"detail",detail)
    collector.collect_category(root,"Chicken")
    assert opened==(["Other burger"] if channel=="DELIVERY" else [excluded,"Other burger"])
    progress=json.loads((tmp_path/"progress.json").read_text())
    assert progress["complete"] is False
    assert progress["excluded_products"]==([excluded] if channel=="DELIVERY" else [])
    assert len(progress["items"])==len(opened)


@pytest.mark.parametrize("recovers", [True, False])
def test_android_not_responding_dialog_is_waited_once(tmp_path, monkeypatch, recovers):
    dialog=ET.fromstring('''<hierarchy>
      <node text="ALBAIK isn't responding" bounds="[0,0][100,100]" />
      <node text="Wait" clickable="true" bounds="[0,100][100,200]" />
    </hierarchy>''')
    menu=ET.fromstring('<hierarchy><node text="MENU" /></hierarchy>')
    class Device:
        taps=0
        def screen_size(self):return 1080,2400
        def tap(self,*_):self.taps+=1
    device=Device()
    collector=Collector(device,"DELIVERY",tmp_path)
    screens=iter([dialog, menu if recovers else dialog])
    monkeypatch.setattr(collector,"screen",lambda *_:next(screens))
    if recovers:
        assert collector.wait(collector.is_menu,"selected-menu") is menu
    else:
        with pytest.raises(CollectionFailure) as error:
            collector.wait(collector.is_menu,"selected-menu")
        assert error.value.code=="APP_NOT_RESPONDING"
    assert device.taps==1


@pytest.mark.parametrize("recovers", [True, False])
def test_navigation_restarts_once_after_persistent_android_dialog(tmp_path, monkeypatch, recovers):
    class Device:
        def screen_size(self):return 1080,2400
    collector=Collector(Device(),"DELIVERY",tmp_path)
    attempts=[]
    root=ET.fromstring('<hierarchy/>')
    def navigate():
        attempts.append(1)
        if len(attempts)==1 or not recovers:
            raise CollectionFailure("APP_NOT_RESPONDING","Android dialog")
        return root
    monkeypatch.setattr(collector,"navigate",navigate)
    monkeypatch.setattr(collector,"discover_categories",lambda root:root)
    monkeypatch.setattr(collector,"select_category",lambda root,_:root)
    monkeypatch.setattr(collector,"collect_category",lambda root,_:root)
    if recovers:
        assert collector.collect()["complete"] is True
    else:
        with pytest.raises(CollectionFailure,match="Android dialog"):
            collector.collect()
    assert len(attempts)==2


def test_spicy_control_is_scrolled_out_from_under_pinned_product_header(tmp_path, monkeypatch):
    fixture=Path(__file__).parent/"fixtures"/"covered-spicy.xml"
    covered=ET.parse(fixture).getroot()
    revealed=deepcopy(covered)
    next(n for n in revealed.iter("node") if n.get("resource-id")=="variation-Spicy").set("bounds","[53,721][511,1081]")
    selected=deepcopy(revealed)
    next(n for n in selected.iter("node") if n.get("text")=="Double Crispy BAIK").set("text","Spicy Double Crispy BAIK")
    screens=iter([covered,revealed,selected])
    class Device:
        swipes=0
        def screen_size(self):return 1080,2400
        def swipe(self,*_):self.swipes+=1
        def tap(self,x,y):assert 53<x<511 and 721<y<1081
        def key(self,key):assert key=="KEYCODE_BACK"
    device=Device()
    collector=Collector(device,"DELIVERY",tmp_path)
    monkeypatch.setattr(collector,"screen",lambda *_:next(screens))
    monkeypatch.setattr("competitors.albaik.collector.app.cache_image",lambda *_:("/albaik-app-images/double.jpg",False))
    collector.detail("Double Crispy BAIK","Chicken")
    assert device.swipes==1
    assert {p['name'] for p in collector.items.values()}=={"Double Crispy BAIK","Spicy Double Crispy BAIK"}


@pytest.mark.parametrize("invalid", [None, "channel", "location", "stale"])
def test_resume_only_accepts_recent_progress_from_the_same_location_and_channel(tmp_path, invalid):
    progress=tmp_path/"source.json"
    data=dict(complete=False,channel="DELIVERY",latitude=app_config.LATITUDE,longitude=app_config.LONGITUDE,
              items=[dict(id="one",name="One",base_name="One")])
    if invalid=="channel":data["channel"]="PICKUP"
    if invalid=="location":data["latitude"]=0
    progress.write_text(json.dumps(data))
    if invalid=="stale":os.utime(progress,(time.time()-7200,time.time()-7200))
    class Device:
        def screen_size(self):return 1080,2400
    collector=Collector(Device(),"DELIVERY",tmp_path/"new")
    if invalid:
        with pytest.raises(CollectionFailure) as error:collector.restore_progress(progress)
        assert error.value.code=="INVALID_PROGRESS"
        assert not collector.items
    else:
        collector.restore_progress(progress)
        assert collector.products_seen=={"One"}
        assert collector.payload(complete=False)["resumed_from"]==str(progress.resolve())
