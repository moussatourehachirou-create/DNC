import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fcfa } from "../api";
import { useSelection } from "../context";

const SEVERITY_LABELS = {
  bloquant: "Bloquant",
  soumis_a_validation: "À valider",
  avertissement: "Avertissement",
};

export default function AnalysisPage() {
  const { versionId } = useSelection();
  const queryClient = useQueryClient();
  const analysis = useQuery({
    queryKey: ["analysis", versionId],
    queryFn: () => api.analysis(versionId!),
    enabled: !!versionId,
  });
  const [envelopeLine, setEnvelopeLine] = useState("");
  const [envelopeAmount, setEnvelopeAmount] = useState(0);
  const saveEnvelope = useMutation({
    mutationFn: () =>
      api.setEnvelopes(versionId!, [{ budget_line: envelopeLine, funding_source: "BN", authorized: envelopeAmount }]),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analysis", versionId] }),
  });

  if (!versionId) return <p className="notice">Choisissez une version de PTA dans le menu.</p>;
  if (!analysis.data) return <p className="muted">Calcul en cours…</p>;
  const { totals, envelopes, violations } = analysis.data;
  const blocking = violations.filter((v) => v.severity === "bloquant").length;

  return (
    <>
      <h1>Enveloppes et contrôles — exercice {analysis.data.fiscal_year}</h1>
      <div className="grid kpis" style={{ marginTop: 12 }}>
        <div className="card kpi">
          <div className="label">Total programmé</div>
          <div className="value">{fcfa(totals.total)}</div>
        </div>
        <div className="card kpi">
          <div className="label">À passer en marché</div>
          <div className="value">{fcfa(totals.passe_en_marche)}</div>
        </div>
        <div className="card kpi">
          <div className="label">Exécution directe</div>
          <div className="value">{fcfa(totals.execution_directe)}</div>
        </div>
        <div className="card kpi">
          <div className="label">Contrôles bloquants</div>
          <div className="value">{blocking}</div>
        </div>
      </div>

      <h2>Enveloppes par ligne budgétaire</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <input placeholder="Nature (ex. 6013)" value={envelopeLine} onChange={(e) => setEnvelopeLine(e.target.value)} />
        <input
          type="number"
          placeholder="Montant autorisé"
          value={envelopeAmount || ""}
          onChange={(e) => setEnvelopeAmount(Number(e.target.value))}
        />
        <button disabled={!envelopeLine} onClick={() => saveEnvelope.mutate()}>
          Enregistrer l'enveloppe
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ligne</th>
              <th>Source</th>
              <th className="num">Autorisé</th>
              <th className="num">Programmé</th>
              <th className="num">Reliquat</th>
              <th>Consommation</th>
            </tr>
          </thead>
          <tbody>
            {envelopes.map((e) => (
              <tr key={`${e.budget_line}-${e.funding_source}`}>
                <td>{e.budget_line}</td>
                <td>{e.funding_source}</td>
                <td className="num">{fcfa(e.authorized)}</td>
                <td className="num">{fcfa(e.programmed)}</td>
                <td className="num">{fcfa(e.remaining)}</td>
                <td>
                  <div className={`bar ${e.overrun > 0 || e.authorized === 0 ? "over" : ""}`}>
                    <span style={{ width: `${Math.min(e.consumption_rate, 1) * 100}%` }} />
                  </div>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {e.authorized ? `${Math.round(e.consumption_rate * 100)} %` : "sans enveloppe"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Contrôles ({violations.length})</h2>
      <div className="table-wrap">
        <table>
          <tbody>
            {violations.map((v, i) => (
              <tr key={i}>
                <td>
                  <span className={`badge ${v.severity}`}>{SEVERITY_LABELS[v.severity]}</span>
                </td>
                <td>{v.message}</td>
                <td className="muted">{v.line_ids.length} ligne(s)</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
