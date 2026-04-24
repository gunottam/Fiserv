import type {
  ChatMessage,
  ChatResponse,
  DemandSeriesResponse,
  HealthResponse,
  InventoryAlert,
  PredictRequest,
  PredictResponse,
} from "./types"

// NEXT_PUBLIC_ env vars are exposed to the browser. In production, point this
// at the deployed FastAPI URL via Vercel/Cloudflare/etc.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = "ApiError"
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    // Never cache — this is a live ops dashboard.
    cache: "no-store",
  })

  if (!res.ok) {
    // Try to surface the backend's error detail; fall back to the status line.
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === "string") detail = body.detail
    } catch {
      // swallow — some errors return plain text
    }
    throw new ApiError(res.status, detail)
  }

  return res.json() as Promise<T>
}

/** Flatten the problem-statement alert shape into the predict request. */
export function alertToPredictRequest(alert: InventoryAlert): PredictRequest {
  const hour = new Date(alert.event_timestamp).getHours()
  return {
    item_id: alert.item_id,
    item_name: alert.item_name,
    current_stock: alert.current_stock,
    threshold: alert.static_threshold,
    day_of_week: alert.metadata.day_of_week,
    hour,
    is_peak_hour: alert.metadata.is_peak_hour,
    store_id: alert.metadata.store_id,
  }
}

export const api = {
  health: () => request<HealthResponse>("/"),

  predict: (payload: PredictRequest) =>
    request<PredictResponse>("/predict", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  chat: (context: PredictResponse, message: string, history: ChatMessage[]) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify({ context, message, history }),
    }),

  demandSeries: (itemId: string, dayOfWeek: string) => {
    const qs = new URLSearchParams({
      item_id: itemId,
      day_of_week: dayOfWeek,
    })
    return request<DemandSeriesResponse>(`/demand-series?${qs.toString()}`)
  },
}

export { ApiError }
