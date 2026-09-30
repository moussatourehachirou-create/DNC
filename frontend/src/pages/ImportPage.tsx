import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fcfa, LEVEL_LABELS, type ImportSummary } from "../api";
import { useSelection } from "../context";

const ANOMALY_LABELS: Record<string, string> = {
  code_illisible: "Code illisible",
  code_duplique: "Code en double",
  libelle_vide: "Libellé vide",
  total_incoherent: "Total incohérent",
  montant_negatif: "Montant négatif",
  montant_aberrant: "Montant aberrant",
  niveau_ambigu: "Niveau ambigu",
};

export default function ImportPage() {
  const { organisationId, setVersionId } = useSelection();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [preview, setPreview] = useState<ImportSummary | null>(null);

  const previewMutation = useMutation({
    mutationFn: () => api.previewImport(file!, sheet || undefined),
    onSuccess: setPreview,
  });
  const importMutation = useMutation({
    mutationFn: () => api.importPta(file!, organisationId!, year, `PTA ${year} (import)`, sheet || undefined),
    onSuccess: (summary) => {
      queryClient.invalidateQueries({ queryKey: ["versions", organisationId] });
      if (summary.version_id) setVersionId(summary.version_id);
      navigate("/pta");
    },
  });

  const anomalyCounts = preview?.anomalies.reduce<Record<string, number>>((acc, a) => {
    acc[a.code] = (acc[a.code] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <h1>Importer un PTA Excel</h1>
      <p className="muted">
        BIE reconnaît la ligne d'en-tête, les colonnes AE/CP par source, l'unité (FCFA ou milliers) et la hiérarchie des
        codes. Rien n'est enregistré avant votre validation.
      </p>
      {!organisationId && <p className="notice">Choisissez d'abord une structure dans le menu.</p>}
      <div className="card row" style={{ marginTop: 12 }}>
        <input type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input placeholder="Onglet (facultatif)" value={sheet} onChange={(e) => setSheet(e.target.value)} />
        <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }} />
        <button disabled={!file || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          {previewMutation.isPending ? "Analyse…" : "Aperçu"}
        </button>
      </div>
      {previewMutation.error && <p className="error">{previewMutation.error.message}</p>}

      {preview && (
        <>
          <h2>Aperçu — onglet « {preview.sheet} »</h2>
          <div className="grid kpis">
            <div className="card kpi">
              <div className="label">Nœuds reconnus</div>
              <div className="value">{preview.nodes}</div>
            </div>
            <div className="card kpi">
              <div className="label">Total CP importé</div>
              <div className="value">{fcfa(preview.total_cp)}</div>
            </div>
            <div className="card kpi">
              <div className="label">Unité détectée</div>
              <div className="value">{preview.unit_multiplier === 1000 ? "Milliers FCFA" : "FCFA"}</div>
            </div>
            <div className="card kpi">
              <div className="label">Anomalies</div>
              <div className="value">{preview.anomalies.length}</div>
            </div>
          </div>
          <div className="grid kpis" style={{ marginTop: 12 }}>
            <div className="card">
              <strong>Niveaux</strong>
              <table>
                <tbody>
                  {Object.entries(preview.levels).map(([level, count]) => (
                    <tr key={level}>
                      <td>{LEVEL_LABELS[level] ?? level}</td>
                      <td className="num">{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <strong>Anomalies par type</strong>
              <table>
                <tbody>
                  {Object.entries(anomalyCounts ?? {}).map(([code, count]) => (
                    <tr key={code}>
                      <td>{ANOMALY_LABELS[code] ?? code}</td>
                      <td className="num">{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {preview.anomalies.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary>Détail des anomalies (ligne Excel)</summary>
              <div className="table-wrap" style={{ maxHeight: 320, overflow: "auto" }}>
                <table>
                  <tbody>
                    {preview.anomalies.slice(0, 200).map((a, i) => (
                      <tr key={i}>
                        <td className="num">{a.row ?? "—"}</td>
                        <td>{ANOMALY_LABELS[a.code] ?? a.code}</td>
                        <td>{a.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <div className="row" style={{ marginTop: 16 }}>
            <button
              className="primary"
              disabled={!organisationId || importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              {importMutation.isPending ? "Import…" : "Valider l'import"}
            </button>
            {importMutation.error && <span className="error">{importMutation.error.message}</span>}
          </div>
        </>
      )}
    </>
  );
}
