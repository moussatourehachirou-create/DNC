import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  api,
  BASIS_LABELS,
  fcfa,
  LEVEL_LABELS,
  priceFor,
  type PlanNode,
  type PriceBasis,
  type PriceHit,
  type Proposal,
} from "../api";
import { useSelection } from "../context";

function flatten(nodes: PlanNode[], depth = 0, out: { node: PlanNode; depth: number }[] = []) {
  for (const node of nodes) {
    out.push({ node, depth });
    flatten(node.children, depth + 1, out);
  }
  return out;
}

function PriceSearch({ onPick }: { onPick: (hit: PriceHit) => void }) {
  const [q, setQ] = useState("");
  const hits = useQuery({ queryKey: ["prices", q], queryFn: () => api.searchPrices(q), enabled: q.length >= 3 });
  return (
    <div>
      <input
        placeholder="Chercher dans l'e-répertoire (ex. carburant, per diem, rame papier)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%" }}
      />
      {hits.data && hits.data.length > 0 && (
        <div className="table-wrap" style={{ maxHeight: 220, overflow: "auto", marginTop: 6 }}>
          <table>
            <tbody>
              {hits.data.map((h) => (
                <tr key={h.id} onClick={() => onPick(h)} style={{ cursor: "pointer" }}>
                  <td>
                    {h.label}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {h.code} · nature {h.nature} {h.nature_label ? `(${h.nature_label})` : ""}
                    </div>
                  </td>
                  <td>{h.unit}</td>
                  <td className="num">
                    {h.price_min != null ? `BI ${fcfa(h.price_min)} – BS ${fcfa(h.price_max)}` : fcfa(h.unit_price)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AddLine({
  node,
  defaultBasis,
  onDone,
}: {
  node: PlanNode;
  defaultBasis: PriceBasis | null;
  onDone: () => void;
}) {
  const [label, setLabel] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState("U");
  const [unitPrice, setUnitPrice] = useState(0);
  const [nature, setNature] = useState("");
  const [reference, setReference] = useState<string | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [basis, setBasis] = useState<PriceBasis | "libre" | null>(null);
  const chooseBasis = (value: PriceBasis | "libre") => {
    setBasis(value);
    if (range && value !== "libre") setUnitPrice(value === "bi" ? range[0] : range[1]);
  };
  const [mode, setMode] = useState("direct");
  const [month, setMonth] = useState(node.start_month ?? 1);
  const create = useMutation({
    mutationFn: () =>
      api.createLine(node.id, {
        label,
        quantity,
        unit,
        unit_price: unitPrice,
        budget_line: nature || null,
        price_source: reference ? "repertoire" : "saisie",
        price_reference: reference,
        price_basis: range ? basis : null,
        execution_mode: mode,
        need_month: month,
      }),
    onSuccess: onDone,
  });
  const outOfRange = range && (unitPrice > range[1] || unitPrice < range[0]);

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <strong>Ajouter une ressource</strong>
      <PriceSearch
        onPick={(h) => {
          setLabel(h.label);
          setUnit(h.unit);
          setNature(h.nature ?? "");
          setReference(h.code);
          const hasRange = h.price_min != null && h.price_max != null;
          setRange(hasRange ? [h.price_min!, h.price_max!] : null);
          setBasis(hasRange ? defaultBasis : null);
          setUnitPrice(priceFor(h, defaultBasis) ?? 0);
          setMode(["6114", "6012"].includes(h.nature ?? "") ? "direct" : "indirect");
        }}
      />
      <div className="row" style={{ marginTop: 8 }}>
        <input placeholder="Libellé" value={label} onChange={(e) => setLabel(e.target.value)} style={{ flex: 2 }} />
        <input value={quantity} onChange={(e) => setQuantity(e.target.value)} style={{ width: 80 }} title="Quantité" />
        <input value={unit} onChange={(e) => setUnit(e.target.value)} style={{ width: 70 }} title="Unité" />
        <input
          type="number"
          value={unitPrice}
          onChange={(e) => setUnitPrice(Number(e.target.value))}
          style={{ width: 120 }}
          title="Prix unitaire"
        />
        <input placeholder="Nature" value={nature} onChange={(e) => setNature(e.target.value)} style={{ width: 80 }} />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="direct">Direct</option>
          <option value="indirect">Indirect (marché)</option>
          <option value="mixte">Mixte</option>
        </select>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} title="Mois de besoin">
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              Mois {i + 1}
            </option>
          ))}
        </select>
        <button
          className="primary"
          disabled={!label || create.isPending || (!!range && !basis)}
          onClick={() => create.mutate()}
        >
          Ajouter
        </button>
      </div>
      {range && (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted">Prix retenu :</span>
          {(["bi", "bs"] as PriceBasis[]).map((b) => (
            <label key={b} className="row" style={{ gap: 4 }}>
              <input type="radio" checked={basis === b} onChange={() => chooseBasis(b)} />
              {BASIS_LABELS[b]} — {fcfa(b === "bi" ? range[0] : range[1])}
            </label>
          ))}
          <label className="row" style={{ gap: 4 }}>
            <input type="radio" checked={basis === "libre"} onChange={() => chooseBasis("libre")} />
            Prix libre
          </label>
          {!basis && <span className="badge soumis_a_validation">choisissez la borne</span>}
        </div>
      )}
      {outOfRange && range && (
        <p className="notice" style={{ marginTop: 8 }}>
          Prix hors de la fourchette de l'e-répertoire ({fcfa(range[0])} – {fcfa(range[1])}).
        </p>
      )}
      {create.error && <p className="error">{create.error.message}</p>}
    </div>
  );
}

function ProposalPanel({
  node,
  defaultBasis,
  onApplied,
}: {
  node: PlanNode;
  defaultBasis: PriceBasis | null;
  onApplied: () => void;
}) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [basis, setBasis] = useState<PriceBasis | null>(defaultBasis);
  const unitPrice = (r: Proposal["tasks"][number]["resources"][number]) =>
    r.price_min != null ? priceFor(r, basis) : r.unit_price;
  const missingBasis = proposal?.tasks.some((t) => t.resources.some((r) => r.price_min != null)) && !basis;
  const [accepted, setAccepted] = useState<Record<number, boolean>>({});
  const propose = useMutation({
    mutationFn: () => api.propose(node.id),
    onSuccess: (p) => {
      setProposal(p);
      setAccepted(Object.fromEntries(p.tasks.map((_, i) => [i, true])));
    },
  });
  const apply = useMutation({
    mutationFn: () =>
      api.applyProposal(
        node.id,
        proposal!.tasks
          .filter((_, i) => accepted[i])
          .map((t) => ({
            label: t.label,
            start_month: t.start_month,
            end_month: t.end_month,
            weight: t.weight,
            resources: t.resources.map((r) => ({
              label: r.label,
              quantity: r.quantity,
              unit: r.unit,
              unit_price: unitPrice(r) ?? 0,
              budget_line: r.budget_line,
              price_source: r.price_source,
              price_reference: r.price_reference,
              price_basis: r.price_min != null ? basis : null,
              execution_mode: r.execution_mode,
              market_category: r.market_category,
              need_month: r.need_month,
            })),
          })),
      ),
    onSuccess: () => {
      setProposal(null);
      onApplied();
    },
  });

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Proposition de tâches et de ressources</strong>
        <button onClick={() => propose.mutate()} disabled={propose.isPending}>
          {propose.isPending ? "L'agent travaille…" : "Proposer avec l'IA"}
        </button>
      </div>
      {propose.error && <p className="error">{propose.error.message}</p>}
      {proposal && (
        <>
          <p className="muted">
            {proposal.mode === "ia" ? "Proposition de l'agent" : "Proposition reprise de l'historique"} · total estimé{" "}
            {fcfa(proposal.total)}. {proposal.remarks}
          </p>
          <div className="row">
            <span className="muted">Borne de prix pour cette proposition :</span>
            <select value={basis ?? ""} onChange={(e) => setBasis((e.target.value || null) as PriceBasis | null)}>
              <option value="">— à choisir —</option>
              <option value="bi">{BASIS_LABELS.bi}</option>
              <option value="bs">{BASIS_LABELS.bs}</option>
            </select>
          </div>
          {proposal.tasks.map((task, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
              <label className="row">
                <input
                  type="checkbox"
                  checked={!!accepted[i]}
                  onChange={(e) => setAccepted({ ...accepted, [i]: e.target.checked })}
                />
                <strong>{task.label}</strong>
                <span className="muted">
                  mois {task.start_month}–{task.end_month}
                </span>
              </label>
              {task.resources.length > 0 && (
                <table style={{ marginTop: 6 }}>
                  <tbody>
                    {task.resources.map((r, j) => (
                      <tr key={j}>
                        <td>
                          {r.label}
                          <div className="muted" style={{ fontSize: 12 }}>
                            {r.justification}
                          </div>
                          {r.needs_review
                            .filter((m) => !(basis && m.startsWith("borne de prix")))
                            .map((m) => (
                            <div key={m} className="badge soumis_a_validation" style={{ marginTop: 2 }}>
                              {m}
                            </div>
                          ))}
                        </td>
                        <td className="num">
                          {r.quantity} {r.unit}
                        </td>
                        <td className="num">
                          {fcfa(unitPrice(r))}
                          {r.price_min != null && (
                            <div className="muted" style={{ fontSize: 12 }}>
                              BI {fcfa(r.price_min)} – BS {fcfa(r.price_max)}
                            </div>
                          )}
                        </td>
                        <td className="num">
                          {unitPrice(r) != null ? fcfa(Number(r.quantity) * (unitPrice(r) ?? 0)) : "—"}
                        </td>
                        <td>{r.budget_line ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
          <div className="row" style={{ marginTop: 12 }}>
            <button
              className="primary"
              onClick={() => apply.mutate()}
              disabled={apply.isPending || missingBasis}
              title={missingBasis ? "Choisissez la borne de prix" : undefined}
            >
              Ajouter les tâches retenues au PTA
            </button>
            <button onClick={() => setProposal(null)}>Écarter</button>
          </div>
        </>
      )}
    </div>
  );
}

export default function PlanPage() {
  const { versionId, organisationId } = useSelection();
  const queryClient = useQueryClient();
  const orgs = useQuery({ queryKey: ["organisations"], queryFn: api.organisations });
  const defaultBasis = orgs.data?.find((o) => o.id === organisationId)?.price_basis ?? null;
  const tree = useQuery({ queryKey: ["tree", versionId], queryFn: () => api.tree(versionId!), enabled: !!versionId });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [newActivity, setNewActivity] = useState("");
  const rows = useMemo(() => flatten(tree.data ?? []), [tree.data]);
  const selected = rows.find((r) => r.node.id === selectedId)?.node ?? null;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["tree", versionId] });
  const addActivity = useMutation({
    mutationFn: () =>
      api.createNode(versionId!, {
        level: selected && selected.level !== "tache" ? "activite" : "activite",
        label: newActivity,
        parent_id: selected && !["activite", "tache"].includes(selected.level) ? selected.id : null,
      }),
    onSuccess: (node) => {
      setNewActivity("");
      refresh();
      setSelectedId(node.id);
    },
  });
  const deleteLine = useMutation({ mutationFn: api.deleteLine, onSuccess: refresh });

  if (!versionId) return <p className="notice">Choisissez une structure et une version de PTA dans le menu.</p>;
  const total = (tree.data ?? []).reduce((sum, n) => sum + n.cost, 0);
  const visible = filter
    ? rows.filter((r) => r.node.label.toLowerCase().includes(filter.toLowerCase()) || r.node.code?.startsWith(filter))
    : rows;

  return (
    <>
      <h1>PTA — activités, tâches et coûts</h1>
      <p className="muted">
        Total programmé : <strong>{fcfa(total)}</strong> · {rows.length} éléments
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <input
          placeholder="Nouvelle activité (une phrase suffit)"
          value={newActivity}
          onChange={(e) => setNewActivity(e.target.value)}
          style={{ flex: 1, minWidth: 280 }}
        />
        <button className="primary" disabled={!newActivity} onClick={() => addActivity.mutate()}>
          Créer l'activité
        </button>
      </div>
      <div className="tree">
        <div className="card">
          <input
            placeholder="Filtrer par libellé ou code"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: "100%", marginBottom: 8 }}
          />
          <div className="tree-list">
            {visible.slice(0, 1500).map(({ node, depth }) => (
              <div
                key={node.id}
                className={`tree-item ${node.id === selectedId ? "selected" : ""}`}
                style={{ paddingLeft: 8 + depth * 14 }}
                onClick={() => setSelectedId(node.id)}
              >
                <span>
                  <span className="lvl">{LEVEL_LABELS[node.level] ?? node.level}</span>
                  {node.code && <span className="muted">{node.code} · </span>}
                  {node.label}
                </span>
                <span className="num muted">{node.cost ? fcfa(node.cost) : ""}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          {!selected && <div className="card muted">Sélectionnez un élément de l'arbre.</div>}
          {selected && (
            <>
              <div className="card">
                <div className="muted">{LEVEL_LABELS[selected.level]}</div>
                <h2 style={{ marginTop: 0 }}>{selected.label}</h2>
                <p>
                  Coût : <strong>{fcfa(selected.cost)}</strong>
                  {selected.imputation && <> · imputation {selected.imputation}</>}
                  {selected.execution_mode && <> · mode {selected.execution_mode}</>}
                </p>
                {selected.lines.length > 0 && (
                  <table>
                    <thead>
                      <tr>
                        <th>Ressource</th>
                        <th className="num">Qté</th>
                        <th className="num">PU</th>
                        <th className="num">Coût</th>
                        <th>Nature</th>
                        <th>Mode</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {selected.lines.map((l) => (
                        <tr key={l.id}>
                          <td>
                            {l.label}
                            {l.price_reference && (
                              <div className="muted" style={{ fontSize: 12 }}>
                                e-répertoire {l.price_reference}
                                {l.price_basis && ` · ${l.price_basis === "libre" ? "prix libre" : l.price_basis.toUpperCase()}`}
                              </div>
                            )}
                          </td>
                          <td className="num">
                            {l.quantity} {l.unit}
                          </td>
                          <td className="num">{fcfa(l.unit_price)}</td>
                          <td className="num">{fcfa(l.cost)}</td>
                          <td>{l.budget_line ?? "—"}</td>
                          <td>{l.execution_mode}</td>
                          <td>
                            <button onClick={() => deleteLine.mutate(l.id)} title="Supprimer">
                              ✕
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              {selected.level === "activite" && (
                <ProposalPanel key={selected.id} node={selected} defaultBasis={defaultBasis} onApplied={refresh} />
              )}
              {["activite", "tache"].includes(selected.level) && (
                <AddLine key={selected.id} node={selected} defaultBasis={defaultBasis} onDone={refresh} />
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
