/**
 * The bpmn-js integration.
 *
 * Studio does not draw BPMN itself: bpmn-js is the reference implementation of
 * the notation, it speaks BPMN 2.0 XML natively, and it already owns an edit
 * history, hit-testing, connection routing and element rules. Writing a
 * competing canvas would take months and be worse.
 *
 * What this hook owns is the *contract between the editor and the engine*:
 *
 * - XML flows in when the document changes elsewhere (generated from text,
 *   opened from a file, re-laid out by the server);
 * - XML flows out, debounced, whenever the user edits, so the server can
 *   re-derive elements, validation and narration from the real document;
 * - the two never fight, because a push-back is recognised by its own XML and
 *   does not trigger a re-import.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import BpmnModeler from 'bpmn-js/lib/Modeler';
import minimapModule from 'diagram-js-minimap';
import type { Element } from 'bpmn-js/lib/model/Types';
import { useStudio } from '../state/store';
import type { ElementSpec } from '../lib/elements';

import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn.css';
import 'diagram-js-minimap/assets/diagram-js-minimap.css';

const SYNC_DELAY_MS = 700;
const HIGHLIGHT_CLASS = 'ba-highlight';
const PROBLEM_CLASS = 'ba-problem';

/** Minimal surface of the diagram-js services this module uses. */
interface CanvasService {
  zoom(level?: number | string, center?: unknown): number;
  addMarker(element: string | Element, marker: string): void;
  removeMarker(element: string | Element, marker: string): void;
  getRootElement(): Element;
}
interface ElementRegistryService {
  get(id: string): Element | undefined;
  getAll(): Element[];
}
interface SelectionService {
  select(element: Element | Element[] | null): void;
  get(): Element[];
}
interface CommandStackService {
  undo(): void;
  redo(): void;
  canUndo(): boolean;
  canRedo(): boolean;
}
interface ModelingService {
  updateProperties(element: Element, properties: Record<string, unknown>): void;
  updateModdleProperties(
    element: Element,
    moddleElement: ModdleElement,
    properties: Record<string, unknown>,
  ): void;
  updateLabel(element: Element, text: string): void;
  removeElements(elements: Element[]): void;
  moveElements(elements: Element[], delta: { x: number; y: number }, target?: Element): void;
}
interface BpmnFactoryService {
  create(type: string, attrs?: Record<string, unknown>): ModdleElement;
}

/** The moddle (XML-backed) side of an element. */
interface ModdleElement {
  $type: string;
  id?: string;
  name?: string;
  body?: string;
  text?: string;
  documentation?: { text?: string }[];
  eventDefinitions?: ModdleElement[];
  conditionExpression?: ModdleElement;
  default?: ModdleElement;
  timeDuration?: ModdleElement;
  timeCycle?: ModdleElement;
  timeDate?: ModdleElement;
  [key: string]: unknown;
}

/** What the properties panel needs to know about the selected element. */
export interface ElementSnapshot {
  id: string;
  type: string;
  name: string;
  documentation: string;
  eventDefinitionType: string;
  timer: string;
  condition: string;
  isDefaultFlow: boolean;
  defaultFlowId: string;
  laneId: string;
  laneName: string;
  incoming: { id: string; name: string }[];
  outgoing: { id: string; name: string }[];
  isConnection: boolean;
}
interface ElementFactoryService {
  createShape(attrs: Record<string, unknown>): Element;
}
interface CreateService {
  start(event: Event, shape: Element | Element[], context?: unknown): void;
}
interface ToolService {
  activateHand?(event: Event, reactivate?: boolean): void;
  activateSelection?(event: Event, autoActivate?: boolean): void;
  start?(event: Event): void;
}
interface CopyPasteService {
  copy(elements: Element[]): unknown;
  paste(context?: unknown): unknown;
}
interface BpmnReplaceService {
  replaceElement(element: Element, target: Record<string, unknown>): Element;
}
export interface ModelerApi {
  ready: boolean;
  canUndo: boolean;
  canRedo: boolean;
  zoom: number;
  undo: () => void;
  redo: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  zoomTo: (level: number) => void;
  fit: () => void;
  removeSelection: () => void;
  copySelection: () => void;
  paste: () => void;
  selectById: (id: string | null) => void;
  startCreate: (event: React.DragEvent | React.MouseEvent, spec: ElementSpec) => void;
  activateTool: (tool: 'hand' | 'lasso' | 'space' | 'connect', event: React.MouseEvent) => void;
  rename: (id: string, name: string) => void;
  changeType: (id: string, type: string, eventDefinitionType?: string) => void;
  setProperties: (id: string, properties: Record<string, unknown>) => void;
  moveToLane: (id: string, laneId: string) => void;
  inspect: (id: string) => ElementSnapshot | null;
  setDocumentation: (id: string, text: string) => void;
  setCondition: (flowId: string, condition: string) => void;
  setDefaultFlow: (gatewayId: string, flowId: string | null) => void;
  setTimer: (eventId: string, value: string) => void;
  lanes: () => { id: string; name: string }[];
  exportXml: () => Promise<string>;
  exportSvg: () => Promise<string>;
  elementIds: () => string[];
}

function referenceList(value: unknown): { id: string; name: string }[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const reference = item as ModdleElement;
    return { id: reference.id ?? '', name: reference.name ?? '' };
  });
}

function isDefaultOf(registry: ElementRegistryService | null, flow: ModdleElement): boolean {
  if (flow.$type !== 'bpmn:SequenceFlow' || !registry) return false;
  const source = flow.sourceRef as ModdleElement | undefined;
  return Boolean(source?.default && source.default.id === flow.id);
}

export function useModeler(container: React.RefObject<HTMLDivElement | null>): ModelerApi {
  const modelerRef = useRef<BpmnModeler | null>(null);
  const lastXmlRef = useRef<string>('');
  const timerRef = useRef<number | null>(null);

  const [ready, setReady] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [zoom, setZoom] = useState(1);

  const bpmn = useStudio((state) => state.bpmn);
  const highlighted = useStudio((state) => state.highlighted);
  const selectedId = useStudio((state) => state.selectedId);
  const diagram = useStudio((state) => state.diagram);

  const service = useCallback(<T,>(name: string): T | null => {
    const modeler = modelerRef.current;
    if (!modeler) return null;
    try {
      return modeler.get<T>(name);
    } catch {
      return null;
    }
  }, []);

  // -- lifecycle -----------------------------------------------------------

  useEffect(() => {
    if (!container.current) return;
    const modeler = new BpmnModeler({
      container: container.current,
      additionalModules: [minimapModule as never],
      minimap: { open: false },
      // Keyboard binding is implicit in current diagram-js; passing bindTo
      // makes it refuse the whole configuration.
    });
    modelerRef.current = modeler;

    const refreshHistory = () => {
      const stack = modeler.get<CommandStackService>('commandStack');
      setCanUndo(stack.canUndo());
      setCanRedo(stack.canRedo());
    };

    const scheduleSync = () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(async () => {
        try {
          const { xml } = await modeler.saveXML({ format: true });
          if (!xml || xml === lastXmlRef.current) return;
          lastXmlRef.current = xml;
          await useStudio.getState().syncFromModeler(xml);
        } catch {
          /* an intermediate state that cannot serialise: wait for the next edit */
        }
      }, SYNC_DELAY_MS);
    };

    modeler.on('commandStack.changed', () => {
      refreshHistory();
      useStudio.getState().markDirty();
      scheduleSync();
    });
    modeler.on('selection.changed', (event: unknown) => {
      const selection = (event as { newSelection?: Element[] }).newSelection ?? [];
      useStudio.getState().select(selection.length === 1 ? (selection[0]?.id ?? null) : null);
    });
    modeler.on('canvas.viewbox.changed', () => {
      const canvas = modeler.get<CanvasService>('canvas');
      setZoom(canvas.zoom());
    });

    setReady(true);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      modeler.destroy();
      modelerRef.current = null;
      setReady(false);
    };
  }, [container]);

  // -- inbound: XML changed somewhere else ---------------------------------

  useEffect(() => {
    const modeler = modelerRef.current;
    if (!modeler || !ready || !bpmn || bpmn === lastXmlRef.current) return;
    let cancelled = false;
    void (async () => {
      try {
        await modeler.importXML(bpmn);
        if (cancelled) return;
        lastXmlRef.current = bpmn;
        const canvas = modeler.get<CanvasService>('canvas');
        canvas.zoom('fit-viewport', 'auto');
        setZoom(canvas.zoom());
      } catch (error) {
        useStudio
          .getState()
          .notify('error', `Не удалось открыть диаграмму: ${(error as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bpmn, ready]);

  // -- markers: text ↔ diagram link and validation problems ----------------

  useEffect(() => {
    const canvas = service<CanvasService>('canvas');
    const registry = service<ElementRegistryService>('elementRegistry');
    if (!canvas || !registry) return;
    const marked = highlighted.filter((id) => registry.get(id));
    marked.forEach((id) => canvas.addMarker(id, HIGHLIGHT_CLASS));
    return () => marked.forEach((id) => registry.get(id) && canvas.removeMarker(id, HIGHLIGHT_CLASS));
  }, [highlighted, service, bpmn]);

  useEffect(() => {
    const canvas = service<CanvasService>('canvas');
    const registry = service<ElementRegistryService>('elementRegistry');
    if (!canvas || !registry || !diagram) return;
    const problems = diagram.validation.diagnostics
      .filter((item) => item.severity === 'error' && item.elementId)
      .map((item) => item.elementId as string)
      .filter((id) => registry.get(id));
    problems.forEach((id) => canvas.addMarker(id, PROBLEM_CLASS));
    return () => problems.forEach((id) => registry.get(id) && canvas.removeMarker(id, PROBLEM_CLASS));
  }, [diagram, service, bpmn]);

  // -- outbound selection --------------------------------------------------

  useEffect(() => {
    const registry = service<ElementRegistryService>('elementRegistry');
    const selection = service<SelectionService>('selection');
    if (!registry || !selection) return;
    const current = selection.get();
    if (!selectedId) {
      if (current.length) selection.select(null);
      return;
    }
    if (current.length === 1 && current[0]?.id === selectedId) return;
    const element = registry.get(selectedId);
    if (element) selection.select(element);
  }, [selectedId, service]);

  // -- imperative API ------------------------------------------------------

  const withElement = useCallback(
    (id: string, action: (element: Element, modeling: ModelingService) => void) => {
      const registry = service<ElementRegistryService>('elementRegistry');
      const modeling = service<ModelingService>('modeling');
      const element = registry?.get(id);
      if (element && modeling) action(element, modeling);
    },
    [service],
  );

  const applyZoom = useCallback(
    (next: number | string) => {
      const canvas = service<CanvasService>('canvas');
      if (!canvas) return;
      canvas.zoom(next, next === 'fit-viewport' ? 'auto' : undefined);
      setZoom(canvas.zoom());
    },
    [service],
  );

  return {
    ready,
    canUndo,
    canRedo,
    zoom,
    undo: () => service<CommandStackService>('commandStack')?.undo(),
    redo: () => service<CommandStackService>('commandStack')?.redo(),
    zoomIn: () => applyZoom(Math.min(4, Number((zoom + 0.2).toFixed(2)))),
    zoomOut: () => applyZoom(Math.max(0.2, Number((zoom - 0.2).toFixed(2)))),
    zoomTo: (level: number) => applyZoom(level),
    fit: () => applyZoom('fit-viewport'),

    removeSelection: () => {
      const selection = service<SelectionService>('selection');
      const modeling = service<ModelingService>('modeling');
      const elements = selection?.get() ?? [];
      if (elements.length && modeling) modeling.removeElements([...elements]);
    },

    copySelection: () => {
      const selection = service<SelectionService>('selection');
      const copyPaste = service<CopyPasteService>('copyPaste');
      const elements = selection?.get() ?? [];
      if (elements.length && copyPaste) copyPaste.copy([...elements]);
    },

    paste: () => service<CopyPasteService>('copyPaste')?.paste(),

    selectById: (id) => useStudio.getState().select(id),

    startCreate: (event, spec) => {
      const factory = service<ElementFactoryService>('elementFactory');
      const create = service<CreateService>('create');
      if (!factory || !create) return;
      const attrs: Record<string, unknown> = { type: spec.type };
      if (spec.eventDefinitionType) attrs.eventDefinitionType = spec.eventDefinitionType;
      if (spec.isExpanded !== undefined) attrs.isExpanded = spec.isExpanded;
      create.start(event.nativeEvent, factory.createShape(attrs));
    },

    activateTool: (tool, event) => {
      const name =
        tool === 'hand'
          ? 'handTool'
          : tool === 'lasso'
            ? 'lassoTool'
            : tool === 'space'
              ? 'spaceTool'
              : 'globalConnect';
      const instance = service<ToolService>(name);
      if (!instance) return;
      const native = event.nativeEvent;
      if (tool === 'hand') instance.activateHand?.(native);
      else if (tool === 'connect') instance.start?.(native);
      else instance.activateSelection?.(native);
    },

    rename: (id, name) =>
      withElement(id, (element, modeling) => {
        modeling.updateLabel(element, name);
      }),

    changeType: (id, type, eventDefinitionType) => {
      const registry = service<ElementRegistryService>('elementRegistry');
      const replace = service<BpmnReplaceService>('bpmnReplace');
      const element = registry?.get(id);
      if (!element || !replace) return;
      const target: Record<string, unknown> = { type };
      if (eventDefinitionType) target.eventDefinitionType = eventDefinitionType;
      if (type === 'bpmn:SubProcess') target.isExpanded = false;
      const replaced = replace.replaceElement(element, target);
      useStudio.getState().select(replaced?.id ?? null);
    },

    setProperties: (id, properties) =>
      withElement(id, (element, modeling) => {
        modeling.updateProperties(element, properties);
      }),

    moveToLane: (id, laneId) => {
      const registry = service<ElementRegistryService>('elementRegistry');
      const modeling = service<ModelingService>('modeling');
      const element = registry?.get(id);
      const lane = registry?.get(laneId);
      if (!element || !lane || !modeling) return;
      // Moving an element into a lane is a move to the lane's vertical centre;
      // bpmn-js re-parents it and rewrites the flowNodeRef itself.
      const elementHeight = element.height ?? 0;
      const laneHeight = lane.height ?? 0;
      const dy = (lane.y ?? 0) + laneHeight / 2 - (element.y ?? 0) - elementHeight / 2;
      modeling.moveElements([element], { x: 0, y: dy }, lane);
    },

    inspect: (id) => {
      const registry = service<ElementRegistryService>('elementRegistry');
      const element = registry?.get(id);
      if (!element) return null;
      const business = (element as unknown as { businessObject: ModdleElement }).businessObject;
      const definition = business.eventDefinitions?.[0];
      const parent = (element as unknown as { parent?: { id?: string; businessObject?: ModdleElement } })
        .parent;
      const isLane = parent?.businessObject?.$type === 'bpmn:Lane';
      return {
        id: business.id ?? id,
        type: business.$type,
        name: business.name ?? '',
        documentation: business.documentation?.[0]?.text ?? '',
        eventDefinitionType: definition?.$type ?? '',
        timer:
          definition?.timeDuration?.body ??
          definition?.timeCycle?.body ??
          definition?.timeDate?.body ??
          '',
        condition: business.conditionExpression?.body ?? '',
        isDefaultFlow: isDefaultOf(registry, business),
        defaultFlowId: business.default?.id ?? '',
        laneId: isLane ? (parent?.id ?? '') : '',
        laneName: isLane ? (parent?.businessObject?.name ?? '') : '',
        incoming: referenceList(business.incoming),
        outgoing: referenceList(business.outgoing),
        isConnection: business.$type === 'bpmn:SequenceFlow' || business.$type === 'bpmn:MessageFlow',
      };
    },

    setDocumentation: (id, text) => {
      const factory = service<BpmnFactoryService>('bpmnFactory');
      withElement(id, (element, modeling) => {
        modeling.updateProperties(element, {
          documentation: text.trim() && factory ? [factory.create('bpmn:Documentation', { text })] : [],
        });
      });
    },

    setCondition: (flowId, condition) => {
      const factory = service<BpmnFactoryService>('bpmnFactory');
      withElement(flowId, (element, modeling) => {
        modeling.updateProperties(element, {
          conditionExpression:
            condition.trim() && factory
              ? factory.create('bpmn:FormalExpression', { body: condition })
              : undefined,
        });
      });
    },

    setDefaultFlow: (gatewayId, flowId) => {
      const registry = service<ElementRegistryService>('elementRegistry');
      withElement(gatewayId, (element, modeling) => {
        const flow = flowId ? registry?.get(flowId) : null;
        const business = flow
          ? (flow as unknown as { businessObject: ModdleElement }).businessObject
          : undefined;
        modeling.updateProperties(element, { default: business ?? undefined });
        // The BPMN spec forbids a condition on a default flow.
        if (flow && business?.conditionExpression) {
          modeling.updateProperties(flow, { conditionExpression: undefined });
        }
      });
    },

    setTimer: (eventId, value) => {
      const factory = service<BpmnFactoryService>('bpmnFactory');
      const registry = service<ElementRegistryService>('elementRegistry');
      const modeling = service<ModelingService>('modeling');
      const element = registry?.get(eventId);
      if (!element || !modeling || !factory) return;
      const business = (element as unknown as { businessObject: ModdleElement }).businessObject;
      const definition = business.eventDefinitions?.[0];
      if (!definition) return;
      // A repeating expression is a cycle, a duration starts with P.
      const isCycle = !/^P/i.test(value.trim()) && value.trim().length > 0;
      modeling.updateModdleProperties(element, definition, {
        timeDuration: !isCycle && value.trim() ? factory.create('bpmn:FormalExpression', { body: value }) : undefined,
        timeCycle: isCycle ? factory.create('bpmn:FormalExpression', { body: value }) : undefined,
      });
    },

    lanes: () => {
      const registry = service<ElementRegistryService>('elementRegistry');
      return (registry?.getAll() ?? [])
        .filter(
          (element) =>
            (element as unknown as { businessObject?: ModdleElement }).businessObject?.$type ===
            'bpmn:Lane',
        )
        .map((element) => ({
          id: element.id,
          name:
            (element as unknown as { businessObject: ModdleElement }).businessObject.name ??
            element.id,
        }));
    },

    exportXml: async () => {
      const modeler = modelerRef.current;
      if (!modeler) return '';
      const { xml } = await modeler.saveXML({ format: true });
      return xml ?? '';
    },

    exportSvg: async () => {
      const modeler = modelerRef.current;
      if (!modeler) return '';
      const { svg } = await modeler.saveSVG();
      return svg ?? '';
    },

    elementIds: () => service<ElementRegistryService>('elementRegistry')?.getAll().map((e) => e.id) ?? [],
  };
}
