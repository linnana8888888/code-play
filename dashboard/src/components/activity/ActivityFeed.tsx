import { useState } from "react";
import { useWebSocket } from "../../api/websocket";
import type { WsEvent } from "../../types/api";

export default function ActivityFeed() {
  const [events, setEvents] = useState<WsEvent[]>([]);

  useWebSocket((event) => {
    setEvents((prev) => [event, ...prev].slice(0, 50));
  });

  return (
    <div className="rounded-xl border border-border bg-bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Live Activity</h2>
      </div>
      <div className="max-h-80 overflow-y-auto">
        {events.length === 0 ? (
          <p className="p-4 text-sm text-text-muted">Waiting for events...</p>
        ) : (
          events.map((e, i) => (
            <div key={i} className="border-b border-border/50 px-4 py-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium text-accent">{e.type}</span>
                <span className="text-xs text-text-muted">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <p className="mt-0.5 text-text-muted truncate">
                {JSON.stringify(e.data).slice(0, 120)}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
