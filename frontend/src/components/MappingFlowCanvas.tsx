import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { GripVertical, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  comparePrices,
  comparisonCopy,
  flowProductKey,
  flowProductName,
  signedPercent,
  type FlowProduct,
  type PriceComparison,
} from "../lib/playground";
import { Price } from "./Price";
import { ProductImage } from "./ProductImage";

type FlowMode = "edit" | "view";

interface MappingNodeData extends Record<string, unknown> {
  product: FlowProduct | null;
  comparison: PriceComparison | null;
  anchor: boolean;
  selected: boolean;
  disabled: boolean;
  sourcePosition: Position;
  targetPosition: Position;
  mode: FlowMode;
  detailsId: string;
  onSelect: () => void;
  onChooseKudu: () => void;
  onRemove: () => void;
}

type MappingNode = Node<MappingNodeData, "mapping-item">;

export interface MappingFlowCanvasProps {
  mode: FlowMode;
  kuduItem: FlowProduct | null;
  competitorItems: FlowProduct[];
  selectedKey: string | null;
  disabled?: boolean;
  detailsId?: string;
  onSelect: (product: FlowProduct) => void;
  onChooseKudu?: () => void;
  onAddCompetitors?: () => void;
  onRemoveCompetitor?: (product: FlowProduct) => void;
}

function MappingNodeCard({ data }: NodeProps<MappingNode>) {
  const productName = data.product ? flowProductName(data.product) : "Choose KUDU item";
  const select = () => {
    if (data.product) data.onSelect();
    else data.onChooseKudu();
  };

  return (
    <div className={`mapping-flow-node${data.selected ? " is-selected" : ""}${data.product?.missing ? " is-missing" : ""}`}>
      {!data.anchor ? (
        <Handle
          type="target"
          position={data.targetPosition}
          isConnectable={false}
          className="mapping-flow-handle"
        />
      ) : null}
      <div className="mapping-node-drag-handle" aria-hidden="true">
        <GripVertical size={14} />
        <span>Drag node</span>
      </div>
      <button
        type="button"
        className="mapping-flow-node-main nodrag nopan"
        aria-pressed={data.selected}
        aria-controls={data.detailsId}
        aria-label={data.product ? `Show details for ${productName}` : data.disabled ? "Choose channel first" : productName}
        disabled={data.disabled}
        onClick={select}
      >
        {data.product ? (
          <>
            <ProductImage src={data.product.imageUrl} alt={productName} />
            <span className="mapping-node-copy">
              <span className="mapping-node-eyebrow">
                {data.anchor ? "KUDU anchor" : data.product.brandName}
              </span>
              <strong className="mapping-node-title" dir="auto">{productName}</strong>
              <span className="mapping-node-meta">
                <Price value={data.product.effectivePrice} currency={data.product.currency} />
              </span>
              {data.comparison ? (
                <span className="mapping-node-comparison" dir="auto">
                  {comparisonCopy(data.comparison, data.product.currency)}
                  {data.comparison.percentage !== null ? (
                    <span dir="ltr"> ({signedPercent(data.comparison.percentage)})</span>
                  ) : null}
                </span>
              ) : null}
              {data.product.missing ? (
                <span className="mapping-node-unavailable">No longer available</span>
              ) : null}
            </span>
          </>
        ) : (
          <span className="mapping-empty-node-copy">
            <Plus size={20} aria-hidden="true" />
            <strong>{data.disabled ? "Choose channel first" : "Choose KUDU item"}</strong>
            <span>Start the flow with the KUDU anchor.</span>
          </span>
        )}
      </button>
      {data.mode === "edit" && data.product ? (
        <div className="mapping-node-actions nodrag nopan">
          {data.anchor ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={data.onChooseKudu}>
              Change
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost btn-sm destructive-text"
              aria-label={`Remove ${productName}`}
              onClick={data.onRemove}
            >
              <X size={14} aria-hidden="true" />
              Remove
            </button>
          )}
        </div>
      ) : null}
      {data.anchor ? (
        <Handle
          type="source"
          position={data.sourcePosition}
          isConnectable={false}
          className="mapping-flow-handle"
        />
      ) : null}
    </div>
  );
}

const nodeTypes = { "mapping-item": MappingNodeCard };

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, [query]);

  return matches;
}

function useDocumentRtl(): boolean {
  const [rtl, setRtl] = useState(() => document.documentElement.dir === "rtl");

  useEffect(() => {
    const update = () => setRtl(document.documentElement.dir === "rtl");
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["dir"] });
    update();
    return () => observer.disconnect();
  }, []);

  return rtl;
}

function MappingFlowInner({
  mode,
  kuduItem,
  competitorItems,
  selectedKey,
  disabled = false,
  detailsId = "mapping-item-details",
  onSelect,
  onChooseKudu,
  onAddCompetitors,
  onRemoveCompetitor,
}: MappingFlowCanvasProps) {
  const compact = useMediaQuery("(max-width: 640px)");
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const rtl = useDocumentRtl();
  const callbacks = useRef({ onSelect, onChooseKudu, onRemoveCompetitor });
  callbacks.current = { onSelect, onChooseKudu, onRemoveCompetitor };
  const { fitView } = useReactFlow<MappingNode, Edge>();
  const [nodes, setNodes, onNodesChange] = useNodesState<MappingNode>([]);

  const signature = useMemo(
    () => [kuduItem, ...competitorItems]
      .map((item) => item
        ? [
          flowProductKey(item),
          item.nameEn,
          item.nameAr,
          item.imageUrl,
          item.effectivePrice,
          item.currency,
          item.missing,
        ].join("|")
        : "empty")
      .join("~~"),
    [competitorItems, kuduItem],
  );

  const buildNodes = (): MappingNode[] => {
    const sourcePosition = compact ? Position.Bottom : rtl ? Position.Left : Position.Right;
    const targetPosition = compact ? Position.Top : rtl ? Position.Right : Position.Left;
    const gap = compact ? 230 : 190;
    const anchorY = compact
      ? 32
      : competitorItems.length > 0
        ? 44 + ((competitorItems.length - 1) * gap) / 2
        : 150;
    const anchorX = compact ? 32 : rtl ? 560 : 40;
    const competitorX = compact ? 32 : rtl ? 40 : 560;

    const anchorId = kuduItem ? flowProductKey(kuduItem) : "kudu-anchor";
    const anchor: MappingNode = {
      id: anchorId,
      type: "mapping-item",
      position: { x: anchorX, y: anchorY },
      selected: Boolean(kuduItem && selectedKey === anchorId),
      draggable: true,
      dragHandle: ".mapping-node-drag-handle",
      deletable: false,
      data: {
        product: kuduItem,
        comparison: null,
        anchor: true,
        selected: Boolean(kuduItem && selectedKey === anchorId),
        disabled,
        sourcePosition,
        targetPosition,
        mode,
        detailsId,
        onSelect: () => {
          if (kuduItem) callbacks.current.onSelect(kuduItem);
        },
        onChooseKudu: () => callbacks.current.onChooseKudu?.(),
        onRemove: () => undefined,
      },
    };

    const competitors = competitorItems.map((product, index): MappingNode => {
      const id = flowProductKey(product);
      return {
        id,
        type: "mapping-item",
        position: {
          x: competitorX,
          y: compact ? 300 + index * gap : 44 + index * gap,
        },
        selected: selectedKey === id,
        draggable: true,
        dragHandle: ".mapping-node-drag-handle",
        deletable: false,
        data: {
          product,
          comparison: comparePrices(product, kuduItem),
          anchor: false,
          selected: selectedKey === id,
          disabled: false,
          sourcePosition,
          targetPosition,
          mode,
          detailsId,
          onSelect: () => callbacks.current.onSelect(product),
          onChooseKudu: () => undefined,
          onRemove: () => callbacks.current.onRemoveCompetitor?.(product),
        },
      };
    });

    return [anchor, ...competitors];
  };

  const fitCurrentView = () => {
    requestAnimationFrame(() => {
      void fitView({ padding: 0.22, duration: reducedMotion ? 0 : 180, maxZoom: 1.05 });
    });
  };

  useEffect(() => {
    setNodes(buildNodes());
    fitCurrentView();
    // Re-layout only when the graph itself or its logical direction changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compact, disabled, mode, rtl, signature]);

  useEffect(() => {
    setNodes((current) => current.map((node) => {
      const isSelected = node.id === selectedKey;
      if (node.selected === isSelected && node.data.selected === isSelected) return node;
      return { ...node, selected: isSelected, data: { ...node.data, selected: isSelected } };
    }));
  }, [selectedKey, setNodes]);

  const edges = useMemo<Edge[]>(() => {
    if (!kuduItem) return [];
    const source = flowProductKey(kuduItem);
    return competitorItems.map((product) => ({
      id: `${source}--${flowProductKey(product)}`,
      source,
      target: flowProductKey(product),
      type: "smoothstep",
      focusable: false,
      selectable: false,
      style: { stroke: "var(--kudu-border-default)", strokeWidth: 1.5 },
      pathOptions: { borderRadius: 14 },
    }));
  }, [competitorItems, kuduItem]);

  const resetLayout = () => {
    setNodes(buildNodes());
    fitCurrentView();
  };

  const relationshipDescription = kuduItem
    ? competitorItems.length > 0
      ? `${flowProductName(kuduItem)} is mapped to ${competitorItems.map((item) => `${item.brandName} ${flowProductName(item)}`).join(", ")}.`
      : `${flowProductName(kuduItem)} has no competitor items yet.`
    : "Choose a KUDU item to start this mapping flow.";

  return (
    <div className="mapping-flow-shell">
      <p className="visually-hidden" id="mapping-flow-description">{relationshipDescription}</p>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesReconnectable={false}
        edgesFocusable={false}
        deleteKeyCode={null}
        minZoom={0.35}
        maxZoom={1.5}
        fitView
        fitViewOptions={{ padding: 0.22, maxZoom: 1.05 }}
        panOnDrag
        zoomOnPinch
        zoomOnScroll
        zoomOnDoubleClick={false}
        preventScrolling
        aria-label="Mapping flow canvas"
        aria-describedby="mapping-flow-description"
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1}
          color="var(--kudu-border-subtle)"
        />
        <Controls showInteractive={false} position="bottom-left" />
        <Panel position="top-right" className="mapping-flow-toolbar">
          {mode === "edit" ? (
            <button
              type="button"
              className="btn btn-primary btn-sm nodrag nopan"
              disabled={!kuduItem || disabled}
              onClick={onAddCompetitors}
            >
              <Plus size={14} aria-hidden="true" />
              Add competitor items
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-secondary btn-sm nodrag nopan"
            onClick={resetLayout}
          >
            <RotateCcw size={14} aria-hidden="true" />
            Reset layout
          </button>
        </Panel>
      </ReactFlow>
      <span className="visually-hidden" aria-live="polite">
        {selectedKey ? `Selected flow node ${selectedKey}. Details are available in ${detailsId}.` : ""}
      </span>
    </div>
  );
}

export function MappingFlowCanvas(props: MappingFlowCanvasProps) {
  return (
    <ReactFlowProvider>
      <MappingFlowInner {...props} />
    </ReactFlowProvider>
  );
}
