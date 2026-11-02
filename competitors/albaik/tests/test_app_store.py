from copy import deepcopy

import pytest

from adapters.albaik import AlbaikAdapter
from adapters.hungerstation import HungerstationOverlayAdapter
from competitors.albaik.backend.app_store import latest_collection_status, save_failure, save_success
from competitors.hungerstation import database as hs_database


def snapshot(channel="PICKUP", run="one", time="2026-11-02T07:00:00Z"):
    return dict(run_id=run,channel=channel,started_at=time,finished_at=time,
                location="Olaya, Riyadh",complete=True,
                items=[dict(id=f"product-{i}",name=f"Product {i}",category="Chicken",
                            price=10+i,image_url=f"/albaik-app-images/product-{i}.jpg")
                       for i in range(12)])


def test_channels_keep_separate_prices_and_failed_pull_keeps_last_success(tmp_path):
    path = tmp_path / "albaik.db"
    first = snapshot()
    save_success(first, path)
    delivery = snapshot("DELIVERY", "two")
    delivery["items"][0]["price"] = 15
    save_success(delivery, path)
    save_failure("three","PICKUP","2026-11-02T08:00:00Z","2026-11-02T08:01:00Z","App unavailable",path)
    adapter = AlbaikAdapter(path)
    assert len(adapter.list_products(channel="pickup")) == 12
    assert len(adapter.list_products(channel="delivery")) == 12
    assert adapter.get_brand().health == "partial"
    assert adapter.list_runs()[0].error_summary == "App unavailable"
    product = next(p for p in adapter.list_products(channel="pickup") if p.name_en == "Product 0")
    assert product.regular_price == 10
    assert adapter.get_product_history(product.id).observations[0].regular_price == 10


def test_price_changes_are_computed_within_channel(tmp_path):
    path=tmp_path / "albaik.db"
    first=snapshot()
    save_success(first,path)
    second=deepcopy(first)
    second.update(run_id="two",started_at="2026-11-02T08:00:00Z",finished_at="2026-11-02T08:01:00Z")
    second["items"][0]["price"]=12
    save_success(second,path)
    events=AlbaikAdapter(path).list_changes(event_type="price_increased")
    assert len(events)==1
    assert events[0].channel=="pickup"
    assert float(events[0].before_value)==10
    assert float(events[0].after_value)==12


def test_official_app_and_hungerstation_keep_their_own_prices_photos_and_history(tmp_path):
    app_path,hs_path=tmp_path/"app.db",tmp_path/"hs.db"
    pickup=snapshot()
    delivery=snapshot("DELIVERY","delivery")
    delivery["items"][0]["price"]=11
    save_success(pickup,app_path)
    save_success(delivery,app_path)
    hs_database.save_success(run_id="hs",batch_id=None,brand_id="albaik",restaurant_name="AlBaik",
        started_at=pickup["started_at"],finished_at=pickup["finished_at"],raw_capture_path=None,path=hs_path,
        items=[dict(source_product_id="HUNGERSTATION|albaik|product-0",name_en="Product 0",
                    regular_price=20,effective_price=20,image_url="/hungerstation-images/own.jpg")])
    adapter=HungerstationOverlayAdapter(brand_id="albaik",brand_name="AlBaik",base=AlbaikAdapter(app_path),db_path=hs_path)
    assert adapter.get_brand().channels==["pickup","delivery","hungerstation"]
    rows=adapter.list_products(query="Product 0")
    assert {p.channel:p.regular_price for p in rows}=={"pickup":10,"delivery":11,"hungerstation":20}
    hs=next(p for p in rows if p.channel=="hungerstation")
    assert hs.image_url=="/hungerstation-images/own.jpg"
    assert adapter.get_product_history(hs.id).observations[0].regular_price==20
    assert {r.channel for r in adapter.get_overview().runs}=={"pickup","delivery","hungerstation"}


def test_panel_uses_latest_recorded_results_including_cli_and_preserves_running_progress(tmp_path):
    path=tmp_path/"app.db"
    assert latest_collection_status(None,path) is None
    save_success(snapshot(),path)
    save_failure("delivery-failed","DELIVERY","2026-11-02T08:00:00Z","2026-11-02T08:01:00Z","No coverage",path)
    partial=latest_collection_status(None,path,tmp_path)
    assert partial["status"]=="partial"
    assert partial["brands"][0]["message"]=="Collected 12 products."
    assert partial["brands"][1]["message"]=="No coverage"
    active={"status":"running","runId":"active","brands":[]}
    assert latest_collection_status(active,path) is active
    save_success(snapshot("DELIVERY","cli","2026-11-02T09:00:00Z"),path)
    (tmp_path/"cli").mkdir()
    (tmp_path/"cli"/"capture.json").write_text('{"images_new":0,"excluded_products":["BAIKEEZ Burger with Lahaleebo Sauce"],"unreadable_products":{"Tahina Sauce":"Did not open twice"}}')
    complete=latest_collection_status(partial,path,tmp_path)
    assert complete["status"]=="success"
    assert complete["runId"]!=partial["runId"]
    assert "Excluded as requested: BAIKEEZ Burger with Lahaleebo Sauce" in complete["brands"][1]["message"]
    assert "Could not open after two attempts (skipped): Tahina Sauce" in complete["brands"][1]["message"]
    startup_failure={**complete,"status":"partial","brands":[dict(row) for row in complete["brands"]]}
    startup_failure["brands"][0].update(status="failed",startedAt="2026-11-02T10:00:00+00:00",
                                        completedAt="2026-11-02T10:01:00+00:00",message="Collector could not start")
    failure=latest_collection_status(startup_failure,path,tmp_path)
    assert failure["status"]=="partial"
    assert failure["brands"][0]["status"]=="failed"
    assert failure["brands"][0]["message"]=="Collector could not start"


@pytest.mark.parametrize("problem",["incomplete","missing_price","missing_image","duplicate","large_drop","missing_spicy"])
def test_invalid_snapshot_does_not_replace_previous_data(tmp_path,problem):
    path=tmp_path / "albaik.db"
    first=snapshot()
    if problem=="large_drop":
        first["items"] += [dict(id=f"extra-{i}",name=f"Extra {i}",category="Sides",price=5,image_url="/image.jpg") for i in range(10)]
    save_success(first,path)
    bad=snapshot(run="bad",time="2026-11-02T08:00:00Z")
    if problem=="incomplete":bad["complete"]=False
    if problem=="missing_price":bad["items"][0]["price"]=None
    if problem=="missing_image":bad["items"][0]["image_url"]=None
    if problem=="duplicate":bad["items"][1]["id"]=bad["items"][0]["id"]
    if problem=="missing_spicy":bad["items"][0].update(base_name="Product 0",customizations={"Spicy":"Spicy"})
    with pytest.raises(ValueError):save_success(bad,path)
    assert len(AlbaikAdapter(path).list_products())==len(first["items"])
