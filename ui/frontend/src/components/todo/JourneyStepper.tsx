// JourneyStepper — the R2 sticky SUBWAY MAP over the dossier journey's eight
// pipeline stations. Pure presentation, in the R0 PeekPanel spirit: it fetches
// nothing, derives nothing, and owns no scroll state. The parent hands it the
// stations (journeyStations.stationsFor), the scrollspy's current key, and a
// select handler; clicking a station is the parent's business (it scrolls).
//
// Node color is EXCLUSIVELY the semantic status set, via the shared StatusDot
// primitive — the station's real outcome, never decoration. The ONE accent is
// reserved for the active-station marker (R0: accent is links/action/focus/
// active, never status).
import StatusDot from "../../design/StatusDot";
import type { Station, StationKey } from "./journeyStations";
import "./journeyStepper.css";

export default function JourneyStepper({
  stations,
  activeKey,
  onSelect,
}: {
  stations: Station[];
  /** The section currently in view (scrollspy) — null before any resolves. */
  activeKey: StationKey | null;
  onSelect: (key: StationKey) => void;
}) {
  return (
    <nav
      data-testid="journey-stepper"
      aria-label="pipeline stations"
      className="dsn-stepper"
    >
      <ol className="dsn-stepper-rail">
        {stations.map((s) => {
          const active = s.key === activeKey;
          return (
            <li key={s.key} className="dsn-station">
              <button
                type="button"
                data-testid={`stepper-station-${s.key}`}
                data-status={s.status}
                data-reached={s.reached ? "true" : "false"}
                data-phase2={s.phase2 ? "true" : "false"}
                data-active={active ? "true" : "false"}
                aria-current={active ? "step" : undefined}
                title={`${s.label} — ${s.summary}`}
                onClick={() => onSelect(s.key)}
                className="dsn-station-btn"
              >
                <span className="dsn-station-node">
                  <StatusDot status={s.status} label={`${s.label} ${s.status}`} />
                </span>
                <span className="dsn-station-label">{s.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
