import { useState, useEffect, useCallback } from "react";
import { getMessages, getChannels, postMessage } from "../api/client";
import type { Message } from "../types/api";

export function useMessages(projectId: string | undefined, channel: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [channels, setChannels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    if (!projectId) return;
    Promise.all([getMessages(projectId, channel), getChannels(projectId)])
      .then(([msgs, chs]) => { setMessages(msgs); setChannels(chs); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId, channel]);

  useEffect(() => { refresh(); }, [refresh]);

  const send = async (content: string, sender = "human") => {
    if (!projectId) return;
    const msg = await postMessage(projectId, channel, sender, content);
    setMessages((prev) => [...prev, msg]);
  };

  return { messages, channels, loading, refresh, send };
}
