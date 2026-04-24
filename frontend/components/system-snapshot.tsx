"use client"

import * as React from "react"
import { CircleCheckIcon, CircleIcon, TriangleAlertIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export type SnapshotCounts = {
  HIGH: number
  MEDIUM: number
  LOW: number
}

/** Compact system-wide snapshot: HIGH / MEDIUM / STABLE pill chips.
 *
 * Sits in the top bar so the operator always has a zoom-out view of alert
 * pressure regardless of which SKU is currently open in the main panel. */
export function SystemSnapshot({
  counts,
  loading,
  className,
}: {
  counts: SnapshotCounts
  loading?: boolean
  className?: string
}) {
  if (loading) {
    return (
      <div className={cn("flex items-center gap-1.5", className)}>
        <Skeleton className="h-6 w-16 rounded-md" />
        <Skeleton className="h-6 w-16 rounded-md" />
        <Skeleton className="h-6 w-16 rounded-md" />
      </div>
    )
  }

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <SnapshotChip
        tone="destructive"
        icon={TriangleAlertIcon}
        label="High"
        count={counts.HIGH}
      />
      <SnapshotChip
        tone="warning"
        icon={CircleIcon}
        label="Medium"
        count={counts.MEDIUM}
      />
      <SnapshotChip
        tone="success"
        icon={CircleCheckIcon}
        label="Stable"
        count={counts.LOW}
      />
    </div>
  )
}

type ChipTone = "destructive" | "warning" | "success"

function SnapshotChip({
  tone,
  icon: Icon,
  label,
  count,
}: {
  tone: ChipTone
  icon: React.ComponentType<{ className?: string }>
  label: string
  count: number
}) {
  const muted = count === 0

  return (
    <Badge
      variant={muted ? "outline" : tone}
      className={cn(
        "gap-1.5 px-2 py-1 text-[11px] font-medium tabular-nums",
        muted && "text-muted-foreground"
      )}
    >
      <Icon className="size-3" />
      <span>{count}</span>
      <span className="hidden font-normal opacity-80 sm:inline">{label}</span>
    </Badge>
  )
}
