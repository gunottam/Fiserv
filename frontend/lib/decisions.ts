import type { PredictResponse, Urgency } from "./types"

/** One-line headline (~12–15 words) synthesized from decision numbers.
 *
 * Drives the Layer-1 "AI recommendation" card. We synthesize it in the client
 * rather than truncating the LLM explanation so the surface stays short,
 * deterministic, and always cites the key numbers. */
export function buildHeadline(decision: PredictResponse): string {
  const coverage = decision.coverage_hours.toFixed(1)
  const item = decision.item_name

  if (decision.urgency === "HIGH") {
    return `Restock ${decision.restock} ${item} now — only ${coverage}h coverage before stockout.`
  }
  if (decision.urgency === "MEDIUM") {
    return `Queue ${decision.restock} ${item} — coverage tightens to ${coverage}h at current pace.`
  }
  if (decision.restock === 0) {
    return `${item} is stable — ${decision.current_stock} units covers ${coverage}h at current demand.`
  }
  return `Light restock of ${decision.restock} ${item} — ${coverage}h coverage keeps you safe.`
}

/** Tiny "0.8h left" style figure used in the sidebar row. */
export function coverageLabel(decision: PredictResponse): string {
  return `${decision.coverage_hours.toFixed(1)}h left`
}

/** Signal = one concrete "cause → impact" driver behind the urgency bucket.
 *
 * Emitted in the order the reasoning panel should render them. Each signal
 * is deterministic and fully derived from the backend response (no LLM) so
 * it stays scannable and verifiable. */
export type DecisionSignal = {
  id: string
  key: string
  impact: string
}

export function buildSignals(decision: PredictResponse): DecisionSignal[] {
  const signals: DecisionSignal[] = []

  for (const factor of decision.context_factors) {
    if (factor === "Peak hour") {
      signals.push({
        id: "peak",
        key: "Peak hour",
        impact: "+20% demand",
      })
    } else if (factor === "Weekend") {
      signals.push({
        id: "weekend",
        key: "Weekend",
        impact: "+20% demand",
      })
    } else if (factor === "Historical stockouts") {
      const pct = Math.round(decision.historical_stockout_rate * 100)
      signals.push({
        id: "history",
        key: "Stockouts",
        impact: `${pct}% historical rate`,
      })
    } else {
      signals.push({ id: factor, key: factor, impact: "+20% demand" })
    }
  }

  signals.push({
    id: "coverage",
    key: "Coverage",
    impact: `${decision.coverage_hours.toFixed(1)}h at current velocity`,
  })

  const gap = decision.threshold - decision.current_stock
  if (gap > 0) {
    signals.push({
      id: "threshold",
      key: "Threshold",
      impact: `${gap} units below reorder level`,
    })
  }

  return signals
}

/** Stable ordering for urgency so the sidebar sorts High → Medium → Low. */
export const URGENCY_RANK: Record<Urgency, number> = {
  HIGH: 0,
  MEDIUM: 1,
  LOW: 2,
}
