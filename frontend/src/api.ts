// Client de l'API BIE. Toutes les routes sont préfixées par /api (proxy Vite en dev).

export type PriceBasis = "bi" | "bs";
export type Organisation = { id: string; code: string; name: string; kind: string; price_basis: PriceBasis | null };
export type Version = { id: string; label: string; kind: string; status: string; fiscal_year_id: string };

export type Line = {
  id: string;
  node_id: string;
  label: string;
  quantity: string;
  unit: string;
  unit_price: number;
  cost: number;
  budget_line: string | null;
  funding_source: string;
  execution_mode: string;
  market_category: string | null;
  need_month: number;
  price_source: string;
  price_reference: string | null;
  price_basis: "bi" | "bs" | "libre" | null;
};

export type PlanNode = {
  id: string;
  parent_id: string | null;
  level: string;
  code: string | null;
  label: string;
  imputation: string | null;
  start_month: number | null;
  end_month: number | null;
  execution_mode: string | null;
  origin: string;
  cost: number;
  children: PlanNode[];
  lines: Line[];
};

export type Anomaly = { row: number | null; code: string; message: string };
export type ImportSummary = {
  sheet: string;
  header_row: number;
  unit_multiplier: number;
  nodes: number;
  lines: number;
  total_cp: number;
  levels: Record<string, number>;
  anomalies: Anomaly[];
  version_id: string | null;
};

export type Violation = {
  code: string;
  severity: "avertissement" | "soumis_a_validation" | "bloquant";
  message: string;
  structure_id: string;
  budget_line: string | null;
  line_ids: string[];
};

export type Lot = {
  id: string;
  category: string;
  market_type: string;
  amount: number;
  amount_ht: number;
  procedure: string;
  procedure_code: string;
  control_body: string;
  community_publication: boolean;
  need_date: string;
  launch_date: string;
  preparation_start: string;
  needs: number;
  steps: {
    code: string;
    label: string;
    start: string;
    end: string;
    duration: number;
    unit: "ouvrables" | "calendaires";
    basis: string;
    indicative: boolean;
  }[];
};

export type Analysis = {
  fiscal_year: number;
  totals: { total: number; passe_en_marche: number; execution_directe: number };
  envelopes: {
    budget_line: string;
    funding_source: string;
    authorized: number;
    programmed: number;
    remaining: number;
    consumption_rate: number;
    overrun: number;
  }[];
  lots: Lot[];
  violations: Violation[];
  rules_version: string;
};

export type PriceHit = {
  id: string;
  code: string | null;
  label: string;
  unit: string;
  unit_price: number | null;
  price_min: number | null;
  price_max: number | null;
  nature: string | null;
  nature_label: string | null;
};

export type ProposedResource = {
  label: string;
  quantity: string;
  unit: string;
  unit_price: number | null;
  price_min: number | null;
  price_max: number | null;
  price_source: string;
  price_reference: string | null;
  price_basis: PriceBasis | null;
  budget_line: string | null;
  budget_line_label: string | null;
  execution_mode: string;
  market_category: string | null;
  need_month: number;
  justification: string;
  needs_review: string[];
  cost: number | null;
};

export type Proposal = {
  activity_id: string;
  mode: string;
  total: number;
  sources: string[];
  remarks: string;
  tasks: { label: string; start_month: number; end_month: number; weight: number; resources: ProposedResource[] }[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* corps non JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  organisations: () => request<Organisation[]>("/organisations"),
  createOrganisation: (body: { code: string; name: string; kind: string }) =>
    request<Organisation>("/organisations", json("POST", body)),
  updateOrganisation: (orgId: string, body: { price_basis: PriceBasis }) =>
    request<Organisation>(`/organisations/${orgId}`, json("PATCH", body)),
  versions: (orgId: string) => request<Version[]>(`/organisations/${orgId}/versions`),
  createVersion: (orgId: string, year: number, label: string) => {
    const form = new FormData();
    form.set("year", String(year));
    form.set("label", label);
    return request<Version>(`/organisations/${orgId}/versions`, { method: "POST", body: form });
  },
  previewImport: (file: File, sheet?: string) => {
    const form = new FormData();
    form.set("file", file);
    if (sheet) form.set("sheet", sheet);
    return request<ImportSummary>("/imports/pta/preview", { method: "POST", body: form });
  },
  importPta: (file: File, organisationId: string, year: number, label: string, sheet?: string) => {
    const form = new FormData();
    form.set("file", file);
    form.set("organisation_id", organisationId);
    form.set("year", String(year));
    form.set("label", label);
    if (sheet) form.set("sheet", sheet);
    return request<ImportSummary>("/imports/pta", { method: "POST", body: form });
  },
  tree: (versionId: string) => request<PlanNode[]>(`/versions/${versionId}/tree`),
  createNode: (versionId: string, body: { level: string; label: string; parent_id?: string | null }) =>
    request<PlanNode>(`/versions/${versionId}/nodes`, json("POST", body)),
  createLine: (nodeId: string, body: Partial<Line>) => request<Line>(`/nodes/${nodeId}/lines`, json("POST", body)),
  deleteLine: (lineId: string) => request<void>(`/lines/${lineId}`, { method: "DELETE" }),
  analysis: (versionId: string) => request<Analysis>(`/versions/${versionId}/analysis`),
  setEnvelopes: (versionId: string, rows: { budget_line: string; funding_source: string; authorized: number }[]) =>
    request<void>(`/versions/${versionId}/envelopes`, json("PUT", rows)),
  searchPrices: (q: string) => request<PriceHit[]>(`/prices/search?q=${encodeURIComponent(q)}`),
  loadBundledPrices: () => request<{ items: number; label: string }>("/prices/editions/bundled", { method: "POST" }),
  propose: (nodeId: string) => request<Proposal>(`/nodes/${nodeId}/propose`, { method: "POST" }),
  applyProposal: (nodeId: string, tasks: unknown) =>
    request<PlanNode[]>(`/nodes/${nodeId}/apply-proposal`, json("POST", tasks)),
  exportUrl: (versionId: string, kind: "pta" | "pcc" | "ppm") => `/api/versions/${versionId}/exports/${kind}.xlsx`,
};

export const fcfa = (value: number | null | undefined) =>
  value == null ? "—" : `${new Intl.NumberFormat("fr-FR").format(Math.round(value))} FCFA`;

export const millions = (value: number) =>
  `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(value / 1e6)} M`;

export const LEVEL_LABELS: Record<string, string> = {
  programme: "Programme",
  objectif_specifique: "Objectif spécifique",
  resultat: "Résultat",
  action: "Action",
  activite_budgetaire: "Activité budgétaire",
  activite: "Activité",
  tache: "Tâche",
};

/** Prix d'un article selon la borne choisie ; null si aucune borne n'est choisie. */
export function priceFor(
  hit: { unit_price: number | null; price_min: number | null; price_max: number | null },
  basis: PriceBasis | null,
): number | null {
  if (hit.price_min == null || hit.price_max == null) return hit.unit_price;
  if (basis === "bi") return hit.price_min;
  if (basis === "bs") return hit.price_max;
  return null;
}

export const BASIS_LABELS: Record<PriceBasis, string> = {
  bi: "Borne inférieure (BI)",
  bs: "Borne supérieure (BS)",
};
