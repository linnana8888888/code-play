import { useState, useRef, useEffect } from "react";
import { useMessages } from "../../hooks/useMessages";

interface Props {
  projectId: string;
}

export default function ChannelView({ projectId }: Props) {
  const [channel, setChannel] = useState("general");
  const { messages, channels, loading, send, refresh } = useMessages(projectId, channel);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Poll for new messages
  useEffect(() => {
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    send(input.trim());
    setInput("");
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-bg-card">
      {/* Channel tabs */}
      <div className="flex items-center gap-1 border-b border-border px-4 py-2">
        {channels.map((ch) => (
          <button
            key={ch}
            onClick={() => setChannel(ch)}
            className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
              ch === channel
                ? "bg-accent/15 text-accent"
                : "text-text-muted hover:bg-bg-hover"
            }`}
          >
            #{ch}
          </button>
        ))}
        {channels.length === 0 && !loading && (
          <span className="text-xs text-text-muted">No channels yet</span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m) => (
          <div key={m.id} className="flex gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-hover text-xs font-bold uppercase text-accent">
              {m.sender[0]}
            </div>
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium">{m.sender}</span>
                <span className="text-[10px] text-text-muted">
                  {new Date(m.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <p className="text-sm text-text-muted">{m.content}</p>
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSend} className="border-t border-border p-3">
        <input
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
          placeholder={`Message #${channel}...`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
      </form>
    </div>
  );
}
