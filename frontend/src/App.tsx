import { Fragment } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { BrandChangesPage } from "./pages/BrandChangesPage";
import { BrandHistoryIndexPage } from "./pages/BrandHistoryIndexPage";
import { BrandMenuPage } from "./pages/BrandMenuPage";
import { BrandOverviewPage } from "./pages/BrandOverviewPage";
import { BrandPromotionsPage } from "./pages/BrandPromotionsPage";
import { ChangeDetailPage } from "./pages/ChangeDetailPage";
import { MarketChangesPage } from "./pages/MarketChangesPage";
import { MarketOverviewPage } from "./pages/MarketOverviewPage";
import { MarketPromotionsPage } from "./pages/MarketPromotionsPage";
import { ProductHistoryPage } from "./pages/ProductHistoryPage";
import { PromotionDetailPage } from "./pages/PromotionDetailPage";

const BRANDS = ["kfc", "hardees", "burger-king", "herfy"];

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<MarketOverviewPage />} />
        <Route path="/changes" element={<MarketChangesPage />} />
        <Route path="/promotions" element={<MarketPromotionsPage />} />
        <Route path="/changes/:changeId" element={<ChangeDetailPage />} />
        {BRANDS.map((brandId) => (
          <Fragment key={brandId}>
            <Route path={`/competitors/${brandId}`} element={<BrandOverviewPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/menu`} element={<BrandMenuPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/promotions`} element={<BrandPromotionsPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/promotions/:promotionId`} element={<PromotionDetailPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/changes`} element={<BrandChangesPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/history`} element={<BrandHistoryIndexPage brandId={brandId} />} />
            <Route path={`/competitors/${brandId}/products/:productId`} element={<ProductHistoryPage brandId={brandId} />} />
          </Fragment>
        ))}
      </Route>
    </Routes>
  );
}
