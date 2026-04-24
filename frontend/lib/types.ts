// Types that mirror the FastAPI backend schemas.
// Keep these in sync with backend/routes/*.py — they are the client-side
// source of truth for the shape of API payloads.

export type Urgency = "HIGH" | "MEDIUM" | "LOW"

export interface PredictRequest {
  item_id: string
  item_name: string
  current_stock: number
  threshold: number
  day_of_week: string
  hour: number
  is_peak_hour: boolean
  historical_stockout_rate?: number | null
}

export interface PredictResponse {
  urgency: Urgency
  restock: number
  predicted_velocity: number
  adjusted_velocity: number
  explanation: string

  item_id: string
  item_name: string
  current_stock: number
  threshold: number
  coverage_hours: number
  stockout_risk: number
  context_factors: string[]

  day_of_week: string
  hour: number
  is_peak_hour: boolean
  historical_stockout_rate: number
}

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export interface ChatRequest {
  context: PredictResponse
  message: string
  history: ChatMessage[]
}

export interface ChatResponse {
  reply: string
  groq_used: boolean
}

export interface DemandPoint {
  hour: number
  demand: number
  samples: number
}

export interface DemandSeriesResponse {
  item_id: string
  day_of_week: string
  baseline: number
  series: DemandPoint[]
}

export interface HealthResponse {
  service: string
  status: string
  model_loaded: boolean
  item_stats_loaded: boolean
  dataset_available: boolean
  groq_configured: boolean
}

// The "alert" shape from the problem statement (what a real monitoring
// system would fire). The dashboard flattens this into a PredictRequest.
export interface InventoryAlert {
  alert_id: string
  event_timestamp: string
  item_id: string
  item_name: string
  current_stock: number
  static_threshold: number
  metadata: {
    store_id: string
    day_of_week: string
    is_peak_hour: boolean
  }
}
