import { useEffect, useRef, useState } from "react";

// WebRTC through the hub's go2rtc proxy; reconnects when the stream drops.
export function Player({ url }: { url: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState("connecting");

  useEffect(() => {
    let pc: RTCPeerConnection | null = null;
    let timer: number | undefined;
    let stopped = false;

    const play = () => {
      pc?.close();
      const conn = (pc = new RTCPeerConnection());
      conn.addTransceiver("video", { direction: "recvonly" });
      conn.addTransceiver("audio", { direction: "recvonly" });
      conn.ontrack = (e) => {
        if (video.current) video.current.srcObject = e.streams[0] || new MediaStream([e.track]);
      };
      // "disconnected" is often a short blip: only reconnect if it has not recovered after 3 s
      const retry = () => {
        clearTimeout(timer);
        timer = window.setTimeout(() => {
          if (!stopped && pc === conn && conn.connectionState !== "connected") {
            setState("reconnecting");
            play();
          }
        }, 3000);
      };
      conn.onconnectionstatechange = () => {
        if (conn.connectionState === "connected") setState("");
        if (conn.connectionState === "failed" || conn.connectionState === "disconnected") retry();
      };
      conn
        .createOffer()
        .then((o) => conn.setLocalDescription(o))
        .then(() =>
          fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: "offer", sdp: conn.localDescription?.sdp }),
          }),
        )
        .then((r) => {
          if (!r.ok) throw new Error(String(r.status));
          return r.json();
        })
        .then((answer) => conn.setRemoteDescription(answer))
        .catch(retry);
    };

    play();
    return () => {
      stopped = true;
      clearTimeout(timer);
      pc?.close();
    };
  }, [url]);

  return (
    <>
      <video ref={video} autoPlay muted playsInline />
      {state && <span className="state">{state}</span>}
    </>
  );
}
