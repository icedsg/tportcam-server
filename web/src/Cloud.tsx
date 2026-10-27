import { useCallback, useEffect, useState } from "react";
import { Camera, Cloud, getCloud, removeCloud, saveCloud } from "./api";

// Send to tport.stream: stream id + publish key copied from the tport cam app; the hub pushes that camera to the
// relay. Keys are sent to the hub once and never shown again.
export function CloudSettings({ cams }: { cams: Camera[] }) {
  const [cloud, setCloud] = useState<Cloud | null>(null);
  const load = useCallback(() => void getCloud().then(setCloud).catch(() => setCloud(null)), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);
  if (!cloud?.relay) return null;
  return (
    <div className="cloud">
      <h2>Send to tport.stream</h2>
      <p className="dim">In the tport cam app, add a stream and copy its id and publish key here. Sub stream (720p) unless your plan includes full quality.</p>
      {cams.filter((c) => c.main).map((c) => (
        <CloudRow key={c.id} cam={c} link={cloud.cameras[c.id]} onChange={load} />
      ))}
    </div>
  );
}

function CloudRow({ cam, link, onChange }: { cam: Camera; link?: Cloud["cameras"][string]; onChange: () => void }) {
  const [streamId, setStreamId] = useState(link?.stream_id || "");
  const [key, setKey] = useState("");
  const [quality, setQuality] = useState(link?.quality || "sub");
  const [msg, setMsg] = useState("");
  const act = (p: Promise<void>, done: string) =>
    p.then(() => { setKey(""); setMsg(done); onChange(); }).catch((e) => setMsg(String(e.message || e)));
  return (
    <div className="cloudrow">
      <b>{cam.name}</b>
      <input placeholder="Stream id" value={streamId} onChange={(e) => setStreamId(e.target.value.trim())} />
      <input type="password" placeholder={link?.has_key ? "Key saved" : "Publish key"} value={key} onChange={(e) => setKey(e.target.value.trim())} />
      <select value={quality} onChange={(e) => setQuality(e.target.value as "sub" | "main")}>
        <option value="sub">Sub (720p)</option>
        <option value="main">Main</option>
      </select>
      <button onClick={() => act(saveCloud(cam.id, { stream_id: streamId, key, quality, enabled: true }), "Saved")}>Save</button>
      {link && <button onClick={() => act(removeCloud(cam.id), "Removed")}>Stop</button>}
      <span className="dim">{msg || (link ? link.status : "")}</span>
    </div>
  );
}
