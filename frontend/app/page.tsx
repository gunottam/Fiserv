"use client"

import * as React from "react"
import {
  ActivityIcon,
  AlertCircleIcon,
  ArrowUpRightIcon,
  BoxesIcon,
  CheckIcon,
  ChevronDownIcon,
  ClockIcon,
  MoonIcon,
  RefreshCwIcon,
  SparklesIcon,
  SunIcon,
  TrendingUpIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { useTheme } from "next-themes"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts"
import { toast } from "sonner"

import { AlertFeed } from "@/components/alert-feed"
import { ChatDrawer } from "@/components/chat-drawer"
import { SystemSnapshot, type SnapshotCounts } from "@/components/system-snapshot"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Progress,
  ProgressIndicator,
  ProgressTrack,
} from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { alertToPredictRequest, api } from "@/lib/api"
import {
  buildHeadline,
  buildSignals,
  type DecisionSignal,
} from "@/lib/decisions"
import { SAMPLE_ALERTS } from "@/lib/sample-alerts"
import type {
  DemandSeriesResponse,
  InventoryAlert,
  PredictResponse,
  Urgency,
} from "@/lib/types"
import { cn } from "@/lib/utils"

type UrgencyVariant = "destructive" | "warning" | "success"

const URGENCY_CONFIG: Record<
  Urgency,
  {
    label: string
    badgeVariant: UrgencyVariant
    ringClass: string
    tintClass: string
    accentText: string
    accentBg: string
  }
> = {
  HIGH: {
    label: "High urgency",
    badgeVariant: "destructive",
    ringClass: "ring-destructive/40",
    tintClass: "bg-destructive/5",
    accentText: "text-destructive",
    accentBg: "bg-destructive",
  },
  MEDIUM: {
    label: "Medium urgency",
    badgeVariant: "warning",
    ringClass: "ring-warning/40",
    tintClass: "bg-warning/5",
    accentText: "text-warning",
    accentBg: "bg-warning",
  },
  LOW: {
    label: "Low urgency",
    badgeVariant: "success",
    ringClass: "ring-success/40",
    tintClass: "bg-success/5",
    accentText: "text-success",
    accentBg: "bg-success",
  },
}

const CHART_CONFIG = {
  demand: { label: "Demand", color: "var(--destructive)" },
} satisfies ChartConfig

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [decisions, setDecisions] = React.useState<
    Record<string, PredictResponse>
  >({})
  const [seriesMap, setSeriesMap] = React.useState<
    Record<string, DemandSeriesResponse>
  >({})
  const [activeAlertId, setActiveAlertId] = React.useState<string>(
    SAMPLE_ALERTS[0].alert_id
  )
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  const activeAlert =
    SAMPLE_ALERTS.find((a) => a.alert_id === activeAlertId) ??
    SAMPLE_ALERTS[0]
  const activeDecision = decisions[activeAlertId] ?? null
  const seriesKey = `${activeAlert.item_id}:${activeAlert.metadata.day_of_week}`
  const activeSeries = seriesMap[seriesKey] ?? null

  // Fan-out: on mount (and on refresh) we predict every alert in parallel so
  // the sidebar can render urgencies immediately. Demand series is fetched
  // lazily per-alert and cached by (item_id, day_of_week).
  const refreshAll = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const entries = await Promise.all(
        SAMPLE_ALERTS.map(async (alert) => {
          const payload = alertToPredictRequest(alert)
          const pred = await api.predict(payload)
          return [alert.alert_id, pred] as const
        })
      )
      setDecisions(Object.fromEntries(entries))
      setSeriesMap({}) // bust the per-item cache so the chart re-pulls fresh numbers
    } catch (err) {
      setDecisions({})
      setError(
        err instanceof Error
          ? err.message
          : "Could not reach the backend at " +
            (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000")
      )
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  // Lazy-load the demand profile for whichever alert is currently active.
  React.useEffect(() => {
    if (!activeAlert || seriesMap[seriesKey]) return
    let cancelled = false
    void api
      .demandSeries(activeAlert.item_id, activeAlert.metadata.day_of_week)
      .then((s) => {
        if (!cancelled) setSeriesMap((m) => ({ ...m, [seriesKey]: s }))
      })
      .catch(() => {
        // demand-series failure shouldn't block the main decision UI — the
        // chart falls back to an empty state.
      })
    return () => {
      cancelled = true
    }
  }, [activeAlert, seriesKey, seriesMap])

  const counts = React.useMemo<SnapshotCounts>(() => {
    const out: SnapshotCounts = { HIGH: 0, MEDIUM: 0, LOW: 0 }
    for (const d of Object.values(decisions)) out[d.urgency] += 1
    return out
  }, [decisions])

  function handleApproveRestock() {
    if (!activeDecision) return
    toast.success("Restock order placed", {
      description: `+${activeDecision.restock} units of ${activeDecision.item_name} dispatched to ${activeAlert.metadata.store_id}.`,
      icon: <CheckIcon />,
    })
  }

  const urgency = activeDecision
    ? URGENCY_CONFIG[activeDecision.urgency]
    : URGENCY_CONFIG.LOW
  const stockPct = activeDecision
    ? Math.min(
        100,
        (activeDecision.current_stock / activeDecision.threshold) * 100
      )
    : 0

  return (
    <div className="min-h-svh bg-background">
      <SiteHeader
        counts={counts}
        countsLoading={loading && Object.keys(decisions).length === 0}
        storeId={activeAlert.metadata.store_id}
        onRefresh={() => void refreshAll()}
        refreshing={loading}
      />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-6">
          <AlertFeed
            alerts={SAMPLE_ALERTS}
            decisions={decisions}
            activeId={activeAlertId}
            onSelect={setActiveAlertId}
            loading={loading}
            className="w-full shrink-0 lg:sticky lg:top-20 lg:w-[320px]"
          />

          <div className="flex min-w-0 flex-1 flex-col gap-6">
            {error && (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertTitle>Backend unreachable</AlertTitle>
                <AlertDescription>
                  {error} · Start the FastAPI server:{" "}
                  <code className="rounded bg-destructive/10 px-1 py-0.5 text-xs">
                    cd backend && uvicorn app:app --reload --port 8000
                  </code>
                </AlertDescription>
              </Alert>
            )}

            {loading && !activeDecision ? (
              <MainSkeleton />
            ) : activeDecision ? (
              <>
                <AlertPanel
                  alert={activeAlert}
                  decision={activeDecision}
                  urgency={urgency}
                  stockPct={stockPct}
                  onApprove={handleApproveRestock}
                />
                <ContextPanel decision={activeDecision} />
                <div className="grid gap-6 xl:grid-cols-5">
                  <ReasoningPanel
                    decision={activeDecision}
                    className="xl:col-span-3"
                  />
                  <DemandChartCard
                    decision={activeDecision}
                    series={activeSeries}
                    className="xl:col-span-2"
                  />
                </div>
              </>
            ) : null}
          </div>
        </div>
      </main>

      <ChatDrawer decision={activeDecision} disabled={loading} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function SiteHeader({
  counts,
  countsLoading,
  storeId,
  onRefresh,
  refreshing,
}: {
  counts: SnapshotCounts
  countsLoading: boolean
  storeId: string
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BoxesIcon className="size-4" />
          </div>
          <div className="hidden flex-col leading-tight sm:flex">
            <span className="text-sm font-semibold tracking-tight">
              Contextual Inventory Intelligence
            </span>
            <span className="text-xs text-muted-foreground">
              Store {storeId} · Bakery Counter
            </span>
          </div>
        </div>

        <Separator orientation="vertical" className="mx-1 hidden h-6 md:block" />

        <SystemSnapshot counts={counts} loading={countsLoading} />

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <div className="hidden items-center gap-2 text-xs text-muted-foreground md:flex">
            <span className="inline-flex size-1.5 animate-pulse rounded-full bg-success" />
            Live
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh all alerts"
          >
            <RefreshCwIcon className={cn(refreshing && "animate-spin")} />
          </Button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => {
    setMounted(true)
  }, [])

  const isDark = mounted ? resolvedTheme === "dark" : true

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="Toggle theme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {isDark ? <MoonIcon /> : <SunIcon />}
    </Button>
  )
}

// ---------------------------------------------------------------------------
// Alert panel — the big call-to-action
// ---------------------------------------------------------------------------

type UrgencyConfig = (typeof URGENCY_CONFIG)[Urgency]

function AlertPanel({
  alert,
  decision,
  urgency,
  stockPct,
  onApprove,
}: {
  alert: InventoryAlert
  decision: PredictResponse
  urgency: UrgencyConfig
  stockPct: number
  onApprove: () => void
}) {
  return (
    <Card
      className={cn(
        "relative overflow-hidden ring-1",
        urgency.ringClass,
        urgency.tintClass
      )}
    >
      <div
        aria-hidden
        className={cn(
          "absolute inset-x-0 top-0 h-px",
          urgency.accentBg,
          "opacity-80"
        )}
      />
      <CardContent className="flex flex-col gap-6 p-6 lg:flex-row lg:items-stretch lg:gap-10 lg:p-8">
        <div className="flex flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={urgency.badgeVariant}>
              <TriangleAlertIcon data-icon="inline-start" />
              {urgency.label}
            </Badge>
            <Badge variant="outline" className="font-mono text-[11px]">
              {alert.alert_id}
            </Badge>
            <Badge variant="outline" className="font-mono text-[11px]">
              {decision.item_id}
            </Badge>
          </div>

          <div className="flex flex-col gap-1">
            <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">
              {decision.item_name}
            </h2>
            <p className="text-sm text-muted-foreground">
              {decision.current_stock <= decision.threshold
                ? "Below reorder threshold · action required"
                : "Above threshold · monitoring"}
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-4">
              <div className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "text-2xl font-semibold tabular-nums",
                    urgency.accentText
                  )}
                >
                  {decision.current_stock}
                </span>
                <span className="text-sm text-muted-foreground">
                  of {decision.threshold} threshold
                </span>
              </div>
              <span
                className={cn(
                  "text-xs font-medium uppercase tracking-wide tabular-nums",
                  urgency.accentText
                )}
              >
                {decision.threshold - decision.current_stock > 0
                  ? `${decision.threshold - decision.current_stock} below target`
                  : "on target"}
              </span>
            </div>
            <Progress value={stockPct} className="flex-col gap-0">
              <ProgressTrack className="h-2 bg-muted/70">
                <ProgressIndicator className={cn(urgency.accentBg)} />
              </ProgressTrack>
            </Progress>
          </div>
        </div>

        <Separator orientation="vertical" className="hidden lg:block" />

        <div className="flex flex-col items-stretch justify-center gap-4 lg:min-w-[260px]">
          <div className="flex flex-col items-start gap-1 lg:items-end">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Recommended action
            </span>
            <div className="flex items-baseline gap-2 lg:justify-end">
              <span
                className={cn(
                  "text-5xl font-bold tabular-nums leading-none md:text-6xl",
                  urgency.accentText
                )}
              >
                +{decision.restock}
              </span>
              <span className="text-sm font-medium text-muted-foreground">
                units
              </span>
            </div>
            <span className="text-lg font-semibold tracking-tight lg:text-right">
              {decision.restock > 0 ? "Restock now" : "Hold · no action"}
            </span>
          </div>
          <Button
            size="lg"
            className="w-full"
            onClick={onApprove}
            disabled={decision.restock === 0}
          >
            <CheckIcon data-icon="inline-start" />
            {decision.restock > 0 ? "Approve Restock" : "Nothing to approve"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Context metrics (unchanged)
// ---------------------------------------------------------------------------

function ContextPanel({ decision }: { decision: PredictResponse }) {
  const boostDelta = +(
    decision.adjusted_velocity - decision.predicted_velocity
  ).toFixed(1)

  return (
    <section
      aria-label="Context metrics"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      <MetricCard
        icon={TrendingUpIcon}
        label="Predicted velocity"
        value={decision.predicted_velocity.toFixed(1)}
        unit="units/hr"
        caption="Model baseline for this hour"
      />
      <MetricCard
        icon={ActivityIcon}
        label="Adjusted velocity"
        value={decision.adjusted_velocity.toFixed(1)}
        unit="units/hr"
        caption={
          decision.context_factors.length > 0
            ? `${decision.context_factors.length} boost${
                decision.context_factors.length > 1 ? "s" : ""
              } applied`
            : "No context boosts"
        }
        delta={
          boostDelta > 0
            ? { text: `+${boostDelta} from context`, variant: "warning" }
            : undefined
        }
      />
      <MetricCard
        icon={ClockIcon}
        label="Stock coverage"
        value={decision.coverage_hours.toFixed(1)}
        unit={decision.coverage_hours === 1 ? "hour left" : "hours left"}
        caption="At adjusted sell-through"
        tone={decision.coverage_hours < 1 ? "destructive" : "default"}
      />
      <MetricCard
        icon={TriangleAlertIcon}
        label="Stockout risk"
        value={decision.stockout_risk.toFixed(0)}
        unit="%"
        caption="Within the next hour"
        tone={decision.stockout_risk >= 50 ? "destructive" : "default"}
        progress={decision.stockout_risk}
      />
    </section>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  caption,
  delta,
  tone = "default",
  progress,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  unit: string
  caption: string
  delta?: { text: string; variant: "warning" | "success" | "destructive" }
  tone?: "default" | "destructive"
  progress?: number
}) {
  const toneText =
    tone === "destructive" ? "text-destructive" : "text-foreground"

  return (
    <Card className="h-full">
      <CardHeader className="flex-row items-center justify-between gap-2 pb-2">
        <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
          <Icon className="size-3.5" />
          {label}
        </CardDescription>
        {delta && (
          <Badge variant={delta.variant} className="text-[10px]">
            {delta.text}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-baseline gap-1.5">
          <span
            className={cn(
              "text-4xl font-semibold tabular-nums leading-none",
              toneText
            )}
          >
            {value}
          </span>
          <span className="text-sm font-medium text-muted-foreground">
            {unit}
          </span>
        </div>
        <span className="text-xs text-muted-foreground">{caption}</span>
        {typeof progress === "number" && (
          <Progress value={progress} className="flex-col gap-0">
            <ProgressTrack className="h-1.5 bg-muted">
              <ProgressIndicator
                className={cn(
                  tone === "destructive" ? "bg-destructive" : "bg-primary"
                )}
              />
            </ProgressTrack>
          </Progress>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Reasoning — two-layer: concrete headline + collapsible full rationale
// ---------------------------------------------------------------------------

function ReasoningPanel({
  decision,
  className,
}: {
  decision: PredictResponse
  className?: string
}) {
  const [open, setOpen] = React.useState(false)
  const headline = buildHeadline(decision)
  const signals = buildSignals(decision)

  // Reset the drawer when the selected alert changes so the operator's next
  // look is always the compact headline first.
  React.useEffect(() => {
    setOpen(false)
  }, [decision.item_id, decision.urgency])

  return (
    <Card
      className={cn(
        "relative overflow-hidden bg-gradient-to-br from-primary/5 via-card to-card",
        className
      )}
    >
      <CardHeader className="gap-3">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <SparklesIcon className="size-4" />
          </div>
          <div className="flex flex-col">
            <CardTitle className="text-base">AI recommendation</CardTitle>
            <CardDescription className="text-xs">
              Grounded on model output + context rules
            </CardDescription>
          </div>
          <Badge variant="outline" className="ml-auto gap-1">
            <span className="size-1.5 rounded-full bg-primary" />
            Live
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-5">
        {/* Layer 1 — concrete, scannable, always visible. */}
        <p className="text-lg font-semibold leading-snug text-foreground md:text-xl">
          {headline}
        </p>

        <SignalList signals={signals} />

        {/* Layer 2 — full LLM rationale tucked behind a disclosure button. */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger
            render={
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-center"
                aria-expanded={open}
              >
                <ChevronDownIcon
                  data-icon="inline-start"
                  className={cn(
                    "transition-transform duration-200",
                    open && "rotate-180"
                  )}
                />
                {open ? "Hide reasoning" : "View reasoning"}
              </Button>
            }
          />
          <CollapsibleContent
            className={cn(
              // Grid-rows trick for smooth height animation that works with
              // base-ui's data-open / data-closed states on the panel.
              "grid transition-[grid-template-rows] duration-200 ease-out",
              "data-[open]:grid-rows-[1fr] data-[closed]:grid-rows-[0fr]"
            )}
          >
            <div className="overflow-hidden">
              <div className="mt-4 flex flex-col gap-3 rounded-lg border border-border/60 bg-background/40 p-4">
                <p className="text-sm leading-6 text-muted-foreground">
                  {decision.explanation}
                </p>
                <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                  <span className="rounded-md border border-border/60 bg-background/60 px-2 py-1">
                    Historical stockout rate:{" "}
                    <span className="font-medium tabular-nums text-foreground">
                      {(decision.historical_stockout_rate * 100).toFixed(1)}%
                    </span>
                  </span>
                  <span className="rounded-md border border-border/60 bg-background/60 px-2 py-1">
                    Coverage rule:{" "}
                    <span className="font-medium text-foreground">
                      {decision.is_peak_hour ? "5h peak" : "3h off-peak"}
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}

function SignalList({ signals }: { signals: DecisionSignal[] }) {
  if (signals.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
        Signals driving this
      </span>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {signals.map((signal) => (
          <li
            key={signal.id}
            className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/40 px-3 py-2 text-sm"
          >
            <span className="truncate font-medium text-foreground">
              {signal.key}
            </span>
            <span className="text-muted-foreground" aria-hidden>
              →
            </span>
            <span className="truncate text-muted-foreground">
              {signal.impact}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Demand chart — real historical hourly mean from the CSV
// ---------------------------------------------------------------------------

function DemandChartCard({
  decision,
  series,
  className,
}: {
  decision: PredictResponse
  series: DemandSeriesResponse | null
  className?: string
}) {
  const hasSeries = (series?.series?.length ?? 0) > 0

  const chartData = (series?.series ?? []).map((p) => ({
    hour: formatHour(p.hour),
    index: p.hour,
    demand: p.demand,
  }))
  const currentPoint = chartData.find((p) => p.index === decision.hour)
  const baseline = series?.baseline ?? 0

  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="gap-1">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">
            Demand · typical {decision.day_of_week}
          </CardTitle>
          {currentPoint && currentPoint.demand > baseline ? (
            <Badge variant="destructive" className="gap-1">
              <ArrowUpRightIcon data-icon="inline-start" />
              Above baseline
            </Badge>
          ) : (
            <Badge variant="outline" className="gap-1">
              At baseline
            </Badge>
          )}
        </div>
        <CardDescription className="text-xs">
          Historical mean units/hr · current hour highlighted
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hasSeries ? (
          <ChartContainer config={CHART_CONFIG} className="h-[220px] w-full">
            <AreaChart
              data={chartData}
              margin={{ left: -24, right: 8, top: 8, bottom: 0 }}
            >
              <defs>
                <linearGradient id="demand-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor="var(--color-demand)"
                    stopOpacity={0.35}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--color-demand)"
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                vertical={false}
                strokeDasharray="3 3"
                stroke="var(--border)"
              />
              <XAxis
                dataKey="hour"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={16}
                className="text-xs"
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={32}
                className="text-xs"
              />
              <ChartTooltip
                cursor={{
                  stroke: "var(--muted-foreground)",
                  strokeDasharray: 3,
                }}
                content={
                  <ChartTooltipContent
                    indicator="line"
                    labelFormatter={(v) => `Hour ${v}`}
                  />
                }
              />
              {baseline > 0 && (
                <ReferenceLine
                  y={baseline}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="4 4"
                  strokeOpacity={0.6}
                  label={{
                    value: "Baseline",
                    position: "insideTopRight",
                    fill: "var(--muted-foreground)",
                    fontSize: 10,
                  }}
                />
              )}
              <Area
                dataKey="demand"
                type="monotone"
                stroke="var(--color-demand)"
                strokeWidth={2.5}
                fill="url(#demand-fill)"
                activeDot={{
                  r: 5,
                  stroke: "var(--background)",
                  strokeWidth: 2,
                }}
              />
              {currentPoint && (
                <ReferenceDot
                  x={currentPoint.hour}
                  y={currentPoint.demand}
                  r={6}
                  fill="var(--destructive)"
                  stroke="var(--background)"
                  strokeWidth={2}
                />
              )}
            </AreaChart>
          </ChartContainer>
        ) : (
          <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
            No historical rows for this combination.
          </div>
        )}

        <div className="mt-4 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="size-2 rounded-full bg-destructive" />
            Now · {currentPoint ? currentPoint.demand.toFixed(1) : "—"} units/hr
          </div>
          <span className="font-medium text-muted-foreground">
            Baseline{" "}
            {baseline > 0 ? `${baseline.toFixed(1)} units/hr` : "n/a"}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

function formatHour(h: number): string {
  if (h === 0) return "12a"
  if (h < 12) return `${h}a`
  if (h === 12) return "12p"
  return `${h - 12}p`
}

// ---------------------------------------------------------------------------
// Skeleton (first-paint, main column only — the sidebar has its own)
// ---------------------------------------------------------------------------

function MainSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-[220px] w-full rounded-xl" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[140px] w-full rounded-xl" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-5">
        <Skeleton className="h-[320px] w-full rounded-xl xl:col-span-3" />
        <Skeleton className="h-[320px] w-full rounded-xl xl:col-span-2" />
      </div>
    </div>
  )
}
