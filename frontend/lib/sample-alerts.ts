import type { InventoryAlert } from "./types"

// Preset alerts mirroring the problem-statement JSON shape. SKUs and names
// track the bakery_inventory.csv catalog (BK-01 … BK-10). Each preset is
// chosen to land in a distinct urgency bucket so demoing the dashboard
// exercises the full pipeline without hand-editing requests.
//
// Picks rationale:
//   Glazed Donuts   — highest-velocity SKU (18.9 u/hr), Sat peak → HIGH urgency.
//   Croissants      — mid-velocity SKU, Sat peak morning rush → HIGH.
//   Fruit Tart      — lowest velocity (3.4) but highest historical stockout
//                     rate (~19%), so the boost fires → MEDIUM/HIGH.
//   Baguette        — mid-velocity, Wed off-peak afternoon → LOW.
//   Coffee Cake     — low velocity, Mon peak morning → MEDIUM.
export const SAMPLE_ALERTS: InventoryAlert[] = [
  {
    alert_id: "ALT-4601",
    event_timestamp: "2026-04-25T10:00:00",
    item_id: "BK-06",
    item_name: "Glazed Donuts",
    current_stock: 14,
    static_threshold: 15,
    metadata: {
      store_id: "IND-01",
      day_of_week: "Saturday",
      is_peak_hour: true,
    },
  },
  {
    alert_id: "ALT-4602",
    event_timestamp: "2026-04-25T09:15:00",
    item_id: "BK-01",
    item_name: "Croissants",
    current_stock: 7,
    static_threshold: 10,
    metadata: {
      store_id: "IND-01",
      day_of_week: "Saturday",
      is_peak_hour: true,
    },
  },
  {
    alert_id: "ALT-4603",
    event_timestamp: "2026-04-26T11:00:00",
    item_id: "BK-08",
    item_name: "Fruit Tart",
    current_stock: 3,
    static_threshold: 6,
    metadata: {
      store_id: "IND-01",
      day_of_week: "Sunday",
      is_peak_hour: true,
    },
  },
  {
    alert_id: "ALT-4604",
    event_timestamp: "2026-04-22T15:00:00",
    item_id: "BK-10",
    item_name: "Baguette",
    current_stock: 22,
    static_threshold: 15,
    metadata: {
      store_id: "IND-01",
      day_of_week: "Wednesday",
      is_peak_hour: false,
    },
  },
  {
    alert_id: "ALT-4605",
    event_timestamp: "2026-04-20T07:30:00",
    item_id: "BK-09",
    item_name: "Coffee Cake",
    current_stock: 18,
    static_threshold: 8,
    metadata: {
      store_id: "IND-01",
      day_of_week: "Monday",
      is_peak_hour: true,
    },
  },
]

// Readable label for the alert-selector dropdown.
export function alertLabel(alert: InventoryAlert): string {
  const time = new Date(alert.event_timestamp).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })
  return `${alert.item_name} · ${alert.metadata.day_of_week} ${time}${
    alert.metadata.is_peak_hour ? " · peak" : ""
  }`
}
