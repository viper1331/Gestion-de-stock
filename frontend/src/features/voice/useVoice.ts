import { useEffect, useState } from "react";

import { createWebSocket } from "../../lib/ws";

export function useVoice() {
  const [isListening, setIsListening] = useState(false);

  useEffect(() => {
    const socket = createWebSocket("/ws/voice");
    socket.onopen = () => setIsListening(true);
    socket.onclose = () => setIsListening(false);
    return () => socket.close();
  }, []);

  return { isListening };
}
