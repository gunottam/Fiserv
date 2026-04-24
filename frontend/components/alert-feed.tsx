"use client"

import * as React from "react"
import {
  BellIcon,
  CircleCheckIcon,
  RadioIcon,
  TriangleAlertIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { URGENCY_RANK, coverageLabel } from "@/lib/decisions"
import type { InventoryAlert, PredictResponse, Urgency } from "@/lib/types"
import { cn } from "@/lib/utils"

type UrgencyVariant = "destructive" | "warning" | "success"

const URGENCY_BADGE: Record<
  Urgency,
  { label: string; variant: UrgencyVariant }
> = {
  HIGH: { label: "High", variant: "destructive" },
  MEDIUM: { label: "Medium", variant: "warning" },
  LOW: { label: "Low", variant: "success" },
}

const ACTIVE_RING: Record<Urgency, string> = {
  HIGH: "ring-destructive/50 bg-destructive/5",
  MEDIUM: "ring-warning/50 bg-warning/5",
  LOW: "ring-success/50 bg-success/5",
}

/** Left-rail live-alerts feed. Clicking a row promotes it to the main panel.
 *
 * Scales arbitrarily — the underlying <ScrollArea> handles overflow, and the
 * list is pre-sorted by urgency so the operator's eye lands on HIGH items
 * first without having to scan. */
export function AlertFeed({
  alerts,
  decisions,
  activeId,
  onSelect,
  loading,
  className,
}: {
  alerts: InventoryAlert[]
  decisions: Record<string, PredictResponse>
  activeId: string
  onSelect: (id: string) => void
  loading: boolean
  className?: string
}) {
  const sorted = React.useMemo(() => {
    return [...alerts].sort((a, b) => {
      const da = decisions[a.alert_id]
      const db = decisions[b.alert_id]
      const ra = da ? URGENCY_RANK[da.urgency] : 3
      const rb = db ? URGENCY_RANK[db.urgency] : 3
      if (ra !== rb) return ra - rb
      if (da && db && da.coverage_hours !== db.coverage_hours) {
        return da.coverage_hours - db.coverage_hours
      }
      return a.item_name.localeCompare(b.item_name)
    })
  }, [alerts, decisions])

  const resolvedCount = Object.keys(decisions).length
  const subtitle = loading
    ? `${resolvedCount}/${alerts.length} evaluated`
    : `${alerts.length} active`

  return (
    <Card className={cn("flex h-full flex-col", className)}>
      <CardHeader className="flex-row items-center justify-between gap-2 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <BellIcon className="size-3.5" />
          </div>
          <CardTitle className="text-sm">Live alerts</CardTitle>
        </div>
        <Badge variant="outline" className="gap-1.5 text-[11px] font-normal">
          <RadioIcon className="size-3 text-success" />
          {subtitle}
        </Badge>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full max-h-[520px] px-3 pb-3 lg:max-h-[calc(100svh-12rem)]">
          <ul className="flex flex-col gap-1.5">
            {sorted.map((alert) => {
              const decision = decisions[alert.alert_id]
              return (
                <li key={alert.alert_id}>
                  <AlertFeedRow
                    alert={alert}
                    decision={decision}
                    active={alert.alert_id === activeId}
                    onSelect={onSelect}
                  />
                </li>
              )
            })}
            {loading && resolvedCount < alerts.length && (
              <li className="flex flex-col gap-1.5 pt-1">
                <Skeleton className="h-16 rounded-lg" />
              </li>
            )}
          </ul>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

function AlertFeedRow({
  alert,
  decision,
  active,
  onSelect,
}: {
  alert: InventoryAlert
  decision: PredictResponse | undefined
  active: boolean
  onSelect: (id: string) => void
}) {
  const urgency = decision?.urgency
  const badge = urgency ? URGENCY_BADGE[urgency] : null
  const ring = urgency ? ACTIVE_RING[urgency] : "ring-border/60"

  return (
    <button
      type="button"
      onClick={() => onSelect(alert.alert_id)}
      aria-pressed={active}
      className={cn(
        "group w-full rounded-lg border border-border/60 bg-card px-3 py-2.5 text-left transition-colors",
        "hover:bg-accent/40",
        "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active && cn("ring-1", ring)
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-sm font-medium leading-tight">
            {alert.item_name}
          </span>
          <span className="truncate font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
            {alert.item_id} · {alert.metadata.day_of_week.slice(0, 3)}
            {alert.metadata.is_peak_hour ? " · peak" : ""}
          </span>
        </div>
        {badge ? (
          <Badge variant={badge.variant} className="shrink-0 text-[10px]">
            {urgency === "HIGH" ? (
              <TriangleAlertIcon data-icon="inline-start" />
            ) : urgency === "LOW" ? (
              <CircleCheckIcon data-icon="inline-start" />
            ) : null}
            {badge.label}
          </Badge>
        ) : (
          <Skeleton className="size-5 shrink-0 rounded-full" />
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="tabular-nums">
          {decision ? coverageLabel(decision) : "—"}
        </span>
        {decision && decision.restock > 0 ? (
          <span className="tabular-nums font-medium text-foreground">
            +{decision.restock} units
          </span>
        ) : decision ? (
          <span>No action</span>
        ) : (
          <span>Evaluating…</span>
        )}
      </div>
    </button>
  )
}
