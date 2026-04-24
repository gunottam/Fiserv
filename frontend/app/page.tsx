"use client"

import * as React from "react"
import {
  ActivityIcon,
  ArrowUpRightIcon,
  BoxesIcon,
  CalendarClockIcon,
  CheckIcon,
  CloudSunIcon,
  ClockIcon,
  HistoryIcon,
  MoonIcon,
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
  Progress,
  ProgressIndicator,
  ProgressTrack,
} from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"

const ITEM = {
  name: "Croissants",
  sku: "BKR-CRS-002",
  location: "Store #42 · Bakery Counter",
  stock: 18,
  threshold: 40,
  predictedDemand: 18,
  adjustedDemand: 22,
  coverageHours: 0.8,
  stockoutRisk: 42,
  restockUnits: 30,
  urgency: "high" as const,
}

const DEMAND_SERIES: Array<{ hour: string; index: number; demand: number }> = [
  { hour: "6a", index: 6, demand: 4 },
  { hour: "7a", index: 7, demand: 10 },
  { hour: "8a", index: 8, demand: 16 },
  { hour: "9a", index: 9, demand: 22 },
  { hour: "10a", index: 10, demand: 19 },
  { hour: "11a", index: 11, demand: 14 },
  { hour: "12p", index: 12, demand: 18 },
  { hour: "1p", index: 13, demand: 15 },
  { hour: "2p", index: 14, demand: 10 },
  { hour: "3p", index: 15, demand: 8 },
  { hour: "4p", index: 16, demand: 11 },
  { hour: "5p", index: 17, demand: 13 },
  { hour: "6p", index: 18, demand: 10 },
  { hour: "7p", index: 19, demand: 6 },
  { hour: "8p", index: 20, demand: 4 },
  { hour: "9p", index: 21, demand: 2 },
]
const CURRENT_HOUR_INDEX = 9
const BASELINE_DEMAND = 18

const CHART_CONFIG = {
  demand: {
    label: "Demand",
    color: "var(--destructive)",
  },
} satisfies ChartConfig

const REASONING_FACTORS = [
  {
    icon: CalendarClockIcon,
    title: "Saturday peak",
    detail: "+22% vs weekday avg",
  },
  {
    icon: HistoryIcon,
    title: "2 recent stockouts",
    detail: "Past 3 Saturdays, 9–10am",
  },
  {
    icon: TrendingUpIcon,
    title: "Trend rising",
    detail: "+18% hourly velocity",
  },
  {
    icon: CloudSunIcon,
    title: "Clear weather",
    detail: "Expected foot traffic +12%",
  },
]

const URGENCY_CONFIG = {
  high: {
    label: "High urgency",
    badgeVariant: "destructive" as const,
    ringClass: "ring-destructive/40",
    tintClass: "bg-destructive/5",
    accentText: "text-destructive",
    accentBg: "bg-destructive",
  },
  medium: {
    label: "Medium urgency",
    badgeVariant: "warning" as const,
    ringClass: "ring-warning/40",
    tintClass: "bg-warning/5",
    accentText: "text-warning",
    accentBg: "bg-warning",
  },
  low: {
    label: "Low urgency",
    badgeVariant: "success" as const,
    ringClass: "ring-success/40",
    tintClass: "bg-success/5",
    accentText: "text-success",
    accentBg: "bg-success",
  },
}

export default function DashboardPage() {
  const urgency = URGENCY_CONFIG[ITEM.urgency]
  const stockPct = Math.min(100, (ITEM.stock / ITEM.threshold) * 100)

  function handleApproveRestock() {
    toast.success("Restock order placed", {
      description: `+${ITEM.restockUnits} units of ${ITEM.name} dispatched to ${ITEM.location}.`,
      icon: <CheckIcon />,
    })
  }

  return (
    <div className="min-h-svh bg-background">
      <SiteHeader />
      <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <AlertPanel
          urgency={urgency}
          stockPct={stockPct}
          onApprove={handleApproveRestock}
        />
        <ContextPanel />
        <div className="grid gap-6 lg:grid-cols-5">
          <ReasoningPanel className="lg:col-span-3" />
          <DemandChartCard className="lg:col-span-2" />
        </div>
      </main>
    </div>
  )
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BoxesIcon className="size-4" />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold tracking-tight">
              Contextual Inventory Intelligence
            </span>
            <span className="text-xs text-muted-foreground">
              {ITEM.location}
            </span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="hidden items-center gap-2 text-xs text-muted-foreground md:flex">
            <span className="inline-flex size-1.5 animate-pulse rounded-full bg-success" />
            Live · Saturday · 09:15 AM
          </div>
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

type UrgencyConfig = (typeof URGENCY_CONFIG)[keyof typeof URGENCY_CONFIG]

function AlertPanel({
  urgency,
  stockPct,
  onApprove,
}: {
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
              {ITEM.sku}
            </Badge>
          </div>

          <div className="flex flex-col gap-1">
            <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">
              {ITEM.name}
            </h2>
            <p className="text-sm text-muted-foreground">
              Falling below reorder threshold · action required
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
                  {ITEM.stock}
                </span>
                <span className="text-sm text-muted-foreground">
                  of {ITEM.threshold} threshold
                </span>
              </div>
              <span
                className={cn(
                  "text-xs font-medium uppercase tracking-wide tabular-nums",
                  urgency.accentText
                )}
              >
                {ITEM.threshold - ITEM.stock} below target
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
                +{ITEM.restockUnits}
              </span>
              <span className="text-sm font-medium text-muted-foreground">
                units
              </span>
            </div>
            <span className="text-lg font-semibold tracking-tight lg:text-right">
              Restock now
            </span>
          </div>
          <Button size="lg" className="w-full" onClick={onApprove}>
            <CheckIcon data-icon="inline-start" />
            Approve Restock
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function ContextPanel() {
  return (
    <section
      aria-label="Context metrics"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <MetricCard
        icon={TrendingUpIcon}
        label="Predicted demand"
        value="18"
        unit="units/hr"
        caption="Baseline forecast"
      />
      <MetricCard
        icon={ActivityIcon}
        label="Adjusted demand"
        value="22"
        unit="units/hr"
        caption="After context boost"
        delta={{ text: "+4 from context", variant: "warning" }}
      />
      <MetricCard
        icon={ClockIcon}
        label="Stock coverage"
        value="0.8"
        unit="hours left"
        caption="At current sell-through"
        tone="destructive"
      />
      <MetricCard
        icon={TriangleAlertIcon}
        label="Stockout risk"
        value="42"
        unit="%"
        caption="Within the next hour"
        tone="destructive"
        progress={42}
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
  const toneText = tone === "destructive" ? "text-destructive" : "text-foreground"

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

function ReasoningPanel({ className }: { className?: string }) {
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
            <CardTitle className="text-base">AI Recommendation</CardTitle>
            <CardDescription className="text-xs">
              Reasoned from real-time signals · Groq
            </CardDescription>
          </div>
          <Badge variant="outline" className="ml-auto gap-1">
            <span className="size-1.5 rounded-full bg-primary" />
            Live
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <p className="text-base leading-relaxed text-foreground md:text-[15px] md:leading-7">
          <span className="font-semibold text-destructive">
            High urgency.
          </span>{" "}
          Saturday morning peak is driving demand to{" "}
          <span className="font-semibold tabular-nums">22 units/hr</span>, with
          an increasing trend and two stock-outs in the past three Saturdays.
          Add{" "}
          <span className="font-semibold tabular-nums text-foreground">
            30 units now
          </span>{" "}
          to hold coverage through the 9–11am rush and prevent lost sales.
        </p>

        <div>
          <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            Signals driving this
          </span>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {REASONING_FACTORS.map((factor) => (
              <div
                key={factor.title}
                className="flex items-start gap-3 rounded-lg border border-border/60 bg-background/40 p-3"
              >
                <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <factor.icon className="size-3.5" />
                </div>
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">
                    {factor.title}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {factor.detail}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function DemandChartCard({ className }: { className?: string }) {
  const currentPoint = DEMAND_SERIES.find(
    (p) => p.index === CURRENT_HOUR_INDEX
  )!

  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="gap-1">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">Demand · last 16 hours</CardTitle>
          <Badge variant="destructive" className="gap-1">
            <ArrowUpRightIcon data-icon="inline-start" />
            Spike now
          </Badge>
        </div>
        <CardDescription className="text-xs">
          Units/hr velocity · current hour highlighted
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer
          config={CHART_CONFIG}
          className="h-[220px] w-full"
        >
          <AreaChart
            data={DEMAND_SERIES}
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
              cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: 3 }}
              content={
                <ChartTooltipContent
                  indicator="line"
                  labelFormatter={(v) => `Hour ${v}`}
                />
              }
            />
            <ReferenceLine
              y={BASELINE_DEMAND}
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
            <ReferenceDot
              x={currentPoint.hour}
              y={currentPoint.demand}
              r={6}
              fill="var(--destructive)"
              stroke="var(--background)"
              strokeWidth={2}
            />
          </AreaChart>
        </ChartContainer>

        <div className="mt-4 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="size-2 rounded-full bg-destructive" />
            Now · {currentPoint.demand} units/hr
          </div>
          <span className="font-medium text-muted-foreground">
            Baseline {BASELINE_DEMAND} units/hr
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
