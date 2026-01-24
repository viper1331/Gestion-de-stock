import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

interface ReportRange {
  start: string;
  end: string;
  bucket: "day" | "week" | "month";
}

interface ReportKpis {
  in_qty: number;
  out_qty: number;
  net_qty: number;
  low_stock_count: number;
  open_orders: number;
}

interface ReportMoveSeriesPoint {
  t: string;
  in: number;
  out: number;
}

interface ReportNetSeriesPoint {
  t: string;
  net: number;
}

interface ReportLowStockSeriesPoint {
  t: string;
  count: number;
}

interface ReportOrderSeriesPoint {
  t: string;
  created: number;
  ordered: number;
  partial: number;
  received: number;
  cancelled: number;
}

interface ReportTopItem {
  sku: string;
  name: string;
  qty: number;
}

interface ReportDataQuality {
  missing_sku: number;
  missing_supplier: number;
  missing_threshold: number;
  abnormal_movements: number;
}

interface ReportOverview {
  module: string;
  range: ReportRange;
  kpis: ReportKpis;
  series: {
    moves: ReportMoveSeriesPoint[];
    net: ReportNetSeriesPoint[];
    low_stock: ReportLowStockSeriesPoint[];
    orders: ReportOrderSeriesPoint[];
  };
  tops: {
    out: ReportTopItem[];
    in: ReportTopItem[];
  };
  data_quality: ReportDataQuality;
}

interface ModuleDefinition {
  key: string;
  label: string;
}

const PERIOD_OPTIONS = [
  { value: "7d", label: "7 jours" },
  { value: "30d", label: "30 jours" },
  { value: "90d", label: "90 jours" },
  { value: "12m", label: "12 mois" },
  { value: "custom", label: "Personnalisé" }
];

const BUCKET_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "day", label: "Jour" },
  { value: "week", label: "Semaine" },
  { value: "month", label: "Mois" }
];

const PIE_COLORS = ["#38bdf8", "#fbbf24", "#34d399", "#f87171"];

const formatNumber = (value: number) => new Intl.NumberFormat("fr-FR").format(value);

const formatDateInput = (value: Date) => value.toISOString().slice(0, 10);

export function ReportsPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });

  const [period, setPeriod] = useState<string>("30d");
  const [startDate, setStartDate] = useState<string>(() =>
    formatDateInput(new Date(Date.now() - 29 * 24 * 60 * 60 * 1000))
  );
  const [endDate, setEndDate] = useState<string>(() => formatDateInput(new Date()));
  const [bucket, setBucket] = useState<string>("auto");
  const [includeDotation, setIncludeDotation] = useState(true);
  const [includeAdjustment, setIncludeAdjustment] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(10);

  const { data: availableModules = [], isFetching: isFetchingModules } = useQuery({
    queryKey: ["available-modules"],
    queryFn: async () => {
      const response = await api.get<ModuleDefinition[]>("/permissions/modules/available");
      return response.data;
    },
    enabled: Boolean(user)
  });

  const accessibleModules = useMemo(() => {
    if (!user) {
      return [];
    }
    if (user.role === "admin") {
      return availableModules;
    }
    return availableModules.filter((entry) => modulePermissions.canAccess(entry.key));
  }, [availableModules, modulePermissions, user]);

  const [selectedModule, setSelectedModule] = useState<string>("");

  useEffect(() => {
    if (!selectedModule && accessibleModules.length > 0) {
      setSelectedModule(accessibleModules[0]?.key ?? "");
    }
  }, [accessibleModules, selectedModule]);

  useEffect(() => {
    if (period === "custom") {
      return;
    }
    const now = new Date();
    const end = formatDateInput(now);
    let start = new Date(now);
    if (period === "7d") {
      start.setDate(now.getDate() - 6);
    } else if (period === "30d") {
      start.setDate(now.getDate() - 29);
    } else if (period === "90d") {
      start.setDate(now.getDate() - 89);
    } else if (period === "12m") {
      start.setFullYear(now.getFullYear() - 1);
      start.setDate(now.getDate() + 1);
    }
    setStartDate(formatDateInput(start));
    setEndDate(end);
  }, [period]);

  const canView = user?.role === "admin" || accessibleModules.length > 0;

  const { data: reportData, isFetching, isLoading, error, refetch } = useQuery({
    queryKey: [
      "reports",
      "overview",
      selectedModule,
      startDate,
      endDate,
      bucket,
      includeDotation,
      includeAdjustment
    ],
    queryFn: async () => {
      const response = await api.get<ReportOverview>("/reports/overview", {
        params: {
          module: selectedModule,
          start: startDate,
          end: endDate,
          bucket: bucket === "auto" ? undefined : bucket,
          include_dotation: includeDotation,
          include_adjustment: includeAdjustment
        }
      });
      return response.data;
    },
    enabled: Boolean(canView && selectedModule)
  });

  const orderStatusData = useMemo(() => {
    const totals = (reportData?.series.orders ?? []).reduce(
      (acc, entry) => ({
        ordered: acc.ordered + entry.ordered,
        partial: acc.partial + entry.partial,
        received: acc.received + entry.received,
        cancelled: acc.cancelled + entry.cancelled
      }),
      { ordered: 0, partial: 0, received: 0, cancelled: 0 }
    );
    return [
      { name: "Commandé", value: totals.ordered },
      { name: "Partiel", value: totals.partial },
      { name: "Reçu", value: totals.received },
      { name: "Annulé", value: totals.cancelled }
    ];
  }, [reportData?.series.orders]);

  useEffect(() => {
    if (!refetch || !canView) {
      return;
    }
    const interval = Math.max(5, refreshInterval || 10) * 1000;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        refetch();
      }
    }, interval);
    return () => window.clearInterval(timer);
  }, [canView, refreshInterval, refetch, selectedModule, startDate, endDate, bucket]);

  const content = (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Rapports</h2>
        <p className="text-sm text-slate-400">
          Analyse temps réel des mouvements, commandes et qualité de données par module.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-slate-800/70 bg-slate-900/60 p-4 backdrop-blur">
        <label className="text-sm text-slate-300">
          Module du rapport
          <select
            value={selectedModule}
            onChange={(event) => setSelectedModule(event.target.value)}
            className="mt-1 w-48 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            {accessibleModules.map((module) => (
              <option key={module.key} value={module.key}>
                {module.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-slate-300">
          Période
          <select
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            className="mt-1 w-40 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            {PERIOD_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {period === "custom" ? (
          <>
            <label className="text-sm text-slate-300">
              Début
              <AppTextInput
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
                className="mt-1 w-40 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              />
            </label>
            <label className="text-sm text-slate-300">
              Fin
              <AppTextInput
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
                className="mt-1 w-40 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              />
            </label>
          </>
        ) : null}
        <label className="text-sm text-slate-300">
          Granularité
          <select
            value={bucket}
            onChange={(event) => setBucket(event.target.value)}
            className="mt-1 w-32 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            {BUCKET_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-slate-300">
          Rafraîchissement (s)
          <AppTextInput
            type="number"
            min={5}
            value={refreshInterval}
            onChange={(event) => setRefreshInterval(Number(event.target.value))}
            className="mt-1 w-28 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
        </label>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={includeDotation}
              onChange={(event) => setIncludeDotation(event.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
            />
            Inclure dotations
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={includeAdjustment}
              onChange={(event) => setIncludeAdjustment(event.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
            />
            Inclure ajustements
          </label>
        </div>
        {isFetching ? (
          <span className="text-xs text-slate-400">Mise à jour en cours...</span>
        ) : null}
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 text-sm text-slate-300">
          Chargement des rapports...
        </div>
      ) : null}
      {error ? (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          Erreur lors du chargement des rapports.
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-5">
        {[
          { label: "Entrées", value: reportData?.kpis.in_qty ?? 0, accent: "text-emerald-300" },
          { label: "Sorties", value: reportData?.kpis.out_qty ?? 0, accent: "text-rose-300" },
          { label: "Net", value: reportData?.kpis.net_qty ?? 0, accent: "text-indigo-300" },
          { label: "Sous seuil", value: reportData?.kpis.low_stock_count ?? 0, accent: "text-amber-300" },
          { label: "BC en cours", value: reportData?.kpis.open_orders ?? 0, accent: "text-sky-300" }
        ].map((kpi) => (
          <div
            key={kpi.label}
            className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur"
          >
            <p className="text-xs uppercase tracking-wide text-slate-400">{kpi.label}</p>
            <p className={`mt-2 text-2xl font-semibold ${kpi.accent}`}>{formatNumber(kpi.value)}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Mouvements entrées / sorties</h3>
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={reportData?.series.moves ?? []}>
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Legend />
                <Bar dataKey="in" stackId="moves" fill="#34d399" name="Entrées" />
                <Bar dataKey="out" stackId="moves" fill="#f87171" name="Sorties" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Net flow</h3>
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={reportData?.series.net ?? []}>
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Line type="monotone" dataKey="net" stroke="#818cf8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">BC créés</h3>
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={reportData?.series.orders ?? []}>
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Bar dataKey="created" fill="#38bdf8" name="BC créés" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Statut des BC</h3>
          <div className="mt-3 flex h-64 items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  data={orderStatusData}
                >
                  {PIE_COLORS.map((color) => (
                    <Cell key={color} fill={color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Tendance sous seuil</h3>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={reportData?.series.low_stock ?? []}>
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Line type="monotone" dataKey="count" stroke="#fbbf24" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Qualité des données</h3>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={[
                  { name: "Sans SKU", value: reportData?.data_quality.missing_sku ?? 0 },
                  { name: "Sans fournisseur", value: reportData?.data_quality.missing_supplier ?? 0 },
                  { name: "Sans seuil", value: reportData?.data_quality.missing_threshold ?? 0 },
                  { name: "Mouv. anormaux", value: reportData?.data_quality.abnormal_movements ?? 0 }
                ]}
              >
                <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }} />
                <Bar dataKey="value" fill="#a855f7" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Top sorties</h3>
          <div className="mt-3 overflow-hidden">
            <table className="w-full table-fixed border-separate border-spacing-y-2 text-sm text-slate-200">
              <thead className="text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-2 text-left">Article</th>
                  <th className="px-2 text-left">SKU</th>
                  <th className="px-2 text-right">Qté</th>
                </tr>
              </thead>
              <tbody>
                {(reportData?.tops.out ?? []).map((row) => (
                  <tr key={`${row.sku}-${row.name}`} className="rounded-lg bg-slate-950/70">
                    <td className="px-2 py-2">{row.name || "—"}</td>
                    <td className="px-2 py-2 text-slate-400">{row.sku || "—"}</td>
                    <td className="px-2 py-2 text-right text-rose-300">{formatNumber(row.qty)}</td>
                  </tr>
                ))}
                {(reportData?.tops.out ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-2 py-4 text-center text-slate-500">
                      Aucune sortie enregistrée.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 p-4 backdrop-blur">
          <h3 className="text-sm font-semibold text-slate-200">Top entrées</h3>
          <div className="mt-3 overflow-hidden">
            <table className="w-full table-fixed border-separate border-spacing-y-2 text-sm text-slate-200">
              <thead className="text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-2 text-left">Article</th>
                  <th className="px-2 text-left">SKU</th>
                  <th className="px-2 text-right">Qté</th>
                </tr>
              </thead>
              <tbody>
                {(reportData?.tops.in ?? []).map((row) => (
                  <tr key={`${row.sku}-${row.name}`} className="rounded-lg bg-slate-950/70">
                    <td className="px-2 py-2">{row.name || "—"}</td>
                    <td className="px-2 py-2 text-slate-400">{row.sku || "—"}</td>
                    <td className="px-2 py-2 text-right text-emerald-300">{formatNumber(row.qty)}</td>
                  </tr>
                ))}
                {(reportData?.tops.in ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-2 py-4 text-center text-slate-500">
                      Aucune entrée enregistrée.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "reports-main",
      title: "Rapports",
      required: true,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 18 },
        md: { x: 0, y: 0, w: 10, h: 18 },
        sm: { x: 0, y: 0, w: 6, h: 18 },
        xs: { x: 0, y: 0, w: 4, h: 18 }
      },
      render: () => (
        <EditableBlock id="reports-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Rapports</h2>
          <p className="text-sm text-slate-400">Chargement des permissions...</p>
        </header>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Rapports</h2>
          <p className="text-sm text-slate-400">Analyse temps réel des modules.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  if (!isFetchingModules && accessibleModules.length === 0) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Rapports</h2>
          <p className="text-sm text-slate-400">
            Aucun module disponible pour votre compte.
          </p>
        </header>
      </section>
    );
  }

  return (
    <EditablePageLayout
      pageKey="module:reports:clothing"
      blocks={blocks}
      className="space-y-6"
    />
  );
}
