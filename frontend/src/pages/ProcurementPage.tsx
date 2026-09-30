import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api, fcfa } from "../api";
import { useSelection } from "../context";

const TYPES: Record<string, string> = {
  T: "Travaux",
  F: "Fournitures",
  S: "Services",
  PI: "Prestations intellectuelles",
  PI_IND: "Consultant individuel",
};

const date = (iso: string) => new Date(iso).toLocaleDateString("fr-FR");

export default function ProcurementPage() {
  const { versionId } = useSelection();
  const [open, setOpen] = useState<string | null>(null);
  const analysis = useQuery({
    queryKey: ["analysis", versionId],
    queryFn: () => api.analysis(versionId!),
    enabled: !!versionId,
  });
  if (!versionId) return <p className="notice">Choisissez une version de PTA dans le menu.</p>;
  if (!analysis.data) return <p className="muted">Calcul en cours…</p>;
  const lots = [...analysis.data.lots].sort((a, b) => a.launch_date.localeCompare(b.launch_date));
  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <h1>Plan de passation des marchés</h1>
      <p className="muted">
        Généré depuis le PTA : les lignes en mode indirect (et la part marché des lignes mixtes) sont regroupées par
        catégorie sur tout l'exercice, ce qui prévient le fractionnement. Procédures et organes de contrôle selon le
        décret n° 2020-599 ({analysis.data.rules_version}) ; délais selon la loi n° 2020-26, les décrets n° 2020-600 et
        2020-605 et le manuel de procédures de l'ARMP. Cliquez sur un lot pour voir son calendrier réglementaire.
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <a className="button primary" href={api.exportUrl(versionId, "ppm")}>
          Exporter le PPM (Excel)
        </a>
        <a className="button" href={api.exportUrl(versionId, "pta")}>
          Exporter le PTA
        </a>
        <a className="button" href={api.exportUrl(versionId, "pcc")}>
          Exporter le PCC
        </a>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Catégorie</th>
              <th>Type</th>
              <th className="num">Montant HT</th>
              <th>Procédure</th>
              <th>Contrôle</th>
              <th>Préparation</th>
              <th>Lancement</th>
              <th>Besoin</th>
              <th className="num">Besoins</th>
            </tr>
          </thead>
          <tbody>
            {lots.map((lot) => (
              <Fragment key={lot.id}>
              <tr onClick={() => setOpen(open === lot.id ? null : lot.id)} style={{ cursor: "pointer" }}>
                <td>
                  {open === lot.id ? "▾" : "▸"} {lot.category.replaceAll("_", " ")}
                </td>
                <td>{TYPES[lot.market_type] ?? lot.market_type}</td>
                <td className="num">{fcfa(lot.amount_ht)}</td>
                <td>{lot.procedure}</td>
                <td>
                  {lot.control_body}
                  {lot.community_publication && <div className="badge">publication UEMOA</div>}
                </td>
                <td>
                  {date(lot.preparation_start)}
                  {lot.preparation_start < today && lot.launch_date >= today && (
                    <div className="badge soumis_a_validation">en retard</div>
                  )}
                </td>
                <td>
                  {date(lot.launch_date)}
                  {lot.launch_date < today && <div className="badge bloquant">dépassé</div>}
                </td>
                <td>{date(lot.need_date)}</td>
                <td className="num">{lot.needs}</td>
              </tr>
              {open === lot.id && (
                <tr>
                  <td colSpan={9} style={{ background: "var(--surface-2)" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Étape</th>
                          <th>Début</th>
                          <th>Fin</th>
                          <th>Délai</th>
                          <th>Base réglementaire</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lot.steps.map((s) => (
                          <tr key={s.code}>
                            <td>{s.label}</td>
                            <td>{date(s.start)}</td>
                            <td>{date(s.end)}</td>
                            <td>
                              {s.duration ? `${s.duration} j. ${s.unit}` : "échéance"}
                              {s.indicative && <div className="badge">indicatif</div>}
                            </td>
                            <td className="muted">{s.basis}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
