import { useCallback, useEffect, useState } from "react";
import { Camera, getCameras, getHub, Hub } from "./api";
import { CloudSettings } from "./Cloud";
import { Player } from "./Player";
import { Settings, useSettings } from "./settings";

type Tab = "grid" | "cameras" | "settings";
const TABS: Tab[] = ["grid", "cameras", "settings"];

export function App() {
  const [tab, setTab] = useState<Tab>("grid");
  const [hub, setHub] = useState<Hub | null>(null);
  const [cams, setCams] = useState<Camera[] | null>(null);
  const [error, setError] = useState("");
  const [full, setFull] = useState<string | null>(null);
  const [settings, setSettings] = useSettings();

  const load = useCallback(() => {
    setError("");
    Promise.all([getHub(), getCameras()])
      .then(([h, c]) => {
        setHub(h);
        setCams(c.cameras);
        document.title = h.name;
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setFull(null);
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, []);

  const live = (cams || []).filter((c) => c.main);
  const fullCam = live.find((c) => c.id === full);

  return (
    <>
      <header>
        <h1>{hub?.name || "camgrid hub"}</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
      </header>
      {error && (
        <p className="note">
          Can't reach the hub ({error}). <button onClick={load}>Try again</button>
        </p>
      )}
      {tab === "grid" && cams && <Grid cams={live} settings={settings} setSettings={setSettings} onOpen={setFull} />}
      {tab === "cameras" && cams && (
        <CameraList cams={cams} onOpen={(id) => { setTab("grid"); setFull(id); }} />
      )}
      {tab === "settings" && <SettingsView hub={hub} settings={settings} setSettings={setSettings} />}
      {tab === "settings" && cams && <CloudSettings cams={cams} />}
      {fullCam?.main && (
        <div className="full" onClick={() => setFull(null)}>
          <Player url={fullCam.main.webrtc} />
          <span className="label">{fullCam.name} · tap or Esc to close</span>
        </div>
      )}
    </>
  );
}

type SettingsProps = { settings: Settings; setSettings: (s: Partial<Settings>) => void };

function Grid({ cams, settings, setSettings, onOpen }: SettingsProps & { cams: Camera[]; onOpen: (id: string) => void }) {
  if (!cams.length) return <p className="note">No cameras with a stream yet. Check the camera credentials on the hub.</p>;
  return (
    <>
      <div className="cols">
        Columns
        {[1, 2, 3, 4].map((n) => (
          <button key={n} className={settings.cols === n ? "on" : ""} onClick={() => setSettings({ cols: n })}>
            {n}
          </button>
        ))}
      </div>
      <div className="grid" style={{ gridTemplateColumns: `repeat(${settings.cols}, 1fr)` }}>
        {cams.map((c) => {
          // sub stream in the grid unless settings say main; full screen always plays main
          const urls = settings.gridQuality === "main" || !c.sub ? c.main! : c.sub;
          return (
            <div key={c.id} className="tile" onClick={() => onOpen(c.id)}>
              <Player url={urls.webrtc} />
              {settings.labels && <span className="label">{c.name}</span>}
            </div>
          );
        })}
      </div>
    </>
  );
}

function CameraList({ cams, onOpen }: { cams: Camera[]; onOpen: (id: string) => void }) {
  if (!cams.length) return <p className="note">No cameras found on this network.</p>;
  return (
    <table className="list">
      <thead>
        <tr><th></th><th>Name</th><th>IP</th><th>Model</th><th>Stream</th></tr>
      </thead>
      <tbody>
        {cams.map((c) => (
          <tr key={c.id}>
            <td>{c.snapshot && <img src={c.snapshot} alt="" loading="lazy" />}</td>
            <td>{c.name}</td>
            <td>{c.ip}</td>
            <td>{[c.manufacturer, c.model].filter(Boolean).join(" ")}</td>
            <td>
              {c.main ? (
                <>
                  <button onClick={() => onOpen(c.id)}>Watch</button>
                  <div className="rtsp">{c.main.rtsp}</div>
                </>
              ) : (
                <span className="err">{c.error || "no stream"}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SettingsView({ hub, settings, setSettings }: SettingsProps & { hub: Hub | null }) {
  return (
    <div className="settings">
      <label>
        Grid quality
        <select
          value={settings.gridQuality}
          onChange={(e) => setSettings({ gridQuality: e.target.value as Settings["gridQuality"] })}
        >
          <option value="sub">Sub stream (lighter)</option>
          <option value="main">Main stream</option>
        </select>
      </label>
      <label>
        <input type="checkbox" checked={settings.labels} onChange={(e) => setSettings({ labels: e.target.checked })} />
        Camera names on tiles
      </label>
      <p className="dim">These settings are kept in this browser.</p>
      {hub && (
        <p className="dim">
          Hub: {hub.name} · {hub.cameras} camera{hub.cameras === 1 ? "" : "s"} · API {hub.api}
        </p>
      )}
    </div>
  );
}
